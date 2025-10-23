import atexit
from typing import Optional

from logger import get_logger
from windows_utils import (
    find_window,
    get_process_name,
    get_window_title,
    close_window,
    kill_processes,
    resume_process_from_suspend,
    suspend_process_for_duration,
)

logger = get_logger(name="game_process")


class GameProcess:
    """封装与游戏窗口和进程相关的各种方法"""

    # 与 GTA V 增强版相关的进程名称列表
    GTA_ASSOCIATED_PROCESS_NAMES = [
        "GTA5.exe",
        "GTA5_Enhanced.exe",
        "GTA5_Enhanced_BE.exe",
        "PlayGTAV.exe",
        "RockstarErrorHandler.exe",
        "RockstarService.exe",
        "SocialClubHelper.exe",
        "Launcher.exe",
    ]
    # GTA V 增强版进程名
    GTA_PROCESS_NAMES = "GTA5_Enhanced.exe"
    # GTA V 增强版窗口标题
    GTA_WINDOW_TITLE = "Grand Theft Auto V"

    def __init__(
        self,
        hwnd: Optional[int] = None,
        pid: Optional[int] = None,
    ):
        self.hwnd = hwnd  # 窗口句柄
        self.pid = pid  # 进程ID

        # 注册退出处理函数，以确保Python程序退出时 GTA V 进程不会被挂起
        atexit.register(self.resume)

    def update_info(self, hwnd: Optional[int] = None, pid: Optional[int] = None):
        """
        传入窗口句柄和 PID ，更新对象的信息。

        如果未提供，则根据窗口标题和进程名寻找窗口句柄和 PID 。未找到将设置窗口句柄和 PID 为 None。
        """
        # 仅适用于增强版
        logger.info("正在更新 GTA V 进程信息...")
        if hwnd and pid:
            logger.debug(f"使用传入的窗口句柄: {self.hwnd}, 进程ID: {self.pid} 更新进程信息。")
            self.hwnd, self.pid = hwnd, pid
        else:
            info = find_window(self.GTA_WINDOW_TITLE, self.GTA_PROCESS_NAMES)
            if info:
                logger.debug(f"找到 GTA V 窗口。窗口句柄: {self.hwnd}, 进程ID: {self.pid}")
                self.hwnd, self.pid = info
            else:
                logger.error("未找到 GTA V 窗口。")
                self.hwnd, self.pid = None, None
                return

        logger.info("更新 GTA V 进程信息完成。")

    def suspend(self, suspend_time: float):
        """
        将 GTA V 进程挂起指定时间。如果 GTA V 未启动，则不做任何事。

        :param suspend_time: 挂起时间，单位秒
        """
        if self.pid:
            try:
                suspend_process_for_duration(self.pid, suspend_time)
            except ValueError:
                logger.error(f"挂起 GTA V 进程失败，GTA V 进程 PID({self.pid}) 无效。")
                self.update_info()
            except Exception as e:
                logger.error(f"挂起 GTA V 进程时，发生异常: {e}")

    def resume(self):
        """将 GTA V 进程从挂起中恢复。如果 GTA V 未启动，则不做任何事。"""
        if self.pid:
            try:
                resume_process_from_suspend(self.pid)
            except Exception as e:
                # 所有异常都不做处理
                logger.error(f"恢复 GTA V 进程时，发生异常: {e}")

    def kill(self):
        """杀死 GTA V 所有相关进程，并且清除窗口句柄和 PID 。"""
        kill_processes(self.GTA_ASSOCIATED_PROCESS_NAMES)
        self.hwnd, self.pid = None, None

    def request_exit(self):
        """
        触发 alt+f4 退出，如果 GTA V 未启动，则不做任何事。

        :raises ``Exception``: 向 GTA V 进程发出中断信号时出错
        """
        if self.hwnd:
            try:
                close_window(self.hwnd)
            except Exception as e:
                raise Exception("触发 alt+f4 退出失败") from e

    # --- 状态检查方法 ---
    @staticmethod
    def is_game_started() -> bool:
        """
        检查游戏是否启动。
        **注意这个方法不会检查或修改对象记录的游戏信息，需要手动更新**。
        """
        window_info = find_window(GameProcess.GTA_WINDOW_TITLE, GameProcess.GTA_PROCESS_NAMES)
        if window_info:
            return True
        else:
            return False

    def is_hwnd_valid(self) -> bool:
        """检查窗口句柄是否有效。"""
        if self.hwnd and self.GTA_WINDOW_TITLE == get_window_title(self.hwnd):
            return True
        else:
            return False

    def is_pid_vaild(self) -> bool:
        """检查进程 PID 是否有效。"""
        if self.pid and self.GTA_PROCESS_NAMES == get_process_name(self.pid):
            return True
        else:
            return False
