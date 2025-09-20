import enum
from typing import Callable


class OperationTimeoutContext(enum.Enum):
    """抛出 OperationTimeout 异常时，可能处于的上下文"""

    GAME_WINDOW_STARTUP = "等待游戏窗口启动"
    MAIN_MENU_LOAD = "等待主菜单加载"
    STORY_MODE_LOAD = "等待故事模式加载"
    JOIN_ONLINE_SESSION = "等待加入在线战局"
    WAIT_TEAMMATE = "等待队友"
    PLAYER_JOIN = "等待玩家完成加入"
    RESPAWN_IN_AGENCY = "等待在事务所复活"
    JOB_SETUP_PANEL_OPEN = "等待差事面板打开"


class GameState(enum.Enum):
    """定义了游戏中所有可被程序识别的高级状态。"""

    # is_running: 游戏正在运行
    # is_playable: 可以控制角色
    # is_online: 处于在线模式中
    UNKNOWN = "无法识别的未知状态", {"is_running": True, "is_playable": False, "is_online": False}
    OFF = "游戏未运行", {"is_running": False, "is_playable": False, "is_online": False}
    MAIN_MENU = "主菜单", {"is_running": True, "is_playable": False, "is_online": False}
    IN_STORY_MODE = "故事模式", {"is_running": True, "is_playable": True, "is_online": False}
    IN_ONLINE_LOBBY = "在线战局自由模式", {"is_running": True, "is_playable": True, "is_online": True}
    DEAD_ONLINE = "在线模式死亡", {"is_running": True, "is_playable": False, "is_online": True}
    LOADING_SCREEN = "加载界面", {"is_running": True, "is_playable": False, "is_online": False}
    IN_MISSION = "任务中", {"is_running": True, "is_playable": True, "is_online": True}
    SCOREBOARD = "任务失败计分板", {"is_running": True, "is_playable": False, "is_online": True}
    STORY_PAUSED = "故事模式暂停菜单", {"is_running": True, "is_playable": False, "is_online": False}
    ONLINE_PAUSED = "在线模式暂停菜单", {"is_running": True, "is_playable": False, "is_online": True}
    JOB_PANNEL_1 = "任务面板第一页", {"is_running": True, "is_playable": False, "is_online": True}
    JOB_PANNEL_2 = "任务面板第二页", {"is_running": True, "is_playable": False, "is_online": True}
    WARNING = "警告/错误页面", {"is_running": True, "is_playable": False, "is_online": False}
    BAD_PCSETTING_BIN = "此时无法载入您保存的数据", {
        "is_running": True,
        "is_playable": False,
        "is_online": False,
    }


class NavigationFailedContext(enum.Enum):
    """抛出 NavigationFailed 异常时，可能处于的上下文"""


class UIElementNotFoundContext(enum.Enum):
    """抛出 UIElementNotFound 异常时，可能处于的上下文"""

    STORY_MODE_MENU = "故事模式菜单"
    ONLINE_MODE_TAB = "在线模式选项卡"
    JOB_SETUP_PANEL = "任务准备面板"
    JOB_TRIGGER_POINT = "任务触发点"


class NetworkErrorContext(enum.Enum):
    """抛出 NetworkError 异常时，可能处于的上下文"""

    FETCH_WARPBOT_INFO = "获取差传Bot战局信息"
    JOIN_WARPBOT_SESSION = "加入差传Bot战局"


class GameAutomationException(Exception):
    """所有游戏自动化相关错误的基类。"""

    pass


class OperationTimeout(GameAutomationException):
    """操作在规定时间内未完成的错误。"""

    def __init__(self, context: OperationTimeoutContext):
        self.context = context
        self.message = f"{self.context.value}超时"
        super().__init__(self.message)


class UnexpectedGameState(GameAutomationException):
    """
    游戏处于意外状态的错误。

    Params:
        expected: 方法期望游戏处于的一个或多个状态。
        actual: 程序检测到的游戏当前实际状态。
    """

    def __init__(
        self,
        # 期望可以是：单个状态，一组状态，或一个返回布尔值的函数
        expected: GameState | set[GameState] | Callable[[GameState], bool],
        actual: GameState,
    ):
        self.expected = expected
        self.actual_state = actual
        expected_str = self._format_expected()

        self.message = f'期望状态为 "{expected_str}", 但实际状态为 "{actual.name}"。'

        super.__init__(self.message)

    def _format_expected(self) -> str:
        """辅助方法，用于生成清晰的期望描述。"""
        if isinstance(self.expected, GameState):
            return self.expected.name
        if isinstance(self.expected, set):
            return " or ".join(s.name for s in self.expected)
        if callable(self.expected):
            # 尝试从函数名中获取有意义的描述
            # 例如 lambda s: s.is_playable -> "is_playable"
            return f"满足属性 '{self.expected.__name__}'"
        return "未知期望"


class NavigationFailed(GameAutomationException):
    """角色移动失败的错误。"""

    def __init__(self, context: NavigationFailedContext):
        self.context = context
        self.message = f"无法{self.context.value}"
        super().__init__(self.message)


class UIElementNotFound(GameAutomationException):
    """在屏幕上找不到预期的UI元素的错误。"""

    def __init__(self, context: UIElementNotFoundContext):
        self.context = context
        self.message = f"找不到{self.context.value}"
        super().__init__(self.message)


class NetworkError(GameAutomationException):
    """在线会话相关的错误。"""

    def __init__(self, context: NetworkErrorContext):
        self.context = context
        self.message = f"{context.value}时发生网络错误"
        super().__init__(self.message)
