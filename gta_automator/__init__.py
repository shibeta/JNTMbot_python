import atexit

from config import Config
from gamepad_utils import GamepadSimulator
from logger import get_logger
from ocr_utils import OCREngine
from steambot_utils import SteamBotClient

from .exception import *
from .process import GameProcess
from .screen import GameScreen
from .action import Action
from .lifecycle import Lifecycle
from .session import Session
from .workflow import JobWorkflow

logger = get_logger("automator_facade")


class GTAAutomator:
    """
    用于自动化操作 GTA V 的类。
    """

    def __init__(self, config: Config, ocr_engine: OCREngine, steam_bot: SteamBotClient):
        # 初始化底层模块
        process = GameProcess()
        screen = GameScreen(ocr_engine, process)
        player_input = Action(GamepadSimulator(), config)

        # 初始化管理器，注入依赖
        self.lifecycle = Lifecycle(screen, player_input, process, config)
        self.session = Session(screen, player_input, process, config)
        self.workflow = JobWorkflow(screen, player_input, process, config, steam_bot)

        # 注册退出处理函数，以确保Python程序退出时 GTA V 进程不会被挂起
        atexit.register(process.resume_gta_process)
        # 注册退出处理函数，以确保Python程序退出时 GTA V 窗口不会处于置顶状态
        atexit.register(screen.unset_gta_window_topmost)

    def run_dre_bot(self):
        """
        执行一轮完整的德瑞 Bot 任务，从准备游戏到完成一轮差事流程。
        如果遇到可恢复的错误（如超时），会自行处理并结束当前循环。
        如果遇到致命错误，会向上抛出异常。

        :raises ``UnexpectedGameState(actual=GameState.OFF)``: 在自动化任务中，游戏意外关闭
        :raises ``UnexpectedGameState(expected={GameState.IN_ONLINE_LOBBY, GameState.IN_MISSION}, actual=GameState.UNKNOWN)``: 切换战局时失败
        :raises ``OperationTimeout(OperationTimeoutContext.RESPAWN_IN_AGENCY)``: 等待在事务所床上复活超时
        :raises ``UIElementNotFound(UIElementNotFoundContext.JOB_TRIGGER_POINT)``: 无法找到任务触发点
        :raises ``UIElementNotFound(UIElementNotFoundContext.JOB_SETUP_PANEL)``: 在等待玩家和启动差事阶段，意外离开了任务面板
        """
        logger.info("动作: 正在开始新一轮循环...")

        # 步骤1: 确保游戏就绪并进入新战局
        self.lifecycle.setup_gta()
        try:
            self.session.start_new_match()
        except UnexpectedGameState as e:
            if (
                e.expected == {GameState.IN_ONLINE_LOBBY, GameState.IN_MISSION}
                and e.actual_state == GameState.UNKNOWN
            ):
                # 开始新战局时，用尽全部恢复策略后仍无法切换战局
                logger.error("开始新战局失败次数过多。杀死 GTA V 进程。")
                self.lifecycle.process.kill_gta()
            raise e

        # 步骤2: 等待复活
        self.workflow.wait_for_respawn()

        # 步骤3: 导航至任务点
        self.workflow.navigate_from_bed_to_job_point()

        # 步骤4: 进入差事并等待面板
        self.workflow.enter_and_wait_for_job_panel()

        # 步骤5: 管理大厅并启动差事
        try:
            self.workflow.setup_wait_start_job()
        except OperationTimeout as e:
            # 玩家超时是正常现象，不是Bot的错。记录日志并安全退出当前循环。
            logger.warning(f"等待队伍时发生超时: {e}。将开始下一轮。")
            self.workflow.exit_job_panel()
            return
        except UnexpectedGameState as e:
            if e.actual_state == GameState.BAD_JOB_PANEL_STANDBY_PLAYER:
                logger.warning(f"发现待命玩家: {e}。将开始下一轮。")
                self.workflow.exit_job_panel()
                return
            else:
                raise  # 其他UnexpectedGameState是致命的，向上抛出

        # 步骤6: 处理差事启动后阶段
        self.workflow.handle_post_job_start()

        # 步骤7: 检查最终状态
        self.workflow.verify_mission_status_after_glitch()

        logger.info("本轮循环成功完成。")
