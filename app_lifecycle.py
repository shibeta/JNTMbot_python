import ctypes
from ctypes import wintypes
import _thread
import os
import sys
import threading
import atexit
import time

from logger import get_logger

logger = get_logger(__name__)

# ----------------- 全局生命周期状态 -----------------
# 退出信号：一旦被 set()，表示程序进入死亡倒计时
_exit_event = threading.Event()
# 暂停信号：一旦被 set()，表示程序业务应当挂起
_pause_event = threading.Event()

# Windows API 句柄引用防回收
_win_handler_ref = None
_cleanup_done_event = threading.Event()

# ----------------- 信号控制 API -----------------


def trigger_exit(reason: str):
    """触发全局退出信号，并打断主线程"""
    if _exit_event.is_set():
        return
    if reason:
        logger.warning(f"准备退出程序，原因: {reason} 。")
    _exit_event.set()
    if threading.current_thread() is not threading.main_thread():
        _thread.interrupt_main()


def toggle_pause():
    """切换程序的暂停/恢复状态"""
    if _pause_event.is_set():
        logger.warning("暂停/恢复热键被按下，Bot 已恢复。")
        _pause_event.clear()
    else:
        logger.warning("暂停/恢复热键被按下，Bot 即将暂停。按 CTRL+F9 恢复。")
        _pause_event.set()


def is_exiting() -> bool:
    return _exit_event.is_set()


def is_paused() -> bool:
    return _pause_event.is_set()


# ----------------- 程序重启 -----------------


def restart_program():
    """
    使用 os.execl() 重启应用程序。

    在重启前，会清理现有的程序资源:
    - 触发 atexit 中注册的回调
    - 刷新 stdout 和 stderr 缓冲区

    成功时该函数**不会返回**（当前进程已被新进程替换）。

    :raises ``SystemExit``: 重启失败且用户确认后，以退出码 1 结束进程
    """
    logger.info("正在重启应用程序...")

    # 触发 atexit 清理
    try:
        atexit._run_exitfuncs()
    except Exception as e:
        logger.error(f"执行 atexit 退出回调时发生异常: {e}")

    # 刷新 IO 缓冲区（pythonw / 无控制台启动时，流可能已被关闭或替换）
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (AttributeError, OSError, ValueError):
            pass

    # 重启
    executable = sys.executable
    # 打包后 sys.argv[0] 是 exe 自身，不能再作为参数重复传一次
    args = sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv
    try:
        os.execl(executable, executable, *args)
    except OSError as e:
        logger.error(f"重启失败: {e}")
        # stdin 可能已关闭（pythonw、服务、CI），此时 input() 会抛 EOFError，
        # 必须吞掉它，否则会绕过下面这条 sys.exit(1)
        try:
            input("请手动重启程序。按 Enter 键退出...")
        except (EOFError, OSError):
            pass
        sys.exit(1)


# ----------------- 睡眠函数封装族 -----------------


def sleep_stoppable(duration: float) -> bool:
    """
    仅带退出信号检查的休眠。

    不需要响应暂停的线程或原子方法应当使用该方法替换 `time.sleep()` 。

    该计时器精度低于 `time.sleep()` 。

    :return: True 表示正常休眠结束，False 表示被退出信号打断
    """
    # event.wait() 返回 True 表示事件被 set 了 (即收到了退出信号)
    is_interrupted = _exit_event.wait(timeout=duration)
    return not is_interrupted


def sleep_smart(duration: float) -> bool:
    """
    同时带有退出信号检查和暂停检查的 sleep 方法。
    如果在休眠中发生暂停，计时器不走，直到恢复后继续补足剩余的休眠时间。

    需要响应暂停的线程应当使用该方法替换 `time.sleep()` 。

    该计时器精度低于 `sleep_stoppable()` 。

    :return: True 表示正常休眠结束，False 表示被退出信号打断
    """
    remaining = duration

    while remaining > 0:
        # 检查是否需要退出
        if _exit_event.is_set():
            return False

        # 检查是否被暂停
        if _pause_event.is_set():
            # 同样等待退出信号
            _exit_event.wait(0.5)
            continue  # 暂停期间，remaining 计时器不减少

        # 正常休眠：分块睡眠，避免长时间阻塞
        chunk = min(remaining, 0.5)
        start = time.monotonic()

        _exit_event.wait(timeout=chunk)

        elapsed = time.monotonic() - start
        remaining -= elapsed

    return not _exit_event.is_set()


# ----------------- Windows 事件拦截 -----------------


def _mark_cleanup_done():
    """
    注册在 atexit 的最后，一旦执行到这里，说明其他 atexit 和 finally 都已经跑完了。
    注意 atexit 是 FILO ，因此该方法应当第一个注册到 atexit 。
    """
    _cleanup_done_event.set()


def _console_ctrl_handler(ctrl_type):
    """拦截关闭窗口事件，调用退出方法以释放资源，而不是直接关闭程序"""
    CTRL_CLOSE_EVENT = 2
    if ctrl_type == CTRL_CLOSE_EVENT:
        # logger.warning("接收到窗口关闭信号...")
        trigger_exit("接收到系统关闭信号 (WM_CLOSE)")

        # 给主线程争取清理时间 (最大等 4.5 秒，避免 5 秒后被系统直接杀死)
        _cleanup_done_event.wait(timeout=4.5)
        return True
    return False


def init_lifecycle_manager():
    """
    初始化生命周期管理器，注册系统回调。
    注意早于该方法执行的 atexit 回调在接收到 WM_CLOSE 信号将不会被执行。
    """
    global _win_handler_ref

    # 将 Windows 的等待锁的释放注册到 atexit 链中
    # 因为 atexit 执行回调时是 FILO 的，所以在 WM_CLOSE 时只有晚于该语句注册的回调才能执行
    atexit.register(_mark_cleanup_done)

    # 注册拦截关闭事件
    HandlerRoutine = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    _win_handler_ref = HandlerRoutine(_console_ctrl_handler)
    ctypes.windll.kernel32.SetConsoleCtrlHandler(_win_handler_ref, True)
