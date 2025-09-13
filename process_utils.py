import time
import psutil
import win32gui
import win32process
from win32con import SW_RESTORE
from typing import Tuple, Optional

from logger import get_logger

GLogger = get_logger("process_utils")

# 与 GTA V 相关的进程名称列表
GTA_PROCESS_NAMES = [
    "GTA5.exe",
    "GTA5_Enhanced.exe",
    "GTA5_Enhanced_BE.exe",
    "PlayGTAV.exe",
    "RockstarErrorHandler.exe",
    "RockstarService.exe",
    "SocialClubHelper.exe",
    "Launcher.exe",
]


def is_process_exist(pid: int):
    """
    检查进程ID是否有效。

    Args:
        pid: 进程ID (整数)

    Returns:
        bool: True表示进程存在，False表示不存在
    """
    try:
        if pid is not None:
            return psutil.pid_exists(pid)
        else:
            raise ValueError("PID 必须是一个整数")
    except Exception as e:
        GLogger.error(f"检查进程ID({pid})是否存在时出错: {e}。")
        return False


def is_window_handler_exist(hwnd: int):
    """
    检查窗口句柄是否有效

    Args:
        hwnd: 窗口句柄 (整数)

    Returns:
        bool: True表示窗口存在，False表示不存在
    """
    try:
        if hwnd is not None:
            return bool(win32gui.IsWindow(hwnd))
        else:
            raise ValueError("窗口句柄必须是一个整数")
    except Exception as e:
        GLogger.error(f"检查窗口句柄({hwnd})是否存在时出错: {e}。")
        return False


def get_window_info(window_name: str) -> Optional[Tuple[int, int]]:
    """
    根据窗口名称查找窗口，并返回其句柄(hwnd)和进程ID(pid)。

    Args:
        window_name: 目标窗口的标题。

    Returns:
        一个包含 (hwnd, pid) 的元组，如果未找到窗口则返回 None。
    """
    hwnd = win32gui.FindWindow(None, window_name)
    if not hwnd:
        return None

    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if not pid:
            return None
        return hwnd, pid
    except Exception as e:
        GLogger.error(f"获取窗口 '{window_name}' 的进程ID时出错: {e}")
        return None


def get_process_pid_by_window_handler(handler: int) -> int:
    """
    根据窗口句柄获取进程pid

    Args:
        handler: 目标窗口的句柄
    """
    try:
        _, pid = win32process.GetWindowThreadProcessId(handler)
        if not pid:
            return None
        return pid
    except Exception as e:
        GLogger.error(f"获取句柄{handler}的进程ID时出错: {e}")
        return None


def suspend_process_for_duration(pid: int, duration_seconds: int):
    """
    将一个进程挂起指定的时长，然后恢复它。

    Args:
        pid: 要挂起的进程的 PID
        duration_seconds: 要挂起的时间(秒)
    """
    if not is_process_exist(pid):
        GLogger.warning(f"无法挂起：无效的PID ({pid})。")
        return
    try:
        proc = psutil.Process(pid)
        GLogger.info(f"正在挂起进程 {pid}，持续 {duration_seconds} 秒。")
        proc.suspend()
        time.sleep(duration_seconds)
    except psutil.NoSuchProcess:
        GLogger.error(f"挂起失败：未找到 PID 为 {pid} 的进程。")
    except Exception as e:
        GLogger.error(f"在挂起进程期间发生错误: {e}")
    finally:
        try:
            # 确保进程总是被恢复
            if "proc" in locals() and proc.status() == psutil.STATUS_STOPPED:
                proc.resume()
                GLogger.info(f"已恢复进程 {pid}。")
        except psutil.NoSuchProcess:
            pass  # 进程可能在操作期间关闭了
        except Exception as e:
            GLogger.error(f"恢复进程 {pid} 时出错: {e}")


def kill_processes(process_names: list[str]):
    """
    根据进程名称终止一组进程。

    Args:
        process_names: 进程名称列表
    """
    for proc in psutil.process_iter(["pid", "name"]):
        if proc.info["name"] in process_names:
            try:
                GLogger.info(f"正在终止进程: {proc.info['name']} (PID: {proc.pid})")
                proc.kill()
            except Exception as e:
                GLogger.warning(f"无法终止进程 {proc.info['name']}: {e}")


def set_active_window(hwnd: int):
    """
    将传入的窗口句柄从最小化还原并设置为当前活动窗口。传入的句柄无效则不做任何事。

    Args:
        hwnd: 窗口句柄 (整数)
    """
    if is_window_handler_exist(hwnd):
        try:
            if hwnd != win32gui.GetForegroundWindow():
                win32gui.SetForegroundWindow(hwnd)
                win32gui.ShowWindow(hwnd, SW_RESTORE)
        except Exception as e:
            GLogger.error(f"将窗口({hwnd})设置为活动窗口时出错: {e}")
            return
    else:
        return
