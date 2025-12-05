import time
from typing import Callable, Optional

from logger import get_logger
from config import Config
from steambot_utils import SteamBot
from steamgui_automation import SteamAutomation

from ._base_workflow import _BaseWorkflow
from .game_process import GameProcess
from .game_screen import GameScreen
from .exception import *
from .game_action import GameAction

logger = get_logger(__name__.split(".")[-1])


class LobbyStateTracker:
    """封装了跟踪差事面板状态的所有逻辑。"""

    def __init__(
        self,
        gamescreen: GameScreen,
        handle_warning_page_func: Callable,
        start_immediately_when_full: bool,
        normal_start_delay: float,
        wait_timeout: float,
        joining_timeout: float,
    ):
        """
        初始化面板状态跟踪器

        :param gta_automator.game_screen.GameScreen gamescreen: GameScreen对象
        :param bool start_immediately_when_full: 满员时是否立刻开始游戏
        :param float normal_start_delay: 开始差事等待延迟
        :param float wait_timeout: 面板无人加入时重开时间
        :param float joining_timeout: 等待正在加入玩家超时重开时间
        """
        self.screen = gamescreen
        self.handle_warning_page_func = handle_warning_page_func
        self.start_immediately_when_full = start_immediately_when_full
        self.normal_start_delay = normal_start_delay
        self.wait_timeout = wait_timeout
        self.joining_timeout = joining_timeout
        self.init()

    def init(self):
        # 开始等待的时间
        self.start_wait_time = time.monotonic()
        # 是否在差事面板中
        self.in_lobby = False
        # 上一次队伍状态发生变动的时间
        self.team_status_last_changed_time = self.start_wait_time
        # 上一次变为没有正在加入的玩家的时间
        self.last_zero_joining_player_time = self.start_wait_time
        # 最新一次检查时正在加入的玩家数
        self.joining_count = 0
        # 最新一次检查时已加入的玩家数
        self.joined_count = 0
        # 最新一次检查时待命状态的玩家数
        self.standby_count = 0

    def update(self, ocr_text: Optional[str] = None):
        """
        从屏幕上获取最新的大厅状态。这个方法会自动处理警告页面。

        :param str ocr_text: 可选的 OCR 结果字符串，传入时将跳过 OCR，直接使用该字符串作为识别结果
        """
        current_time = time.monotonic()

        is_on_panel, joining, joined, standby = self.screen.get_job_setup_status(ocr_text)

        # 处理警告页面
        if not is_on_panel:
            self.handle_warning_page_func()
            is_on_panel, joining, joined, standby = self.screen.get_job_setup_status(ocr_text)

        # 如果能识别到任务面板则说明在大厅中，反之亦然
        self.in_lobby = is_on_panel

        # 如果人数结构发生变化，更新队伍状态变化计时器和大厅人数计数器
        if joining != self.joining_count or joined != self.joined_count or standby != self.standby_count:
            self.team_status_last_changed_time = current_time
            self.joining_count = joining
            self.joined_count = joined
            self.standby_count = standby
            # 如果队伍状态变化且没有正在加入的玩家，更新无加入状态玩家计时器
            if joining == 0:
                self.last_zero_joining_player_time = current_time

    @property
    def is_lobby_full(self):
        """检查队伍是否已满"""
        return self.joined_count + self.joining_count + self.standby_count >= 3

    @property
    def has_standby_player(self):
        """检查是否有待命状态的玩家。"""
        return self.standby_count > 0

    @property
    def has_wait_timeout(self):
        """检查是否长时间没有任何玩家加入。"""
        is_empty = self.joined_count == 0 and self.joining_count == 0
        time_elapsed = time.monotonic() - self.start_wait_time
        return is_empty and time_elapsed > self.wait_timeout

    @property
    def has_joining_timeout(self):
        """检查是否有人长时间卡在“正在加入”状态。"""
        is_stuck = self.joining_count > 0  # 有人正在加入
        time_elapsed = time.monotonic() - self.last_zero_joining_player_time
        return is_stuck and time_elapsed > self.joining_timeout

    @property
    def should_start_job(self):
        """根据当前状态和配置，判断是否应该开始差事。"""
        # 有待命状态玩家
        if self.standby_count != 0:
            return False

        # 队伍已满，且配置了满队立刻启动
        team_is_full = self.joined_count >= 3
        if team_is_full and self.start_immediately_when_full:
            return True

        # 有人已加入，且无人正在加入，且距离上一次队伍状态变化时间已经超过了启动延时
        can_start_with_delay = self.joined_count > 0 and self.joining_count == 0
        delay_passed = (time.monotonic() - self.team_status_last_changed_time) > self.normal_start_delay
        if can_start_with_delay and delay_passed:
            return True

        return False


class JobWorkflow(_BaseWorkflow):
    """差事相关的操作"""

    def __init__(
        self,
        screen: GameScreen,
        input: GameAction,
        process: GameProcess,
        config: Config,
        steam_bot: SteamBot | SteamAutomation,
    ):
        super(JobWorkflow, self).__init__(screen, input, process, config)
        self.steam_bot = steam_bot
        self.lobby_tracker = LobbyStateTracker(
            screen,
            self.handle_warning_page,
            config.startOnAllJoined,
            config.startMatchDelay,
            self.config.matchPanelTimeout,
            self.config.playerJoiningTimeout,
        )

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

        :raises ``UIElementNotFound(UIElement.JOB_TRIGGER_POINT)``: 未找到任务触发点
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
                action(self.config.moveTimeFindJob)
                time.sleep(0.3)  # 等待移动结束
                if self.screen.is_job_marker_found():
                    logger.info("成功找到差事触发点。")
                    return

        # 如果遍历完所有搜索模式仍未找到
        logger.error("执行完所有搜索步骤后仍未找到差事触发点。")
        raise UIElementNotFound(UIElement.JOB_TRIGGER_POINT)

    def navigate_from_bed_to_job_point(self):
        """
        执行从床边导航到任务点并确认找到的完整流程。

        :raises ``UIElementNotFound(UIElement.JOB_TRIGGER_POINT)``: 未找到任务触发点
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        # 目前的摇杆操作实现的下楼有可能会卡在墙上，考虑引入CV小模型识别地图，计算所需的摇杆指令
        if self.config.manualMoveToPoint:
            self.action.go_job_point_from_bed_by_bot_owner()
        else:
            self.action.go_job_point_from_bed()
        time.sleep(0.5)  # 等待移动结束
        self._find_job_point()

    def enter_and_wait_for_job_panel(self):
        """
        进入差事并等待差事面板出现。

        :raises ``OperationTimeout(OperationTimeoutContext.JOB_SETUP_PANEL_OPEN)``: 等待差事面板打开超时
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        for _ in range(3):
            # 多点两下，有时候第一次按没反应
            # 这游戏bug真多
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
        except Exception:
            pass  # 忽略发送消息失败

    def _try_to_start_job(self) -> bool:
        """
        尝试启动差事。启动失败时会尝试回到差事面板，无法回到面板会抛出异常。

        :return: True: 差事成功启动。False: 启动失败
        :raises ``UIElementNotFound(UIElement.JOB_SETUP_PANEL)``: 启动差事时意外离开了任务面板
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        logger.info("动作: 正在启动差事...")
        try:
            self.steam_bot.send_group_message(self.config.msgJobStarting)
        except Exception:
            pass  # 忽略发送消息失败

        time.sleep(1)  # 等待 1 秒以给其他玩家反应时间
        self.action.confirm()  # 按 A 键启动
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
                raise UIElementNotFound(UIElement.JOB_SETUP_PANEL)
            logger.info("仍在差事面板中，将继续等待。")
            return False  # 启动失败

    def setup_wait_start_job(self):
        """
        初始化差事准备页面，等待队友，然后开始差事。

        :raises ``UIElementNotFound(UIElement.JOB_SETUP_PANEL)``: 意外离开了任务面板
        :raises ``OperationTimeout(OperationTimeoutContext.WAIT_TEAMMATE)``: 长时间没有玩家加入，超时
        :raises ``OperationTimeout(OperationTimeoutContext.PLAYER_JOIN)``: 玩家长期卡在"正在加入"状态，超时
        :raises ``UnexpectedGameState(expected=GameState.JOB_PANEL_2, actual=GameState.BAD_JOB_PANEL_STANDBY_PLAYER)``: 发现"待命"状态的玩家
        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        logger.info("动作: 正在等待队伍成员并开始差事...")

        # 初始化任务大厅
        self._initialize_job_lobby()

        # 初始化时设置为未发送过满员消息
        lobby_full_notified = False

        # 初始化大厅状态跟踪器
        self.lobby_tracker.init()

        while True:
            # 获取最新的大厅状态
            self.lobby_tracker.update()

            # 检查是否在大厅
            if not self.lobby_tracker.in_lobby:
                raise UIElementNotFound(UIElement.JOB_SETUP_PANEL)

            logger.info(
                f"队伍状态: {self.lobby_tracker.joined_count}人已加入, {self.lobby_tracker.joining_count}人正在加入, {self.lobby_tracker.standby_count}人待命。"
            )

            # 有待命玩家时，抛出异常
            if self.lobby_tracker.has_standby_player:
                raise UnexpectedGameState(GameState.JOB_PANEL_2, GameState.BAD_JOB_PANEL_STANDBY_PLAYER)

            # 满员时发送消息，整个等待过程只发送一次
            if not lobby_full_notified and self.lobby_tracker.is_lobby_full:
                try:
                    self.steam_bot.send_group_message(self.config.msgTeamFull)
                except Exception:
                    pass  # 忽略发送消息失败
                finally:
                    lobby_full_notified = True

            # 检查是否该启动差事
            if self.lobby_tracker.should_start_job:
                if self._try_to_start_job():
                    # 启动成功则退出循环
                    break
                else:
                    # 启动失败继续等，不进行无人加入和正在加入超时检查
                    time.sleep(self.config.lobbyCheckLoopTime)
                    continue

            # 长时间无人加入，发送消息，抛出异常
            if self.lobby_tracker.has_wait_timeout:
                logger.warning("长时间没有玩家加入，放弃本次差事。")
                try:
                    self.steam_bot.send_group_message(self.config.msgMatchPanelTimeout)
                except Exception:
                    pass  # 忽略发送消息失败
                raise OperationTimeout(OperationTimeoutContext.TEAMMATE)

            # 玩家长期卡在正在加入，发送消息，抛出异常
            if self.lobby_tracker.has_joining_timeout:
                logger.warning('玩家长期卡在"正在加入"状态，放弃本次差事。')
                try:
                    self.steam_bot.send_group_message(self.config.msgPlayerJoiningTimeout)
                except Exception:
                    pass  # 忽略发送消息失败
                raise OperationTimeout(OperationTimeoutContext.PLAYER_JOIN)

            # 每次检查大厅状态间间隔一定时间，通过配置文件指定
            time.sleep(self.config.lobbyCheckLoopTime)

        logger.info(f"成功发车，本班车载有 {self.lobby_tracker.joined_count} 人。")

    def exit_job_panel(self):
        """
        从差事准备面板退出到自由模式，如果不在差事准备面板中则不做任何事。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        """
        logger.info("动作: 正在退出差事面板...")
        # 处理警告屏幕
        self.handle_warning_page()

        # 从差事准备面板退出
        ocr_result = self.screen.ocr_game_window(0, 0, 1, 1)
        if self.screen.is_on_second_job_setup_page(ocr_result):
            logger.debug("检测到在差事面板第二页，正在退出...")
            self.action.exit_job_panel_from_second_page()
        elif self.screen.is_on_first_job_setup_page(ocr_result):
            logger.debug("检测到在差事面板第一页，正在退出...")
            self.action.exit_job_panel_from_first_page()
        else:
            logger.debug("未检测到差事面板的任何一页，不做任何事。")

        logger.info("已退出差事面板。")

    def handle_post_job_start(self):
        """
        处理差事启动后的一系列操作：等待加载，卡单，等待落地，卡单。

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
        logger.info("动作: 正在检查当前差事状态，等待 10 秒以响应其他玩家离开。")
        time.sleep(10)  # 响应其他玩家离开

        if not self.screen.is_job_started():
            logger.warning("未检测到在差事中，可能因其他玩家导致任务失败。正在检查计分板...")
            if self.wait_for_state(self.screen.is_on_scoreboard, timeout=15):
                logger.info("检测到任务失败计分板。等待20秒以自动退出。")
                # 略去发送消息的时间
                wait_end_time = time.monotonic() + 20
                try:
                    self.steam_bot.send_group_message(self.config.msgDetectedSB)
                except Exception:
                    pass  # 忽略发送消息失败
                # 计算还需要等待的时间
                remaining_wait_time = wait_end_time - time.monotonic()
                if remaining_wait_time > 0:
                    time.sleep(remaining_wait_time)
            else:
                logger.warning("无法确定当前差事状态。")
        else:
            logger.info("当前在差事中，状态正常。")
