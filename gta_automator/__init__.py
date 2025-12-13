from enum import Enum, auto
import time
from typing import Any, Callable, Optional

from config import Config
from gamepad_utils import GamepadSimulator
from logger import get_logger

from .exception import *
from .game_process import GameProcess
from .game_screen import GameScreen, OcrFuncProtocol
from .game_action import GameAction
from .lifecycle_workflow import LifecycleWorkflow
from .online_workflow import OnlineWorkflow
from .job_workflow import JobWorkflow

logger = get_logger(__name__)


class BotMode(Enum):
    DRE = auto()  # 德瑞 Bot
    RECOVERY = auto()  # 恢复模式 (挂机降低恶意值)


class GTAAutomator:
    """
    用于自动化操作 GTA V 的类。
    """

    def __init__(
        self,
        config: Config,
        ocr_func: OcrFuncProtocol,
        send_steam_message_func: Callable[[str], Any],
        push_message_func: Callable[[str, str], Any],
        gamepad: Optional[GamepadSimulator] = None,
    ):
        # 初始化底层模块
        process = GameProcess()
        screen = GameScreen(ocr_func, process)
        player_input = GameAction(gamepad if gamepad else GamepadSimulator(), config)

        # 初始化工作流，注入依赖
        self.lifecycle_workflow = LifecycleWorkflow(screen, player_input, process, config)
        self.online_workflow = OnlineWorkflow(screen, player_input, process, config)
        self.job_workflow = JobWorkflow(screen, player_input, process, config, send_steam_message_func)

        # 初始化时，状态为德瑞 Bot
        self.bot_mode: BotMode = BotMode.DRE

        # 用于推送消息的方法
        self.push_message = push_message_func

        # 上一次恶意值检查结果为清白玩家的时间戳，None 表示尚未进行过恶意值检查
        self._last_clean_player_verified_timestamp: Optional[float] = None
        # 恶意值检查间隔 (秒)
        self.bad_sport_check_interval: float = 3600
        # 问题玩家是否自动挂机降恶意值
        self.recovery_on_dodgy_player = config.autoReduceBadSportOnDodgyPlayer
        # 降低恶意值时，挂机结束的目标时间戳，None 表示当前没有正在进行的挂机任务
        self._recovery_target_timestamp: Optional[float] = None
        # 降低恶意值时，总挂机目标: 20 小时
        self._recovery_total_duration = 20 * 3600
        # 降低恶意值时，单次挂机的时长: 10 分钟
        self._recovery_chunk_size = 10 * 60

    def is_in_recovery_mode(self):
        """
        判断当前是否处于恢复模式（挂机模式）。
        用于健康检查时抑制 Steam 消息超时报警。
        """
        return self.bot_mode == BotMode.RECOVERY

    def run_one_cycle(self):
        """
        统一的入口方法，根据当前模式执行一个“周期”的任务:
        - 如果是德瑞 Bot 模式，执行一轮差事。
        - 如果是恢复模式，执行一段短时间的挂机。

        :raises ``UnexpectedGameState(actual=GameState.OFF)``: 在自动化任务中，游戏意外关闭
        :raises ``UnexpectedGameState(expected=GameState.CLEAN_PLAYER_LEVEL, actual=GameState.BAD_SPORT_LEVEL)``: 恶意等级为恶意玩家
        :raises ``UnexpectedGameState(expected=GameState.CLEAN_PLAYER_LEVEL, actual=GameState.DODGY_PLAYER_LEVEL)``: 恶意等级为问题玩家
        :raises ``UnexpectedGameState({GameState.ONLINE_FREEMODE, GameState.IN_MISSION, GameState.ONLINE_PAUSED}, GameState.UNKNOWN)``: 切换新战局失败次数过多
        :raises ``UnexpectedGameState(GameState.ONLINE_PAUSED, GameState.UNKNOWN)``: 游戏卡死，无法切换战局
        :raises ``UnexpectedGameState(expected={GameState.ONLINE_FREEMODE, GameState.IN_MISSION}, actual=GameState.UNKNOWN)``: 挂机时离开了在线战局
        :raises ``UnexpectedGameState(expected=GameState.ONLINE_FREEMODE, actual=GameState.UNKNOWN)``: 启动游戏失败
        :raises ``UIElementNotFound(UIElement.PAUSE_MENU)``: 打开暂停菜单失败
        :raises ``UIElementNotFound(UIElement.BAD_SPORT_LEVEL_INDICATOR)``: 读取恶意等级失败
        :raises ``UIElementNotFound(UIElement.JOB_TRIGGER_POINT)``: 无法找到任务触发点
        :raises ``UIElementNotFound(UIElement.JOB_SETUP_PANEL)``: 在等待玩家和启动差事阶段，意外离开了任务面板
        :raises ``OperationTimeout(OperationTimeoutContext.RESPAWN_IN_AGENCY)``: 等待在事务所床上复活超时
        :raises ``OperationTimeout(OperationTimeoutContext.JOB_SETUP_PANEL_OPEN)``: 等待差事面板打开超时
        """
        # 确保游戏基础状态
        game_restarted = self.setup()

        if self.bot_mode == BotMode.DRE:
            self._run_dre_cycle(game_restarted)
        elif self.bot_mode == BotMode.RECOVERY:
            self._run_recovery_cycle()

    def setup(self):
        """
        初始化游戏状态，确保 GTA V 已启动并进入在线模式。

        :return bool: 是否重启了游戏
        :raises ``UnexpectedGameState(expected=GameState.ONLINE_FREEMODE, actual=GameState.UNKNOWN)``: 启动游戏失败
        """
        logger.info("动作: 正在初始化 GTA V ...")

        if self.lifecycle_workflow.is_game_ready():
            logger.info("初始化 GTA V 完成。")
            return False

        # 如果游戏未就绪，重启游戏
        logger.warning("游戏状态不正常，将重启游戏。")
        self.lifecycle_workflow.restart()

        logger.info("初始化 GTA V 完成。")
        return True

    def _run_dre_cycle(self, game_restarted: bool):
        """
        执行一轮完整的德瑞 Bot 循环逻辑:
        1. 启动游戏并确保进入在线模式。
        2. 检查恶意值(按需)
        3. 切换战局
        3. 执行一轮德瑞差事。

        :raises ``UnexpectedGameState(expected=GameState.CLEAN_PLAYER_LEVEL, actual=GameState.BAD_SPORT_LEVEL)``: 恶意等级为恶意玩家
        :raises ``UnexpectedGameState(expected=GameState.CLEAN_PLAYER_LEVEL, actual=GameState.DODGY_PLAYER_LEVEL)``: 恶意等级为问题玩家
        :raises ``UnexpectedGameState({GameState.ONLINE_FREEMODE, GameState.IN_MISSION, GameState.ONLINE_PAUSED}, GameState.UNKNOWN)``: 切换新战局失败次数过多
        :raises ``UnexpectedGameState(GameState.ONLINE_PAUSED, GameState.UNKNOWN)``: 游戏卡死，无法切换战局
        :raises ``UnexpectedGameState(actual=GameState.OFF)``: 在自动化任务中，游戏意外关闭
        :raises ``OperationTimeout(OperationTimeoutContext.RESPAWN_IN_AGENCY)``: 等待在事务所床上复活超时
        :raises ``OperationTimeout(OperationTimeoutContext.JOB_SETUP_PANEL_OPEN)``: 等待差事面板打开超时
        :raises ``UIElementNotFound(UIElement.JOB_SETUP_PANEL)``: 在等待玩家和启动差事阶段，意外离开了任务面板
        :raises ``UIElementNotFound(UIElement.PAUSE_MENU)``: 打开暂停菜单失败
        :raises ``UIElementNotFound(UIElement.BAD_SPORT_LEVEL_INDICATOR)``: 读取恶意等级失败
        :raises ``UIElementNotFound(UIElement.JOB_TRIGGER_POINT)``: 无法找到任务触发点
        """
        logger.info("动作: 正在开始新一轮德瑞 Bot 任务...")
        # 按需检查恶意值
        if self._should_check_bad_sport(game_restarted):
            try:
                self._perform_bad_sport_check()
            except UnexpectedGameState as e:
                # 捕获恶意玩家异常，并切换到恢复模式
                if e.actual_state == GameState.DODGY_PLAYER_LEVEL:
                    if self.recovery_on_dodgy_player:
                        # 如果启用自动挂机降恶意值，切换到恢复模式
                        logger.warning(f"检测到问题玩家状态，切换至恢复模式。")
                        self.push_message("恶意值过高(问题玩家)", "Bot 将开始挂机以降低恶意值。")
                        self.bot_mode = BotMode.RECOVERY
                        self._recovery_target_timestamp = None  # 重置计时
                        return  # 结束本轮循环，下次调用将进入 RECOVERY 分支
                    else:
                        # 如果未启用自动挂机降恶意值，退出
                        self.lifecycle_workflow.shutdown()
                        raise
                elif e.actual_state == GameState.BAD_SPORT_LEVEL:
                    # 恶意玩家只能退出
                    self.lifecycle_workflow.shutdown()
                    raise

        # 切换到新战局
        try:
            self.online_workflow.start_new_match()
        except UnexpectedGameState as e:
            if (
                e.expected == {GameState.ONLINE_FREEMODE, GameState.IN_MISSION}
                and e.actual_state == GameState.UNKNOWN
            ):
                # 开始新战局时，用尽全部恢复策略后仍无法切换战局
                logger.error("初始化游戏时，切换战局失败次数过多，退出游戏。")
                self.lifecycle_workflow.shutdown()
            raise

        # 等待复活
        try:
            self.job_workflow.wait_for_respawn()
        except OperationTimeout as e:
            if e.context == OperationTimeoutContext.RESPAWN_IN_AGENCY:
                # 等待复活超时，为避免无法进入线上模式等严重错误，退出游戏
                logger.error("初始化游戏时，等待在事务所复活超时，退出游戏。")
                self.lifecycle_workflow.shutdown()
            raise

        # 执行德瑞 Bot 差事
        self.play_dre_job()

        logger.info("本轮德瑞 Bot 任务成功完成。")

    def _run_recovery_cycle(self):
        """
        执行一轮恢复逻辑，支持断点续传。
        1. 初始化挂机时间
        2. 检查恶意值，恶意玩家抛出异常
        3. 挂机

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        :raises ``UnexpectedGameState(GameState.CLEAN_PLAYER_LEVEL, GameState.BAD_SPORT_LEVEL)``: 恶意等级为恶意玩家
        :raises ``UnexpectedGameState(expected={GameState.ONLINE_FREEMODE, GameState.IN_MISSION}, actual=GameState.UNKNOWN)``: 离开了在线战局
        :raises ``UIElementNotFound(UIElement.BAD_SPORT_LEVEL_INDICATOR)``: 读取恶意等级失败
        """
        logger.info("动作: 正在挂机以降低恶意值...")

        # 初始化或恢复计时器
        if self._recovery_target_timestamp is None:
            self._recovery_target_timestamp = time.monotonic() + self._recovery_total_duration
            logger.info(f"开启新的恶意值恢复任务，目标时长: {self._recovery_total_duration/3600:.1f} 小时")

        remaining = self._recovery_target_timestamp - time.monotonic()

        # 检查是否完成
        if remaining <= 0:
            logger.info("恶意值恢复时间已达标，切换回德瑞 Bot 模式。")
            self.push_message("降低恶意值完成", "Bot 将恢复执行德瑞差事。")
            self.bot_mode = BotMode.DRE
            self._recovery_target_timestamp = None
            return

        # 检查是否为恶意玩家，恶意玩家无法降低恶意值
        logger.info("正在检查恶意值...")
        try:
            bad_sport_level = self.online_workflow.get_bad_sport_level()
        except UIElementNotFound as e:
            if e.element_not_found == UIElement.BAD_SPORT_LEVEL_INDICATOR:
                logger.error("检查恶意值失败，退出游戏。")
                self.lifecycle_workflow.shutdown()
            raise
        if bad_sport_level == "恶意玩家":
            logger.error("当前恶意等级为恶意玩家，无法降低恶意值，退出游戏。")
            # 清空挂机目标计时器
            self._afk_target_timestamp = None
            self.lifecycle_workflow.shutdown()
            raise UnexpectedGameState(GameState.CLEAN_PLAYER_LEVEL, GameState.BAD_SPORT_LEVEL)

        # 其他恶意等级无条件执行挂机
        logger.info(f"当前恶意等级为 {bad_sport_level}，开始挂机以降低恶意值。")

        # 执行挂机
        # 每次只挂机 _recovery_chunk_size (例如10分钟) 或者 剩余时间
        current_chunk = min(self._recovery_chunk_size, remaining)

        logger.info(f"执行恢复模式挂机: {current_chunk/60:.1f} 分钟 (总剩余: {remaining/3600:.2f} 小时)")

        try:
            self.online_workflow.afk(current_chunk)
        except UnexpectedGameState as e:
            # 挂机期间离开了在线模式
            # 下一次执行时会自动断点续传
            logger.warning("挂机过程中游戏状态异常。")
            raise e

    def play_dre_job(self):
        """
        执行德瑞差事的任务流程:
        1. 移动到任务触发点，进入别惹德瑞
        2. 发送消息，等待玩家加入
        3. 启动差事，卡单
        4. 落地后，卡单
        5. 检查是否在任务中

        :raises ``UnexpectedGameState(actual=GameState.OFF)``: 在自动化任务中，游戏意外关闭
        :raises ``UnexpectedGameState(GameState.ONLINE_PAUSED, GameState.UNKNOWN)``: 游戏卡死，无法切换战局
        :raises ``UnexpectedGameState({GameState.ONLINE_FREEMODE, GameState.IN_MISSION, GameState.ONLINE_PAUSED}, GameState.UNKNOWN)``: 切换新战局失败次数过多
        :raises ``UIElementNotFound(UIElement.JOB_SETUP_PANEL)``: 在等待玩家和启动差事阶段，意外离开了任务面板
        :raises ``UIElementNotFound(UIElement.JOB_TRIGGER_POINT)``: 无法找到任务触发点
        :raises ``OperationTimeout(OperationTimeoutContext.JOB_SETUP_PANEL_OPEN)``: 等待差事面板打开超时
        :raises ``OperationTimeout(OperationTimeoutContext.RESPAWN_IN_AGENCY)``: 等待在事务所床上复活超时
        """
        # 移动到任务触发点
        self.job_workflow.navigate_from_bed_to_job_point()

        # 进入差事准备面板
        try:
            self.job_workflow.enter_and_wait_for_job_panel()
        except OperationTimeout as e:
            # 等待差事面板打开超时
            logger.warning("等待差事面板打开超时，尝试回到自由模式。")
            self.job_workflow.exit_job_panel()
            time.sleep(2)
            if self.lifecycle_workflow.check_if_in_onlinemode():
                return
            else:
                logger.error("无法回到自由模式，退出游戏。")
                self.lifecycle_workflow.shutdown()
                raise

        # 管理大厅并启动差事
        try:
            self.job_workflow.setup_wait_start_job()
        except OperationTimeout as e:
            # 等待玩家加入超时，退出差事
            logger.warning(f"{e.message}。退出差事。")
            self.job_workflow.exit_job_panel()
            return
        except UnexpectedGameState as e:
            # 有待命状态玩家，退出差事
            if e.actual_state == GameState.BAD_JOB_PANEL_STANDBY_PLAYER:
                logger.warning(f"发现待命状态玩家。退出差事。")
                self.job_workflow.exit_job_panel()
                return
            else:
                raise  # 其他异常向上抛出
        except UIElementNotFound as e:
            # 意外离开差事面板，退出差事
            if e.element_not_found == UIElement.JOB_SETUP_PANEL:
                logger.warning(f"不知为何离开了面板。退出差事。")
                self.job_workflow.exit_job_panel()
                return
            else:
                raise  # 其他异常向上抛出

        # 处理差事启动后阶段
        try:
            self.job_workflow.handle_post_job_start()
        except OperationTimeout as e:
            if (
                e.context == OperationTimeoutContext.JOB_SETUP_PANEL_DISAPPEAR
                or OperationTimeoutContext.CHARACTER_LAND
            ):
                timeout_context = e.context.value
                # 在差事中检查状态超时，尝试更换战局
                # 在差事中退出游戏可能导致恶意值增加，所以这里选择切换战局
                logger.warning(f"{e.message}。卡单并切换战局。")
                # 首先需要卡单，进入单人战局状态，因为在多人差事中切换战局会增加恶意值
                self.online_workflow.glitch_single_player_session()
                time.sleep(2)  # 等待游戏状态稳定

                # 切换战局
                try:
                    self.online_workflow.start_new_match()
                    self.job_workflow.wait_for_respawn()
                    return  # 切换战局成功，结束当前差事流程

                except UnexpectedGameState as e:
                    if (
                        e.expected == {GameState.ONLINE_FREEMODE, GameState.IN_MISSION}
                        and e.actual_state == GameState.UNKNOWN
                    ):
                        # 这种情况下要么不在任务中，要么游戏卡死了，只能退出游戏
                        logger.error(f"处理{timeout_context}超时时，切换战局失败次数过多，退出游戏。")
                        self.lifecycle_workflow.shutdown()
                    raise
                except OperationTimeout as e:
                    if e.context == OperationTimeoutContext.RESPAWN_IN_AGENCY:
                        # 等待复活超时，退出游戏
                        logger.error(f"处理{timeout_context}超时时，切换战局等待复活超时，退出游戏。")
                        self.lifecycle_workflow.shutdown()
                    raise
            else:
                raise  # 其他超时是致命的，向上抛出

        # 检查最终状态
        self.job_workflow.verify_mission_status_after_glitch()

    def _should_check_bad_sport(self, game_restarted: bool):
        """
        判断是否需要检查恶意值:
        - 游戏刚刚重启
        - 第一次运行
        - 距离上次检查超过 1 小时

        :param game_restarted: 本次流程启动时是否重启了游戏
        :return bool: 需要进行恶意值检查
        """
        if game_restarted:
            logger.info("触发恶意值检查: 游戏已重启。")
            return True
        elif self._last_clean_player_verified_timestamp is None:
            logger.info("触发恶意值检查: 尚未检查过。")
            return True
        elif (time.monotonic() - self._last_clean_player_verified_timestamp) > self.bad_sport_check_interval:
            logger.info(f"触发恶意值检查: 距离上次检查已超过 {self.bad_sport_check_interval/60:.0f} 分钟。")
            return True

        return False

    def _perform_bad_sport_check(self):
        """
        执行恶意值检查。如果不是清白玩家，会抛出异常。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        :raises ``UnexpectedGameState(expected=GameState.CLEAN_PLAYER_LEVEL, actual=GameState.BAD_SPORT_LEVEL)``: 恶意等级为恶意玩家
        :raises ``UnexpectedGameState(expected=GameState.CLEAN_PLAYER_LEVEL, actual=GameState.DODGY_PLAYER_LEVEL)``: 恶意等级为问题玩家
        :raises ``UIElementNotFound(UIElement.BAD_SPORT_LEVEL_INDICATOR)``: 读取恶意等级失败
        :raises ``UIElementNotFound(UIElement.PAUSE_MENU)``: 打开暂停菜单失败
        """
        logger.info("正在检查恶意值...")
        try:
            bad_sport_level = self.online_workflow.get_bad_sport_level()
        except UIElementNotFound as e:
            if e.element_not_found == UIElement.BAD_SPORT_LEVEL_INDICATOR:
                logger.error("检查恶意值失败，退出游戏。")
                self.lifecycle_workflow.shutdown()
            raise

        if bad_sport_level != "清白玩家":
            logger.warning(f"当前恶意等级为 {bad_sport_level} ，恶意值过高。")
            if bad_sport_level == "问题玩家":
                raise UnexpectedGameState(GameState.CLEAN_PLAYER_LEVEL, GameState.DODGY_PLAYER_LEVEL)
            else:
                # 恶意玩家
                raise UnexpectedGameState(GameState.CLEAN_PLAYER_LEVEL, GameState.BAD_SPORT_LEVEL)

        logger.info(f"当前恶意等级为 {bad_sport_level} ，恶意值正常。")

        # 检查通过，更新时间戳
        self._last_clean_player_verified_timestamp = time.monotonic()
