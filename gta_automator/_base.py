import ctypes.wintypes
import struct
from pathlib import Path
import time
from typing import Optional
import requests

from config import Config
from gta_automator.exception import *
from logger import get_logger

from .screen import GameScreen
from .action import Action
from .process import GameProcess

logger = get_logger("automator_common")


class _BaseManager:
    """
    为所有管理器提供共享的底层模块和通用子流程。
    这不是一个应该被直接实例化的类。
    """

    def __init__(self, screen: GameScreen, action: Action, process: GameProcess, config: Config):
        # 所有管理器都需要这些底层依赖
        self.screen = screen
        self.action = action
        self.process = process
        self.config = config

    # --- 管理器的公用方法 ---
    def ensure_pause_menu_is_open(self):
        """
        确保暂停菜单是打开的，如果不是，则打开它。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        if not self.screen.is_on_pause_menu():
            self.action.open_or_close_pause_menu()

    def check_if_in_onlinemode(self, max_retries: int = 3) -> bool:
        """
        检查当前是否在在线模式中。

        :param max_retries: 最大尝试次数，默认值为 3
        :return: 如果在在线模式中则返回 True，否则返回 False
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        for _ in range(max_retries):
            self.action.open_onlinemode_info_panel()
            if self.screen.is_on_onlinemode_info_panel():
                # 进入了在线模式
                return True
        else:
            return False

    def check_if_in_storymode(self, max_retries: int = 3) -> bool:
        """
        检查当前是否在故事模式中。

        :param max_retries: 最大尝试次数，默认值为 3
        :return: 如果在在线模式中则返回 True，否则返回 False
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        for _ in range(max_retries):
            self.action.open_or_close_pause_menu()
            if self.screen.is_on_story_pause_menu():
                # 在故事模式暂停菜单中，表示当前在故事模式中
                self.action.open_or_close_pause_menu()
                return True
        else:
            return False

    def glitch_single_player_session(self):
        """通过暂停进程卡单人战局"""
        logger.info("动作: 正在卡单人战局。。。")
        self.process.suspend_gta_process(self.config.suspendGTATime)
        logger.info("卡单人战局完成。")

    def confirm_warning_page(self, ocr_text: Optional[str] = None) -> bool:
        """
        如果当前在警告页面，则按 A 键确认。

        :param ocr_text: 可选的 OCR 结果字符串，如果未提供则会自动获取当前屏幕的 OCR 结果
        :return: 没有发现警告页面时返回 False，发现并确认警告页面时返回 True
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        if self.screen.is_on_warning_page(ocr_text):
            logger.info("动作: 发现警告页面，正在按 A 键确认...")
            self.action.confirm()
            logger.info("已确认警告页面。")
            return True
        else:
            return False

    def wait_for_state(self, check_function, timeout: int, check_interval: float = 1.0, game_started: bool = True) -> bool:
        """
        通用等待函数，在超时前反复检查某个状态。如果游戏没有运行，会停止检查并抛出异常。

        :param check_function: 一个无参数并返回布尔值的函数 (e.g., self.screen.is_on_job_panel)
        :param timeout: 超时秒数
        :param check_interval: 检查间隔秒数
        :param game_started: 游戏是否已经启动。传入 False 时，会跳过游戏运行检查
        :return: 如果在超时前状态达成则返回 True，否则返回 False
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        start_time = time.monotonic()
        while time.monotonic() - start_time < timeout:
            # 确保游戏还在运行
            if game_started and not self.screen.is_game_started():
                raise UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)

            if check_function():
                return True
            time.sleep(check_interval)
        return False

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

    def get_mageangela_jobwarp_bot_steamjvp(self) -> list[str]:
        """
        从 mageangela 的接口获取差传 Bot 的战局链接。

        :raises ``NetworkError(NetworkErrorContext.FETCH_WARPBOT_INFO)``: 从 mageangela 的接口获取差传 Bot 的战局链接时发生网络错误
        """
        try:
            res = requests.get("http://quellgtacode.mageangela.cn:52014/botJvp/", timeout=10)
            res.raise_for_status()
            response_lines = res.text.replace("\r", "").split("\n")
        except requests.RequestException as e:
            raise NetworkError(NetworkErrorContext.FETCH_WARPBOT_INFO)

        # 前三行是注释，删除
        raw_bot_lines = response_lines[3:]
        # 保留的行格式类似于
        """
        差传1-郑州联通(12bot)|Vm9Y1LlGNdnAwXDOmiAAAAAAEaRdRXe%3D%3D
        差传2-郑州移动(13bot)|
        赞助1-小羊咩咩(辅助瞄准差传)|fJEwz2fHrrBAwhKsZ2AAAAAAEaRdRXeAh0S%3D%3D
        """

        list_bot_steamjvp = []
        for line in raw_bot_lines:
            # 以防万一，清理无关行
            if "|" not in line:
                continue
            _, jvp_id = line.split("|", 1)
            # Bot 挂掉后，"|"后将没有内容
            if not jvp_id:
                continue
            list_bot_steamjvp.append(jvp_id)

        return list_bot_steamjvp

    def wait_for_mainmenu_load(self):
        """
        等待主菜单加载完成。

        :raises ``OperationTimeout(OperationTimeoutContext.MAIN_MENU_LOAD)``: 等待主菜单加载超时
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR

        """
        logger.info("动作: 正在等待主菜单加载...")
        start_time = time.monotonic()
        while time.monotonic() - start_time < 180:  # 3分钟加载超时
            # 两次检查需要分开进行 OCR , 因为 OCR 区域不一样
            # 检查是否在主菜单
            if self.screen.is_on_mainmenu_online_page():
                # 进入了主菜单
                return
            # 有时候主菜单会展示一个显示 GTA+ 广告的窗口
            elif self.screen.is_on_mainmenu_gtaplus_advertisement_page():
                time.sleep(2)  # 等待广告页面加载完成
                self.action.confirm()
                # 确认掉广告页面后，也会进入主菜单
                return
            time.sleep(5)
        else:
            # 循环结束仍未加载成功
            raise OperationTimeout(OperationTimeoutContext.MAIN_MENU_LOAD)

    def wait_for_gta_window_showup(self):
        """
        等待 GTA V 窗口出现。
        :raises ``OperationTimeout(OperationTimeoutContext.GAME_WINDOW_STARTUP)``: 等待 GTA V 窗口出现超时
        """
        logger.info("正在等待 GTA V 窗口出现...")

        if not self.wait_for_state(self.screen.is_game_started, 300, 5, False):
            raise OperationTimeout(OperationTimeoutContext.GAME_WINDOW_STARTUP)

    def wait_for_storymode_load(self):
        """
        等待故事模式加载完成。

        :raises ``OperationTimeout(OperationTimeoutContext.STORY_MODE_LOAD)``: 等待故事模式加载超时
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR

        """
        logger.info("动作: 正在等待故事模式加载...")

        if not self.wait_for_state(self.check_if_in_storymode, 120, 5):
            raise OperationTimeout(OperationTimeoutContext.STORY_MODE_LOAD)

    def wait_for_online_mode_load(self):
        """
        等待进入在线模式，并处理加载过程中的各种意外情况。

        :raises ``OperationTimeout(OperationTimeoutContext.JOIN_ONLINE_SESSION)``: 等待进入在线模式超时
        :raises ``UnexpectedGameState(expected=GameState.IN_ONLINE_LOBBY, actual=GameState.BAD_PCSETTING_BIN)``: 由于 pc_setting.bin 问题无法进入在线模式
        :raises ``UnexpectedGameState(expected=GameState.IN_ONLINE_LOBBY, actual=GameState.MAIN_MENU)``: 由于网络问题等原因被回退到主菜单
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        logger.info("正在等待进入在线模式...")
        start_time = time.monotonic()
        has_triggered_single_session = False

        while time.monotonic() - start_time < 300:  # 5分钟超时
            # 每10秒检查一次
            time.sleep(10)

            # 获取一次当前屏幕状态
            ocr_text = self.screen.ocr_game_window(0, 0, 1, 1)

            # 检查各种错误/意外状态
            if self.screen.is_on_bad_pcsetting_warning_page(ocr_text):
                # 由于 pc_setting.bin 问题无法进线上
                raise UnexpectedGameState(GameState.IN_ONLINE_LOBBY, GameState.BAD_PCSETTING_BIN)
            elif self.confirm_warning_page(ocr_text):
                # 弹出错误窗口，比如网络不好，R星发钱等情况
                continue
            elif self.screen.is_on_mainmenu_online_page(ocr_text):
                # 增强版由于网络不好或者被BE踢了，进入了主菜单
                raise UnexpectedGameState(GameState.IN_ONLINE_LOBBY, GameState.MAIN_MENU)

            # TODO: 补充传承版被回退到故事模式的处理方法，目前问题在于难以检测是否在故事模式中
            # TODO: R星有时候会更新用户协议，需要补充确认新的用户协议的检查和动作。目前问题在于不清楚如何判断在用户协议页面和如何用手柄确认

            # 检查是否进入了在线模式
            if self.check_if_in_onlinemode():
                return

            if not has_triggered_single_session and time.monotonic() - start_time > 60:
                # 进入在线模式等待超过1分钟后，进行卡单以缓解卡云
                logger.info("等待进入在线模式超过1分钟，尝试卡单人战局以缓解卡云...")
                self.glitch_single_player_session()
                has_triggered_single_session = True
        else:
            # 循环结束仍未加载成功
            raise OperationTimeout(OperationTimeoutContext.JOIN_ONLINE_SESSION)
