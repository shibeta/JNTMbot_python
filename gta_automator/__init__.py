import time
from typing import Optional

from config import Config
from gamepad_utils import GamepadSimulator
from logger import get_logger
from ocr_utils import OCREngine
from steambot_utils import SteamBot
from steamgui_automation import SteamAutomation

from .exception import *
from .game_process import GameProcess
from .game_screen import GameScreen
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
        ocr_engine: OCREngine,
        steam_bot: SteamBot | SteamAutomation,
        gamepad: Optional[GamepadSimulator] = None,
    ):
        # 初始化底层模块
        process = GameProcess()
        screen = GameScreen(ocr_engine, process)
        player_input = GameAction(gamepad if gamepad else GamepadSimulator(), config)

        # 初始化工作流，注入依赖
        self.lifecycle_workflow = LifecycleWorkflow(screen, player_input, process, config)
        self.online_workflow = OnlineWorkflow(screen, player_input, process, config)
        self.job_workflow = JobWorkflow(screen, player_input, process, config, steam_bot)

    def setup(self):
        """
        初始化游戏状态，确保 GTA V 已启动并进入在线模式。

        如果游戏未启动或不在在线模式中，会重启游戏并检查恶意值。

        :raises ``UnexpectedGameState(expected=GameState.ON, actual=GameState.OFF)``: 游戏意外关闭
        :raises ``UnexpectedGameState(expected=GameState.ONLINE_FREEMODE, actual=GameState.UNKNOWN)``: 启动游戏失败
        :raises ``UnexpectedGameState(expected=GameState.CLEAN_PLAYER_LEVEL, actual=GameState.BAD_SPORT_LEVEL)``: 恶意等级为恶意玩家
        :raises ``UnexpectedGameState(expected=GameState.CLEAN_PLAYER_LEVEL, actual=GameState.DODGY_PLAYER_LEVEL)``: 恶意等级为问题玩家
        :raises ``UIElementNotFound(UIElement.BAD_SPORT_LEVEL_INDICATOR)``: 读取恶意等级失败
        """
        logger.info("动作: 正在初始化 GTA V ...")

        if self.lifecycle_workflow.is_game_ready():
            logger.info("初始化 GTA V 完成。")
            return

        # 如果游戏未就绪，重启游戏
        logger.warning("游戏状态错误，将重启游戏。")
        self.lifecycle_workflow.restart()

        # 重启游戏后，检查恶意值
        bad_sport_level = self.online_workflow.get_bad_sport_level()
        if bad_sport_level != "清白玩家":
            logger.warning(f"当前恶意等级为 {bad_sport_level} ，恶意等级过高。")
            if bad_sport_level == "问题玩家":
                raise UnexpectedGameState(GameState.CLEAN_PLAYER_LEVEL, GameState.DODGY_PLAYER_LEVEL)
            else:  # 恶意玩家
                raise UnexpectedGameState(GameState.CLEAN_PLAYER_LEVEL, GameState.BAD_SPORT_LEVEL)
        else:
            logger.info(f"当前恶意等级为 {bad_sport_level} ，恶意等级正常。")

        logger.info("初始化 GTA V 完成。")

    def play_dre_job(self):
        """
        执行德瑞差事的任务流程:
        1. 移动到任务触发点，进入别惹德瑞
        2. 发送消息，等待玩家加入，启动差事
        3. 落地后，卡单
        4. 检查是否在任务中

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

    def run_dre_bot(self):
        """
        执行一轮完整的德瑞 Bot 任务:
        1. 启动游戏并确保进入在线模式。
        2. 执行一轮德瑞差事。

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
        try:
            self.setup()
        except UnexpectedGameState as e:
            if e.actual_state == GameState.BAD_SPORT_LEVEL:
                # 恶意等级过高，退出游戏
                logger.error("初始化游戏时，检测到恶意等级过高，退出游戏。")
                self.lifecycle_workflow.shutdown()
            raise
        except UIElementNotFound as e:
            if e.element_not_found == UIElement.BAD_SPORT_LEVEL_INDICATOR:
                # 无法检查恶意等级，为避免恶意等级过高，退出游戏以再次触发恶意等级检查
                logger.error("初始化游戏时，检测恶意等级失败，退出游戏。")
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

        # 执行德瑞bot任务
        self.play_dre_job()

        logger.info("本轮德瑞 Bot 任务成功完成。")
