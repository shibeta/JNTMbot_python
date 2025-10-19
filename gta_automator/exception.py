import enum


class OperationTimeoutContext(enum.Enum):
    """抛出 OperationTimeout 异常时，可能处于的上下文"""

    GAME_WINDOW_STARTUP = "游戏窗口启动"
    MAIN_MENU_LOAD = "主菜单加载"
    STORY_MODE_LOAD = "故事模式加载"
    JOIN_ONLINE_SESSION = "加入在线战局"
    WAIT_TEAMMATE = "队友"
    PLAYER_JOIN = "玩家完成加入"
    RESPAWN_IN_AGENCY = "在事务所复活"
    JOB_SETUP_PANEL_OPEN = "差事面板打开"
    JOB_START = "差事启动"
    CHARACTER_LAND = "人物落地"


class GameState(enum.Enum):
    """定义了游戏中所有可被程序识别的高级状态。"""

    ON = "游戏运行中的任意状态"  # 仅用于expected
    UNKNOWN = "游戏运行中的无法识别的状态"  # 仅用于actual
    OFF = "游戏未运行"
    OFFLINE = "离线模式"
    MAIN_MENU = "主菜单"
    STORY_MODE = "故事模式"
    ONLINE_FREEMODE = "在线战局自由模式"
    DEAD_ONLINE = "在线模式死亡"
    LOADING_SCREEN = "加载界面"
    IN_MISSION = "任务中"
    SCOREBOARD = "任务失败计分板"
    STORY_PAUSED = "故事模式暂停菜单"
    ONLINE_PAUSED = "在线模式暂停菜单"
    JOB_PANEL_1 = "任务面板第一页"
    JOB_PANEL_2 = "任务面板第二页"
    BAD_JOB_PANEL_STANDBY_PLAYER = "有待命状态玩家的任务面板"
    WARNING = "警告/错误页面"
    BAD_PCSETTING_BIN = "此时无法载入您保存的数据"


class NavigationFailedContext(enum.Enum):
    """抛出 NavigationFailed 异常时，可能处于的上下文"""

    ENTER_AGENCY = "进入事务所"
    EXIT_AGENCY = "离开事务所"


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


class GameAutomatorException(Exception):
    """所有游戏自动化相关错误的基类。"""

    pass


class OperationTimeout(GameAutomatorException):
    """操作在规定时间内未完成的错误。"""

    def __init__(self, context: OperationTimeoutContext):
        self.context = context
        self.message = f"等待{self.context.value}超时"
        super().__init__(self.message)


class UnexpectedGameState(GameAutomatorException):
    """
    游戏处于意外状态的错误。

    Params:
        expected: 方法期望游戏处于的一个或多个状态。
        actual: 程序检测到的游戏当前实际状态。
    """

    def __init__(
        self,
        expected: GameState | set[GameState],
        actual: GameState,
    ):
        self.expected = expected
        self.actual_state = actual
        expected_str = self._format_expected()

        self.message = f'期望状态为 "{expected_str}", 但实际状态为 "{actual.value}"'

        super().__init__(self.message)

    def _format_expected(self) -> str:
        """辅助方法，用于生成清晰的期望描述。"""
        if isinstance(self.expected, GameState):
            return self.expected.value
        if isinstance(self.expected, set):
            return " 或 ".join(s.value for s in self.expected)

        return "未知期望"


class NavigationFailed(GameAutomatorException):
    """角色移动失败的错误。"""

    def __init__(self, context: NavigationFailedContext):
        self.context = context
        self.message = f"无法{self.context.value}"
        super().__init__(self.message)


class UIElementNotFound(GameAutomatorException):
    """在屏幕上找不到预期的UI元素的错误。"""

    def __init__(self, context: UIElementNotFoundContext):
        self.context = context
        self.message = f"找不到{self.context.value}"
        super().__init__(self.message)


class NetworkError(GameAutomatorException):
    """在线会话相关的错误。"""

    def __init__(self, context: NetworkErrorContext):
        self.context = context
        self.message = f"{context.value}时发生网络错误"
        super().__init__(self.message)


if __name__ == "__main__":
    print("--- 开始测试自定义异常 ---")

    # 1. 测试 OperationTimeout
    try:
        print("\n测试: OperationTimeout")
        raise OperationTimeout(OperationTimeoutContext.GAME_WINDOW_STARTUP)
    except OperationTimeout as e:
        print(f"成功捕获异常: {e}")
        assert e.message == "等待游戏窗口启动超时"

    # 2. 测试 UnexpectedGameState
    # 2a. 期望是单个状态
    try:
        print("\n测试: UnexpectedGameState (期望单个状态)")
        raise UnexpectedGameState(expected=GameState.ONLINE_FREEMODE, actual=GameState.LOADING_SCREEN)
    except UnexpectedGameState as e:
        print(f"成功捕获异常: {e}")
        assert e.message == '期望状态为 "IN_ONLINE_LOBBY", 但实际状态为 "LOADING_SCREEN"'

    # 2b. 期望是一组状态
    try:
        print("\n测试: UnexpectedGameState (期望一组状态)")
        expected_states = {GameState.ONLINE_FREEMODE, GameState.IN_MISSION}
        raise UnexpectedGameState(expected=expected_states, actual=GameState.ONLINE_PAUSED)
    except UnexpectedGameState as e:
        print(f"成功捕获异常: {e}")
        assert (
            e.message == '期望状态为 "IN_ONLINE_LOBBY 或 IN_MISSION", 但实际状态为 "ONLINE_PAUSED"'
            or e.message == '期望状态为 "IN_MISSION 或 IN_ONLINE_LOBBY", 但实际状态为 "ONLINE_PAUSED"'
        )

    # 3. 测试 NavigationFailed
    try:
        print("\n测试: NavigationFailed")
        # 注意: 我为 NavigationFailedContext 添加了示例成员，以便测试
        raise NavigationFailed(NavigationFailedContext.ENTER_AGENCY)
    except NavigationFailed as e:
        print(f"成功捕获异常: {e}")
        assert e.message == "无法进入事务所"

    # 4. 测试 UIElementNotFound
    try:
        print("\n测试: UIElementNotFound")
        raise UIElementNotFound(UIElementNotFoundContext.JOB_TRIGGER_POINT)
    except UIElementNotFound as e:
        print(f"成功捕获异常: {e}")
        assert e.message == "找不到任务触发点"

    # 5. 测试 NetworkError
    try:
        print("\n测试: NetworkError")
        raise NetworkError(NetworkErrorContext.JOIN_WARPBOT_SESSION)
    except NetworkError as e:
        print(f"成功捕获异常: {e}")
        assert e.message == "加入差传Bot战局时发生网络错误"

    print("\n--- 所有测试用例执行完毕 ---")
