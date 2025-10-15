from pathlib import Path
import struct
import time
import os
from typing import List, Optional, Tuple, Union
import requests
import re
import atexit
import ctypes.wintypes

from config import Config
from ocr_utils import OCREngine
from keyboard_utils import KeyboardSimulator
from gamepad_utils import GamepadSimulator, Button, JoystickDirection
from steambot_utils import SteamBotClient
from process_utils import (
    find_window,
    resume_process_from_suspend,
    suspend_process_for_duration,
    kill_processes,
    unset_top_window,
)
from logger import get_logger
from gameautomator_exception import *

logger = get_logger(name="gta5_utils")


class GameAutomator:
    """封装了所有用于自动化 GTA V 内操作的逻辑。"""

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
        config: Config,
        ocr_engine: OCREngine,
        steam_bot: SteamBotClient,
        hwnd: int = None,
        pid: int = None,
    ):
        self.config = config
        self.ocr = ocr_engine
        self.steam_bot = steam_bot
        self.hwnd = hwnd
        self.pid = pid
        self.gamepad = GamepadSimulator()

        # 注册一个退出处理函数，以确保Python程序退出时 GTA V 进程不会被挂起
        atexit.register(self._resume_gta_process)
        # 注册一个退出处理函数，以确保Python程序退出时 GTA V 窗口不会处于置顶状态
        atexit.register(self._unset_gta_window_topmost)

    def glitch_single_player_session(self):
        """通过暂停进程卡单人战局"""
        logger.info("动作: 正在卡单人战局。。。")
        try:
            suspend_process_for_duration(self.pid, self.config.suspendGTATime)
        except ValueError as e:
            logger.error(f"卡单人战局失败，GTA V 进程 PID({self.pid}) 无效。")
            self._update_gta_window_info()
        except Exception as e:
            # 其他异常不做处理
            logger.error(f"卡单人战局时，发生异常: {e}")

        logger.info("卡单人战局完成。")

    def _update_gta_window_info(self):
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
            self.hwnd, self.pid = None
            return

    def _resume_gta_process(self):
        """将 GTA V 进程从挂起中恢复"""
        if self.pid:
            try:
                resume_process_from_suspend(self.pid)
            except Exception as e:
                # 所有异常都不做处理
                logger.error(f"恢复 GTA V 进程时，发生异常: {e}")

    def _unset_gta_window_topmost(self):
        """将 GTA V 窗口取消置顶"""
        if self.hwnd:
            try:
                unset_top_window(self.hwnd)
            except Exception:
                # 所有异常都不做处理
                logger.error(f"取消 GTA V 窗口置顶时，发生异常: {e}")

    def kill_gta(self):
        """杀死 GTA V 进程，并且清除窗口句柄和 PID 。"""
        logger.info("动作: 正在杀死 GTA V 相关进程。。。")
        kill_processes(self.GTA_PROCESS_NAMES)
        self.hwnd, self.pid = None, None
        logger.info("杀死 GTA V 相关进程完成。")

    def setup_gta(self):
        """
        确保 GTA V 启动，同时更新 PID 和窗口句柄。

        :raises ``UnexpectedGameState(expected=lambda state: state.is_running, actual=GameState.OFF)``: 启动 GTA V 失败
        """
        logger.info("动作: 正在初始化 GTA V 。。。")

        if not self.is_game_started():
            # 没启动就先启动
            logger.warning("GTA V 未启动。正在启动游戏...")
            # 尝试启动 restartGTAConsecutiveFailThreshold 次，至少一次
            for retry_times in range(max(self.config.restartGTAConsecutiveFailThreshold, 1)):
                self.kill_and_restart_gta()
                if self.is_game_started():
                    # 启动过程中会自己设置 PID 和窗口句柄, 不需要做任何事
                    return
                else:
                    logger.warning(f"GTA V 启动失败。将重试 {5-1-retry_times} 次。")
                    continue
            else:
                # 达到最大失败次数后抛出异常
                logger.error("GTA V 启动失败次数过多，认为游戏处于无法启动的状态。")
                raise UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)
        else:
            # 如果启动了则更新 PID 和窗口句柄
            self._update_gta_window_info()

        # 以防万一将其从挂起中恢复
        self._resume_gta_process()

        logger.info("初始化 GTA V 完成。")

    def ocr_game_window(self, left, top, width, height) -> str:
        """
        对游戏窗口的指定区域执行 OCR，并返回识别结果。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        if not self.hwnd:
            raise UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)

        return self.ocr.ocr(self.hwnd, left, top, width, height)

    def _search_in_text(
        self,
        content_to_search: str,
        query_text: Union[str, List[str], Tuple[str, ...], re.Pattern[str]],
    ) -> bool:
        """
        辅助函数，用于检查文本是否存在于给定的字符串中。
        """
        if isinstance(query_text, re.Pattern):
            return query_text.search(content_to_search) is not None
        elif isinstance(query_text, (list, tuple)):
            pattern_str = "|".join(re.escape(text) for text in query_text)
            return re.search(pattern_str, content_to_search) is not None
        else:
            return query_text in content_to_search

    def _search_text_in_area(
        self,
        query_text: Union[str, List[str], Tuple[str, ...], re.Pattern[str]],
        left: float,
        top: float,
        width: float,
        height: float,
    ) -> bool:
        """
        辅助函数，用于检查文本是否存在于游戏窗口的指定区域。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        # 执行 OCR
        ocr_result = self.ocr_game_window(left, top, width, height)

        return self._search_in_text(ocr_result, query_text)

    def _check_state(
        self,
        query_text: Union[str, List[str], Tuple[str, ...], re.Pattern[str]],
        ocr_text: Optional[str],
        left: float,
        top: float,
        width: float,
        height: float,
    ):
        """
        辅助函数，用于检查文本是否存在于游戏窗口的指定区域。

        - texts (Pattern): 如果是预编译的正则表达式对象，会用它来搜索。空的正则表达式总是返回 False。
        - texts (str): 如果是单个字符串，会检查该文本是否存在。空字符串总是返回 False。
        - texts (list/tuple): 如果是字符串列表/元组，会检查是否有至少一个元素存在。空列表/元组总是返回 False。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        # 检查参数有效性
        if isinstance(query_text, (list, tuple)):
            if not query_text:
                logger.warning(f'要查找的文本: "{query_text}" 是空列表/元组。')
                return False
        elif isinstance(query_text, re.Pattern):
            if not query_text.pattern:
                logger.warning(f"传入了从空字符串编译的Pattern。")
                return False
        else:
            if not query_text:
                logger.warning(f'要查找的文本: "{query_text}" 是空字符串。')
                return False

        if ocr_text is not None:
            return self._search_in_text(ocr_text, query_text)
        else:
            return self._search_text_in_area(query_text, left, top, width, height)

    _PATTERN_IS_ON_JOB_PANEL = re.compile("|".join(re.escape(text) for text in ["浑球", "办事", "角色"]))

    def get_job_setup_status(self) -> tuple[bool, int, int]:
        """
        检查差事面板状态，包括是否在面板中，以及加入的玩家数。
        如果不在面板中玩家数将固定返回-1。

        :return: 是否在面板(bool)，正在加入的玩家数(int)，已经加入的玩家数(int)，待命状态的玩家数(int)
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        ocr_result = self.ocr_game_window(0.5, 0, 0.5, 1)

        # 使用正则表达式搜索是否在面板中
        if re.search(self._PATTERN_IS_ON_JOB_PANEL, ocr_result) is not None:
            # 在面板中则识别加入玩家数
            # "离开"是加入失败，可以认为这也是一种"正在加入"状态
            joining_count = ocr_result.count("正在") + ocr_result.count("离开")
            joined_count = ocr_result.count("已加")
            standby_count = ocr_result.count("待命")

            return True, joining_count, joined_count, standby_count
        else:
            # 不在面板中则跳过识别直接返回-1
            return False, -1, -1, -1

    # --- 状态检查方法 ---
    def is_game_started(self) -> bool:
        """检查游戏是否启动。"""
        window_info = find_window("Grand Theft Auto V", "GTA5_Enhanced.exe")
        if window_info:
            logger.debug(f"GTA V 已启动。窗口句柄: {window_info[0]}, 进程ID: {window_info[1]}")
            return True
        else:
            logger.debug("未找到 GTA V 窗口。GTA V 未启动。")
            return False

    _PATTERN_IS_ON_MAINMENU_GTAPLUS_ADVERTISEMENT_PAGE = re.compile(
        "|".join(re.escape(text) for text in ["导览", "跳过"])
    )

    def is_on_mainmenu_gtaplus_advertisement_page(self, ocr_text: Optional[str]) -> bool:
        """
        检查游戏是否在主菜单的gta+广告页面。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(
            self._PATTERN_IS_ON_MAINMENU_GTAPLUS_ADVERTISEMENT_PAGE, ocr_text, 0.5, 0.8, 0.5, 0.2
        )

    def is_on_mainmenu_logout(self, ocr_text: Optional[str]) -> bool:
        """
        检查游戏是否在登出的主菜单页面。
        注意无法确认是在线页面还是 GTA+ 页面，因为两个页面的 OCR 结果是相同的。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state("已登出", ocr_text, 0, 0, 1, 1)

    def is_on_mainmenu_online_page(self, ocr_text: Optional[str]) -> bool:
        """
        检查游戏是否在主菜单的在线页面。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state("加入自由模式", ocr_text, 0, 0.5, 0.7, 0.5)

    def is_on_mainmenu_storymode_page(self, ocr_text: Optional[str]) -> bool:
        """
        检查游戏是否在主菜单的故事页面。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state("故事模式", ocr_text, 0, 0.5, 0.7, 0.5)

    def is_on_onlinemode_info_panel(self, ocr_text: Optional[str]) -> bool:
        """
        检查游戏是否在在线模式的左上角显示玩家信息的菜单。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state("在线模式", ocr_text, 0, 0, 0.4, 0.1)

    def is_respawned_in_agency(self, ocr_text: Optional[str]) -> bool:
        """
        检查玩家是否已在事务所的床上复活。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state("床", ocr_text, 0, 0, 0.5, 0.5)

    _PATTERN_IS_ON_JOB_PANEL = re.compile("|".join(re.escape(text) for text in ["别惹", "德瑞", "搭档"]))

    def is_on_job_panel(self, ocr_text: Optional[str]) -> bool:
        """
        检查当前是否在差事面板界面。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(self._PATTERN_IS_ON_JOB_PANEL, ocr_text, 0, 0, 0.5, 0.5)

    _PATTERN_IS_ON_FIRST_JOB_SETUP_PAGE = re.compile(
        "|".join(re.escape(text) for text in ["设置", "镜头", "武器"])
    )

    def is_on_first_job_setup_page(self, ocr_text: Optional[str]) -> bool:
        """
        检查当前是否在差事准备面板的第一页。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(self._PATTERN_IS_ON_FIRST_JOB_SETUP_PAGE, ocr_text, 0, 0, 1, 1)

    _PATTERN_IS_ON_SECOND_JOB_SETUP_PAGE = re.compile(
        "|".join(re.escape(text) for text in ["匹配", "邀请", "帮会"])
    )

    def is_on_second_job_setup_page(self, ocr_text: Optional[str]) -> bool:
        """
        检查当前是否在差事准备面板的第二页。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(self._PATTERN_IS_ON_SECOND_JOB_SETUP_PAGE, ocr_text, 0, 0, 1, 1)

    _PATTERN_IS_ON_SCOREBOARD = re.compile("|".join(re.escape(text) for text in ["别惹", "德瑞"]))

    def is_on_scoreboard(self, ocr_text: Optional[str]) -> bool:
        """
        检查当前是否在差事失败的计分板界面。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(self._PATTERN_IS_ON_SCOREBOARD, ocr_text, 0, 0, 0.5, 0.5)

    _PATTERN_IS_JOB_MARKER_FOUND = re.compile("|".join(re.escape(text) for text in ["猎杀", "约翰尼"]))

    def is_job_marker_found(self, ocr_text: Optional[str]) -> bool:
        """
        检查是否找到了差事的黄色光圈提示。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(self._PATTERN_IS_JOB_MARKER_FOUND, ocr_text, 0, 0, 0.5, 0.5)

    # 有时任务会以英文启动，因此检查"团队生命数"作为保底
    _PATTERN_IS_JOB_STARTED = re.compile(
        "|".join(re.escape(text) for text in ["前往", "出现", "汇报", "进度", "团队", "生命数"])
    )

    def is_job_started(self, ocr_text: Optional[str]) -> bool:
        """
        检查是否在别惹德瑞任务中。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(self._PATTERN_IS_JOB_STARTED, ocr_text, 0, 0.8, 1, 0.2)

    _PATTERN_IS_JOB_STARTING = re.compile("|".join(re.escape(text) for text in ["正在", "启动", "战局"]))

    def is_job_starting(self, ocr_text: Optional[str]) -> bool:
        """
        检查任务是否在启动中。如果使用 OCR 则进行 3 次检查，以避免游戏响应慢。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        if ocr_text is not None:
            return self._search_in_text(ocr_text, self._PATTERN_IS_JOB_STARTING)
        else:
            for _ in range(3):
                if self._search_text_in_area(self._PATTERN_IS_JOB_STARTING, 0.7, 0.9, 0.3, 0.1):
                    return True
                time.sleep(0.1)
            else:
                return False

    _PATTERN_IS_ON_WARNING_PAGE = re.compile("|".join(re.escape(text) for text in ["警告", "注意"]))

    def is_on_warning_page(self, ocr_text: Optional[str]) -> bool:
        """
        检查是否在黑屏警告页面。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(self._PATTERN_IS_ON_WARNING_PAGE, ocr_text, 0, 0, 1, 1)

    # 增强版是"目前无法从Rockstar云服务器下载您保存的数据"，确认后会返回主菜单
    # 传承版是"此时无法从Rockstar云服务器载入您保存的数据"，确认后会返回故事模式
    _PATTERN_IS_ON_BAD_PCSETTING_WARNING_PAGE = re.compile(
        "|".join(re.escape(text) for text in ["目前无法", "此时无法"])
    )

    def is_on_bad_pcsetting_warning_page(self, ocr_text: Optional[str]) -> bool:
        """
        检查是否在因 pcsetting.bin 损坏而无法进入在线模式的警告页面。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(self._PATTERN_IS_ON_BAD_PCSETTING_WARNING_PAGE, ocr_text, 0, 0, 1, 1)

    _PATTERN_IS_ON_PAUSE_MENU = re.compile("|".join(re.escape(text) for text in ["地图", "职业", "简讯"]))

    def is_on_pause_menu(self, ocr_text: Optional[str]) -> bool:
        """
        检查是否在暂停菜单。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(self._PATTERN_IS_ON_PAUSE_MENU, ocr_text, 0, 0, 0.5, 0.5)

    _PATTERN_IS_ON_GO_ONLINE_MENU = re.compile(
        "|".join(re.escape(text) for text in ["公开战局", "邀请的", "帮会战局", "公开帮会", "公开好友"])
    )

    def is_on_go_online_menu(self, ocr_text: Optional[str]) -> bool:
        """
        检查是否在"进入在线模式"菜单。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(self._PATTERN_IS_ON_GO_ONLINE_MENU, ocr_text, 0, 0, 0.5, 0.5)

    # --- 动作序列 ---
    def go_job_point_from_bed(self):
        """从事务所的床出发，下到一楼，移动到任务点附近。"""
        logger.info("动作：正在从事务所个人空间走到楼梯间...")
        # 走到柱子上卡住
        self.gamepad.hold_left_joystick(JoystickDirection.FULL_LEFTUP, 1500)
        # 走到个人空间门口
        self.gamepad.hold_left_joystick(JoystickDirection.FULL_RIGHT, 5500)
        # 走出个人空间的门
        start_time = time.monotonic()
        while time.monotonic() - start_time < 2:
            self.gamepad.hold_left_joystick(JoystickDirection.HALF_RIGHTDOWN, 250)
            self.gamepad.hold_left_joystick(JoystickDirection.HALF_RIGHTUP, 250)
        # 走到楼梯间门口
        self.gamepad.hold_left_joystick(JoystickDirection.FULL_RIGHT, 1000)
        # 走进楼梯门
        self.gamepad.hold_left_joystick(JoystickDirection.FULL_UP, 2200)
        # 走下楼梯
        logger.info("动作：正在下楼...")
        self.gamepad.hold_left_joystick(JoystickDirection.FULL_DOWN, 4000)
        self.gamepad.hold_left_joystick(JoystickDirection.FULL_RIGHTUP, 1500)
        self.gamepad.hold_left_joystick(JoystickDirection.FULL_LEFT, 4500)
        # 走出楼梯间
        start_time = time.monotonic()
        while time.monotonic() - start_time < self.config.goOutStairsTime / 1000.0:
            self.gamepad.hold_left_joystick(JoystickDirection.HALF_DOWN, 250)
            self.gamepad.hold_left_joystick(JoystickDirection.HALF_LEFT, 250)
        # 穿过走廊
        logger.info("动作：正在穿过差事层走廊...")
        start_time = time.monotonic()
        self.gamepad.hold_left_joystick((-0.95, -1.0), self.config.crossAisleTime)

    def find_job_point(self):
        """
        检查是否到达任务触发点。如果没有，会尝试向任务触发点移动。

        :raises ``UIElementNotFound(UIElementNotFoundContext.JOB_TRIGGER_POINT)``: 未找到任务触发点
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        # 一边搜索任务标记，一边向任务黄圈移动
        logger.info("动作：正在寻找差事触发点...")

        for _ in range(5):
            self.gamepad.hold_left_joystick(JoystickDirection.HALF_LEFT, self.config.walkLeftTimeGoJob)
            time.sleep(0.1)
            if self.is_job_marker_found():
                break
            self.gamepad.hold_left_joystick(JoystickDirection.HALF_DOWN, self.config.walkDownTimeGoJob)
            time.sleep(0.1)
            if self.is_job_marker_found():
                break
        else:
            raise UIElementNotFound(UIElementNotFoundContext.JOB_TRIGGER_POINT)

        logger.info("成功找到差事触发点。")

    def enter_job_setup(self):
        """在差事点上进入差事准备面板，目前只需要按一下十字键右键。"""
        logger.info("动作: 正在进入差事准备面板...")
        self.gamepad.click_button(Button.DPAD_RIGHT)
        logger.info("成功进入差事准备面板。")

    def start_new_match(self):
        """
        尝试从在线战局中切换到另一个仅邀请战局，必须在自由模式下才能工作。

        :raises ``UnexpectedGameState(expected={GameState.IN_ONLINE_LOBBY, GameState.IN_MISSION}, actual=GameState.UNKNOWN)``: 游戏状态未知，无法切换战局
        :raises ``UnexpectedGameState(expected={GameState.IN_MISSION, GameState.IN_ONLINE_LOBBY}, actual=GameState.OFF)``: 游戏未启动，无法切换战局
        """
        logger.info("动作: 正在切换新战局...")
        # 切换新战局会尝试5次，在不同次数中，会使用不同措施尝试使游戏回到"正常状态"。
        for new_match_error_count in range(5):
            if new_match_error_count > 0:
                logger.info("正在重试...")
            logger.info("动作: 正在打开暂停菜单...")
            # 第3次尝试时，先按B键返回游戏再打开菜单
            if new_match_error_count == 2:
                logger.info("动作: 尝试通过多次按 B 键来恢复正常状态...")
                for _ in range(7):
                    self.gamepad.click_button(Button.B)
                    time.sleep(0.5)
                logger.info("已停止按 B 键。")
            # 第4次尝试时，先按B键和A键返回游戏再打开菜单
            if new_match_error_count == 3:
                logger.info("动作: 尝试通过多次按 B 键和 A 键来恢复正常状态...")
                for _ in range(4):
                    self.gamepad.click_button(Button.B)
                    time.sleep(0.5)
                    self.gamepad.click_button(Button.A)
                    time.sleep(0.5)
                logger.info("已停止按 B 键和 A 键。")
            # 第5次尝试时，先卡单人战局再打开菜单
            if new_match_error_count == 4:
                logger.info("尝试通过卡单来恢复正常状态。")
                self.glitch_single_player_session()
            # 以下开始是正常的开始新战局的指令
            # 检查游戏状态
            if not self.is_game_started():
                raise UnexpectedGameState(
                    expected={GameState.IN_MISSION, GameState.IN_ONLINE_LOBBY}, actual=GameState.OFF
                )
            # 处理警告屏幕
            if self.is_on_warning_page():
                self.gamepad.click_button(Button.A)
                time.sleep(0.5)

            # 打开暂停菜单
            if not self.is_on_pause_menu():
                self.gamepad.click_button(Button.MENU)
                time.sleep(2)

            # 检查暂停菜单是否被打开，未打开则按菜单键并进行下一次尝试
            if not self.is_on_pause_menu():
                self.gamepad.click_button(Button.MENU)
                logger.warning(f"打开暂停菜单失败 (尝试次数 {new_match_error_count + 1})。")
                continue

            logger.info("成功打开暂停菜单。")

            # 尝试切换到在线选项卡以切换战局
            logger.info("动作: 正在打开切换战局菜单...")
            self.gamepad.click_button(Button.RIGHT_SHOULDER)
            time.sleep(2)
            self.gamepad.click_button(Button.A)
            time.sleep(1)
            for _ in range(5):
                self.gamepad.click_button(Button.DPAD_UP)
                time.sleep(0.6)
            self.gamepad.click_button(Button.A)
            time.sleep(1)

            # 验证当前是否在切换战局的菜单，未打开则按菜单键并进行下一次尝试
            if not self.is_on_go_online_menu():
                self.gamepad.click_button(Button.MENU)
                logger.warning(f"打开切换战局菜单失败 (尝试次数 {new_match_error_count})。")
                continue

            logger.info("成功打开切换战局菜单。")

            # 选择"仅邀请战局"选项，确认
            self.gamepad.click_button(Button.DPAD_DOWN)
            time.sleep(0.6)
            self.gamepad.click_button(Button.A)
            time.sleep(2)
            self.gamepad.click_button(Button.A)
            break
        else:
            logger.error(f"切换新战局失败次数过多，认为游戏正处于未知状态。")
            raise UnexpectedGameState({GameState.IN_ONLINE_LOBBY, GameState.IN_MISSION}, GameState.UNKNOWN)

        logger.info("成功进入新战局。")

    def setup_wait_start_job(self) -> bool:
        """
        初始化差事准备页面，等待队友，然后开始差事。

        :raises ``UIElementNotFound(UIElementNotFoundContext.JOB_SETUP_PANEL)``: 意外离开了任务面板
        :raises ``OperationTimeout(OperationTimeoutContext.WAIT_TEAMMATE)``: 长时间没有玩家加入，超时
        :raises ``OperationTimeout(OperationTimeoutContext.PLAYER_JOIN)``: 玩家长期卡在"正在加入"状态，超时
        :raises ``UnexpectedGameState(expected=GameState.JOB_PANEL_2, actual=GameState.BAD_JOB_PANEL_STANDBY_PLAYER)``: 发现"待命"状态的玩家
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        logger.info("动作: 正在等待队伍成员并开始差事...")

        # 导航面板以选中"开始差事"选项
        logger.info("动作: 正在设置差事面板...")
        self.gamepad.click_button(Button.DPAD_UP)
        time.sleep(0.8)
        self.gamepad.click_button(Button.A)
        time.sleep(1)
        self.gamepad.click_button(Button.DPAD_LEFT)  # 关闭匹配功能，防止玩家通过匹配功能意外进入该差事
        time.sleep(0.8)
        self.gamepad.click_button(Button.DPAD_UP)
        logger.info("差事面板设置完成")

        # 发送差事就绪消息
        try:
            self.steam_bot.send_group_message(self.config.msgOpenJobPanel)
        except requests.RequestException as e:
            # 发送信息失败，小事罢了，不影响自动化运行
            pass

        start_wait_time = time.monotonic()  # 记录开始等待的时间
        last_activity_time = start_wait_time  # 记录最近队伍状态变化的时间，当发生人数变化或玩家由"正在加入"变成"已加入"时，更新该时间
        last_joining_time = (
            start_wait_time  # 记录最近加入状态变化的时间，当"正在加入"的人数变化时，更新该时间
        )
        last_joining_count = 0  # 记录上一次 OCR 时"正在加入"的人数
        last_joined_count = 0  # 记录上一次 OCR 时"已加入"的人数

        # 长循环实现等待玩家加入和启动差事
        while True:
            current_time = time.monotonic()

            # 获取准备界面状态
            is_on_job_panel, joining_count, joined_count, standby_count = self.get_job_setup_status()

            # 不知为何离开任务面板
            if not is_on_job_panel:
                logger.error("等待玩家时意外离开了任务面板。")
                raise UIElementNotFound(UIElementNotFoundContext.JOB_SETUP_PANEL)

            logger.info(
                f"队伍状态: {joined_count} 人已加入, {joining_count} 人正在加入, {standby_count} 人待命。"
            )

            # 有待命状态玩家说明bot匹配关慢了
            if standby_count > 0:
                logger.error("等待玩家时发现有玩家处于待命状态，无法在这种情况下启动差事。")
                raise UnexpectedGameState(GameState.JOB_PANEL_2, GameState.BAD_JOB_PANEL_STANDBY_PLAYER)

            # 队伍人数从未满变为满员时，发送满员消息
            if joining_count + joined_count != last_joining_count + last_joined_count:
                if joined_count + joining_count >= 3:  # 队伍已满 (1个主机 + 3个玩家)
                    try:
                        self.steam_bot.send_group_message(self.config.msgTeamFull)
                    except requests.RequestException as e:
                        # 发送信息失败，小事罢了，不影响自动化运行
                        pass

            # 没人加入超时
            if (
                current_time - start_wait_time > self.config.matchPanelTimeout
                and last_joined_count == 0
                and last_joining_count == 0
                and joining_count == 0
                and joined_count == 0
            ):
                logger.warning("长时间没有玩家加入，放弃本次差事。")
                try:
                    self.steam_bot.send_group_message(self.config.msgWaitPlayerTimeout)
                except requests.RequestException as e:
                    # 发送信息失败，小事罢了，不影响自动化运行
                    pass
                raise OperationTimeout(OperationTimeoutContext.WAIT_TEAMMATE)

            # 有人卡在“正在加入”超时
            if (
                current_time - last_joining_time > self.config.joiningPlayerKick
                and last_joining_count > 0
                and joining_count > 0
            ):
                logger.warning('玩家长期卡在"正在加入"状态，放弃本次差事。')
                try:
                    self.steam_bot.send_group_message(self.config.msgJoiningPlayerKick)
                except requests.RequestException as e:
                    # 发送信息失败，小事罢了，不影响自动化运行
                    pass
                raise OperationTimeout(OperationTimeoutContext.PLAYER_JOIN)

            # 检查是否应该开始差事
            # 满员且设置了满员立即启动
            # 或者有已加入的并且没有未加入的，同时记录最近队伍状态变化的时间已经超过开始差事等待延迟
            if (joined_count == 3 and self.config.startOnAllJoined) or (
                current_time - last_activity_time > self.config.startMatchDelay
                and joined_count > 0
                and joining_count == 0
            ):
                logger.info("动作: 正在启动差事...")
                # 发送差事启动消息
                try:
                    self.steam_bot.send_group_message(self.config.msgJobStarting)
                except requests.RequestException as e:
                    # 发送信息失败，小事罢了，不影响自动化运行
                    pass
                self.gamepad.click_button(Button.A)
                # "正在启动战局" 不一定会马上出现
                time.sleep(0.5)
                if self.is_job_starting():
                    break
                else:
                    logger.warning("启动差事失败。")
                    # 有时确实启动不了
                    # 处理警告页面
                    if self.is_on_warning_page():
                        self.gamepad.click_button(Button.A)
                        time.sleep(0.5)

                    if self.is_on_job_panel():
                        # 如果还在差事页面可以等下次再试，直到超过卡比时间退出
                        logger.info("回到面板，将尝试继续启动。")
                        continue
                    else:
                        # 差事都没了就没办法了
                        logger.warning("未回到面板，无法继续，放弃本次差事。")
                        try:
                            self.steam_bot.send_group_message(self.config.msgJobStartFail)
                        except requests.RequestException as e:
                            # 发送信息失败，小事罢了，不影响自动化运行
                            pass
                        raise UIElementNotFound(UIElementNotFoundContext.JOB_SETUP_PANEL)

            # 队伍加入状态变化时，更新最近加入状态变化的时间，最近队伍状态变化的时间，上一次的正在加入人数，上一次的已加入人数
            if joining_count != last_joining_count or joined_count != last_joined_count:
                if joining_count != last_joining_count:
                    last_joining_time = current_time
                last_joining_count, last_joined_count = joining_count, joined_count
                last_activity_time = current_time

            # 休眠一段时间再继续检测
            time.sleep(self.config.checkLoopTime)

        logger.info("启动差事成功。")

    def exit_job_panel(self):
        """
        从差事准备面板退出到自由模式，如果不在差事准备面板中则行为是未定义的。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        logger.info("动作: 正在退出差事面板...")
        # 处理警告屏幕
        if self.is_on_warning_page():
            self.gamepad.click_button(Button.A)
            time.sleep(0.5)

        # 从差事准备面板退出
        ocr_result = self.ocr_game_window(0, 0, 1, 1)
        if self.is_on_second_job_setup_page(ocr_result):
            # 如果在差事面板的第二个页面，按两次 B 和一次 A 退出
            self.gamepad.click_button(Button.B)
            time.sleep(1)
            self.gamepad.click_button(Button.B)
            time.sleep(1)
            self.gamepad.click_button(Button.A)
            time.sleep(5)
        elif self.is_on_first_job_setup_page(ocr_result):
            # 如果在差事面板的第一个页面，按一次 B 和一次 A 退出
            self.gamepad.click_button(Button.B)
            time.sleep(1)
            self.gamepad.click_button(Button.A)
            time.sleep(5)

        logger.info("已退出差事面板。")

    # 不认为加入差传bot是一个好主意，重启游戏是更稳妥更快捷的处理方案
    def deprecated_try_to_join_jobwarp_bot(self):
        """
        尝试通过 SteamJvp 加入差传 Bot 战局。

        该方法应当在游戏启动后才能运行，否则会卡在steam确认启动游戏。

        注意该方法目前已废弃，将在未来版本中被移除。

        如何迁移到其他方法: 用于回到在线模式自由模式: 重启游戏。用于差传: alt+f4等40秒。用于换战局: 菜单寻找新战局

        :raises ``UnexpectedGameState(expected=lambda state: state.is_running, actual=GameState.OFF)``: 游戏未启动所以无法加入差传 Bot 战局
        :raises ``NetworkError(NetworkErrorContext.FETCH_WARPBOT_INFO)``: 从 mageangela 的接口获取差传 Bot 的战局链接时发生网络错误
        :raises ``NetworkError(NetworkErrorContext.JOIN_WARPBOT_SESSION)``: 加入所有差传 Bot 战局均失败
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        logger.info("动作: 正在加入差传 Bot 战局...")

        if not self.is_game_started():
            raise UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)
        # 从 mageangela 的接口获取差传 Bot 的战局链接
        try:
            res = requests.get("http://quellgtacode.mageangela.cn:52014/botJvp/", timeout=10)
            res.raise_for_status()
            bot_list = res.text.replace("\r", "").split("\n")
        except requests.RequestException as e:
            raise NetworkError(NetworkErrorContext.FETCH_WARPBOT_INFO)

        start_index = 3 + (self.config.jobTpBotIndex if self.config.jobTpBotIndex >= 0 else 0)
        bot_lines_to_try = (
            [bot_list[start_index]] if self.config.jobTpBotIndex >= 0 else bot_list[start_index:]
        )

        # 根据 config 中的配置决定加入哪些差传 Bot
        for line in bot_lines_to_try:
            if "|" not in line:
                continue
            _, jvp_id = line.split("|", 1)
            if not jvp_id:
                continue

            # 使用 Steam 加入差传 Bot 战局
            try:
                self.join_session_through_steam(jvp_id)
            except OperationTimeout as e:
                logger.error(f"加入差传 Bot 时，{e}")
            except UnexpectedGameState as e:
                logger.error(f"加入差传 Bot 时，{e}")

            if self.config.jobTpBotIndex >= 0:
                # 如果指定了索引，只尝试一次
                break
        else:
            raise NetworkError(NetworkErrorContext.JOIN_WARPBOT_SESSION)

        logger.info("成功加入差传 Bot 战局。")

    def join_session_through_steam(self, steam_jvp: str):
        """
        通过 Steam 的"加入游戏"功能，加入一个战局。

        必须在游戏启动时运行，否则会弹出一个程序当前无法处理的 Steam 警告窗口。

        :param steam_jvp: URL 编码后的 steam_jvp 参数
        :raises ``UnexpectedGameState(expected=lambda state: state.is_running, actual=GameState.OFF)``: 游戏未启动所以无法加入战局
        :raises ``OperationTimeout(OperationTimeoutContext.ONLINE_SESSION_JOIN)``: 加入战局时超时
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        logger.info(f"动作: 正在加入战局: {steam_jvp}")

        if not self.is_game_started():
            raise UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)

        steam_url = f"steam://rungame/3240220/76561199074735990/-steamjvp={steam_jvp}"
        os.startfile(steam_url)
        time.sleep(3)

        # 等待加入战局
        start_join_time = time.monotonic()
        has_triggered_single_session = False
        while time.monotonic() - start_join_time < 300:  # 5分钟加载超时
            self.gamepad.click_button(Button.A)
            time.sleep(0.5)
            self.gamepad.click_button(Button.DPAD_DOWN)
            time.sleep(1)
            if self._search_text_in_area("在线模式", 0, 0, 0.5, 0.5):
                # 进入了在线模式
                logger.info("成功加入战局。5 秒后将卡单以避免战局中有其他玩家。")
                time.sleep(5)
                self.glitch_single_player_session()
                break
            if not has_triggered_single_session and time.monotonic() - start_join_time > 30:
                # 等待 30 秒的时候先卡一次单
                logger.info("为缓解进入公开战局卡云，进行卡单。")
                self.glitch_single_player_session()
                has_triggered_single_session = True
        else:
            # 超时后再卡一次单，并且休息一会
            logger.info("加入战局时超时。尝试卡单以缓解。")
            self.glitch_single_player_session()
            time.sleep(10)
            raise OperationTimeout(OperationTimeoutContext.JOIN_ONLINE_SESSION)

        logger.info(f"成功加入战局: {steam_jvp}")

    def kill_and_restart_gta(self) -> bool:
        """
        杀死并重启 GTA V 游戏，并进入在线模式仅邀请战局。

        如果重启游戏失败，将杀死游戏进程。
        """
        logger.info(f"动作: 正在杀死并重启 GTA V...")

        self.kill_gta()
        logger.info("20秒后将重启 GTA V...")
        time.sleep(20)  # 等待20秒钟用于 steam 客户端响应 GTA V 退出
        # 以防万一
        self.kill_gta()

        # 启动游戏
        try:
            self.start_gta_steam()
        except OperationTimeout as e:
            logger.error(f"启动 GTA V 时，发生异常: {e}")
            self.kill_gta()
            return
        except UnexpectedGameState as e:
            logger.error(f"启动 GTA V 时，发生异常: {e}")
            self.kill_gta()
            return

        # 进入故事模式
        time.sleep(2)
        try:
            self.enter_storymode_from_mainmenu()
        except OperationTimeout as e:
            logger.error(f"进入故事模式时，发生异常: {e}")
            self.kill_gta()
            return
        except UIElementNotFound as e:
            logger.error(f"进入故事模式时，发生异常: {e}")
            self.kill_gta()
            return
        except UnexpectedGameState as e:
            logger.error(f"进入故事模式时，发生异常: {e}")
            self.kill_gta()
            return

        # 进入在线模式
        time.sleep(2)
        try:
            self.enter_onlinemode_from_storymode()
        except UIElementNotFound as e:
            logger.error(f"进入在线模式时，发生异常: {e}")
            self.kill_gta()
            return
        except UnexpectedGameState as e:
            logger.error(f"进入在线模式时，发生异常: {e}")
            if e.actual_state == GameState.BAD_PCSETTING_BIN:
                self.kill_gta()
                self.clean_pcsetting()
            else:
                self.kill_gta()
            return
        except OperationTimeout as e:
            logger.error(f"进入在线模式时，发生异常: {e}")
            self.kill_gta()
            return

        logger.info("重启 GTA V 成功。")

    def start_gta_steam(self):
        """
        如果 GTA V 没有启动，通过 Steam 启动游戏，并更新 pid 和 hwnd。

        如果 GTA V 已经启动，则仅更新 pid 和 hwnd，不做其他事。

        :raises ``OperationTimeout(OperationTimeoutContext.GAME_WINDOW_STARTUP)``: 等待游戏窗口出现超时
        :raises ``OperationTimeout(OperationTimeoutContext.MAIN_MENU_LOAD)``: 等待主菜单加载超时
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        # 游戏启动则仅更新 pid 和 hwnd
        if self.is_game_started():
            self._update_gta_window_info()
            logger.warning(
                "在游戏运行时，调用启动游戏方法将仅更新 GTA V 窗口信息。如果需要重启，请调用重启方法。"
            )
            return

        logger.info("动作: 正在通过 Steam 启动 GTA V...")
        os.startfile("steam://rungameid/3240220")

        # 等待 GTA V 进程启动
        logger.info("正在等待 GTA V 窗口出现...")
        process_start_time = time.monotonic()
        while time.monotonic() - process_start_time < 300:  # 5分钟总超时
            if self.is_game_started():
                logger.info("GTA V 窗口已出现，更新窗口信息。")
                self._update_gta_window_info()
                break
            time.sleep(5)
        else:
            raise OperationTimeout(OperationTimeoutContext.GAME_WINDOW_STARTUP)

        # 等待主菜单加载
        logger.info("正在等待主菜单出现...")
        main_menu_load_start_time = time.monotonic()
        while time.monotonic() - main_menu_load_start_time < 180:  # 3分钟加载超时
            if self.is_on_mainmenu_online_page():
                logger.info("主菜单已加载。")
                break
            elif self.is_on_mainmenu_gtaplus_advertisement_page():
                # 有时候主菜单会展示一个显示 GTA+ 广告的窗口
                time.sleep(2)
                self.gamepad.click_button(Button.A)
                logger.info("主菜单已加载。")
                break
            time.sleep(5)
        else:
            # logger.error("重启 GTA 失败：等待主菜单加载超时。")
            raise OperationTimeout(OperationTimeoutContext.MAIN_MENU_LOAD)

        logger.info("已启动 GTA V。")

    def enter_storymode_from_mainmenu(self):
        """
        从主菜单进入故事模式，并打开暂停菜单。

        如果不在菜单中，其行为是未定义的。

        :raises ``UIElementNotFound(UIElementNotFoundContext.FINDING_STORY_MODE_MENU)``: 无法找到故事模式菜单。
        :raises ``OperationTimeout(OperationTimeoutContext.STORY_MODE_LOAD)``: 等待故事模式加载超时
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR

        """
        # 在主菜单中切换到故事模式页面
        logger.info("动作: 正在进入故事模式...")
        if self.is_on_mainmenu_logout():
            logger.warning("未登录 Social Club。将无法进入在线模式。")
        for _ in range(3):
            self.gamepad.click_button(Button.RIGHT_SHOULDER)
            time.sleep(3)

        # 检查是否在故事模式页面
        if not self.is_on_mainmenu_storymode_page():
            # logger.error("进入故事模式失败：无法找到故事模式菜单。")
            raise UIElementNotFound(UIElementNotFoundContext.STORY_MODE_MENU)

        self.gamepad.click_button(Button.A)
        logger.info("正在等待故事模式加载...")
        story_mode_load_start_time = time.monotonic()
        while time.monotonic() - story_mode_load_start_time < 120:  # 2分钟加载超时
            if self.is_on_pause_menu():
                break
            self.gamepad.click_button(Button.MENU)
            time.sleep(5)
        else:
            # logger.error("进入故事模式失败：等待进入故事模式超时。")
            raise OperationTimeout(OperationTimeoutContext.STORY_MODE_LOAD)

        logger.info("已进入故事模式。")

    def enter_onlinemode_from_storymode(self):
        """
        从故事模式进入在线模式的仅邀请战局。
        如果不在菜单中，其行为是未定义的。

        :raises ``UIElementNotFound(UIElementNotFoundContext.ONLINE_MODE_TAB)``: 找不到在线模式选择卡
        :raises ``UnexpectedGameState(expected=GameState.IN_ONLINE_LOBBY, actual=GameState.BAD_PCSETTING_BIN)``: 无法进入在线模式，因为pcsetting.bin故障
        :raises ``UnexpectedGameState(expected=GameState.IN_ONLINE_LOBBY, actual=GameState.MAIN_MENU)``: 无法进入在线模式，因为被回退到主菜单
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        :raises ``OperationTimeout(OperationTimeoutContext.ONLINE_SESSION_JOIN)``: 等待进入在线模式超时
        """
        logger.info("动作: 正在进入在线模式...")

        # 打开暂停菜单
        if not self.is_on_pause_menu():
            self.gamepad.click_button(Button.MENU)

        # 打开进入在线模式的菜单
        # 有时会吞键或无法找到在线模式菜单，这里尝试 3 次
        for _ in range(3):
            for _ in range(5):
                self.gamepad.click_button(Button.RIGHT_SHOULDER)
                time.sleep(2)
            self.gamepad.click_button(Button.A)
            time.sleep(1)
            self.gamepad.click_button(Button.DPAD_UP)
            time.sleep(1)
            self.gamepad.click_button(Button.A)
            time.sleep(1)

            # 验证是否打开了进入在线模式的菜单
            # 如果离线或未登录 RockStar Social Club，会无法找到在线模式菜单
            if self.is_on_go_online_menu():
                # 进入下一步
                break
            else:
                # 找不到则关闭菜单
                for _ in range(3):
                    self.gamepad.click_button(Button.B)
                    time.sleep(1)
                # 再次打开地图
                time.sleep(3)
                if not self.is_on_pause_menu():
                    self.gamepad.click_button(Button.MENU)
                    time.sleep(5)
                continue
        else:
            # logger.error("进入在线模式失败：找不到在线模式选项卡。")
            raise UIElementNotFound(UIElementNotFoundContext.ONLINE_MODE_TAB)

        # 选择进入仅邀请战局
        self.gamepad.click_button(Button.DPAD_DOWN)
        time.sleep(1)
        self.gamepad.click_button(Button.A)
        time.sleep(2)
        self.gamepad.click_button(Button.A)

        # 等待进入在线模式
        logger.info("正在等待进入在线模式...")
        online_mode_load_start_time = time.monotonic()

        is_on_onlinemode = False
        while time.monotonic() - online_mode_load_start_time < 300:  # 5分钟加载超时
            # 处理各种意外情况
            ocr_result = self.ocr_game_window(0, 0, 1, 1)
            if self.is_on_bad_pcsetting_warning_page(ocr_result):
                # 由于 pc_setting.bin 问题无法进线上
                raise UnexpectedGameState(GameState.IN_ONLINE_LOBBY, GameState.BAD_PCSETTING_BIN)
            elif self.is_on_warning_page(ocr_result):
                # 弹出错误窗口，比如网络不好，R星发钱等情况
                time.sleep(2)
                self.gamepad.click_button(Button.A)
            elif self.is_on_mainmenu_online_page(ocr_result):
                # 增强版由于网络不好或者被BE踢了，会被回退到主菜单
                # logger.error("进入在线模式失败：进入在线模式时被回退到主菜单，请检查网络。")
                raise UnexpectedGameState(GameState.IN_ONLINE_LOBBY, GameState.MAIN_MENU)

            # TODO: 补充传承版被回退到故事模式的处理方法，目前问题在于难以检测是否在故事模式中
            # TODO: R星有时候会更新用户协议，需要补充确认新的用户协议的检查和动作。目前问题在于不清楚如何判断在用户协议页面和如何用手柄确认

            # 检查是否进入了在线模式
            for _ in range(3):  # 尝试3次
                self.gamepad.click_button(Button.DPAD_DOWN)
                time.sleep(1)
                if self.is_on_onlinemode_info_panel():
                    # 进入了在线模式
                    is_on_onlinemode = True
                    break
            if is_on_onlinemode:
                break

            time.sleep(10)
        else:
            logger.error("进入在线模式失败：等待进入在线模式超时。")
            raise OperationTimeout(OperationTimeoutContext.JOIN_ONLINE_SESSION)

        logger.info("已进入在线模式。")

    def clean_pcsetting(self):
        """
        尝试保留设置并清洗 pc_setting.bin。
        应当在 GTA V 未启动的情况下运行。否则无法生效。
        """
        logger.info("动作: 正在清理 pc_setting.bin...")

        # 获取"我的文档"文件夹位置
        try:
            CSIDL_PERSONAL = 5  # My Documents
            SHGFP_TYPE_CURRENT = 0  # Get current, not default value
            buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, CSIDL_PERSONAL, None, SHGFP_TYPE_CURRENT, buf)
            documents_path = Path(buf.value)
        except Exception as e:
            logger.error(f'调用 Windows API 获取"我的文档"文件夹位置失败 ({e})，将使用默认路径。')
            documents_path = Path.home() / "Documents"

        # 游戏目录名，目前程序仅支持 GTA V 增强版
        # TODO: 增加对传承版的兼容。目前主要问题在于不确定传承版的 pc_settings.bin 格式是否相同
        game_directory_name = "GTAV Enhanced"

        # 用户资料文件路径
        profiles_path = documents_path / "Rockstar Games" / game_directory_name / "Profiles"
        if not profiles_path.is_dir():
            logger.error(f"找不到用户资料文件目录: {profiles_path}")
            return
        logger.debug(f"找到用户资料文件目录: {profiles_path}")

        # 枚举并遍历所有存档子目录
        savedir_list = [d for d in profiles_path.iterdir() if d.is_dir()]
        for savedir in savedir_list:
            settings_file = savedir / "pc_settings.bin"

            if not settings_file.is_file():
                logger.debug(f"跳过 {savedir}，因为未找到 pc_settings.bin")
                continue

            logger.info(f"正在清理: {settings_file}")

            # 检查每 8 字节数据块的前 2 个字节，将其作为一个小端整数进行解析。
            # 如果这个整数值小于 850，则保留这个 8 字节的数据块
            # 来源: https://github.com/mageangela/QuellGTA/
            try:
                # 以二进制打开文件
                with open(settings_file, "rb") as f:
                    p_byte_set = f.read()

                # 创建一个bytearray用于存储需要保留的数据
                o_byte_set = bytearray()
                chunk_size = 8

                # 以8字节为单位循环处理文件内容
                for i in range(0, len(p_byte_set), chunk_size):
                    chunk = p_byte_set[i : i + chunk_size]

                    # 低于8字节不做处理
                    if len(chunk) < chunk_size:
                        continue

                    # 将前2个字节按小端序解析为无符号短整数
                    header_bytes = chunk[:2]
                    value = struct.unpack("<H", header_bytes)[0]

                    # 如果整数值小于850，则保留这个8字节块
                    if value < 850:
                        o_byte_set.extend(chunk)

                # 将处理后的数据写回原文件
                with open(settings_file, "wb") as f:
                    f.write(o_byte_set)

                logger.info(f"清理完成: {settings_file}")

            except IOError as e:
                logger.error(f"处理文件 {settings_file} 时发生IO错误: {e}")
            except Exception as e:
                logger.error(f"处理文件 {settings_file} 时发生未知错误: {e}")

        logger.info("清理 pc_setting.bin 完成。")
