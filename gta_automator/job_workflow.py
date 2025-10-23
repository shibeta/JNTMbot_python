import time
import requests

from logger import get_logger
from config import Config
from steambot_utils import SteamBotClient

from ._base import _BaseWorkflow
from .game_process import GameProcess
from .game_screen import GameScreen
from .exception import *
from .game_action import GameAction

logger = get_logger("job_workflow")


class LobbyStateTracker:
    """封装了跟踪差事面板状态的所有逻辑。"""

    def __init__(self):
        self.start_wait_time = time.monotonic()
        self.team_status_last_changed_time = self.start_wait_time
        self.last_zero_joining_player_time = self.start_wait_time
        self.last_joining_player = 0
        self.last_joined_player = 0
        self.team_full_notified = False

    def get_last_counts(self) -> tuple[int, int]:
        """返回上一轮的玩家数量 (joining, joined)。"""
        return self.last_joining_player, self.last_joined_player

    def update(self, joining_count: int, joined_count: int):
        """用最新的玩家数量更新内部状态和计时器。"""
        current_time = time.monotonic()

        # 如果总人数或加入/正在加入的人数结构发生变化，更新队伍状态变化计时器
        if joining_count != self.last_joining_player or joined_count != self.last_joined_player:
            self.team_status_last_changed_time = current_time
            # 如果没有正在加入的玩家，更新无加入状态玩家计时器
            if joining_count == 0:
                self.last_zero_joining_player_time = current_time

            # 更新大厅人数计数器
            self.last_joining_player = joining_count
            self.last_joined_player = joined_count

    def has_wait_timeout(self, timeout: int) -> bool:
        """检查是否长时间没有任何玩家加入。"""
        is_empty = self.last_joined_player == 0 and self.last_joining_player == 0
        time_elapsed = time.monotonic() - self.start_wait_time
        return is_empty and time_elapsed > timeout

    def has_joining_timeout(self, timeout: int) -> bool:
        """检查是否有人长时间卡在“正在加入”状态。"""
        is_stuck = self.get_last_counts()[0] > 0  # 有人正在加入
        time_elapsed = time.monotonic() - self.last_zero_joining_player_time
        return is_stuck and time_elapsed > timeout

    def should_start_job(
        self,
        joining_count: int,
        joined_count: int,
        start_immediately_when_full: bool,
        normal_start_delay: float,
    ) -> bool:
        """根据当前状态和配置，判断是否应该开始差事。"""
        team_is_full = joined_count >= 3  # 队伍已满
        if team_is_full and start_immediately_when_full:
            return True

        can_start_with_delay = joined_count > 0 and joining_count == 0  # 有人已加入，且没人正在加入了
        delay_passed = (time.monotonic() - self.team_status_last_changed_time) > normal_start_delay
        if can_start_with_delay and delay_passed:
            return True

        return False


class JobWorkflow(_BaseWorkflow):
    """用于在游戏中进行差事的相关操作的封装"""

    def __init__(
        self,
        screen: GameScreen,
        input: GameAction,
        process: GameProcess,
        config: Config,
        steam_bot: SteamBotClient,
    ):
        super(JobWorkflow, self).__init__(screen, input, process, config)
        self.steam_bot = steam_bot

    def wait_for_respawn(self):
        """
        等待玩家在事务所的床上复活。

        :raises ``OperationTimeout(OperationTimeoutContext.RESPAWN_IN_AGENCY)``: 等待在事务所床上复活超时
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        logger.info("等待在事务所床上复活...")

        if not self.wait_for_state(self.screen.is_respawned_in_agency, timeout=60):
            raise OperationTimeout(OperationTimeoutContext.RESPAWN_IN_AGENCY)
        logger.info("在事务所床上复活成功。")

    def _find_job_point(self):
        """
        检查是否到达任务触发点。如果没有，会螺旋形遍历周围空间。

        :raises ``UIElementNotFound(UIElementNotFoundContext.JOB_TRIGGER_POINT)``: 未找到任务触发点
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        logger.info("动作：正在寻找差事触发点...")

        # 检查是否已经站在触发点上
        if self.screen.is_job_marker_found():
            logger.info("成功找到差事触发点。")
            return

        # 定义螺旋搜索模式，先上，再左，再下，再右，不断扩大
        search_pattern = [
            (self.action.walk_forward, 1),
            (self.action.walk_left, 1),
            (self.action.walk_backward, 2),
            (self.action.walk_right, 2),
            (self.action.walk_forward, 3),
            (self.action.walk_left, 3),
        ]

        # 执行搜索
        for action, repetitions in search_pattern:
            for _ in range(repetitions):
                # 每走一步都检查一次
                action(self.config.walkTimeFindJob)
                time.sleep(0.1)  # 等待移动结束
                if self.screen.is_job_marker_found():
                    logger.info("成功找到差事触发点。")
                    return

        # 如果遍历完所有搜索模式仍未找到
        logger.error("执行完所有搜索步骤后仍未找到差事触发点。")
        raise UIElementNotFound(UIElementNotFoundContext.JOB_TRIGGER_POINT)

    def navigate_from_bed_to_job_point(self):
        """
        执行从床边导航到任务点并确认找到的完整流程。

        :raises ``UIElementNotFound(UIElementNotFoundContext.JOB_TRIGGER_POINT)``: 未找到任务触发点
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        self.action.go_job_point_from_bed()
        time.sleep(0.5)  # 等待移动结束
        self._find_job_point()

    def enter_and_wait_for_job_panel(self):
        """
        进入差事并等待差事面板出现。

        :raises ``OperationTimeout(OperationTimeoutContext.JOB_SETUP_PANEL_OPEN)``: 等待差事面板打开超时
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        self.action.launch_job_setup_panel()
        logger.info("等待差事面板打开...")
        if not self.wait_for_state(self.screen.is_on_job_panel, timeout=60):
            # 这个过程需要从 RockStar 在线服务下载一些差事参数，如果相关服务故障，将无法打开面板
            logger.error("等待差事面板打开超时。")
            raise OperationTimeout(OperationTimeoutContext.JOB_SETUP_PANEL_OPEN)

    def _initialize_job_lobby(self):
        """执行设置差事面板和发送初始通知的动作。"""
        logger.info("动作: 正在设置差事面板...")
        self.action.setup_job_panel()
        logger.info("差事面板设置完成。")

        try:
            self.steam_bot.send_group_message(self.config.msgOpenJobPanel)
        except requests.RequestException:
            pass  # 忽略网络错误

    def _check_lobby_integrity(self, is_on_job_panel: bool, standby_count: int):
        """
        检查大厅状态是否有效，如果无效则抛出异常。

        :raises ``UIElementNotFound(UIElementNotFoundContext.JOB_SETUP_PANEL)``: 意外离开了任务面板
        :raises ``UnexpectedGameState(expected=GameState.JOB_PANEL_2, actual=GameState.BAD_JOB_PANEL_STANDBY_PLAYER)``: 发现"待命"状态的玩家
        """
        if not is_on_job_panel:
            raise UIElementNotFound(UIElementNotFoundContext.JOB_SETUP_PANEL)
        if standby_count > 0:
            raise UnexpectedGameState(GameState.JOB_PANEL_2, GameState.BAD_JOB_PANEL_STANDBY_PLAYER)

    def _handle_full_lobby_notifications(
        self, lobby_tracker: LobbyStateTracker, joining_count: int, joined_count: int
    ):
        """处理队伍已满的消息发送。"""
        if not lobby_tracker.team_full_notified and (joining_count + joined_count) >= 3:
            try:
                self.steam_bot.send_group_message(self.config.msgTeamFull)
                lobby_tracker.team_full_notified = True  # 标记为已通知，避免重复发送
            except requests.RequestException:
                pass  # 忽略网络错误

    def _check_for_timeouts(self, lobby_tracker: LobbyStateTracker):
        """
        检查并处理各种超时情况。

        :raises ``OperationTimeout(OperationTimeoutContext.WAIT_TEAMMATE)``: 长时间没有玩家加入，超时
        :raises ``OperationTimeout(OperationTimeoutContext.PLAYER_JOIN)``: 玩家长期卡在"正在加入"状态，超时
        """
        if lobby_tracker.has_wait_timeout(self.config.matchPanelTimeout):
            logger.warning("长时间没有玩家加入，放弃本次差事。")
            try:
                self.steam_bot.send_group_message(self.config.msgMatchPanelTimeout)
            except requests.RequestException:
                pass
            raise OperationTimeout(OperationTimeoutContext.WAIT_TEAMMATE)

        if lobby_tracker.has_joining_timeout(self.config.playerJoiningTimeout):
            logger.warning('玩家长期卡在"正在加入"状态，放弃本次差事。')
            try:
                self.steam_bot.send_group_message(self.config.msgPlayerJoiningTimeout)
            except requests.RequestException:
                pass
            raise OperationTimeout(OperationTimeoutContext.PLAYER_JOIN)

    def _try_to_start_job(self) -> bool:
        """
        尝试启动差事。启动失败时会尝试回到差事面板，无法回到面板会抛出异常。

        :return: True: 差事成功启动。False: 启动失败
        :raises ``UIElementNotFound(UIElementNotFoundContext.JOB_SETUP_PANEL)``: 启动差事时意外离开了任务面板
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        logger.info("动作: 正在启动差事...")
        try:
            self.steam_bot.send_group_message(self.config.msgJobStarting)
        except requests.RequestException:
            pass

        self.action.confirm()  # 按A键启动
        # 不能等太久，否则"启动中"状态可能被跳过
        time.sleep(0.5)  # 多等一会，让游戏响应差事启动

        # 检查 3 次，避免游戏响应太慢
        for _ in range(3):
            if self.screen.is_job_starting():
                logger.info("启动差事成功。")
                return True  # 成功启动
            time.sleep(0.1)  # 每次检查间等待 0.1 秒
        else:
            # 处理启动失败的情况
            logger.warning("启动差事失败，正在尝试恢复...")
            self.handle_warning_page()  # 处理可能出现的警告弹窗
            if not self.screen.is_on_job_panel():
                logger.error("启动失败且已离开差事面板，无法恢复。")
                raise UIElementNotFound(UIElementNotFoundContext.JOB_SETUP_PANEL)
            logger.info("仍在差事面板中，将继续等待。")
            return False  # 启动失败

    def setup_wait_start_job(self):
        """
        初始化差事准备页面，等待队友，然后开始差事。

        :raises ``UIElementNotFound(UIElementNotFoundContext.JOB_SETUP_PANEL)``: 意外离开了任务面板
        :raises ``OperationTimeout(OperationTimeoutContext.WAIT_TEAMMATE)``: 长时间没有玩家加入，超时
        :raises ``OperationTimeout(OperationTimeoutContext.PLAYER_JOIN)``: 玩家长期卡在"正在加入"状态，超时
        :raises ``UnexpectedGameState(expected=GameState.JOB_PANEL_2, actual=GameState.BAD_JOB_PANEL_STANDBY_PLAYER)``: 发现"待命"状态的玩家
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        logger.info("动作: 正在等待队伍成员并开始差事...")

        # 初始化任务大厅
        self._initialize_job_lobby()

        # 初始化大厅状态跟踪器
        lobby_tracker = LobbyStateTracker()

        while True:
            # 1. 获取最新状态
            is_on_panel, joining, joined, standby = self.screen.get_job_setup_status()
            if is_on_panel:
                logger.info(f"队伍状态: {joined}人已加入, {joining}人正在加入, {standby}人待命。")
            else:
                logger.error("不知为何离开了面板。")

            # 2. 检查致命错误
            self._check_lobby_integrity(is_on_panel, standby)

            # 3. 处理满员通知
            self._handle_full_lobby_notifications(lobby_tracker, joining, joined)

            # 4. 检查超时
            self._check_for_timeouts(lobby_tracker)

            # 5. 更新状态追踪器
            lobby_tracker.update(joining, joined)

            # 6. 检测是否该启动差事
            should_start_job = lobby_tracker.should_start_job(
                joining, joined, self.config.startOnAllJoined, self.config.startMatchDelay
            )

            # 7. 尝试启动差事，如果成功则退出循环
            if should_start_job:
                if self._try_to_start_job():
                    break

            # 8. 等待下一轮检查
            time.sleep(self.config.lobbyCheckLoopTime)

        logger.info(f"成功发车，本班车载有 {lobby_tracker.last_joined_player} 人。")

    def exit_job_panel(self):
        """
        从差事准备面板退出到自由模式，如果不在差事准备面板中则行为是未定义的。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        logger.info("动作: 正在退出差事面板...")
        # 处理警告屏幕
        self.handle_warning_page()

        # 从差事准备面板退出
        ocr_result = self.screen.ocr_game_window(0, 0, 1, 1)
        if self.screen.is_on_second_job_setup_page(ocr_result):
            self.action.exit_job_panel_from_second_page()
        elif self.screen.is_on_first_job_setup_page(ocr_result):
            self.action.exit_job_panel_from_first_page()

        logger.info("已退出差事面板。")

    def handle_post_job_start(self):
        """
        处理差事启动后的一系列操作：等待加载、卡单、等待落地、再次卡单。

        :raises ``OperationTimeout(OperationTimeoutContext.JOB_SETUP_PANEL_DISAPPEAR)``: 启动差事时，等待差事面板消失超时
        :raises ``OperationTimeout(OperationTimeoutContext.CHARACTER_LAND)``: 启动差事后，等待人物落地超时
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        # 等待面板消失
        logger.info("差事启动成功！等待面板消失...")
        if not self.wait_for_state(lambda: not self.screen.is_on_job_panel(), self.config.exitMatchTimeout):
            # 超时后直接抛出异常，应该是网络故障相关
            raise OperationTimeout(OperationTimeoutContext.JOB_SETUP_PANEL_DISAPPEAR)

        # 首次卡单
        logger.info(f"面板已消失。{self.config.delaySuspendTime} 秒后将卡单。")
        time.sleep(self.config.delaySuspendTime)
        self.glitch_single_player_session()

        # 等待人物落地
        logger.info("差事加载完成！等待人物落地...")
        if not self.wait_for_state(self.screen.is_job_started, self.config.exitMatchTimeout):
            logger.warning("等待人物落地超时，卡单并再等待30秒...")
            # 超时后再卡一次单并等 30 秒作为保底，这有时会有效
            self.glitch_single_player_session()
            if not self.wait_for_state(self.screen.is_job_started, 30):
                # 还是不行就只能抛出异常
                raise OperationTimeout(OperationTimeoutContext.CHARACTER_LAND)

        # 再次卡单
        logger.info(f"人物已落地。{10 + self.config.delaySuspendTime} 秒后将卡单。")
        time.sleep(10 + self.config.delaySuspendTime)
        self.glitch_single_player_session()

    def verify_mission_status_after_glitch(self):
        """
        在卡单后，检查并处理任务是成功进行还是失败退回计分板。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        logger.info("动作: 正在检查当前差事状态，等待10秒以响应其他玩家离开")
        time.sleep(10)  # 响应其他玩家离开

        if not self.screen.is_job_started():
            logger.warning("未检测到在差事中，可能因其他玩家导致任务失败。正在检查计分板...")
            if self.wait_for_state(self.screen.is_on_scoreboard, timeout=15):
                logger.info("检测到任务失败计分板。等待20秒以自动退出。")
                # 小技巧: 发送消息也需要时间
                wait_end_time = time.monotonic() + 20
                try:
                    self.steam_bot.send_group_message(self.config.msgDetectedSB)
                except requests.RequestException:
                    pass
                # 计算还需要等待的时间
                remaining_wait_time = wait_end_time - time.monotonic()
                if remaining_wait_time > 0:
                    time.sleep(remaining_wait_time)
            else:
                logger.warning("无法确定当前差事状态。")
        else:
            logger.info("当前在差事中，状态正常。")
