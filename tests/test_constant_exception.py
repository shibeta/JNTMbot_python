"""``gta_automator.constant`` 与 ``gta_automator.exception`` 的单元测试。"""

from __future__ import annotations

import pytest

from gta_automator.constant import (
    GTA_ASSOCIATED_PROCESS_NAMES,
    GTA_PROCESS_NAME,
    GTA_WINDOW_CLASS_NAME,
    GTA_WINDOW_TITLE,
    STEAM_JVP_PATTERN,
    BotMode,
    PlayerLevel,
)
from gta_automator.exception import (
    GameAutomatorException,
    GameState,
    NetworkError,
    NetworkErrorContext,
    OperationTimeout,
    OperationTimeoutContext,
    UIElement,
    UIElementNotFound,
    UnexpectedGameState,
)


class TestBotMode:
    def test_members(self):
        assert {member.name for member in BotMode} == {"DRE", "RECOVERY"}

    def test_members_are_distinct(self):
        assert BotMode.DRE is not BotMode.RECOVERY


class TestPlayerLevel:
    def test_values(self):
        assert PlayerLevel.CLEAN.value == "清白玩家"
        assert PlayerLevel.DODGY.value == "问题玩家"
        assert PlayerLevel.BAD_SPORT.value == "恶意玩家"
        assert PlayerLevel.UNKNOWN.value == "未知等级"

    def test_members(self):
        assert {member.name for member in PlayerLevel} == {"CLEAN", "DODGY", "BAD_SPORT", "UNKNOWN"}


class TestGtaConstants:
    def test_process_name(self):
        assert GTA_PROCESS_NAME == "GTA5_Enhanced.exe"

    def test_window_title_and_class(self):
        assert GTA_WINDOW_TITLE == "Grand Theft Auto V"
        assert GTA_WINDOW_CLASS_NAME == "sgaWindow"

    def test_associated_process_names(self):
        assert "GTA5.exe" in GTA_ASSOCIATED_PROCESS_NAMES
        assert GTA_PROCESS_NAME in GTA_ASSOCIATED_PROCESS_NAMES
        assert len(set(GTA_ASSOCIATED_PROCESS_NAMES)) == len(GTA_ASSOCIATED_PROCESS_NAMES)
        assert all(name.endswith(".exe") for name in GTA_ASSOCIATED_PROCESS_NAMES)


class TestSteamJvpPattern:
    @pytest.mark.parametrize(
        "value",
        [
            "abcd",
            "aB1z",
            "abc%3D",
            "ab%3D%3D",
            "abcdabcd",
            "a%2Bcd",
            "abc%3d",
        ],
    )
    def test_valid_jvp(self, value: str):
        assert STEAM_JVP_PATTERN.fullmatch(value) is not None

    @pytest.mark.parametrize(
        "value",
        [
            "",
            "abc",
            "abcde",
            "abcdefghi",
            "ab%2Fcd",
            "abcd%2Fefgh",
            "中文中文",
            "ab cd",
            "ab;cd",
            "ab&cd",
            "ab$(whoami)",
            "ab'cd",
            "abc%3",
            "ab%3D%2",
            "http://evil.com",
        ],
    )
    def test_invalid_jvp(self, value: str):
        assert STEAM_JVP_PATTERN.fullmatch(value) is None

    def test_anchored_pattern_rejects_trailing_garbage(self):
        assert STEAM_JVP_PATTERN.fullmatch("abcd%3D") is None
        assert STEAM_JVP_PATTERN.fullmatch("abcd extra") is None


class TestOperationTimeout:
    def test_attributes(self):
        error = OperationTimeout(OperationTimeoutContext.RESPAWN_IN_AGENCY)

        assert error.context is OperationTimeoutContext.RESPAWN_IN_AGENCY
        assert error.message == "等待在事务所复活超时"
        assert str(error) == "等待在事务所复活超时"

    def test_is_game_automator_exception(self):
        assert isinstance(OperationTimeout(OperationTimeoutContext.TEAMMATE), GameAutomatorException)

    def test_all_contexts_produce_message(self):
        for context in OperationTimeoutContext:
            assert OperationTimeout(context).message == f"等待{context.value}超时"


class TestUnexpectedGameState:
    def test_single_expected_state(self):
        error = UnexpectedGameState(expected=GameState.ONLINE_FREEMODE, actual=GameState.LOADING_SCREEN)

        assert error.expected is GameState.ONLINE_FREEMODE
        assert error.actual_state is GameState.LOADING_SCREEN
        assert error.message == '期望状态为 "在线战局自由模式", 但实际状态为 "加载界面"'
        assert str(error) == error.message

    def test_set_of_expected_states_joined_with_or(self):
        expected = {GameState.ONLINE_FREEMODE, GameState.IN_MISSION}
        error = UnexpectedGameState(expected=expected, actual=GameState.ONLINE_PAUSED)

        assert error.expected == expected
        assert error.actual_state is GameState.ONLINE_PAUSED
        assert error.message.startswith('期望状态为 "')
        assert error.message.endswith('", 但实际状态为 "在线模式暂停菜单"')
        for state in expected:
            assert state.value in error.message
        assert " 或 " in error.message

    def test_invalid_expected_type_returns_unknown(self):
        error = UnexpectedGameState(expected=[GameState.ON], actual=GameState.OFF)  # type: ignore[arg-type]

        assert error.message == '期望状态为 "未知期望", 但实际状态为 "游戏未运行"'

    def test_is_game_automator_exception(self):
        assert isinstance(UnexpectedGameState(GameState.ON, GameState.OFF), GameAutomatorException)


class TestUIElementNotFound:
    def test_attributes(self):
        error = UIElementNotFound(UIElement.JOB_TRIGGER_POINT)

        assert error.element_not_found is UIElement.JOB_TRIGGER_POINT
        assert error.message == "找不到任务触发点"
        assert str(error) == "找不到任务触发点"

    def test_all_elements_produce_message(self):
        for element in UIElement:
            assert UIElementNotFound(element).message == f"找不到{element.value}"

    def test_is_game_automator_exception(self):
        assert isinstance(UIElementNotFound(UIElement.PAUSE_MENU), GameAutomatorException)


class TestNetworkError:
    def test_attributes(self):
        error = NetworkError(NetworkErrorContext.FETCH_WARPBOT_INFO)

        assert error.context is NetworkErrorContext.FETCH_WARPBOT_INFO
        assert error.message == "获取差传Bot战局信息时发生网络错误"
        assert str(error) == error.message

    def test_is_game_automator_exception(self):
        assert isinstance(NetworkError(NetworkErrorContext.FETCH_WARPBOT_INFO), GameAutomatorException)


def test_exception_hierarchy():
    """所有自定义异常都应是 GameAutomatorException 的子类，便于统一捕获。"""
    assert issubclass(OperationTimeout, GameAutomatorException)
    assert issubclass(UnexpectedGameState, GameAutomatorException)
    assert issubclass(UIElementNotFound, GameAutomatorException)
    assert issubclass(NetworkError, GameAutomatorException)
    assert issubclass(GameAutomatorException, Exception)
