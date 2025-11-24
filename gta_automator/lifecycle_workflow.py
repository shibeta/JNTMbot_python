import time
from typing import Optional

from logger import get_logger
from windows_utils import exec_command_detached

from .exception import *
from ._base_workflow import _BaseWorkflow

logger = get_logger(__name__.split(".")[-1])


class LifecycleWorkflow(_BaseWorkflow):
    """游戏启动与关闭，以及进入在线模式相关的操作"""

    def is_game_ready(self) -> bool:
        """
        检查游戏是否已启动并进入在线模式。

        :return: 如果游戏已启动并进入在线模式则返回 True，否则返回 False
        """
        if not self.process.is_game_started():
            return False

        # 更新游戏进程信息
        self.process.update_info()
        # 确保进程未被挂起
        self.process.resume()

        try:
            # 处理警告页面
            self.handle_warning_page()
            return self.check_if_in_onlinemode()
        except UnexpectedGameState:
            return False

    def shutdown(self):
        """关闭游戏。首先尝试通过 alt+f4 退出，如果失败则杀死进程。"""
        logger.info("动作: 正在退出游戏...")
        # 先尝试常规退出流程
        try:
            # 如过游戏没启动，则跳过常规退出流程
            if not self.process.is_game_started():
                logger.warning("GTA V 未启动，跳过退出流程。")
            else:
                # 处理警告页面，以避免其他警告页面干扰退出页面判断
                self.handle_warning_page()
                # 触发 alt+f4, 然后等待游戏加载退出页面
                self.process.request_exit()
                time.sleep(3)
                # 检查是否在确认退出页面
                if self.screen.is_on_exit_confirm_page():
                    # 游戏会先尝试与 RockStar 在线服务通信以进行保存, 直到保存成功或保存失败后才能确认退出
                    if self.wait_for_state(self.screen.is_confirm_option_available, 30):
                        # 选择退出选项
                        self.action.confirm()
                        # 等待游戏关闭
                        if self.wait_for_state(lambda: not self.process.is_game_started(), 30, 1, False):
                            # 游戏关闭后等待 20 秒，给进程响应时间
                            time.sleep(20)
                            logger.info("通过常规方法退出游戏成功。")
        except Exception as e:
            logger.warning(f"通过常规方法退出游戏时，发生异常: {e}")
            pass
        finally:
            # 更新游戏进程信息
            self.process.update_info()

        # 如果游戏还在运行，强制关闭
        if self.process.is_game_started():
            logger.info("通过常规方法退出游戏失败，将强制关闭游戏。")
            self.force_shutdown()
        logger.info("退出游戏完成。")

    def force_shutdown(self):
        """杀死进程以强制关闭游戏"""
        logger.info("动作: 正在强制关闭游戏...")
        self.process.kill()
        logger.info("强制关闭游戏完成。")

    def launch(self):
        """
        启动游戏，并进入在线模式仅邀请战局。

        如果启动游戏失败，将关闭游戏。
        """
        try:
            self.start_via_steam()
        except GameAutomatorException as e:
            logger.error(f"启动 GTA V 时，发生异常: {e}")
            self.shutdown()
            return

        # 进入故事模式
        time.sleep(2)
        try:
            self.enter_storymode_from_mainmenu()
        except GameAutomatorException as e:
            logger.error(f"进入故事模式时，发生异常: {e}")
            self.shutdown()
            return

        # 进入在线模式
        time.sleep(2)
        try:
            self.enter_onlinemode_from_storymode()
        except UnexpectedGameState as e:
            logger.error(f"进入在线模式时，发生异常: {e}")
            if e.actual_state == GameState.BAD_PCSETTING_BIN:
                self.shutdown()
                self.fix_bad_pcsetting()
            else:
                self.shutdown()
            return
        except GameAutomatorException as e:
            logger.error(f"进入在线模式时，发生异常: {e}")
            self.shutdown()
            return

    def restart(self, force: bool = False):
        """
        杀死并重启 GTA V 游戏，并进入在线模式仅邀请战局。

        如果重启游戏失败，将关闭游戏并抛出异常。

        :param force: 如果为 True，则强制关闭游戏而不尝试常规退出
        :raise ``UnexpectedGameState(expected=GameState.ONLINE_FREEMODE, actual=GameState.UNKNOWN)``: 重启游戏失败次数过多
        """
        logger.info(f"动作: 正在重启 GTA V...")

        # 关闭游戏
        if force:
            self.force_shutdown()
        else:
            self.shutdown()

        logger.info("20秒后将重启 GTA V...")  # 剩下那 10 秒在第一次循环里
        time.sleep(10)  # 等待 10 秒钟用于 steam 客户端响应 GTA V 退出

        # 启动游戏并进入在线模式仅邀请战局
        # 从 config 获取最大尝试次数，至少 1 次
        max_retry_times = max(self.config.restartGTAConsecutiveFailThreshold, 1)
        for retry_times in range(max_retry_times):
            # 每次重试前确保游戏已关闭
            self.force_shutdown()
            time.sleep(10)  # 等待 10 秒钟用于 steam 客户端响应 GTA V 退出
            logger.info(f"GTA V 重启尝试第 {retry_times + 1} 次。")
            self.launch()
            if self.process.is_game_started():
                # 游戏成功启动
                break
            else:
                logger.warning(f"GTA V 重启失败。将重试 {max_retry_times-1-retry_times} 次。")
                continue
        else:
            # 达到最大失败次数后抛出异常
            logger.error("GTA V 重启失败次数过多，退出游戏。")
            if self.process.is_game_started():
                self.shutdown()
            raise UnexpectedGameState(expected=GameState.ONLINE_FREEMODE, actual=GameState.UNKNOWN)

        logger.info("重启 GTA V 成功。")

    def start_via_steam(self):
        """
        如果 GTA V 没有启动，通过 Steam 启动游戏，并更新 pid 和 hwnd。

        如果 GTA V 已经启动，则仅更新 pid 和 hwnd，不做其他事。

        :raises ``OperationTimeout(OperationTimeoutContext.GAME_WINDOW_STARTUP)``: 等待游戏窗口出现超时
        :raises ``OperationTimeout(OperationTimeoutContext.MAIN_MENU_LOAD)``: 等待主菜单加载超时
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        # 游戏启动则仅更新 pid 和 hwnd
        if self.process.is_game_started():
            self.process.update_info()
            logger.warning(
                "在游戏运行时，调用启动游戏方法将仅更新 GTA V 窗口信息。如果需要重启，请调用重启方法。"
            )
            return

        logger.info("动作: 正在通过 Steam 启动 GTA V...")
        exec_command_detached(["start", "", "steam://rungameid/3240220"])

        # 等待 GTA V 窗口出现
        self.wait_for_window_showup()
        logger.info("GTA V 窗口已出现。")
        time.sleep(5)  # 等待5秒钟让游戏稳定

        # 更新 GTA V 窗口信息
        self.process.update_info()

        # 等待主菜单加载
        self.process_main_menu_loading()

        logger.info("已启动 GTA V。")

    def wait_for_window_showup(self):
        """
        等待 GTA V 窗口出现。

        :raises ``OperationTimeout(OperationTimeoutContext.GAME_WINDOW_STARTUP)``: 等待 GTA V 窗口出现超时
        """
        logger.info("正在等待 GTA V 窗口出现...")

        # 5分钟超时，因为rockstar启动器非常慢
        if not self.wait_for_state(self.process.is_game_started, 300, 10, False):
            raise OperationTimeout(OperationTimeoutContext.GAME_WINDOW_STARTUP)

    def process_main_menu_loading(self):
        """
        等待主菜单加载完成，并处理加载过程中的各种意外情况。

        :raises ``OperationTimeout(OperationTimeoutContext.MAIN_MENU_LOAD)``: 等待主菜单加载超时
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR

        """
        logger.info("动作: 正在等待主菜单加载...")
        end_time = time.monotonic() + 180  # 3分钟加载超时，有时需要等待预编译管线
        while time.monotonic() < end_time:
            # 每5秒检查一次
            time.sleep(5)

            # 获取一次当前屏幕状态
            ocr_text = self.screen.ocr_game_window(0.5, 0.8, 0.5, 0.2)

            # 检查是否在主菜单
            if self.screen.is_on_mainmenu(ocr_text):
                # 进入了主菜单
                return
            # 当pcsetting文件损坏时，会展示设置伽马值的页面
            # 有的时候加载主菜单还会显示警告页面，该方法可以一并处理
            elif self.screen.is_on_mainmenu_display_calibration_page(ocr_text):
                time.sleep(2)  # 等待页面加载完成
                self.action.confirm()
                continue
            # 有时候会展示 GTA+ 广告窗口
            elif self.screen.is_on_mainmenu_gtaplus_advertisement_page(ocr_text):
                time.sleep(2)  # 等待广告页面加载完成
                self.action.confirm()
                continue
        else:
            # 循环结束仍未加载成功
            raise OperationTimeout(OperationTimeoutContext.MAIN_MENU_LOAD)

    def enter_storymode_from_mainmenu(self):
        """
        从主菜单进入故事模式，并打开暂停菜单。

        如果不在菜单中，其行为是未定义的。

        :raises ``UIElementNotFound(UIElementNotFoundContext.FINDING_STORY_MODE_MENU)``: 无法找到故事模式菜单。
        :raises ``OperationTimeout(OperationTimeoutContext.STORY_MODE_LOAD)``: 等待故事模式加载超时
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        :raises ``UnexpectedGameState(expected=GameState.MAIN_MENU, actual=GameState.OFFLINE)``: 未登录 Social Club，无法进入在线模式
        """
        logger.info("动作: 正在进入故事模式...")

        # 检查 Social Club 登录状态
        if self.screen.is_on_mainmenu_logout():
            # 未登录时，无法进入在线模式，接下来的操作都没有意义
            raise UnexpectedGameState(GameState.MAIN_MENU, GameState.OFFLINE)

        # 在主菜单中切换到故事模式页面
        self.action.navigate_to_storymode_tab_in_mainmenu()
        time.sleep(1)

        # 检查是否在故事模式页面
        if not self.screen.is_on_mainmenu_storymode_page():
            raise UIElementNotFound(UIElementNotFoundContext.STORY_MODE_MENU)

        # 进入故事模式
        self.action.confirm()

        # 等待故事模式加载
        self.wait_for_storymode_load()

        logger.info("已进入故事模式。")

    def wait_for_storymode_load(self):
        """
        等待故事模式加载完成。

        :raises ``OperationTimeout(OperationTimeoutContext.STORY_MODE_LOAD)``: 等待故事模式加载超时
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR

        """
        logger.info("动作: 正在等待故事模式加载...")

        if not self.wait_for_state(self.check_if_in_storymode, 120, 5):
            raise OperationTimeout(OperationTimeoutContext.STORY_MODE_LOAD)

    def navigate_to_go_online_menu(self):
        """
        从暂停菜单导航至'进入在线模式'的菜单。

        :raises ``UIElementNotFound(UIElementNotFoundContext.ONLINE_MODE_TAB)``: 找不到在线模式选择卡
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        logger.info("动作: 正在导航至在线模式菜单...")
        for attempt in range(3):  # 尝试3次
            logger.debug(f"导航尝试第 {attempt + 1} 次...")
            self.action.navigate_to_online_tab_in_storymode()

            if self.screen.is_on_go_online_menu():
                logger.info("成功打开在线模式菜单。")
                return  # 成功，退出函数

            # 如果失败，执行恢复操作
            logger.warning("导航失败，正在尝试恢复...")
            for _ in range(3):
                self.action.back()
            self.open_pause_menu()
        else:
            # 三次尝试均失败，抛出异常
            raise UIElementNotFound(UIElementNotFoundContext.ONLINE_MODE_TAB)

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
        self.open_pause_menu()

        # 打开进入在线模式的菜单
        self.navigate_to_go_online_menu()

        # 进入仅邀请战局
        self.action.enter_invite_only_session()

        # 等待进入在线模式
        self.process_online_loading()

        logger.info("已进入在线模式。")

    def process_online_loading(self):
        """
        等待进入在线模式，并处理加载过程中的各种意外情况。
        该方法被多个管理器共用，因此被放置在基类中。

        :raises ``OperationTimeout(OperationTimeoutContext.JOIN_ONLINE_SESSION)``: 等待进入在线模式超时
        :raises ``UnexpectedGameState(expected=GameState.IN_ONLINE_LOBBY, actual=GameState.BAD_PCSETTING_BIN)``: 由于 pc_setting.bin 问题无法进入在线模式
        :raises ``UnexpectedGameState(expected=GameState.IN_ONLINE_LOBBY, actual=GameState.MAIN_MENU)``: 由于网络问题等原因被回退到主菜单 (仅限增强版)
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        logger.info("正在等待进入在线模式...")
        start_time = time.monotonic()
        end_time = start_time + 300  # 5分钟超时
        has_triggered_single_session = False

        while time.monotonic() < end_time:
            # 每10秒检查一次
            time.sleep(10)

            # 获取一次当前屏幕状态
            ocr_text = self.screen.ocr_game_window(0, 0, 1, 1)

            # 检查各种错误/意外状态
            if self.screen.is_on_bad_pcsetting_warning_page(ocr_text):
                # 由于 pc_setting.bin 问题无法进线上
                raise UnexpectedGameState(GameState.ONLINE_FREEMODE, GameState.BAD_PCSETTING_BIN)
            elif self.handle_warning_page(ocr_text):
                # 处理错误窗口，比如网络不好，R星发钱等情况
                continue
            elif self.screen.is_on_mainmenu(ocr_text):
                # 由于网络不好或者被BE踢了，进入了主菜单
                raise UnexpectedGameState(GameState.ONLINE_FREEMODE, GameState.MAIN_MENU)
            elif self.handle_online_service_policy_page(ocr_text):
                # 处理 RockStar Games 在线服务政策页面
                continue

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

    def handle_online_service_policy_page(self, ocr_text: Optional[str] = None) -> bool:
        """
        如果当前在"RockStar Games 在线服务政策"页面，则勾选"我已阅读"并提交。

        :param ocr_text: 可选的 OCR 结果字符串，用于检查是否在在线服务政策页面。如果未提供则会自动获取当前屏幕的 OCR 结果
        :return: 没有发现在线服务政策页面时返回 False，发现并确认在线服务政策页面时返回 True
        :raises ``OperationTimeout(OperationTimeoutContext.DOWNLOAD_POLICY)``: 下载在线服务政策超时
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        # 不在在线服务政策页面，直接返回
        if not self.screen.is_on_online_service_policy_page(ocr_text):
            return False

        logger.info("动作: 发现在线服务政策页面，正在确认...")
        # 在线服务政策页面首先会下载各种政策，等待至多 60 秒来完成下载
        if not self.wait_for_state(self.screen.is_online_service_policy_loaded, 60, 1):
            raise OperationTimeout(OperationTimeoutContext.DOWNLOAD_POLICY)

        # 目前有两条在线服务政策，第一条是隐私政策，第二条是服务条款
        # 尝试点击确认键，看看是否还停留在在线服务政策页面
        self.action.confirm()
        # 如果不在在线服务政策页面，说明点到条款里了
        ocr_result = self.screen.ocr_game_window(0, 0, 0.7, 0.3)
        if not self.screen.is_on_online_service_policy_page(ocr_result):
            # 如果在隐私政策中，返回并下移两次，选中"我已确认"
            if self.screen.is_on_privacy_policy_page(ocr_result):
                self.action.back()
                self.action.down()
                self.action.down()
            # 如果在服务条款中，返回并下移一次，选中"我已确认"
            elif self.screen.is_on_term_of_service_page(ocr_result):
                self.action.back()
                self.action.down()

        # 以上步骤会选中"我已确认"选项，进行确认并提交
        self.action.confirm()
        self.action.down()
        self.action.confirm()
        time.sleep(0.2)  # 等待游戏响应页面关闭
        logger.info("已确认在线服务政策页面。")
        return True

    def join_session_through_steam(self, steam_jvp: str):
        """
        通过 Steam 的"加入游戏"功能，加入一个战局。

        该方法只能在游戏启动后才能运行，因为游戏未启动时使用 steam://rungame/ 会出现一个程序无法处理的弹窗。

        :param steam_jvp: URL 编码后的 steam_jvp 参数
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动所以无法加入战局
        :raises ``OperationTimeout(OperationTimeoutContext.ONLINE_SESSION_JOIN)``: 加入战局时超时
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        logger.info(f"动作: 正在加入战局: {steam_jvp}")

        if not self.process.is_game_started():
            raise UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)

        steam_url = f"steam://rungame/3240220/76561199074735990/-steamjvp={steam_jvp}"
        exec_command_detached(["start", "", steam_url])
        time.sleep(3)

        # 等待加入战局
        self.process_online_loading()

        logger.info(f"成功加入战局: {steam_jvp}")
