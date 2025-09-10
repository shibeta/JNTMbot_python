import time
import os
import requests
import re

from config import Config
from ocr_engine import OCREngine
from keyboard_utils import *  # 导入所有键盘功能和常量
from steam_utils import SteamBotClient
from process_utils import get_window_info, suspend_process_for_duration, kill_processes
from logger import setup_logger

GLogger = setup_logger(name="gta5_utils")


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
        hwnd: int | None,
        pid: int | None,
    ):
        self.config = config
        self.ocr = ocr_engine
        self.steam_bot = steam_bot
        self.hwnd = hwnd
        self.pid = pid

    def get_gta_hwnd(self) -> int:
        return self.hwnd

    def enter_single_player_session(self):
        """通过暂停进程卡单人战局"""
        suspend_process_for_duration(self.pid, self.config.suspendGTATime)

    def kill_gta(self):
        """杀死 GTA V 进程，并且清除窗口句柄和 PID 。"""
        kill_processes(self.GTA_PROCESS_NAMES)
        self.hwnd, self.pid = None, None

    def _find_text(self, text, x, y, w, h) -> bool:
        """辅助函数，用于检查文本是否存在于指定区域。"""
        ocr_result = self.ocr.ocr(self.hwnd, x, y, w, h)
        return text in ocr_result

    def _find_multi_text(self, texts: list[str], x, y, w, h) -> bool:
        """辅助函数，用于检查一组文本是否有部分存在于指定区域。"""
        ocr_result = self.ocr.ocr(self.hwnd, x, y, w, h)

        # 避免生成空的正则表达式
        if not texts:
            return False

        # 使用正则表达式搜索
        pattern = "|".join(re.escape(text) for text in texts)  # 转义所有特殊字符
        return re.search(pattern, ocr_result) is not None

    def get_job_setup_status(self) -> tuple[bool, int, int]:
        """
        检查差事面板状态，包括是否在面板中，以及加入的玩家数。
        如果不在面板中玩家数将固定返回-1。

        Return:
            是否在面板(bool)，正在加入的玩家数(int)，已经加入的玩家数(int)
        """
        ocr_result = self.ocr.ocr(self.hwnd, 0.5, 0, 0.5, 1)

        # 使用正则表达式搜索是否在面板中
        pattern = "|".join(["浑球", "办事", "角色"])  # 没有特殊字符所以不需要转义
        # pattern = "|".join(re.escape(text) for text in ["别惹", "德瑞", "搭档"])
        if re.search(pattern, ocr_result) is not None:
            # 在面板中则识别加入玩家数
            joining_count = ocr_result.count("正在")
            joined_count = ocr_result.count("已加")

            return True, joining_count, joined_count
        else:
            # 不在面板中则跳过识别直接返回-1
            return False, -1, -1

    # --- 状态检查方法 ---
    def is_respawned(self) -> bool:
        """检查玩家是否已在床上复活。"""
        return self._find_text("床", 0, 0, 0.5, 0.5)

    def is_on_job_panel(self) -> bool:
        """检查当前是否在差事面板界面。"""
        return self._find_multi_text(["别惹", "德瑞", "搭档"], 0, 0, 0.5, 0.5)

    def is_on_scoreboard(self) -> bool:
        """检查当前是否在差事失败的计分板界面。"""
        return self._find_multi_text(["别惹", "德瑞"], 0, 0, 0.5, 0.5)

    def is_job_marker_found(self) -> bool:
        """检查是否找到了差事的黄色光圈提示。"""
        return self._find_multi_text(["猎杀", "约翰尼"], 0, 0, 0.5, 0.5)

    def is_job_started(self) -> bool:
        """检查是否在别惹德瑞任务中。"""
        return self._find_multi_text(["前往", "出现", "汇报", "进度", "团队", "生命数"], 0, 0.8, 1, 0.2)

    def is_job_starting(self) -> bool:
        """检查任务是否在启动中。"""
        return self._find_multi_text(["正在", "启动", "战局"], 0.7, 0.9, 0.3, 0.1)

    def is_on_warning_page(self) -> bool:
        """检查是否在黑屏警告页面"""
        return self._find_multi_text(["警告", "注意"], 0, 0, 1, 1)

    def is_on_pause_menu(self) -> bool:
        """检查是否在暂停菜单"""
        return self._find_multi_text(["地图", "在线", "职业", "好友", "设置"], 0, 0, 0.5, 0.5)

    def is_on_go_online_menu(self) -> bool:
        """检查是否在"进入在线模式"菜单"""
        return self._find_multi_text(
            ["公开战局", "邀请的", "帮会战局", "公开帮会", "公开好友"], 0, 0, 0.5, 0.5
        )

    # 各种动作序列
    def go_downstairs(self):
        """从事务所的床出发，下到一楼"""
        GLogger.info("动作：正在下楼...")
        press_keyboard("a")
        press_keyboard("w")
        time.sleep(2.0)
        release_keyboard("w")
        release_keyboard("a")
        press_keyboard("d")
        time.sleep(6.0)
        start_time = time.monotonic()
        while time.monotonic() - start_time < 2.5:
            click_keyboard("s", 150)
            click_keyboard("w", 150)
        time.sleep(2.0)
        release_keyboard("d")
        press_keyboard("w")
        time.sleep(2.0)
        release_keyboard("w")
        press_keyboard("s")
        time.sleep(4.0)
        release_keyboard("s")
        press_keyboard("d")
        press_keyboard("w")
        time.sleep(2.0)
        release_keyboard("w")
        release_keyboard("d")
        press_keyboard("a")
        time.sleep(5.0)
        release_keyboard("a")

    def find_job(self) -> bool:
        """从一楼楼梯间开始向任务触发点移动，并检查是否到达任务点。"""
        GLogger.info("动作：正在寻找差事地点...")
        # 走出楼梯间
        start_time = time.monotonic()
        while time.monotonic() - start_time < self.config.goOutStairsTime / 1000.0:
            click_keyboard("s", self.config.pressSTimeStairs)
            click_keyboard("a", self.config.pressATimeStairs)

        # 穿过走廊
        start_time = time.monotonic()
        while time.monotonic() - start_time < self.config.crossAisleTime / 1000.0:
            click_keyboard("s", self.config.pressSTimeAisle)
            click_keyboard("a", self.config.pressATimeAisle)

        # 使用 OCR 搜索差事标记
        start_time = time.monotonic()
        while time.monotonic() - start_time < self.config.waitFindJobTimeout / 1000.0:
            click_keyboard("s", self.config.pressSTimeGoJob)
            if self.is_job_marker_found():
                return True
            click_keyboard("a", self.config.pressATimeGoJob)
            if self.is_job_marker_found():
                return True
        return False

    def enter_job(self):
        """在差事点上开始差事，目前只需要按一下 E。"""
        click_keyboard("e")

    def start_new_match(self) -> bool:
        """尝试从一个战局中切换到另一个仅邀请战局，必须在自由模式下才能工作。"""
        GLogger.info("动作：正在开始一个新差事...")
        # 切换新战局会尝试20次，在某些次数中，会使用不同措施尝试使游戏回到"正常状态"。
        for new_match_error_count in range(20):
            # 各种措施，很难说效果究竟如何，瞎猫撞死耗子
            if new_match_error_count % 3 == 2:
                GLogger.info("尝试通过多次按 ESCAPE 键来恢复正常状态。")
                for _ in range(7):
                    click_keyboard(KEY_ESCAPE)
                    time.sleep(0.5)
            if (new_match_error_count + 1) % 3 == 0:
                GLogger.info("尝试通过多次按 ESCAPE 键和 ENTER 键来恢复正常状态。")
                for _ in range(4):
                    click_keyboard(KEY_ESCAPE)
                    time.sleep(0.5)
                    click_keyboard(KEY_ENTER)
                    time.sleep(0.5)
            if new_match_error_count == 10:
                GLogger.info("尝试通过加入差传 Bot 战局来恢复正常状态。")
                self.try_to_join_bot()
            if new_match_error_count == 15:
                GLogger.info("尝试通过卡单来恢复正常状态。")
                suspend_process_for_duration(self.pid, self.config.suspendGTATime)
            # 以下开始是正常的开始新战局的指令
            # 处理警告屏幕
            if self.is_on_warning_page():
                click_keyboard(KEY_ENTER)
                time.sleep(0.5)

            # 打开暂停菜单
            if not self.is_on_pause_menu():
                click_keyboard(KEY_ESCAPE)
                time.sleep(2)

            # 检查暂停菜单是否被打开，未打开则按 ESC 并进行下一次尝试
            if not self.is_on_pause_menu():
                click_keyboard(KEY_ESCAPE)
                GLogger.warning(f"开始新战局失败 (尝试次数 {new_match_error_count})。正在重试...")
                continue

            # 尝试切换到在线选项卡以切换战局
            click_keyboard("e")
            time.sleep(2)
            click_keyboard(KEY_ENTER)
            time.sleep(1)
            for _ in range(5):
                click_keyboard("w", 100)
                time.sleep(0.6)
            click_keyboard(KEY_ENTER)
            time.sleep(1)

            # 验证当前是否在切换战局的菜单，未打开则按3次 ESC 并进行下一次尝试
            if not self.is_on_go_online_menu():
                for _ in range(3):
                    click_keyboard(KEY_ESCAPE)
                    time.sleep(1)
                GLogger.warning(f"开始新战局失败 (尝试次数 {new_match_error_count})。正在重试...")
                continue

            # 选择"仅邀请战局"选项，确认
            click_keyboard("s")
            time.sleep(0.6)
            click_keyboard(KEY_ENTER)
            time.sleep(2)
            click_keyboard(KEY_ENTER)
            return True
        else:
            return False

    def wait_team(self) -> bool:
        """在差事准备页面，等待队友，然后开始游戏。"""
        GLogger.info("状态：等待队伍成员...")
        start_wait_time = time.monotonic()  # 记录开启面板的时间
        last_activity_time = start_wait_time  # 记录最近队伍状态变化的时间，当发生人数变化或玩家由"正在加入"变成"已加入"时，更新该时间
        last_joining_time = (
            start_wait_time  # 记录最近加入状态变化的时间，当"正在加入"的人数变化时，更新该时间
        )
        last_joining_count = 0  # 记录上一次 OCR 时"正在加入"的人数
        last_joined_count = 0  # 记录上一次 OCR 时"已加入"的人数

        # 发送差事就绪消息
        self.steam_bot.send_group_message(self.config.msgOpenJobPanel)

        # 导航面板以选中"开始差事"选项
        click_keyboard("w")
        time.sleep(0.8)
        click_keyboard(KEY_ENTER)
        time.sleep(1)
        click_keyboard("a")  # 关闭匹配功能，防止玩家通过匹配功能意外进入该差事
        time.sleep(0.8)
        click_keyboard("w")

        while True:
            time.sleep(self.config.checkLoopTime)
            current_time = time.monotonic()

            # 获取准备界面状态
            is_on_job_panel, joining_count, joined_count = self.get_job_setup_status()

            # 找不到面板则直接返回出错
            if not is_on_job_panel:
                GLogger.warning("找不到启动面板。")
                return False

            GLogger.info(f"队伍状态: {joined_count} 人已加入, {joining_count} 人正在加入。")

            # 如果没人加入则超时
            if (
                current_time - start_wait_time > self.config.matchPanelTimeout
                and last_joined_count == 0
                and last_joining_count == 0
                and joining_count == 0
                and joined_count == 0
            ):
                GLogger.info("长时间没有玩家加入，退出差事并重新开始。")
                self.steam_bot.send_group_message(self.config.msgWaitPlayerTimeout)
                return False

            # 如果有人卡在“正在加入”则超时
            if (
                current_time - last_joining_time > self.config.joiningPlayerKick
                and last_joining_count > 0
                and joining_count > 0
            ):
                GLogger.info('玩家长期卡在"正在加入"状态，退出差事并重新开始。')
                self.steam_bot.send_group_message(self.config.msgJoiningPlayerKick)
                return False

            # 检查是否应该开始差事
            # 满员且设置了满员立即启动
            # 或者有已加入的并且没有未加入的，同时记录最近队伍状态变化的时间已经超过开始差事等待延迟
            if (joined_count == 3 and self.config.startOnAllJoined) or (
                current_time - last_activity_time > self.config.startMatchDelay
                and joined_count > 0
                and joining_count == 0
            ):
                GLogger.info("即将启动差事。")
                # 发送差事启动消息
                self.steam_bot.send_group_message(self.config.msgJobStarting)
                click_keyboard(KEY_ENTER)
                for _ in range(3):
                    if self.is_job_starting():
                        # 成功启动，可喜可贺
                        return True
                else:
                    GLogger.warning("启动差事失败。")
                    # 有时确实启动不了
                    # 处理警告页面
                    if self.is_on_warning_page():
                        click_keyboard(KEY_ENTER)
                        time.sleep(0.5)

                    if self.is_on_job_panel():
                        # 如果还在差事页面可以等下次再试，直到超过卡比时间退出
                        GLogger.info("回到面板，将尝试继续启动。")
                        continue
                    else:
                        # 差事都没了就没办法了
                        GLogger.warning("未回到面板，无法继续。")
                        self.steam_bot.send_group_message(self.config.msgJobStartFail)
                        return False

            # 队伍人数从未满变为满员时，发送满员消息
            if joining_count + joined_count != last_joining_count + last_joined_count:
                if joined_count + joining_count >= 3:  # 队伍已满 (1个主机 + 3个玩家)
                    self.steam_bot.send_group_message(self.config.msgTeamFull)

            # 队伍加入状态变化时，更新最近加入状态变化的时间，最近队伍状态变化的时间，上一次的正在加入人数，上一次的已加入人数
            if joining_count != last_joining_count or joined_count != last_joined_count:
                if joining_count != last_joining_count:
                    last_joining_time = current_time
                last_joining_count, last_joined_count = joining_count, joined_count
                last_activity_time = current_time

    def exit_job_panel(self):
        """从差事准备面板退出到自由模式，如果不在差事准备面板中则行为是未定义的"""
        # 处理警告屏幕
        if self.is_on_warning_page():
            click_keyboard(KEY_ENTER)
            time.sleep(0.5)

        # 从差事准备面板退出
        ocr_result = self.ocr.ocr(self.hwnd, 0, 0, 1, 0.8)
        if re.search("|".join(["匹配", "邀请", "帮会"]), ocr_result) is not None:
            # 如果在差事面板的第二个页面，按两次 ESC 和回车退出
            click_keyboard(KEY_ESCAPE)
            time.sleep(1)
            click_keyboard(KEY_ESCAPE)
            time.sleep(1)
            click_keyboard(KEY_ENTER)
            time.sleep(5)
        elif re.search("|".join(["设置", "镜头", "武器"]), ocr_result) is not None:
            # 如果在差事面板的第一个页面，按一次 ESC 和回车退出
            click_keyboard(KEY_ESCAPE)
            time.sleep(1)
            click_keyboard(KEY_ENTER)
            time.sleep(5)

    # TODO komi说不知道这个方法能不能用
    def try_to_join_bot(self):
        """尝试通过 SteamJvp 加入差传 Bot 战局。"""
        GLogger.info("正在尝试加入一个差传机器人战局...")
        try:
            res = requests.get("http://quellgtacode.mageangela.cn:52014/botJvp/", timeout=10)
            res.raise_for_status()
            bot_list = res.text.replace("\r", "").split("\n")
        except requests.RequestException as e:
            GLogger.error(f"获取差传机器人列表失败: {e}")
            return

        start_index = 3 + (self.config.jobTpBotIndex if self.config.jobTpBotIndex >= 0 else 0)
        bot_lines_to_try = (
            [bot_list[start_index]] if self.config.jobTpBotIndex >= 0 else bot_list[start_index:]
        )

        for line in bot_lines_to_try:
            if "|" not in line:
                continue
            _, jvp_id = line.split("|", 1)
            if not jvp_id:
                continue

            steam_url = f"steam://rungame/3240220/76561199074735990/-steamjvp={jvp_id}"
            GLogger.info(f"正在启动 Steam URL: {steam_url}")
            os.startfile(steam_url)
            time.sleep(3)

            start_join_time = time.monotonic()
            has_suspended = False
            while time.monotonic() - start_join_time < 60:
                click_keyboard(KEY_ENTER)
                click_keyboard("z")
                time.sleep(1)
                if self._find_text("在线模式", 0, 0, 0.5, 0.5):
                    GLogger.info("成功加入差传机器人战局。")
                    return
                if not has_suspended and time.monotonic() - start_join_time > 30:
                    suspend_process_for_duration(self.pid, self.config.suspendGTATime)
                    has_suspended = True

            if self.config.jobTpBotIndex >= 0:
                break  # 如果指定了索引，只尝试一次

        GLogger.warning("在时限内加入差传机器人战局失败。")

    def restart_gta(self):
        """重启 GTA V 游戏，并等待其主菜单加载。"""
        GLogger.info("20秒后将重启 GTA V...")
        self.kill_gta()
        time.sleep(20)  # 等待20秒钟用于 steam 客户端响应 GTA V 退出

        GLogger.info("正在通过 Steam 重新启动游戏...")
        os.startfile("steam://rungameid/3240220")

        # 等待 GTA V 进程启动
        GLogger.info("正在等待 GTA 窗口出现...")
        process_start_time = time.monotonic()
        while time.monotonic() - process_start_time < 300:  # 5分钟总超时
            info = get_window_info("Grand Theft Auto V")
            if info:
                self.hwnd, self.pid = info
                GLogger.info(f"GTA 窗口已找到！句柄: {self.hwnd}, PID: {self.pid}")
                break
            time.sleep(5)
        else:
            GLogger.error("重启 GTA 失败：等待 GTA 窗口出现超时。")

        # 等待主菜单加载
        GLogger.info("正在等待主菜单出现...")
        main_menu_load_start_time = time.monotonic()
        while time.monotonic() - main_menu_load_start_time < 180:  # 3分钟加载超时
            if self._find_text("加入自由模式", 0, 0, 1, 1):
                GLogger.info("主菜单已加载。")
                break
            time.sleep(5)
        else:
            GLogger.error("重启 GTA 失败：等待主菜单加载超时。")

        # 进入故事模式
        for _ in range(2):
            click_keyboard("e")
            time.sleep(3)
        click_keyboard(KEY_ENTER)

        # 等待进入故事模式
        GLogger.info("正在等待进入故事模式...")
        story_mode_load_start_time = time.monotonic()
        while time.monotonic() - story_mode_load_start_time < 120:  # 2分钟加载超时
            if self.is_on_pause_menu():
                GLogger.info("已进入故事模式。")
                break
            click_keyboard(KEY_ESCAPE)
            time.sleep(5)
        else:
            GLogger.error("重启 GTA 失败：等待进入故事模式超时。")

        # 进入在线模式
        for _ in range(3):  # 尝试3次
            for _ in range(5):
                click_keyboard("e")
                time.sleep(2)
            click_keyboard(KEY_ENTER)
            time.sleep(1)
            click_keyboard("w")
            time.sleep(1)
            click_keyboard(KEY_ENTER)
            time.sleep(1)

            # 验证是否打开了进入在线模式的菜单
            if self.is_on_go_online_menu():
                # 进入下一步
                break
            else:
                # 找不到则关闭菜单
                for _ in range(3):
                    click_keyboard(KEY_ESCAPE)
                    time.sleep(1)
                # 再次打开地图
                time.sleep(3)
                if not self.is_on_pause_menu():
                    click_keyboard(KEY_ESCAPE)
                    time.sleep(5)
                continue
        else:
            GLogger.error("重启 GTA 失败：找不到在线模式选项卡。")

        # 选择进入仅邀请战局
        click_keyboard("s")
        time.sleep(1)
        click_keyboard(KEY_ENTER)
        time.sleep(2)
        click_keyboard(KEY_ENTER)

        # 等待进入在线模式
        GLogger.info("正在等待进入在线模式...")
        online_mode_load_start_time = time.monotonic()
        while time.monotonic() - online_mode_load_start_time < 300:  # 5分钟加载超时
            if self.is_respawned():
                GLogger.info("已进入在线模式。")
                break
            time.sleep(5)
        else:
            GLogger.error("重启 GTA 失败：等待进入故事模式超时。")
