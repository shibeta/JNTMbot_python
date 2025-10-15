import time
import psutil
import win32gui
import win32process
from win32con import (
    SW_RESTORE,
    HWND_TOPMOST,
    HWND_NOTOPMOST,
    SWP_NOMOVE,
    SWP_NOSIZE,
    SWP_NOACTIVATE,
    SWP_SHOWWINDOW,
)
from typing import Tuple, Optional

from logger import get_logger

logger = get_logger("process_utils")


def is_process_exist(pid: int):
    """
    检查进程ID是否有效。

    :param pid: 进程ID (整数)

    :return: True表示进程存在，False表示不存在
    """
    try:
        if pid is not None:
            return psutil.pid_exists(pid)
        else:
            raise ValueError("PID 必须是一个整数")
    except Exception as e:
        logger.error(f"检查进程ID({pid})是否存在时出错: {e}。")
        return False


def is_window_handler_exist(hwnd: int) -> bool:
    """
    检查窗口句柄是否有效

    :param hwnd: 窗口句柄 (整数)

    :return: True表示窗口存在，False表示不存在
    """
    try:
        if hwnd is not None:
            return bool(win32gui.IsWindow(hwnd))
        else:
            raise ValueError("窗口句柄必须是一个整数")
    except Exception as e:
        logger.error(f"检查窗口句柄({hwnd})是否存在时出错: {e}。")
        return False


def get_window_info(window_name: str) -> Optional[Tuple[int, int]]:
    """
    根据窗口名称查找窗口，并返回其句柄(hwnd)和进程ID(pid)。

    :param window_name: 目标窗口的标题。

    :return: 一个包含 (hwnd, pid) 的元组，如果未找到窗口则返回 None。
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
        return None


def find_window(window_title: str, process_name: str) -> Optional[Tuple[int, int]]:
    """
    一个更加可靠(?)的窗口查找器，用于找到一个标题和进程名称均匹配的，非0*0的窗口。

    :param window_title: 目标窗口的标题。
    :param process_name: 目标窗口的进程名称。

    :return: 一个包含 (hwnd, pid) 的元组，如果未找到窗口则返回 None。
    """
    # 找到所有的窗口
    top_windows = []
    win32gui.EnumWindows(lambda hwnd, top_windows: top_windows.append(hwnd), top_windows)

    candidate_windows = []
    for hwnd in top_windows:
        # 检查标题是否匹配
        if window_title == win32gui.GetWindowText(hwnd):
            # 检查进程名称是否匹配
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                process = psutil.Process(pid)
                if process_name == process.name():
                    candidate_windows.append(hwnd)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    # 从候选者中找到最佳窗口
    for hwnd in candidate_windows:
        # 优先找非最小化的窗口
        if not win32gui.IsIconic(hwnd):
            # 检查窗口是否可见
            if win32gui.IsWindowVisible(hwnd):
                rect = win32gui.GetWindowRect(hwnd)
                width = rect[2] - rect[0]
                height = rect[3] - rect[1]
                # 检查窗口是否具有尺寸
                if width > 1 and height > 1:
                    # 最佳选项
                    _, pid = win32process.GetWindowThreadProcessId(hwnd)
                    return hwnd, pid

    # 如果没找到正在显示的，再检查是否有最小化的候选者
    for hwnd in candidate_windows:
        if win32gui.IsIconic(hwnd):
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return hwnd, pid

    # 遍历完所有窗口都没找到
    return None


def get_process_pid_by_window_handler(handler: int) -> int:
    """
    根据窗口句柄获取进程pid

    :param handler: 目标窗口的句柄
    :raises ``Exception``: 获取进程pid失败
    """
    try:
        _, pid = win32process.GetWindowThreadProcessId(handler)
        if not pid:
            raise Exception(f"找不到句柄{handler}对应的进程")
        return pid
    except Exception as e:
        raise Exception(f"获取句柄{handler}的进程ID时发生异常: {e}") from e


def suspend_process_for_duration(pid: int, duration_seconds: int):
    """
    将一个进程挂起指定的时长，然后恢复它。

    :param pid: 要挂起的进程的 PID
    :param duration_seconds: 要挂起的时间(秒)
    :raises ``ValueError``: 提供的 PID 无效或不存在
    :raises ``Exception``: 挂起或恢复进程时失败
    """
    try:
        proc = psutil.Process(pid)
        logger.info(f"正在挂起进程 {pid}，持续 {duration_seconds} 秒。")
        proc.suspend()
        time.sleep(duration_seconds)
    except psutil.NoSuchProcess:
        raise ValueError(f"挂起失败：未找到 PID 为 {pid} 的进程。")
    except Exception as e:
        raise Exception(f"挂起进程({pid})时发生异常: {e}") from e
    finally:
        # 恢复进程
        try:
            # 确保进程总是被恢复
            resume_process_from_suspend(pid)
        except Exception as e:
            raise e


def resume_process_from_suspend(pid: int):
    """
    将一个挂起的进程恢复。如果进程未被挂起，将不做任何事。

    :param pid: 要恢复的进程的 PID
    :raises ``ValueError``: 提供的 PID 无效或不存在
    :raises ``Exception``: 恢复进程失败
    """
    if not is_process_exist(pid):
        raise ValueError(f"无法从挂起恢复：无效的PID ({pid})。")
    try:
        proc = psutil.Process(pid)
        if proc.status() == psutil.STATUS_STOPPED:
            proc.resume()
            logger.info(f"已恢复进程 {pid}。")
        else:
            pass
    except psutil.NoSuchProcess:
        pass  # 进程可能在操作期间关闭了
    except Exception as e:
        raise Exception(f"恢复进程 {pid} 时出错: {e}") from e


def kill_processes(process_names: list[str]):
    """
    终止所有符合名称的进程。

    :param process_names: 进程名称列表
    """
    for proc in psutil.process_iter(["pid", "name"]):
        if proc.info["name"] in process_names:
            try:
                proc.kill()
                logger.info(f"已终止进程: {proc.info['name']} (PID: {proc.pid})")
            except Exception as e:
                logger.warning(f"无法终止进程 {proc.info['name']}: {e}")


def set_active_window(hwnd: int):
    """
    将传入的窗口句柄从最小化还原并激活。传入的句柄无效则不做任何事。

    :param hwnd: 窗口句柄 (整数)
    :raises ``Exception``: 激活窗口失败
    """
    if not is_window_handler_exist(hwnd):
        return

    try:
        # 如果最小化，从最小化中恢复
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, SW_RESTORE)
            time.sleep(0.2)  # 等待窗口恢复
        # 如果不是活动窗口，将其激活
        if hwnd != win32gui.GetForegroundWindow():
            win32gui.SetForegroundWindow(hwnd)
    except Exception as e:
        raise Exception(f"激活窗口({hwnd})时出错: {e}") from e


def set_top_window(hwnd: int):
    """
    将传入的窗口句柄从最小化还原并置顶。传入的句柄无效则不做任何事。

    :param hwnd: 窗口句柄 (整数)
    :raises ``Exception``: 置顶窗口失败
    """
    if not is_window_handler_exist(hwnd):
        return

    try:
        # 如果最小化，从最小化中恢复
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, SW_RESTORE)
            time.sleep(0.2)  # 等待窗口恢复
        # 将窗口置顶
        win32gui.SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW | SWP_NOACTIVATE
        )
    except Exception as e:
        raise Exception(f"置顶窗口({hwnd})时出错: {e}") from e


def unset_top_window(hwnd: int):
    """
    将传入的窗口句柄设置为非置顶状态。传入的句柄无效则不做任何事。

    :param hwnd: 窗口句柄 (整数)
    :raises ``Exception``: 取消置顶窗口失败
    """
    if not is_window_handler_exist(hwnd):
        return

    try:
        win32gui.SetWindowPos(
            hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW | SWP_NOACTIVATE
        )
    except Exception as e:
        raise Exception(f"取消置顶窗口({hwnd})时出错: {e}") from e
