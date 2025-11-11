import time
import subprocess

from logger import get_logger

from .exception import *
from ._base import _BaseWorkflow

logger = get_logger("lifecycle_workflow")


class LifecycleWorkflow(_BaseWorkflow):
    """处理游戏启动与关闭，以及如何进入在线模式等过程"""

    def setup_gta(self):
        """
        确保 GTA V 启动，同时更新 PID 和窗口句柄。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 启动 GTA V 失败
        """
        logger.info("动作: 正在初始化 GTA V ...")

        if not self.process.is_game_started():
            # 没启动就先启动
            logger.warning("GTA V 未启动。正在启动游戏...")
            # 尝试启动 restartGTAConsecutiveFailThreshold 次，至少一次
            max_retry_times = max(self.config.restartGTAConsecutiveFailThreshold, 1)
            for retry_times in range(max_retry_times):
                self.restart_gta()
                if self.process.is_game_started():
                    # 启动过程中会自己设置 PID 和窗口句柄, 不需要做任何事
                    return
                else:
                    logger.warning(f"GTA V 启动失败。将重试 {max_retry_times-1-retry_times} 次。")
                    continue
            else:
                # 达到最大失败次数后抛出异常
                logger.error("GTA V 启动失败次数过多，认为游戏处于无法启动的状态。")
                raise UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)
        else:
            # 如果启动了则更新 PID 和窗口句柄
            self.process.update_info()

        # 以防万一将其从挂起中恢复
        self.process.resume()

        logger.info("初始化 GTA V 完成。")

    def shutdown_gta(self):
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
            self.force_shutdown_gta()
        logger.info("退出游戏完成。")

    def force_shutdown_gta(self):
        """杀死进程以强制关闭游戏"""
        logger.info("动作: 正在强制关闭游戏...")
        self.process.kill()
        logger.info("强制关闭游戏完成。")

    def launch_gta_online(self):
        """
        启动游戏，并进入在线模式仅邀请战局。

        如果启动游戏失败，将关闭游戏。
        """
        try:
            self.start_gta_steam()
        except GameAutomatorException as e:
            logger.error(f"启动 GTA V 时，发生异常: {e}")
            self.shutdown_gta()
            return

        # 进入故事模式
        time.sleep(2)
        try:
            self.enter_storymode_from_mainmenu()
        except GameAutomatorException as e:
            logger.error(f"进入故事模式时，发生异常: {e}")
            self.shutdown_gta()
            return

        # 进入在线模式
        time.sleep(2)
        try:
            self.enter_onlinemode_from_storymode()
        except UnexpectedGameState as e:
            logger.error(f"进入在线模式时，发生异常: {e}")
            if e.actual_state == GameState.BAD_PCSETTING_BIN:
                self.shutdown_gta()
                self.fix_bad_pcsetting()
            else:
                self.shutdown_gta()
            return
        except GameAutomatorException as e:
            logger.error(f"进入在线模式时，发生异常: {e}")
            self.shutdown_gta()
            return

    def restart_gta(self, force: bool = False):
        """
        杀死并重启 GTA V 游戏，并进入在线模式仅邀请战局。

        如果重启游戏失败，将关闭游戏。
        """
        logger.info(f"动作: 正在重启 GTA V...")

        # 关闭游戏
        if force:
            self.force_shutdown_gta()
        else:
            self.shutdown_gta()

        logger.info("20秒后将重启 GTA V...")
        time.sleep(20)  # 等待20秒钟用于 steam 客户端响应 GTA V 退出
        # 以防万一，再触发一次强制关闭
        self.force_shutdown_gta()

        # 启动游戏并进入在线模式
        self.launch_gta_online()

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
        if self.process.is_game_started():
            self.process.update_info()
            logger.warning(
                "在游戏运行时，调用启动游戏方法将仅更新 GTA V 窗口信息。如果需要重启，请调用重启方法。"
            )
            return

        logger.info("动作: 正在通过 Steam 启动 GTA V...")
        # subprocess.Popen 可以避免阻塞主进程
        # CREATE_BREAKAWAY_FROM_JOB 使主程序退出时不会关闭 Steam 进程和 GTA V 进程
        subprocess.Popen(["start", "", "steam://rungameid/3240220"], shell=True, creationflags=subprocess.CREATE_BREAKAWAY_FROM_JOB)

        # 等待 GTA V 窗口出现
        self.wait_for_gta_window_showup()
        logger.info("GTA V 窗口已出现。")
        time.sleep(5)  # 等待5秒钟让游戏稳定

        # 更新 GTA V 窗口信息
        self.process.update_info()

        # 等待主菜单加载
        self.process_main_menu_loading()

        logger.info("已启动 GTA V。")

    def wait_for_gta_window_showup(self):
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
        start_time = time.monotonic()
        while time.monotonic() - start_time < 180:  # 3分钟加载超时，有时需要等待预编译管线
            # 每5秒检查一次
            time.sleep(5)

            # 获取一次当前屏幕状态
            ocr_text = self.screen.ocr_game_window(0.5, 0.8, 0.5, 0.2)

            # 检查是否在主菜单
            if self.screen.is_on_mainmenu(ocr_text):
                # 进入了主菜单
                return
            # 当pcsetting文件损坏时，会展示设置伽马值的页面
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
            self.ensure_pause_menu_is_open()
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
        self.ensure_pause_menu_is_open()

        # 打开进入在线模式的菜单
        self.navigate_to_go_online_menu()

        # 进入仅邀请战局
        self.action.enter_invite_only_session()

        # 等待进入在线模式
        self.process_online_loading()

        logger.info("已进入在线模式。")
