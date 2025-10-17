from typing import Optional

from logger import get_logger
from windows_utils import (
    find_window,
    kill_processes,
    resume_process_from_suspend,
    suspend_process_for_duration,
)

logger = get_logger(name="automator_process")


class GameProcess:
    """封装与游戏窗口和进程相关的各种方法"""

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

    def __init__(
        self,
        hwnd: Optional[int] = None,
        pid: Optional[int] = None,
    ):
        self.hwnd = hwnd  # 窗口句柄
        self.pid = pid  # 进程ID

    def update_gta_window_info(self):
        """
        根据窗口标题和进程名称，更新 GTA V 窗口句柄和进程 PID。

        如果未找到 GTA V 窗口，将设置窗口句柄和 PID 为 None。
        """
        # 仅适用于增强版
        logger.info("正在更新 GTA V 窗口信息...")
        window_info = find_window("Grand Theft Auto V", "GTA5_Enhanced.exe")
        if window_info:
            logger.debug(f"找到 GTA V 窗口。窗口句柄: {self.hwnd}, 进程ID: {self.pid}")
            self.hwnd, self.pid = window_info
            logger.info("更新 GTA V 窗口信息完成。")
        else:
            logger.error("未找到 GTA V 窗口，更新窗口信息失败。")
            self.hwnd, self.pid = None, None
            return

    def suspend_gta_process(self, suspend_time: float):
        """
        将 GTA V 进程挂起指定时间。

        :param suspend_time: 挂起时间，单位秒
        """
        if self.pid:
            try:
                suspend_process_for_duration(self.pid, suspend_time)
            except ValueError:
                logger.error(f"挂起 GTA V 进程失败，GTA V 进程 PID({self.pid}) 无效。")
                self.update_gta_window_info()
            except Exception as e:
                logger.error(f"挂起 GTA V 进程时，发生异常: {e}")

    def resume_gta_process(self):
        """将 GTA V 进程从挂起中恢复"""
        if self.pid:
            try:
                resume_process_from_suspend(self.pid)
            except Exception as e:
                # 所有异常都不做处理
                logger.error(f"恢复 GTA V 进程时，发生异常: {e}")

    def kill_gta(self):
        """杀死 GTA V 进程，并且清除窗口句柄和 PID 。"""
        logger.info("动作: 正在杀死 GTA V 相关进程。。。")
        kill_processes(self.GTA_PROCESS_NAMES)
        self.hwnd, self.pid = None, None
        logger.info("杀死 GTA V 相关进程完成。")
