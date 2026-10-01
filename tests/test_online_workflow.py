"""``gta_automator.online_workflow`` 的单元测试。

覆盖切换战局的恢复策略链、恶意等级读取的重试逻辑，以及挂机时的在线状态检查。
``screen``/``action``/``process`` 均使用 ``MagicMock`` 注入。
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from gta_automator.constant import PlayerLevel
from gta_automator.exception import GameState, UIElement, UIElementNotFound, UnexpectedGameState
from gta_automator.online_workflow import OnlineWorkflow

ALL_STRATEGY_NAMES = (
    "_recover_by_do_nothing",
    "_recover_by_brute_force_back",
    "_recover_by_back_and_confirm",
    "_recover_by_glitching_session",
)


@pytest.fixture
def deps() -> SimpleNamespace:
    """三个底层依赖的 mock 集合。"""
    screen = MagicMock(name="GameScreen")
    action = MagicMock(name="GameAction")
    process = MagicMock(name="GameProcess")
    # 默认不在警告页面，且暂停菜单可以正常打开
    screen.is_on_warning_page.return_value = False
    screen.is_on_pause_menu.return_value = True
    return SimpleNamespace(screen=screen, action=action, process=process)


@pytest.fixture
def workflow(deps: SimpleNamespace, config) -> OnlineWorkflow:
    return OnlineWorkflow(deps.screen, deps.action, deps.process, config)


class TestTryToSwitchSession:
    def test_happy_path_call_order(self, workflow: OnlineWorkflow, deps: SimpleNamespace):
        deps.screen.is_on_go_online_menu.side_effect = [False, True]

        with patch.object(OnlineWorkflow, "open_pause_menu") as open_pause_menu:
            parent = MagicMock()
            parent.attach_mock(open_pause_menu, "open_pause_menu")
            parent.attach_mock(deps.action.navigate_to_switch_session_tab_in_online_pausemenu, "navigate")
            parent.attach_mock(deps.action.enter_invite_only_session, "enter")

            workflow._try_to_switch_session()

        assert parent.mock_calls == [call.open_pause_menu(), call.navigate(), call.enter()]

    def test_raises_when_stuck_in_go_online_menu(self, workflow: OnlineWorkflow, deps: SimpleNamespace):
        deps.screen.is_on_go_online_menu.return_value = True

        with (
            patch.object(OnlineWorkflow, "open_pause_menu"),
            pytest.raises(UnexpectedGameState) as excinfo,
        ):
            workflow._try_to_switch_session()

        assert excinfo.value.expected is GameState.ONLINE_PAUSED
        assert excinfo.value.actual_state is GameState.UNKNOWN
        deps.action.enter_invite_only_session.assert_not_called()

    def test_raises_when_switch_menu_not_opened(self, workflow: OnlineWorkflow, deps: SimpleNamespace):
        deps.screen.is_on_go_online_menu.side_effect = [False, False]

        with patch.object(OnlineWorkflow, "open_pause_menu"), pytest.raises(UIElementNotFound) as excinfo:
            workflow._try_to_switch_session()

        assert excinfo.value.element_not_found is UIElement.SWITCH_SESSION_TAB
        deps.action.enter_invite_only_session.assert_not_called()

    def test_checks_go_online_menu_before_navigating(self, workflow: OnlineWorkflow, deps: SimpleNamespace):
        deps.screen.is_on_go_online_menu.side_effect = [False, True]

        with patch.object(OnlineWorkflow, "open_pause_menu"):
            workflow._try_to_switch_session()

        deps.action.navigate_to_switch_session_tab_in_online_pausemenu.assert_called_once_with()
        deps.action.enter_invite_only_session.assert_called_once_with()


@pytest.fixture
def strategies():
    """把四个恢复策略替换为 mock。

    源码会读取 ``strategy.__name__`` 写日志，因此 mock 必须带上 ``__name__``。
    """
    patchers = {}
    mocks = {}
    for name in ALL_STRATEGY_NAMES:
        mock = MagicMock(name=name)
        mock.__name__ = name
        patchers[name] = patch.object(OnlineWorkflow, name, mock)
        mocks[name] = mock
    for patcher in patchers.values():
        patcher.start()
    try:
        yield mocks
    finally:
        for patcher in patchers.values():
            patcher.stop()


class TestStartNewMatch:
    def test_returns_immediately_on_first_success(self, workflow: OnlineWorkflow, strategies):
        with patch.object(OnlineWorkflow, "_try_to_switch_session") as try_switch:
            workflow.start_new_match()

        try_switch.assert_called_once_with()
        for name in ALL_STRATEGY_NAMES:
            strategies[name].assert_not_called()

    def test_recovers_with_second_strategy(self, workflow: OnlineWorkflow, strategies):
        # 第一次尝试失败 → do_nothing 后仍失败 → brute_force 后成功
        side_effect = [UIElementNotFound(UIElement.SWITCH_SESSION_TAB)] * 2 + [None]

        with patch.object(OnlineWorkflow, "_try_to_switch_session", side_effect=side_effect):
            parent = MagicMock()
            parent.attach_mock(strategies["_recover_by_do_nothing"], "do_nothing")
            parent.attach_mock(strategies["_recover_by_brute_force_back"], "brute_force")

            workflow.start_new_match()

        assert parent.mock_calls == [call.do_nothing(), call.brute_force()]
        strategies["_recover_by_back_and_confirm"].assert_not_called()
        strategies["_recover_by_glitching_session"].assert_not_called()

    def test_recovers_with_last_strategy(self, workflow: OnlineWorkflow, strategies):
        side_effect = [UIElementNotFound(UIElement.SWITCH_SESSION_TAB)] * 4 + [None]

        with patch.object(OnlineWorkflow, "_try_to_switch_session", side_effect=side_effect) as try_switch:
            workflow.start_new_match()

        assert try_switch.call_count == 5
        for name in ALL_STRATEGY_NAMES:
            strategies[name].assert_called_once_with()

    def test_raises_after_all_strategies_exhausted(self, workflow: OnlineWorkflow, strategies):
        with (
            patch.object(
                OnlineWorkflow,
                "_try_to_switch_session",
                side_effect=UIElementNotFound(UIElement.SWITCH_SESSION_TAB),
            ) as try_switch,
            pytest.raises(UnexpectedGameState) as excinfo,
        ):
            workflow.start_new_match()

        assert excinfo.value.expected == {
            GameState.ONLINE_FREEMODE,
            GameState.IN_MISSION,
            GameState.ONLINE_PAUSED,
        }
        assert excinfo.value.actual_state is GameState.UNKNOWN
        assert try_switch.call_count == 5
        for name in ALL_STRATEGY_NAMES:
            strategies[name].assert_called_once_with()

    def test_non_ui_errors_propagate_without_recovery(self, workflow: OnlineWorkflow, strategies):
        error = UnexpectedGameState(GameState.ON, GameState.OFF)

        with (
            patch.object(OnlineWorkflow, "_try_to_switch_session", side_effect=error),
            pytest.raises(UnexpectedGameState) as excinfo,
        ):
            workflow.start_new_match()

        assert excinfo.value.actual_state is GameState.OFF
        strategies["_recover_by_do_nothing"].assert_not_called()


class TestRecoveryStrategies:
    def test_do_nothing_does_nothing(self, workflow: OnlineWorkflow, deps: SimpleNamespace):
        workflow._recover_by_do_nothing()

        assert deps.action.mock_calls == []

    def test_brute_force_back_presses_back_seven_times(self, workflow: OnlineWorkflow, deps: SimpleNamespace):
        workflow._recover_by_brute_force_back()

        assert deps.action.back.call_count == 7

    def test_back_and_confirm_alternates_four_rounds(self, workflow: OnlineWorkflow, deps: SimpleNamespace):
        workflow._recover_by_back_and_confirm()

        assert deps.action.mock_calls == [call.back(), call.confirm()] * 4

    def test_glitching_session_suspends_process(self, workflow: OnlineWorkflow, no_sleep: MagicMock):
        with patch.object(OnlineWorkflow, "glitch_single_player_session") as glitch:
            workflow._recover_by_glitching_session()

        glitch.assert_called_once_with()
        no_sleep.assert_any_call(5)


class TestGetBadSportLevel:
    def test_returns_level_on_first_read(self, workflow: OnlineWorkflow, deps: SimpleNamespace):
        deps.screen.get_bad_sport_level_of_first_player_in_list.return_value = PlayerLevel.CLEAN

        with patch.object(OnlineWorkflow, "open_pause_menu") as open_pause_menu:
            assert workflow.get_bad_sport_level() is PlayerLevel.CLEAN

        open_pause_menu.assert_called_once_with()
        deps.action.navigate_to_player_list_tab_in_online_pausemenu.assert_called_once_with()
        deps.screen.get_bad_sport_level_of_first_player_in_list.assert_called_once_with()

    def test_retries_after_unknown_then_succeeds(self, workflow: OnlineWorkflow, deps: SimpleNamespace):
        deps.screen.get_bad_sport_level_of_first_player_in_list.side_effect = [
            PlayerLevel.UNKNOWN,
            PlayerLevel.UNKNOWN,
            PlayerLevel.DODGY,
        ]

        with patch.object(OnlineWorkflow, "open_pause_menu"):
            assert workflow.get_bad_sport_level() is PlayerLevel.DODGY

        assert deps.screen.get_bad_sport_level_of_first_player_in_list.call_count == 3

    def test_raises_after_three_failed_retries(self, workflow: OnlineWorkflow, deps: SimpleNamespace):
        deps.screen.get_bad_sport_level_of_first_player_in_list.return_value = PlayerLevel.UNKNOWN

        with patch.object(OnlineWorkflow, "open_pause_menu"), pytest.raises(UIElementNotFound) as excinfo:
            workflow.get_bad_sport_level()

        assert excinfo.value.element_not_found is UIElement.BAD_SPORT_LEVEL_INDICATOR
        # 首次读取 + 三次重试
        assert deps.screen.get_bad_sport_level_of_first_player_in_list.call_count == 4

    def test_closes_pause_menu_even_on_failure(self, workflow: OnlineWorkflow, deps: SimpleNamespace):
        deps.screen.get_bad_sport_level_of_first_player_in_list.return_value = PlayerLevel.UNKNOWN

        with patch.object(OnlineWorkflow, "open_pause_menu"), pytest.raises(UIElementNotFound):
            workflow.get_bad_sport_level()

        deps.action.open_or_close_pause_menu.assert_called_once_with()

    def test_closes_pause_menu_on_success(self, workflow: OnlineWorkflow, deps: SimpleNamespace):
        deps.screen.get_bad_sport_level_of_first_player_in_list.return_value = PlayerLevel.BAD_SPORT

        with patch.object(OnlineWorkflow, "open_pause_menu"):
            assert workflow.get_bad_sport_level() is PlayerLevel.BAD_SPORT

        deps.action.open_or_close_pause_menu.assert_called_once_with()


class TestAfk:
    def test_raises_when_leaving_online_mode(self, workflow: OnlineWorkflow):
        with (
            patch.object(OnlineWorkflow, "check_if_in_onlinemode", return_value=False),
            pytest.raises(UnexpectedGameState) as excinfo,
        ):
            workflow.afk(60)

        assert excinfo.value.expected == {GameState.ONLINE_FREEMODE, GameState.IN_MISSION}
        assert excinfo.value.actual_state is GameState.UNKNOWN

    def test_checks_online_status_repeatedly(self, workflow: OnlineWorkflow, no_sleep: MagicMock):
        with patch.object(OnlineWorkflow, "check_if_in_onlinemode", return_value=True) as check:
            workflow.afk(200, online_check_interval=60)

        assert check.call_count > 1
        no_sleep.assert_any_call(60)

    def test_short_afk_waits_remaining_time(self, workflow: OnlineWorkflow, no_sleep: MagicMock):
        with patch.object(OnlineWorkflow, "check_if_in_onlinemode", return_value=True) as check:
            workflow.afk(10, online_check_interval=60)

        check.assert_called_once_with()
        # 剩余时间小于检查间隔时，按剩余时间休眠
        assert no_sleep.call_count == 1
        waited = no_sleep.call_args.args[0]
        assert 0 < waited <= 10
