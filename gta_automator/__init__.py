import time
from typing import Optional

from config import Config
from gamepad_utils import GamepadSimulator
from logger import get_logger
from ocr_utils import OCREngine
from steambot_utils import SteamBotClient

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
        ocr_engine: Optional[OCREngine] = None,
        steam_bot: Optional[SteamBotClient] = None,
        gamepad: Optional[GamepadSimulator] = None,
    ):
        # 初始化底层模块
        process = GameProcess()
        screen = GameScreen(ocr_engine if ocr_engine else OCREngine(config.ocrArgs), process)
        player_input = GameAction(gamepad if gamepad else GamepadSimulator(), config)

        # 初始化工作流，注入依赖
        self.lifecycle_workflow = LifecycleWorkflow(screen, player_input, process, config)
        self.online_workflow = OnlineWorkflow(screen, player_input, process, config)
        self.job_workflow = JobWorkflow(
            screen, player_input, process, config, steam_bot if steam_bot else SteamBotClient(config)
        )

    def play_dre_job(self):
        """
        执行德瑞差事的任务流程。

        :raises ``UnexpectedGameState(actual=GameState.OFF)``: 在自动化任务中，游戏意外关闭
        :raises ``OperationTimeout(OperationTimeoutContext.RESPAWN_IN_AGENCY)``: 等待在事务所床上复活超时
        :raises ``UIElementNotFound(UIElementNotFoundContext.JOB_TRIGGER_POINT)``: 无法找到任务触发点
        :raises ``OperationTimeout(OperationTimeoutContext.JOB_SETUP_PANEL_OPEN)``: 等待差事面板打开超时
        :raises ``UIElementNotFound(UIElementNotFoundContext.JOB_SETUP_PANEL)``: 在等待玩家和启动差事阶段，意外离开了任务面板
        """
        # 导航至任务点
        self.job_workflow.navigate_from_bed_to_job_point()

        # 进入差事准备面板
        try:
            self.job_workflow.enter_and_wait_for_job_panel()
        except OperationTimeout as e:
            # 等待差事面板打开超时
            logger.error("等待差事面板超时，为避免 RockStar 在线服务导致的故障，退出游戏。")
            self.lifecycle_workflow.shutdown_gta()
            raise

        # 管理大厅并启动差事
        try:
            self.job_workflow.setup_wait_start_job()
        except OperationTimeout as e:
            # 等待玩家加入超时，退出差事
            logger.warning(f"{e.message}。退出差事。")
            self.job_workflow.exit_job_panel()
            return
        except UnexpectedGameState as time_e:
            # 有待命状态玩家，退出差事
            if time_e.actual_state == GameState.BAD_JOB_PANEL_STANDBY_PLAYER:
                logger.warning(f"发现待命状态玩家。退出差事。")
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
                timeout_context = e.context
                # 在差事中检查状态超时，尝试更换战局
                # 在差事中退出游戏可能导致恶意值增加，所以这里选择切换战局
                logger.warning(f"{e.message}。卡单并切换战局。")
                # 首先需要卡单，进入单人战局状态，因为在多人差事中切换战局会增加恶意值
                self.online_workflow.glitch_single_player_session()
                time.sleep(2)  # 等待游戏状态稳定

                # 切换战局
                try:
                    self.online_workflow.start_new_match()
                    return  # 切换战局成功，结束当前差事流程

                except UnexpectedGameState as e:
                    if (
                        e.expected == {GameState.ONLINE_FREEMODE, GameState.IN_MISSION}
                        and e.actual_state == GameState.UNKNOWN
                    ):
                        # 这种情况下要么不在任务中，要么游戏卡死了，只能退出游戏
                        logger.error(f"处理{timeout_context}超时时，切换战局失败次数过多，退出游戏。")
                        self.lifecycle_workflow.shutdown_gta()
                    raise
            else:
                raise  # 其他超时是致命的，向上抛出

        # 检查最终状态
        self.job_workflow.verify_mission_status_after_glitch()

    def reduce_malicious_value(self):
        """
        执行减少恶意值的任务流程。
        """
        logger.info("动作: 正在开始减少恶意值任务流程...")

        # TODO: 实现减少恶意值的差事流程
        # 目前认为，减少恶意值可以通过单纯挂机或完成多人差事来实现
        # 但需要进一步研究恶意值增减的时机和数值，以高效清除恶意值
        logger.info("减少恶意值任务流程尚未实现。")

        logger.info("减少恶意值任务流程成功完成。")

    def run_dre_bot(self):
        """
        执行一轮完整的德瑞 Bot 任务:
        1. 启动游戏并确保进入在线模式。
        2. 执行一轮德瑞差事。

        :raises ``UnexpectedGameState(expected={GameState.IN_ONLINE_LOBBY, GameState.IN_MISSION}, actual=GameState.UNKNOWN)``: 切换战局时失败
        :raises ``UnexpectedGameState(actual=GameState.OFF)``: 在自动化任务中，游戏意外关闭
        :raises ``OperationTimeout(OperationTimeoutContext.RESPAWN_IN_AGENCY)``: 等待在事务所床上复活超时
        :raises ``UIElementNotFound(UIElementNotFoundContext.JOB_TRIGGER_POINT)``: 无法找到任务触发点
        :raises ``OperationTimeout(OperationTimeoutContext.JOB_SETUP_PANEL_OPEN)``: 等待差事面板打开超时
        :raises ``UIElementNotFound(UIElementNotFoundContext.JOB_SETUP_PANEL)``: 在等待玩家和启动差事阶段，意外离开了任务面板
        """
        logger.info("动作: 正在开始新一轮循环...")
        # 确保游戏就绪
        self.lifecycle_workflow.setup_gta()

        # TODO: 添加检测恶意值的逻辑，如果恶意值过高则先执行减少恶意值任务

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
                self.lifecycle_workflow.shutdown_gta()
            raise

        # 等待复活
        self.job_workflow.wait_for_respawn()

        # 执行德瑞bot任务
        self.play_dre_job()

        logger.info("本轮循环成功完成。")
