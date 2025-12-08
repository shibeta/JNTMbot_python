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


class GTAAutomator:
    """
    用于自动化操作 GTA V 的类。
    """

    def __init__(
        self,
        config: Config,
        ocr_func: OcrFuncProtocol,
        send_steam_message_func: Callable[[str], Any],
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

        # 上一次恶意值检查结果为清白玩家的时间戳，None 表示尚未进行过恶意值检查
        self._last_clean_player_verified_timestamp: Optional[float] = None
        # 恶意值检查间隔 (秒)
        self.bad_sport_check_interval: float = 3600
        # 降低恶意值时，挂机结束的目标时间戳，None 表示当前没有正在进行的挂机任务
        self._afk_target_timestamp: Optional[float] = None

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
        logger.warning("游戏状态错误，将重启游戏。")
        self.lifecycle_workflow.restart()

        logger.info("初始化 GTA V 完成。")
        return True

    def play_dre_job(self):
        """
        执行德瑞差事的任务流程:
        1. 移动到任务触发点，进入别惹德瑞
        2. 发送消息，等待玩家加入
        3. 启动差事，卡单
        4. 落地后，卡单
        5. 检查是否在任务中

        :raises ``UnexpectedGameState(actual=GameState.OFF)``: 在自动化任务中，游戏意外关闭
        :raises ``OperationTimeout(OperationTimeoutContext.RESPAWN_IN_AGENCY)``: 等待在事务所床上复活超时
        :raises ``UIElementNotFound(UIElement.JOB_TRIGGER_POINT)``: 无法找到任务触发点
        :raises ``OperationTimeout(OperationTimeoutContext.JOB_SETUP_PANEL_OPEN)``: 等待差事面板打开超时
        :raises ``UIElementNotFound(UIElement.JOB_SETUP_PANEL)``: 在等待玩家和启动差事阶段，意外离开了任务面板
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

    def run_dre_bot(self):
        """
        执行一轮完整的德瑞 Bot 任务:
        1. 启动游戏并确保进入在线模式。
        2. 检查恶意值(按需)
        3. 执行一轮德瑞差事。

        :raises ``UnexpectedGameState(expected=GameState.CLEAN_PLAYER_LEVEL, actual=GameState.BAD_SPORT_LEVEL)``: 恶意等级为恶意玩家
        :raises ``UnexpectedGameState(expected=GameState.CLEAN_PLAYER_LEVEL, actual=GameState.DODGY_PLAYER_LEVEL)``: 恶意等级为问题玩家
        :raises ``UIElementNotFound(UIElement.BAD_SPORT_LEVEL_INDICATOR)``: 读取恶意等级失败
        :raises ``UnexpectedGameState(expected={GameState.IN_ONLINE_LOBBY, GameState.IN_MISSION}, actual=GameState.UNKNOWN)``: 切换战局时失败
        :raises ``UnexpectedGameState(actual=GameState.OFF)``: 在自动化任务中，游戏意外关闭
        :raises ``OperationTimeout(OperationTimeoutContext.RESPAWN_IN_AGENCY)``: 等待在事务所床上复活超时
        :raises ``UIElementNotFound(UIElement.JOB_TRIGGER_POINT)``: 无法找到任务触发点
        :raises ``OperationTimeout(OperationTimeoutContext.JOB_SETUP_PANEL_OPEN)``: 等待差事面板打开超时
        :raises ``UIElementNotFound(UIElement.JOB_SETUP_PANEL)``: 在等待玩家和启动差事阶段，意外离开了任务面板
        """
        logger.info("动作: 正在开始新一轮德瑞 Bot 任务...")
        # 确保游戏就绪，即在在线模式中
        game_restarted = self.setup()

        # 按需检查恶意值
        if self._should_check_bad_sport(game_restarted):
            self._perform_bad_sport_check()

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

        # 执行德瑞bot任务
        self.play_dre_job()

        logger.info("本轮德瑞 Bot 任务成功完成。")

    def reduce_bad_sport_level(self):
        """
        挂机 20 小时来降低恶意值。支持断点续传。

        如果在挂机过程中抛出异常，再次调用此方法会自动计算剩余时间继续挂机。

        任务成功完成后，会自动重置内部计时器。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏未启动，无法执行 OCR
        :raises ``UIElementNotFound(UIElement.BAD_SPORT_LEVEL_INDICATOR)``: 读取恶意等级失败
        :raises ``UnexpectedGameState(expected={GameState.ONLINE_FREEMODE, actual=GameState.IN_MISSION}, GameState.UNKNOWN)``: 离开了在线战局
        """
        TOTAL_AFK_DURATION = 20 * 3600  # 总挂机目标: 20 小时
        AFK_CHUNK_SIZE = 10 * 60  # 单次 AFK 指令的时长: 10 分钟

        logger.info("动作: 正在挂机以降低恶意值...")
        # 确保游戏在在线模式
        self.setup()

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

        # 设定或恢复目标时间
        if self._afk_target_timestamp is None:
            # 新的任务
            self._afk_target_timestamp = time.monotonic() + TOTAL_AFK_DURATION
            logger.info(f"开始新的挂机任务，目标时长: {TOTAL_AFK_DURATION / 3600:.2f} 小时。")
        else:
            # 断点续传
            remaining = self._afk_target_timestamp - time.monotonic()
            if remaining > 0:
                logger.info(f"检测到未完成的挂机任务，继续执行。剩余时间: {remaining / 3600:.2f} 小时。")
            else:
                logger.info("检测到挂机任务时间已在中断期间耗尽。")

        # 循环挂机
        while True:
            # 基于时间戳计时挂机
            remaining_time = self._afk_target_timestamp - time.monotonic()
            # 时间到则退出循环
            if remaining_time <= 0:
                logger.info("挂机时间已达标。")
                break

            # 计算本次挂机时长：取 默认块时长 与 剩余总时长 的较小值
            # 确保最后一次挂机不会超出总时长
            current_chunk = min(AFK_CHUNK_SIZE, remaining_time)

            try:
                # 记录进度
                logger.info(
                    f"剩余需挂机: {remaining_time / 3600:.2f} 小时。执行 AFK 动作 {int(current_chunk)} 秒..."
                )
                # 挂机
                self.online_workflow.afk(current_chunk)

            except UnexpectedGameState as e:
                if e.actual_state == GameState.UNKNOWN:
                    logger.warning("挂机时意外离开了战局，退出游戏。")
                    self.lifecycle_workflow.shutdown()
                raise

        # 挂机完成，重置计时器
        self._afk_target_timestamp = None
        logger.info("已完成降低恶意值工作流程。")
