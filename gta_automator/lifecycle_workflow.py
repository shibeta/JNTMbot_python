import os
import time

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
            for retry_times in range(max(self.config.restartGTAConsecutiveFailThreshold, 1)):
                self.kill_and_restart_gta()
                if self.process.is_game_started():
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
            self.process.update_gta_window_info()

        # 以防万一将其从挂起中恢复
        self.process.resume_gta_process()

        logger.info("初始化 GTA V 完成。")

    def force_shutdown_gta(self):
        """强制退出游戏，通过杀死进程实现"""
        self.process.kill_gta_process()

    def kill_and_restart_gta(self):
        """
        杀死并重启 GTA V 游戏，并进入在线模式仅邀请战局。

        如果重启游戏失败，将杀死游戏进程。
        """
        logger.info(f"动作: 正在杀死并重启 GTA V...")

        self.force_shutdown_gta()
        logger.info("20秒后将重启 GTA V...")
        time.sleep(20)  # 等待20秒钟用于 steam 客户端响应 GTA V 退出
        # 以防万一再杀一次
        self.force_shutdown_gta()

        # 启动游戏
        try:
            self.start_gta_steam()
        except GameAutomatorException as e:
            logger.error(f"启动 GTA V 时，发生异常: {e}")
            self.force_shutdown_gta()
            return

        # 进入故事模式
        time.sleep(2)
        try:
            self.enter_storymode_from_mainmenu()
        except GameAutomatorException as e:
            logger.error(f"进入故事模式时，发生异常: {e}")
            self.force_shutdown_gta()
            return

        # 进入在线模式
        time.sleep(2)
        try:
            self.enter_onlinemode_from_storymode()
        except UnexpectedGameState as e:
            logger.error(f"进入在线模式时，发生异常: {e}")
            if e.actual_state == GameState.BAD_PCSETTING_BIN:
                self.force_shutdown_gta()
                self.fix_bad_pcsetting()
            else:
                self.force_shutdown_gta()
            return
        except GameAutomatorException as e:
            logger.error(f"进入在线模式时，发生异常: {e}")
            self.force_shutdown_gta()
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
        if self.process.is_game_started():
            self.process.update_gta_window_info()
            logger.warning(
                "在游戏运行时，调用启动游戏方法将仅更新 GTA V 窗口信息。如果需要重启，请调用重启方法。"
            )
            return

        logger.info("动作: 正在通过 Steam 启动 GTA V...")
        os.startfile("steam://rungameid/3240220")

        # 等待 GTA V 窗口出现
        self.wait_for_gta_window_showup()
        logger.info("GTA V 窗口已出现。")
        time.sleep(5)  # 等待5秒钟让游戏稳定

        # 更新 GTA V 窗口信息
        self.process.update_gta_window_info()

        # 等待主菜单加载
        self.wait_for_mainmenu_load()

        logger.info("已启动 GTA V。")

    def wait_for_gta_window_showup(self):
        """
        等待 GTA V 窗口出现。
        :raises ``OperationTimeout(OperationTimeoutContext.GAME_WINDOW_STARTUP)``: 等待 GTA V 窗口出现超时
        """
        logger.info("正在等待 GTA V 窗口出现...")

        if not self.wait_for_state(self.process.is_game_started, 300, 10, False):
            raise OperationTimeout(OperationTimeoutContext.GAME_WINDOW_STARTUP)

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

        # 检查是否在故事模式页面
        if not self.screen.is_on_mainmenu_storymode_page():
            raise UIElementNotFound(UIElementNotFoundContext.STORY_MODE_MENU)

        # 进入故事模式
        self.action.confirm()

        # 等待故事模式加载
        self.wait_for_storymode_load()

        logger.info("已进入故事模式。")

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
        self.wait_for_online_mode_load()

        logger.info("已进入在线模式。")
