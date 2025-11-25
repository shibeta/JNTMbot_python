from pathlib import Path
import ctypes.wintypes
import time
from urllib.request import getproxies
import psutil
import subprocess
import winreg
import win32gui
import win32process
import win32con
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

logger = get_logger(__name__)


def is_window_handler_exist(hwnd: int) -> bool:
    """
    检查窗口句柄是否有效

    :param hwnd: 窗口句柄 (整数)
    :return: True表示窗口存在，False表示不存在
    """
    try:
        return bool(win32gui.IsWindow(hwnd))
    except:
        return False


def get_window_title(hwnd: int) -> Optional[str]:
    """
    获取一个窗口句柄的标题

    :param hwnd: 窗口句柄 (整数)
    :return: 标题字符串。如果未找到窗口，会返回 None
    """
    try:
        return win32gui.GetWindowText(hwnd)
    except:
        return None


def get_process_name(pid: int) -> Optional[str]:
    """
    获取一个进程的进程名

    :param pid: 进程 PID (整数)
    :return: 进程名字符串。如果未找到进程，返回 None
    """
    try:
        return psutil.Process(pid).name()
    except:
        return None


def find_window(window_class: str, window_title: str, process_name: str) -> Optional[Tuple[int, int]]:
    """
    通过窗口类名, 窗口标题和进程名查找窗口，返回窗口句柄和进程ID。
    :param window_class: 窗口类名
    :param window_title: 窗口标题
    :param process_name: 进程名称
    :return: 如果找到符合条件的窗口，返回 (hwnd, pid) 元组，否则返回 None
    """
    # 使用 FindWindow 直接查找窗口
    hwnd = win32gui.FindWindow(window_class, window_title)

    if hwnd == 0:
        return None

    # 验证进程名称
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        proc = psutil.Process(pid)
        if proc.name() != process_name:
            # 这种情况极少发生，但可能存在伪装窗口
            return None
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None

    return hwnd, pid


def suspend_process_for_duration(pid: int, duration_seconds: float):
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
        raise ValueError(f"无法挂起：未找到 PID 为 {pid} 的进程")
    except Exception as e:
        raise Exception(f"挂起进程({pid})时发生异常: {e}") from e
    finally:
        # 恢复进程
        try:
            # 确保进程总是被恢复
            resume_process_from_suspend(pid)
        except Exception as e:
            raise


def resume_process_from_suspend(pid: int):
    """
    将一个挂起的进程恢复。如果进程未被挂起，将不做任何事。

    :param pid: 要恢复的进程的 PID
    :raises ``ValueError``: 提供的 PID 无效或不存在
    :raises ``Exception``: 恢复进程失败
    """
    try:
        proc = psutil.Process(pid)
        try:
            if proc.status() == psutil.STATUS_STOPPED:
                proc.resume()
                logger.info(f"已恢复进程 {pid}。")
            else:
                pass  # 进程未被挂起，不需要恢复
        except psutil.NoSuchProcess:
            pass  # 进程可能在操作期间关闭了
    except psutil.NoSuchProcess:
        raise ValueError(f"无法从挂起恢复：未找到 PID 为 {pid} 的进程")
    except Exception as e:
        raise Exception(f"恢复进程 {pid} 时出错: {e}") from e


def kill_processes(process_names: list[str]):
    """
    强制终止所有符合名称的进程。

    :param process_names: 进程名称列表
    :raises ``Exception("`taskkill` 命令未找到，请确保脚本在Windows环境中运行。")``: 未找到taskkill命令
    """
    for proc_name in process_names:
        try:
            # 构建 taskkill 命令
            # /F: 强制终止
            # /IM: 指定进程名
            # /T: 终止指定进程及其所有子进程
            command = ["taskkill", "/F", "/IM", proc_name, "/T"]

            # 使用 subprocess.run 来执行命令，并抑制输出
            result = subprocess.run(command, check=True, capture_output=True, text=True)
            logger.info(f"已发送终止命令给所有名为 '{proc_name}' 的进程。")

        except subprocess.CalledProcessError as e:
            # 如果进程不存在，taskkill 会返回错误码，这通常是可以接受的
            if "not found" in e.stderr:
                logger.info(f"没有找到名为 '{proc_name}' 的正在运行的进程。")
            else:
                logger.warning(f"无法终止进程 '{proc_name}': {e.stderr}")
        except FileNotFoundError as e:
            raise Exception("`taskkill` 命令未找到，请确保脚本在Windows环境中运行。") from e
        except Exception as e:
            logger.error(f"执行 taskkill 时发生未知错误: {e}")


def close_window(hwnd: int):
    """
    向一个窗口发送 WM_CLOSE 消息以触发其关闭。

    :param hwnd: 要关闭的窗口句柄
    :raises ``ValueError``: 提供的窗口句柄不存在
    :raises ``Exception``: 发送 WM_CLOSE 消息时出错
    """
    if not is_window_handler_exist(hwnd):
        raise ValueError(f"未找到句柄为 {hwnd} 的窗口。")
    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)


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


def get_document_fold_path() -> Path:
    """
    获取"我的文档"文件夹位置。

    :return: "我的文档"文件夹的 Path 对象
    """
    try:
        CSIDL_PERSONAL = 5  # My Documents
        SHGFP_TYPE_CURRENT = 0  # Get current, not default value
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, SHGFP_TYPE_CURRENT, buf)
        documents_path = Path(buf.value)
    except Exception as e:
        logger.error(f'调用 Windows API 获取"我的文档"文件夹位置失败 ({e})，将返回默认路径。')
        documents_path = Path.home() / "Documents"

    return documents_path


def get_steam_exe_path() -> Optional[str]:
    """
    从 Windows 注册表中获取 steam.exe 的路径。

    :return: steam.exe 的完整路径字符串。如果未找到，返回 None
    """
    try:
        # HKEY_CURRENT_USER\Software\Valve\Steam
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
        steam_path, _ = winreg.QueryValueEx(key, "SteamExe")
        winreg.CloseKey(key)
        return steam_path
    except FileNotFoundError:
        logger.error("错误: 找不到 Steam 的注册表项。请确保 Steam 已安装。")
        return None
    except Exception as e:
        logger.error(f"读取注册表时发生未知错误: {e}")
        return None

def get_system_proxy() -> Optional[str]:
    """
    使用 urllib3 获取系统代理。优先获取socks代理，其次是http代理。

    :return: 代理字符串。如果未找到，返回 None
    """
    socks_proxy = getproxies().get("socks", None)
    http_proxy = getproxies().get("http", None)
    if socks_proxy:
        return socks_proxy
    elif http_proxy:
        return http_proxy
    else:
        return None

def exec_command_detached(command: list[str]):
    """
    以分离模式执行一个命令行指令。

    :param command: 要执行的命令行指令
    :raises ``Exception``: 启动命令失败
    """
    try:
        # subprocess.Popen 可以避免阻塞主进程
        # CREATE_BREAKAWAY_FROM_JOB 使主程序退出时不会关闭子进程
        subprocess.Popen(
            command,
            shell=True,
            creationflags=subprocess.CREATE_BREAKAWAY_FROM_JOB,
            close_fds=True,
        )
    except Exception as e:
        # Nuitka 打包时会错误地对f-string中的引号报错，改为字符串拼接
        raise Exception("执行命令 '" + " ".join(command) + "' 失败: " + str(e)) from e
