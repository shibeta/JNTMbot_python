import os
import time

from logger import get_logger

from ._base import _BaseManager
from .exception import *

logger = get_logger("automator_session")


class Session(_BaseManager):
    """在线战局相关的逻辑"""

    def _try_to_switch_session(self) -> bool:
        """
        尝试执行一次切换到仅邀请战局的完整操作。

        :return:
        - True: 切换战局成功。
        - False: 在菜单导航中失败。
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法切换战局
        """
        logger.info("动作: 正在打开暂停菜单...")

        # 检查游戏状态
        if not self.screen.is_game_started():
            raise UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)

        # 处理警告屏幕
        self.confirm_warning_page()

        # 打开暂停菜单
        self.ensure_pause_menu_is_open()

        # 检查暂停菜单是否被打开
        if not self.screen.is_on_pause_menu():
            logger.warning("打开暂停菜单失败。")
            return False

        logger.info("成功打开暂停菜单。")

        # 尝试打开切换战局菜单
        logger.info("动作: 正在打开切换战局菜单...")
        self.action.navigate_to_switch_session_tab_in_onlinemode()

        # 检查切换战局菜单是否被打开
        if not self.screen.is_on_go_online_menu():
            logger.warning("打开切换战局菜单失败。")
            return False

        logger.info("成功打开切换战局菜单。")

        # 进入仅邀请战局
        self.action.enter_invite_only_session()

        return True

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
        尝试从在线战局中切换到另一个仅邀请战局，必须在自由模式下才能工作。

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
        if self._try_to_switch_session():
            logger.info("成功进入新战局。")
            return

        # 首次尝试失败，开始执行恢复策略
        for strategy in recovery_strategies:
            strategy()

            # 再次尝试切换战局
            if self._try_to_switch_session():
                logger.info(f"在执行恢复策略 {strategy.__name__} 后，成功进入新战局。")
                return

        # 如果所有策略用尽，抛出异常
        logger.error("切换新战局失败次数过多，认为游戏正处于未知状态。")
        raise UnexpectedGameState({GameState.IN_ONLINE_LOBBY, GameState.IN_MISSION}, GameState.UNKNOWN)

    def deprecated_try_to_join_jobwarp_bot(self):
        """
        尝试通过 Steam 加入差传 Bot 战局。

        该方法只能在游戏启动后才能运行，因为游戏未启动时使用 steam://rungame/ 会出现一个程序无法处理的弹窗。

        该方法目前已废弃，将在未来版本中被移除。

        如何迁移到其他方法: 用于回到在线模式自由模式: 重启游戏。用于差传: alt+f4等40秒。用于换战局: 菜单寻找新战局

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动所以无法加入差传 Bot 战局
        :raises ``NetworkError(NetworkErrorContext.FETCH_WARPBOT_INFO)``: 从 mageangela 的接口获取差传 Bot 的战局链接时发生网络错误
        :raises ``NetworkError(NetworkErrorContext.JOIN_WARPBOT_SESSION)``: 加入所有差传 Bot 战局均失败
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        logger.warning("警告: 正在使用已废弃的加入差传 Bot 方法。该方法将来会被移除，请尽快迁移到其他方法。")
        logger.warning(
            "如何迁移到其他方法: 用于回到在线模式自由模式: 重启游戏。用于差传: alt+f4等40秒。用于换战局: 菜单寻找新战局"
        )

        logger.info("动作: 正在加入差传 Bot 战局...")

        if not self.screen.is_game_started():
            raise UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)

        list_bot_jvp = self.get_mageangela_jobwarp_bot_steamjvp()

        # 根据 config 中的配置决定加入哪些差传 Bot
        if self.config.jobTpBotIndex > 0:
            # 配置为大于 0 时，使用对应该序号的 Bot
            bot_lines_to_try = [list_bot_jvp[self.config.jobTpBotIndex - 1]]
        else:
            # 配置为小于 0 时，使用所有可用的 Bot
            bot_lines_to_try = list_bot_jvp

        # 使用 Steam 加入差传 Bot 战局
        for bot in bot_lines_to_try:
            try:
                self.join_session_through_steam(bot)
                # 加入差传 Bot 后，有时会掉进公开战局，所以需要卡单
                time.sleep(5)  # 等待5秒钟让游戏稳定
                self.glitch_single_player_session()
                break
            except OperationTimeout as e:
                logger.error(f"加入差传 Bot 时，{e}")
                # 超时后先进行一次卡单，然后再尝试下一个 Bot
                time.sleep(5)  # 等待5秒钟让游戏稳定
                self.glitch_single_player_session()
            except UnexpectedGameState as e:
                logger.error(f"加入差传 Bot 时，{e}")
        else:
            raise NetworkError(NetworkErrorContext.JOIN_WARPBOT_SESSION)

        logger.info("成功加入差传 Bot 战局。")

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

        if not self.screen.is_game_started():
            raise UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)

        steam_url = f"steam://rungame/3240220/76561199074735990/-steamjvp={steam_jvp}"
        os.startfile(steam_url)
        time.sleep(3)

        # 等待加入战局
        self.wait_for_online_mode_load()

        logger.info(f"成功加入战局: {steam_jvp}")
