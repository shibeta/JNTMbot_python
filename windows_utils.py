from pathlib import Path
from contextlib import contextmanager
import ctypes.wintypes
import sys
import time
from urllib.request import getproxies
import psutil
import subprocess
import winreg
import win32gui
import win32process
import win32api
import win32print
from win32con import (
    DESKTOPHORZRES,
    SW_RESTORE,
    HWND_TOPMOST,
    HWND_NOTOPMOST,
    THREAD_SUSPEND_RESUME,
    SWP_NOMOVE,
    SWP_NOSIZE,
    SWP_NOACTIVATE,
    SWP_SHOWWINDOW,
    WM_CLOSE,
)
from typing import Optional

from logger import get_logger

logger = get_logger(__name__)


class SuspendException(Exception):
    """挂起进程或线程时，触发的异常"""

    pass


class ResumeException(Exception):
    """恢复进程或线程时，触发的异常"""

    pass


@contextmanager
def open_thread_handle(tid: int):
    """一个用于安全打开和关闭线程句柄的上下文管理器。"""
    thread_handle = None
    try:
        thread_handle = win32api.OpenThread(THREAD_SUSPEND_RESUME, False, tid)
        if not thread_handle:
            # 如果打开失败，OpenThread 返回 None 或 0
            raise ValueError(f"打开线程 {tid} 失败，可能线程不存在或权限不足。")

        yield thread_handle  # 将句柄交给 with 块使用

    finally:
        if thread_handle:
            win32api.CloseHandle(thread_handle)


def is_window_handler_exist(hwnd: int) -> bool:
    """
    检查窗口句柄是否有效

    :param hwnd: 窗口句柄 (整数)
    :return: True表示窗口存在，False表示不存在
    """
    if hwnd == 0:
        return False
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
    if hwnd == 0:
        return None
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
    if pid == 0:
        return None
    try:
        return psutil.Process(pid).name()
    except:
        return None


def get_window_thread_id(hwnd: int) -> Optional[int]:
    """
    获取一个窗口的线程ID

    :param hwnd: 窗口句柄 (整数)
    :return: 线程ID。如果未找到窗口，或者未找到窗口线程，会返回 None
    :raises TypeError: hwnd 类型错误
    """
    if not isinstance(hwnd, int):
        logger.error(f"参数 hwnd 类型错误，期望为 int，实际为 {type(hwnd).__name__}。")
        raise TypeError("窗口句柄必须是一个整数")

    if hwnd == 0:
        return None

    try:
        thread_id, _ = win32process.GetWindowThreadProcessId(hwnd)
        if thread_id == 0:
            logger.error(f"无法找到与窗口句柄 {hwnd} 关联的线程ID。")
            return None
        else:
            return thread_id
    except Exception as e:
        logger.error(f"获取线程ID时出错: {e} (可能窗口已关闭)")
        return None


def enable_dpi_awareness():
    """
    启用 Python 进程的 DPI Awareness。
    在 Windows 8.1+ 上可以获取实时的 DPI 值，在低版本系统仅能获取应用程序启动时的系统 DPI。
    可能与部分截图或屏幕录制库冲突。

    :return:
        - True: 成功启用了 DPI Awareness
        - False: 失败
    """
    version = sys.getwindowsversion()[:2]
    try:
        if version >= (6, 3):
            # Windows 8.1+
            # PROCESS_PER_MONITOR_DPI_AWARE = 2
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        elif (6, 0) <= version < (6, 3):
            # Windows Vista, 7, 8, Server 2012
            # 早期的系统版本仅能配置为 PROCESS_SYSTEM_DPI_AWARE
            ctypes.windll.user32.SetProcessDPIAware()
        return True
    except Exception as e:
        logger.error(f"设置 DPI Awareness 失败: {e}")
        return False


def get_window_dpi_scale(hwnd: int):
    """
    获取指定窗口所在显示器的 DPI 缩放比例。获取失败将返回 1.0 。
    必须设置 Python 进程为 DPI Awareness，才能获取缩放比例。

    :param hwnd: 目标窗口的句柄。
    :return: DPI缩放比例 (例如 1.0, 1.25, 1.5)。
    """
    if not isinstance(hwnd, int) or hwnd == 0:
        logger.warning(f"窗口句柄 '{hwnd}' 不是一个有效的非零整数。")
        return 1.0
    try:
        # 调用 Shcore.dll 的 GetDpiForMonitor 函数获取 DPI 缩放
        # 函数签名: HRESULT GetDpiForMonitor(HMONITOR hmonitor, int dpiType, UINT *dpiX, UINT *dpiY)
        shcore = ctypes.windll.shcore
        monitor = win32api.MonitorFromWindow(hwnd)  # 从窗口句柄获取显示器句柄
        dpi_x = ctypes.c_uint()
        dpi_y = ctypes.c_uint()

        # MONITOR_DPI_TYPE 0: MDT_EFFECTIVE_DPI
        # 我们关心的是有效DPI，它考虑了用户的缩放设置
        result = shcore.GetDpiForMonitor(int(monitor), 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))

        if result != 0:
            # 如果调用失败，返回默认值
            return 1.0

        # 标准DPI是96，计算缩放比例
        # 通常 dpi_x 和 dpi_y 是相等的
        return dpi_x.value / 96.0

    except Exception as e:
        logger.error(f"获取DPI缩放比例时发生异常: {e}", exc_info=e)
        # 在一些非常老的系统上, Shcore.dll 不可用，返回默认值
        return 1.0


def get_primary_monitor_dpi_scale():
    """
    获取主显示器的 DPI 缩放比例。
    必须设置 Python 进程为不支持 DPI Awareness，才能获取缩放比例。

    :return: DPI缩放比例 (例如 1.0, 1.25, 1.5)。
    """
    return round(
        win32print.GetDeviceCaps(win32gui.GetDC(0), DESKTOPHORZRES) / win32api.GetSystemMetrics(0),
        2,
    )


def find_window(window_class: Optional[str] = None, window_title: Optional[str] = None):
    """
    通过窗口类名, 窗口标题查找窗口，返回窗口句柄和进程ID。

    :param window_class: 窗口类名，可选，与 window_title 至少要提供一个
    :param window_title: 窗口标题，可选，与 window_class 至少要提供一个
    :return: 如果找到符合条件的窗口，返回 (hwnd, pid) 元组，否则返回 None
    """
    if window_class is None and window_title is None:
        logger.warning("查找窗口必须要提供窗口类名或窗口标题。")
        return None

    # 使用 FindWindow 直接查找窗口
    hwnd = win32gui.FindWindow(window_class, window_title)
    if hwnd == 0:
        return None

    # 获取窗口对应进程的 PID
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    if pid == 0:
        return None

    return hwnd, pid


def suspend_thread(tid: int):
    """
    挂起一个线程。

    :param tid: 要挂起的线程的 TID
    :return: 线程之前的挂起计数 (>=0)。
    :raises ``SuspendException``: 挂起线程失败
    """
    try:
        with open_thread_handle(tid) as thread_handle:
            result = win32process.SuspendThread(thread_handle)
            if result < 0:
                raise SuspendException(f"调用 SuspendThread API 失败，线程TID: {tid}")
            return result
    except (IOError, Exception) as e:
        raise SuspendException(f"挂起线程 {tid} 时发生异常: {e}") from e


def resume_thread(tid: int) -> int:
    """
    从挂起中恢复一个线程。如果线程未挂起则没有副作用。

    :param tid: 要恢复的线程的 TID
    :return: 线程之前的挂起计数 (>=0)。
    :raises ResumeException: 恢复线程失败
    """
    try:
        with open_thread_handle(tid) as thread_handle:
            result = win32process.ResumeThread(thread_handle)
            if result < 0:
                raise ResumeException(f"调用 ResumeThread API 失败，线程TID: {tid}")
            return result
    except (IOError, Exception) as e:
        raise ResumeException(f"恢复线程 {tid} 时发生异常: {e}") from e


def suspend_window_thread_for_duration(hwnd: int, duration_seconds: float):
    """
    将一个窗口的线程挂起指定的时长，然后恢复它。

    :param hwnd: 要挂起的窗口的句柄
    :param duration_seconds: 要挂起的时间(秒)
    :raises ``ValueError``: 提供的 hwnd 无效，或未找到其窗口线程
    :raises ``SuspendException``: 挂起进程时失败
    :raises ``ResumeException``: 恢复进程时失败 (严重错误，可能导致线程永久挂起)
    """
    thread_id = get_window_thread_id(hwnd)
    if thread_id is None or thread_id == 0:
        raise ValueError(f"无法挂起：未找到窗口 {hwnd} 的主线程")

    try:
        logger.info(f"正在挂起线程 {thread_id}，持续 {duration_seconds} 秒。")
        suspend_thread(thread_id)
    except:
        logger.error(f"挂起线程 {thread_id} 失败，操作中止。")
        raise

    try:
        time.sleep(duration_seconds)
    finally:
        logger.info(f"正在恢复线程 {thread_id}...")
        try:
            resume_thread(thread_id)
            logger.info(f"线程 {thread_id} 已恢复。")
        except ResumeException as e:
            # 记录严重错误并重新抛出，让上层调用者知道发生了重大问题
            logger.critical(f"恢复线程 {thread_id} 失败！该线程可能被永久挂起，导致关联的窗口无响应。")
            raise e


def ensure_window_thread_resumed(hwnd: int):
    """
    确保一个窗口的线程恢复运行。

    此函数会持续调用 resume_thread，直到线程的挂起计数为0。

    :param hwnd: 目标窗口的句柄
    :raises ValueError: 提供的 hwnd 无效，或未找到其关联的线程
    :raises ResumeException: 在最大尝试次数后线程仍未恢复，或者在尝试恢复过程中发生不可恢复的错误。
    """
    thread_id = get_window_thread_id(hwnd)
    if thread_id is None:
        raise ValueError(f"无法操作：未找到窗口 {hwnd} 的线程ID")

    MAX_RESUME_ATTEMPTS = 5
    logger.info(f"正在尝试恢复线程 {thread_id} (窗口 {hwnd}) 运行...")

    for _ in range(MAX_RESUME_ATTEMPTS):
        try:
            previous_suspend_count = resume_thread(thread_id)

            if previous_suspend_count == 0:
                # 如果之前的挂起计数0，那么现在肯定是0。
                logger.info(f"线程 {thread_id} 已确认恢复运行。")
                return

        except ResumeException as e:
            # 如果 resume_thread 内部失败 (例如 OpenThread 失败)，
            # 那么继续尝试没有意义。
            logger.error(f"在尝试恢复线程 {thread_id} 时发生错误，操作中止。")
            raise ResumeException(f"无法恢复线程 {thread_id}，底层API调用失败。") from e

    # 如果循环正常结束（即从未成功返回），则意味着达到了最大尝试次数
    raise ResumeException(f"在 {MAX_RESUME_ATTEMPTS} 次尝试后未能恢复线程 {thread_id}")


def suspend_process_for_duration(pid: int, duration_seconds: float):
    """
    将一个进程挂起指定的时长，然后恢复它。

    :param pid: 要挂起的进程的 PID
    :param duration_seconds: 要挂起的时间(秒)
    :raises ``ValueError``: 提供的 PID 无效或不存在
    :raises ``SuspendException``: 挂起进程时失败
    :raises ``ResumeException``: 恢复进程时失败
    """
    try:
        proc = psutil.Process(pid)
        logger.info(f"正在挂起进程 {pid}，持续 {duration_seconds} 秒。")
        proc.suspend()
        time.sleep(duration_seconds)
    except psutil.NoSuchProcess:
        raise ValueError(f"无法挂起：未找到 PID 为 {pid} 的进程")
    except Exception as e:
        raise SuspendException(f"挂起进程 {pid} 时发生异常: {e}") from e
    finally:
        # 无论如何总是恢复进程
        resume_process(pid)


def resume_process(pid: int, max_retries: int = 5):
    """
    将一个挂起的进程恢复。如果进程未被挂起则没有副作用。

    :param pid: 要恢复的进程的 PID
    :param max_retries: 恢复进程的最大尝试次数
    :raises ``ValueError``: 提供的 PID 无效或不存在
    :raises ``ResumeException``: 恢复进程失败
    """
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        raise ValueError(f"无法从挂起恢复：未找到 PID 为 {pid} 的进程")

    try:
        proc.resume()
    except psutil.NoSuchProcess:
        return  # 进程可能在操作期间关闭了
    except Exception as e:
        logger.error(f"恢复进程 {pid} 时出错: {e}")

    # 检查进程是否仍处于挂起状态
    for retries in range(max_retries - 1):
        # 稍微等待一下，因为 NtResumeProcess 是异步触发的
        time.sleep(0.1)
        try:
            # 注意：如果进程卡死在内核态，status 可能不准，但这是唯一的非侵入式检查手段
            current_status = proc.status()
            if current_status in {
                psutil.STATUS_RUNNING,
                psutil.STATUS_SLEEPING,
                psutil.STATUS_DISK_SLEEP,
            }:
                logger.info(f"已恢复进程 {pid}。")
                return
            elif current_status == psutil.STATUS_STOPPED:
                logger.warning(f"进程 {pid} 仍处于挂起状态，正在尝试第 {retries + 1} 次额外恢复...")
                proc.resume()
            elif current_status in {
                psutil.STATUS_ZOMBIE,
                psutil.STATUS_DEAD,
            }:
                raise ResumeException(f"无法从挂起恢复：进程 {pid} 已变成僵尸或死亡进程")
            else:
                # 其他状态假设进程已恢复
                logger.info(f"进程 {pid} 处于非挂起状态 ({current_status})，视为已恢复。")
                return

        except psutil.NoSuchProcess:
            return  # 进程可能在操作期间关闭了
        except ResumeException:
            raise
        except Exception as e:
            logger.error(f"恢复进程 {pid} 时出错: {e}")

    raise ResumeException(f"尝试了 {max_retries} 次仍无法恢复进程 {pid} ，进程可能被外部调试器挂起或锁死")


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
                logger.debug(f"没有找到名为 '{proc_name}' 的正在运行的进程。")
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
    win32gui.PostMessage(hwnd, WM_CLOSE, 0, 0)


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
        raise Exception(f"激活窗口 {hwnd} 时出错: {e}") from e


def restore_minimized_window(hwnd: int):
    """
    将传入的窗口句柄从最小化还原。
    传入的句柄无效或未被最小化则不做任何事。

    :param hwnd: 窗口句柄
    :type hwnd: int
    :return:
        - True: 窗口存在且被最小化，已从最小化中恢复
        - False: 窗口不存在，或窗口未被最小化
    """
    if not is_window_handler_exist(hwnd):
        return False

    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, SW_RESTORE)
            return True
        else:
            return False
    except Exception as e:
        raise Exception(f"恢复窗口 {hwnd} 时出错: {e}") from e


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
        if restore_minimized_window(hwnd):
            time.sleep(0.2)  # 等待窗口恢复
        # 将窗口置顶
        win32gui.SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW | SWP_NOACTIVATE
        )
    except Exception as e:
        raise Exception(f"置顶窗口 {hwnd} 时出错: {e}") from e


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
        raise Exception(f"取消置顶窗口 {hwnd} 时出错: {e}") from e


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
    使用 urllib3 获取系统代理。优先获取 HTTP 代理，其次是 SOCKS 代理。

    :return: 代理字符串。如果未找到，返回 None
    """
    http_proxy = getproxies().get("http", None)
    socks_proxy = getproxies().get("socks", None)
    if http_proxy:
        return http_proxy
    elif socks_proxy:
        return socks_proxy
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
        command_string = " ".join(command)
        raise Exception(f"执行命令 '{command_string}' 失败: {e}") from e
