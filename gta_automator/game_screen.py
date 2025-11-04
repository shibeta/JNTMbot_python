import atexit
import re
from typing import List, Optional, Union

from ocr_utils import OCREngine
from windows_utils import unset_top_window
from logger import get_logger

from .exception import *
from .game_process import GameProcess

logger = get_logger(name="game_screen")


class GameScreenTextPatterns:
    @staticmethod
    def _compile_to_pattern(
        keywords: Union[str, List[str]],
        escape_spicial_character: bool = True,
    ) -> re.Pattern[str]:
        """将传入的关键字编译为模式字符串"""
        if not keywords:
            raise ValueError(f"关键字 {keywords} 无效")
        if isinstance(keywords, str):
            if escape_spicial_character:
                return re.compile(re.escape(keywords))
            else:
                return re.compile(keywords)
        elif isinstance(keywords, list):
            # 只接受纯字符串构成的列表
            if not all(isinstance(keyword, str) for keyword in keywords):
                raise ValueError(f"列表 {keywords} 中含有非字符串元素")
            if escape_spicial_character:
                final_regex_str = "|".join(re.escape(text) for text in keywords)
            else:
                final_regex_str = "|".join(text for text in keywords)
            return re.compile(final_regex_str)

    IS_ON_JOB_PANEL_RIGHT_SCREEN = _compile_to_pattern(["浑球", "办事", "角色"])
    IS_ON_MAINMENU_DISPLAY_CALIBRATION_PAGE = _compile_to_pattern(["调整", "确认"])
    IS_ON_MAINMENU_GTAPLUS_ADVERTISEMENT_PAGE = _compile_to_pattern(["导览", "跳过"])
    IS_ON_JOB_PANEL_LEFT_SCREEN = _compile_to_pattern(["别惹", "德瑞", "搭档"])
    IS_ON_FIRST_JOB_SETUP_PAGE = _compile_to_pattern(["设置", "镜头", "武器"])
    IS_ON_SECOND_JOB_SETUP_PAGE = _compile_to_pattern(["匹配", "邀请", "帮会"])
    IS_ON_SCOREBOARD = _compile_to_pattern(["别惹", "德瑞"])
    IS_JOB_MARKER_FOUND = _compile_to_pattern(["猎杀", "约翰尼"])
    # 有时任务会以英文启动，因此检查"团队生命数"作为保底
    IS_JOB_STARTED = _compile_to_pattern(["前往", "出现", "汇报", "进度", "团队", "生命数"])
    IS_JOB_STARTING = _compile_to_pattern(["正在", "启动", "战局"])
    IS_ON_WARNING_PAGE = _compile_to_pattern(["警告", "注意"])
    IS_CONFIRM_OPTION_AVAILABLE = _compile_to_pattern(["是", "否"])
    # 增强版是"目前无法从Rockstar云服务器下载您保存的数据"，确认后会返回主菜单
    # 传承版是"此时无法从Rockstar云服务器载入您保存的数据"，确认后会返回故事模式
    IS_ON_BAD_PCSETTING_WARNING_PAGE = _compile_to_pattern(["目前无法", "此时无法"])
    IS_ON_PAUSE_MENU = _compile_to_pattern(["地图", "职业", "简讯"])
    IS_ON_STORY_PAUSE_MENU = _compile_to_pattern(["简讯", "统计", "设置"])
    IS_ON_ONLINE_PAUSE_MENU = _compile_to_pattern(["职业", "好友", "商店"])
    IS_ON_GO_ONLINE_MENU = _compile_to_pattern(["公开战局", "邀请的", "帮会战局"])


class GameScreen:
    """封装与游戏画面相关的各种方法"""

    def __init__(self, OCREngine: OCREngine, process: GameProcess):
        self.ocr = OCREngine
        self.process = process

        # 注册退出处理函数，以确保Python程序退出时 GTA V 窗口不会处于置顶状态
        atexit.register(self.unset_gta_window_topmost)

    def unset_gta_window_topmost(self):
        """将 GTA V 窗口取消置顶"""
        if self.process.hwnd:
            try:
                unset_top_window(self.process.hwnd)
            except Exception as e:
                # 所有异常都不做处理
                logger.error(f"取消 GTA V 窗口置顶时，发生异常: {e}")

    def ocr_game_window(self, left, top, width, height) -> str:
        """
        对游戏窗口的指定区域执行 OCR，并返回识别结果。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        if not self.process.hwnd:
            raise UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)

        return self.ocr.ocr_window(self.process.hwnd, left, top, width, height)

    def _search_in_text(
        self,
        text: str,
        query_text: Union[str, List[str], re.Pattern[str]],
    ) -> bool:
        """
        辅助函数，用于检查文本是否存在于给定的字符串中。
        """
        if isinstance(query_text, re.Pattern):
            return query_text.search(text) is not None
        elif isinstance(query_text, (list, tuple)):
            pattern_str = "|".join(re.escape(text) for text in query_text)
            return re.search(pattern_str, text) is not None
        else:
            return query_text in text

    def _search_text_in_area(
        self,
        query_text: Union[str, List[str], re.Pattern[str]],
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
        query_text: Union[str, List[str], re.Pattern[str]],
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

    def get_job_setup_status(self) -> tuple[bool, int, int, int]:
        """
        检查差事面板状态，包括是否在面板中，以及加入的玩家数。
        如果不在面板中玩家数将固定返回-1。

        :return: 是否在面板(bool)，正在加入的玩家数(int)，已经加入的玩家数(int)，待命状态的玩家数(int)
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        ocr_result = self.ocr_game_window(0.5, 0, 0.5, 1)

        # 使用正则表达式搜索是否在面板中
        if self._search_in_text(ocr_result, GameScreenTextPatterns.IS_ON_JOB_PANEL_RIGHT_SCREEN):
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
    def is_on_mainmenu_display_calibration_page(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查游戏是否在主菜单的亮度调整页面。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(
            GameScreenTextPatterns.IS_ON_MAINMENU_DISPLAY_CALIBRATION_PAGE, ocr_text, 0.25, 0.4, 0.5, 0.2
        )

    def is_on_mainmenu_gtaplus_advertisement_page(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查游戏是否在主菜单的gta+广告页面。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(
            GameScreenTextPatterns.IS_ON_MAINMENU_GTAPLUS_ADVERTISEMENT_PAGE,
            ocr_text,
            0.5,
            0.8,
            0.5,
            0.2,
        )

    def is_on_mainmenu_logout(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查游戏是否在登出的主菜单页面。
        注意无法确认是在线页面还是 GTA+ 页面，因为两个页面的 OCR 结果是相同的。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state("已登出", ocr_text, 0, 0, 1, 1)

    def is_on_mainmenu(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查游戏是否在主菜单的在线页面。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state("移动标签", ocr_text, 0.5, 0.8, 0.5, 0.2)

    def is_on_mainmenu_storymode_page(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查游戏是否在主菜单的故事页面。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state("故事模式", ocr_text, 0, 0.5, 0.7, 0.5)

    def is_on_onlinemode_info_panel(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查游戏是否在在线模式的左上角显示玩家信息的菜单。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state("在线模式", ocr_text, 0, 0, 0.4, 0.1)

    def is_respawned_in_agency(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查玩家是否已在事务所的床上复活。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state("床", ocr_text, 0, 0, 0.5, 0.5)

    def is_on_job_panel(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查当前是否在差事面板界面。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(GameScreenTextPatterns.IS_ON_JOB_PANEL_LEFT_SCREEN, ocr_text, 0, 0, 0.5, 0.5)

    def is_on_first_job_setup_page(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查当前是否在差事准备面板的第一页。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(GameScreenTextPatterns.IS_ON_FIRST_JOB_SETUP_PAGE, ocr_text, 0, 0, 1, 1)

    def is_on_second_job_setup_page(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查当前是否在差事准备面板的第二页。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(GameScreenTextPatterns.IS_ON_SECOND_JOB_SETUP_PAGE, ocr_text, 0, 0, 1, 1)

    def is_on_scoreboard(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查当前是否在差事失败的计分板界面。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(GameScreenTextPatterns.IS_ON_SCOREBOARD, ocr_text, 0, 0, 0.5, 0.5)

    def is_job_marker_found(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查是否找到了差事的黄色光圈提示。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(GameScreenTextPatterns.IS_JOB_MARKER_FOUND, ocr_text, 0, 0, 0.5, 0.5)

    def is_job_started(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查是否在别惹德瑞任务中。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(GameScreenTextPatterns.IS_JOB_STARTED, ocr_text, 0, 0.8, 1, 0.2)

    def is_job_starting(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查任务是否在启动中。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(GameScreenTextPatterns.IS_JOB_STARTING, ocr_text, 0, 0.8, 1, 0.2)

    def is_on_warning_page(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查是否在黑屏警告页面。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(GameScreenTextPatterns.IS_ON_WARNING_PAGE, ocr_text, 0.25, 0, 0.5, 0.6)

    def is_on_exit_confirm_page(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查是否在确认退出页面。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state("退出", ocr_text, 0.25, 0.2, 0.5, 0.5)

    def is_confirm_option_available(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查右下角是否出现"是""否"选项。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(
            GameScreenTextPatterns.IS_CONFIRM_OPTION_AVAILABLE, ocr_text, 0.75, 0.8, 0.25, 0.2
        )

    def is_on_bad_pcsetting_warning_page(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查是否在因 pcsetting.bin 损坏而无法进入在线模式的警告页面。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(
            GameScreenTextPatterns.IS_ON_BAD_PCSETTING_WARNING_PAGE, ocr_text, 0, 0, 1, 1
        )

    def is_on_online_service_policy_page(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查是否在需要确认 RockStar Games 在线服务政策的页面。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state("在线服务政策", ocr_text, 0, 0, 0.7, 0.3)

    def is_online_service_policy_loaded(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查是否在需要确认 RockStar Games 在线服务政策的页面，并且已经完全加载。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        if not ocr_text:
            ocr_text = self.ocr_game_window(0, 0, 0.7, 0.5)
        # 先检查是否在在线服务政策页面
        if self.is_on_online_service_policy_page(ocr_text):
            # 再检查是否有关键字
            return self._search_in_text(ocr_text, "想要阅读")
        else:
            # 如果不在在线服务政策页面，直接返回False
            return False

    def is_on_privacy_policy_page(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查是否在隐私政策页面。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state("隐私政策", ocr_text, 0, 0, 0.7, 0.3)

    def is_on_term_of_service_page(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查是否在服务条款页面。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state("服务条款", ocr_text, 0, 0, 0.7, 0.3)

    def is_on_pause_menu(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查是否在暂停菜单，无论是在线模式还是故事模式。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(GameScreenTextPatterns.IS_ON_PAUSE_MENU, ocr_text, 0, 0.1, 0.5, 0.3)

    def is_on_story_pause_menu(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查是否在故事模式的暂停菜单。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(GameScreenTextPatterns.IS_ON_STORY_PAUSE_MENU, ocr_text, 0.1, 0.1, 0.7, 0.3)

    def is_on_online_pause_menu(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查是否在在线模式的暂停菜单。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(GameScreenTextPatterns.IS_ON_ONLINE_PAUSE_MENU, ocr_text, 0.1, 0.1, 0.5, 0.3)

    def is_on_go_online_menu(self, ocr_text: Optional[str] = None) -> bool:
        """
        检查是否在"进入在线模式"菜单。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        return self._check_state(GameScreenTextPatterns.IS_ON_GO_ONLINE_MENU, ocr_text, 0, 0, 0.5, 0.5)
