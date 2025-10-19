import struct
from pathlib import Path
import time
from typing import Optional
import requests

from config import Config
from gta_automator.exception import *
from logger import get_logger
from windows_utils import get_document_fold_path

from .game_screen import GameScreen
from .game_action import GameAction
from .game_process import GameProcess

logger = get_logger("base_workflow")


class _BaseWorkflow:
    """
    为所有工作流提供共享的底层模块和通用子流程。
    这不是一个应该被直接实例化的类。
    """

    def __init__(self, screen: GameScreen, action: GameAction, process: GameProcess, config: Config):
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
        通过打开信息面板，检查当前是否在在线模式中。只应在打开信息面板操作不会导致副作用的场景下执行

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
        通过打开暂停菜单，检查当前是否在故事模式中。只应在打开暂停菜单操作不会导致副作用的场景下执行

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

    def handle_warning_page(self, ocr_text: Optional[str] = None) -> bool:
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

    def wait_for_state(
        self, check_function, timeout: int, check_interval: float = 1.0, game_started: bool = True
    ) -> bool:
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
            if game_started and not self.process.is_game_started():
                raise UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)

            if check_function():
                return True
            time.sleep(check_interval)
        return False

    def clean_pcsetting_bin(self, pcsetting_bin_path: Path):
        """
        清理 pc_setting.bin 中的数据，并且保留游戏设置。

        清理后，使用对应该 pc_setting.bin 的用户文件启动游戏，主菜单会多出一个"最新"页面，并且只能从故事模式进入在线模式

        :param pcsetting_bin_path: pc_setting.bin的路径
        :raises ``FileNotFoundError(f"文件 {pcsetting_bin_path} 不存在")``: 传入的路径不存在或是一个文件夹
        :raises ``IOError``: 处理文件时发生 I/O 错误
        :raises ``Exception``: 处理文件时发生其他错误
        """
        # 检查 pc_setting.bin 是否存在
        if not pcsetting_bin_path.is_file():
            raise FileNotFoundError(f"文件 {pcsetting_bin_path} 不存在")

        # 清理 pc_setting.bin
        with open(pcsetting_bin_path, "rb") as f:
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
        with open(pcsetting_bin_path, "wb") as f:
            f.write(o_byte_set)

    def fix_bad_pcsetting(self):
        """
        修复 pc_setting.bin 导致的无法进入线上模式。
        应当在 GTA V 未启动的情况下运行。否则无法生效。
        """
        logger.info("动作: 正在修复 pc_setting.bin 无法进线上...")

        # 获取"我的文档"文件夹位置
        documents_path = get_document_fold_path()

        # 游戏目录名，不打算支持传承版
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
            try:
                self.clean_pcsetting_bin(settings_file)
            except FileNotFoundError:
                logger.error(f"清理 {settings_file} 失败: 文件不存在。")
                continue
            except IOError as e:
                logger.error(f"清理 {settings_file} 失败: IO错误: {e}")
                continue
            except Exception as e:
                logger.error(f"清理 {settings_file} 失败: 未知错误: {e}")
                continue

            logger.info(f"清理完成: {settings_file}")

        logger.info("修复 pc_setting.bin 无法进线上完成。")

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
        :raises ``UnexpectedGameState(expected=GameState.IN_ONLINE_LOBBY, actual=GameState.MAIN_MENU)``: 由于网络问题等原因被回退到主菜单 (仅限增强版)
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
                raise UnexpectedGameState(GameState.ONLINE_FREEMODE, GameState.BAD_PCSETTING_BIN)
            elif self.handle_warning_page(ocr_text):
                # 弹出错误窗口，比如网络不好，R星发钱等情况
                continue
            elif self.screen.is_on_mainmenu_online_page(ocr_text):
                # 由于网络不好或者被BE踢了，进入了主菜单
                raise UnexpectedGameState(GameState.ONLINE_FREEMODE, GameState.MAIN_MENU)

            # TODO: R星有时候会更新用户协议，需要补充确认新的用户协议的检查和动作。目前问题在于不清楚如何判断在用户协议页面和如何用手柄确认

            # 检查是否进入了在线模式
            if self.check_if_in_onlinemode():
                return

            if not has_triggered_single_session and time.monotonic() - start_time > 120:
                # 进入在线模式等待超过2分钟后，进行卡单以缓解卡云
                logger.info("等待进入在线模式超过2分钟，尝试卡单人战局以缓解卡云...")
                self.glitch_single_player_session()
                has_triggered_single_session = True
        else:
            # 循环结束仍未加载成功
            raise OperationTimeout(OperationTimeoutContext.JOIN_ONLINE_SESSION)

    