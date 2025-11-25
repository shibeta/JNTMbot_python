import time

from logger import get_logger

from ._base_workflow import _BaseWorkflow
from .exception import *

logger = get_logger(__name__.split(".")[-1])


class OnlineWorkflow(_BaseWorkflow):
    """在线战局相关的操作"""

    def _try_to_switch_session(self):
        """
        尝试执行一次切换到仅邀请战局的完整操作。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法切换战局
        :raises ``UIElementNotFound(UIElementNotFoundContext.PAUSE_MENU)``: 打开暂停菜单失败
        :raises ``UIElementNotFound(UIElementNotFoundContext.SWITCH_SESSION_TAB)``: 打开切换战局菜单失败
        """
        # 打开暂停菜单
        self.open_pause_menu()

        # 尝试打开切换战局菜单
        logger.info("动作: 正在打开切换战局菜单...")
        self.action.navigate_to_switch_session_tab_in_onlinemode()

        # 检查切换战局菜单是否被打开
        if not self.screen.is_on_go_online_menu():
            logger.warning("打开切换战局菜单失败。")
            raise UIElementNotFound(UIElementNotFoundContext.SWITCH_SESSION_TAB)

        logger.info("成功打开切换战局菜单。")

        # 进入仅邀请战局
        self.action.enter_invite_only_session()

    def _recover_by_do_nothing(self):
        """有的时候，什么都不做就是最好的"""
        pass

    def _recover_by_brute_force_back(self):
        """通过狂按 B 键来退出任何可能卡住的子菜单"""
        logger.info("动作: 尝试通过多次按 B 键来恢复正常状态...")
        for _ in range(7):
            self.action.back()
        logger.info("已停止按 B 键。")

    def _recover_by_back_and_confirm(self):
        """通过交替按 B 和 A 键来处理一些需要确认的对话框"""
        logger.info("动作: 尝试通过多次按 B 键和 A 键来恢复正常状态...")
        for _ in range(4):
            self.action.back()
            self.action.confirm()
        logger.info("已停止按 B 键和 A 键。")

    def _recover_by_glitching_session(self):
        """通过卡单人战局来处理卡云"""
        logger.info("尝试通过卡单来恢复正常状态。")
        self.glitch_single_player_session()
        time.sleep(5)  # 卡完单等一会

    def start_new_match(self):
        """
        尝试从在线战局中切换到另一个仅邀请战局，必须在在线模式中才能工作。

        :raises ``UnexpectedGameState(expected={GameState.IN_ONLINE_LOBBY, GameState.IN_MISSION}, actual=GameState.UNKNOWN)``: 游戏状态未知，无法切换战局
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法切换战局
        """
        logger.info("动作: 正在切换新战局...")

        # 恢复策略的列表，按照严重程度排序
        recovery_strategies = [
            self._recover_by_do_nothing,
            self._recover_by_brute_force_back,
            self._recover_by_back_and_confirm,
            self._recover_by_glitching_session,
        ]

        # 第一次尝试切换战局
        try:
            self._try_to_switch_session()
            logger.info("成功进入新战局。")
            return
        except UIElementNotFound:
            # 捕获打开菜单失败的异常，执行恢复策略
            pass

        # 首次尝试失败，开始执行恢复策略
        for strategy in recovery_strategies:
            strategy()
            # 再次尝试切换战局
            try:
                self._try_to_switch_session()
                logger.info(f"在执行恢复策略 {strategy.__name__} 后，成功进入新战局。")
                return
            except UIElementNotFound:
                # 捕获打开菜单失败的异常，继续执行下一个恢复策略
                pass

        # 如果所有策略用尽，抛出异常
        logger.error("切换新战局失败次数过多，认为游戏正处于未知状态。")
        raise UnexpectedGameState({GameState.ONLINE_FREEMODE, GameState.IN_MISSION}, GameState.UNKNOWN)

    def get_bad_sport_level(self) -> str:
        """
        在在线模式中，获取当前角色的恶意等级。
        只能在单人战局中使用，因为该方法实际用于检查战局内第一个玩家的恶意等级。

        :return: 恶意等级字符串，如 "清白玩家", "问题玩家", "恶意玩家"
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        :raises ``UIElementNotFound(UIElementNotFoundContext.BAD_SPORT_LEVEL_INDICATOR)``: 读取恶意等级失败
        """
        logger.info("动作: 正在获取当前角色的恶意值...")
        # 打开暂停菜单并导航到玩家列表
        self.open_pause_menu()
        self.action.navigate_to_player_list_tab_in_onlinemode()
        time.sleep(0.5)  # 等待玩家列表加载
        # 读取恶意等级
        bad_sport_level = self.screen.get_bad_sport_level_of_first_player_in_list()
        if bad_sport_level == "未知等级":
            # 重试最多三次
            for _ in range(3):
                logger.warning("读取恶意等级失败，正在重试...")
                time.sleep(0.5)
                bad_sport_level = self.screen.get_bad_sport_level_of_first_player_in_list()
                if bad_sport_level != "未知等级":
                    break

        # 关闭暂停菜单
        self.action.open_or_close_pause_menu()
        if bad_sport_level == "未知等级":
            raise UIElementNotFound(UIElementNotFoundContext.BAD_SPORT_LEVEL_INDICATOR)

        logger.info(f"当前角色的恶意等级为 {bad_sport_level} 。")
        return bad_sport_level
