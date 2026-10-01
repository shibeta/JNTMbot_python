"""``gta_automator.job_workflow`` 的单元测试。

覆盖差事面板状态跟踪器 ``LobbyStateTracker`` 与差事流程 ``JobWorkflow``。

所有底层依赖（``screen`` / ``action`` / ``process``）均用 ``MagicMock`` 注入，
休眠与 ``time.monotonic`` 由 ``tests/conftest.py`` 的 autouse fixture 拦截，
因此测试中不会产生任何真实的按键、截图、进程操作或等待。
"""

from __future__ import annotations

from typing import NamedTuple
from unittest.mock import MagicMock, call, patch

import pytest

from gta_automator.exception import (
    GameState,
    OperationTimeout,
    OperationTimeoutContext,
    UIElement,
    UIElementNotFound,
    UnexpectedGameState,
)
from gta_automator.job_workflow import JobWorkflow, LobbyStateTracker


@pytest.fixture
def screen() -> MagicMock:
    screen = MagicMock(name="screen")
    # 默认不在警告页面，避免 handle_warning_page 误判
    screen.is_on_warning_page.return_value = False
    return screen


@pytest.fixture
def handle_warning() -> MagicMock:
    return MagicMock(name="handle_warning_page_func")


@pytest.fixture
def tracker(screen: MagicMock, handle_warning: MagicMock) -> LobbyStateTracker:
    """一个使用固定参数构造的大厅状态跟踪器。"""
    return LobbyStateTracker(
        gamescreen=screen,
        handle_warning_page_func=handle_warning,
        start_immediately_when_full=True,
        normal_start_delay=15,
        wait_timeout=180,
        joining_timeout=60,
    )


class JobWorkflowHarness(NamedTuple):
    """把 JobWorkflow 及其全部依赖打包，方便用例断言。"""

    workflow: JobWorkflow
    screen: MagicMock
    action: MagicMock
    process: MagicMock
    send_message: MagicMock


@pytest.fixture
def wf(config) -> JobWorkflowHarness:
    screen = MagicMock(name="screen")
    screen.is_on_warning_page.return_value = False
    action = MagicMock(name="action")
    process = MagicMock(name="process")
    send_message = MagicMock(name="send_steam_message_func")
    workflow = JobWorkflow(screen, action, process, config, send_message)
    return JobWorkflowHarness(workflow, screen, action, process, send_message)


class TestLobbyStateTrackerInit:
    """``LobbyStateTracker`` 的初始化与 ``init()``。"""

    def test_default_state_after_construction(self, tracker: LobbyStateTracker):
        assert tracker.in_lobby is False
        assert tracker.joining_count == 0
        assert tracker.joined_count == 0
        assert tracker.standby_count == 0
        assert tracker.start_wait_time == tracker.team_status_last_changed_time
        assert tracker.start_wait_time == tracker.last_zero_joining_player_time

    def test_init_resets_state_and_timers(self, tracker: LobbyStateTracker, fake_clock):
        tracker.in_lobby = True
        tracker.joined_count = 3
        tracker.joining_count = 2
        tracker.standby_count = 1
        fake_clock.advance(999)

        tracker.init()

        assert tracker.in_lobby is False
        assert (tracker.joining_count, tracker.joined_count, tracker.standby_count) == (0, 0, 0)
        assert tracker.start_wait_time == fake_clock.now
        assert tracker.team_status_last_changed_time == fake_clock.now
        assert tracker.last_zero_joining_player_time == fake_clock.now


class TestLobbyStateTrackerUpdate:
    """``update()`` 的 OCR 复用、警告页兜底与计时器更新。"""

    def test_uses_provided_ocr_text_without_second_ocr(self, tracker: LobbyStateTracker, screen: MagicMock):
        screen.get_job_setup_status.return_value = (True, 0, 1, 0)

        tracker.update("传入的 OCR 文本")

        screen.get_job_setup_status.assert_called_once_with("传入的 OCR 文本")
        assert tracker.in_lobby is True
        assert tracker.joined_count == 1

    def test_not_in_lobby_handles_warning_page_and_retries(
        self, tracker: LobbyStateTracker, screen: MagicMock, handle_warning: MagicMock
    ):
        screen.get_job_setup_status.side_effect = [(False, -1, -1, -1), (True, 1, 1, 0)]

        tracker.update("第一次识别")

        handle_warning.assert_called_once_with()
        assert screen.get_job_setup_status.call_args_list == [call("第一次识别"), call()]
        assert tracker.in_lobby is True
        assert (tracker.joining_count, tracker.joined_count, tracker.standby_count) == (1, 1, 0)

    def test_still_out_of_lobby_after_warning_page(
        self, tracker: LobbyStateTracker, screen: MagicMock, handle_warning: MagicMock
    ):
        screen.get_job_setup_status.return_value = (False, -1, -1, -1)

        tracker.update()

        handle_warning.assert_called_once_with()
        assert tracker.in_lobby is False
        assert (tracker.joining_count, tracker.joined_count, tracker.standby_count) == (-1, -1, -1)

    def test_team_change_updates_timer_only_on_change(self, tracker: LobbyStateTracker, screen: MagicMock, fake_clock):
        screen.get_job_setup_status.return_value = (True, 1, 1, 0)
        fake_clock.step = 0
        fake_clock.set(500.0)
        tracker.team_status_last_changed_time = 500.0
        tracker.last_zero_joining_player_time = 500.0

        fake_clock.advance(30)
        tracker.update()

        assert tracker.team_status_last_changed_time == 530.0
        # 有人在"正在加入"，不应刷新无加入计时器
        assert tracker.last_zero_joining_player_time == 500.0

        fake_clock.advance(10)
        tracker.update()

        # 人数结构没有变化，计时器保持不变
        assert tracker.team_status_last_changed_time == 530.0

    def test_zero_joining_updates_timer(self, tracker: LobbyStateTracker, screen: MagicMock, fake_clock):
        screen.get_job_setup_status.return_value = (True, 0, 1, 0)
        fake_clock.step = 0
        fake_clock.set(700.0)
        tracker.last_zero_joining_player_time = 100.0

        tracker.update()

        assert tracker.last_zero_joining_player_time == 700.0


class TestLobbyStateTrackerProperties:
    """跟踪器的各个判断属性。"""

    @pytest.mark.parametrize(
        ("joining", "joined", "standby", "expected"),
        [
            (0, 0, 0, False),
            (0, 2, 0, False),
            (0, 3, 0, True),
            (1, 1, 1, True),
            (0, 0, 3, True),
        ],
    )
    def test_is_lobby_full(self, tracker: LobbyStateTracker, joining: int, joined: int, standby: int, expected: bool):
        tracker.joining_count = joining
        tracker.joined_count = joined
        tracker.standby_count = standby

        assert tracker.is_lobby_full is expected

    def test_has_standby_player(self, tracker: LobbyStateTracker):
        tracker.standby_count = 0
        assert tracker.has_standby_player is False

        tracker.standby_count = 1
        assert tracker.has_standby_player is True

    def test_has_wait_timeout(self, tracker: LobbyStateTracker, fake_clock):
        tracker.wait_timeout = 180
        fake_clock.step = 0
        fake_clock.set(1000.0)
        tracker.start_wait_time = 1000.0

        assert tracker.has_wait_timeout is False

        fake_clock.advance(181)
        assert tracker.has_wait_timeout is True

    @pytest.mark.parametrize(("joined", "joining"), [(1, 0), (0, 1)])
    def test_has_wait_timeout_requires_empty_lobby(
        self, tracker: LobbyStateTracker, fake_clock, joined: int, joining: int
    ):
        tracker.wait_timeout = 180
        tracker.joined_count = joined
        tracker.joining_count = joining
        fake_clock.step = 0
        fake_clock.set(1000.0)
        tracker.start_wait_time = 0.0

        assert tracker.has_wait_timeout is False

    def test_has_joining_timeout(self, tracker: LobbyStateTracker, fake_clock):
        tracker.joining_timeout = 60
        tracker.joining_count = 1
        fake_clock.step = 0
        fake_clock.set(1000.0)
        tracker.last_zero_joining_player_time = 1000.0

        assert tracker.has_joining_timeout is False

        fake_clock.advance(61)
        assert tracker.has_joining_timeout is True

    def test_has_joining_timeout_without_joining_player(self, tracker: LobbyStateTracker, fake_clock):
        tracker.joining_timeout = 60
        tracker.joining_count = 0
        tracker.last_zero_joining_player_time = 0.0
        fake_clock.step = 0
        fake_clock.set(1000.0)

        assert tracker.has_joining_timeout is False

    def test_should_start_job_false_with_standby_player(self, tracker: LobbyStateTracker):
        tracker.start_immediately_when_full = True
        tracker.joined_count = 3
        tracker.standby_count = 1

        assert tracker.should_start_job is False

    def test_should_start_job_true_when_full_and_immediate(self, tracker: LobbyStateTracker):
        tracker.start_immediately_when_full = True
        tracker.joined_count = 3
        tracker.joining_count = 0

        assert tracker.should_start_job is True

    def test_should_start_job_true_after_normal_delay(self, tracker: LobbyStateTracker, fake_clock):
        tracker.start_immediately_when_full = False
        tracker.normal_start_delay = 15
        tracker.joined_count = 1
        tracker.joining_count = 0
        fake_clock.step = 0
        fake_clock.set(1000.0)
        tracker.team_status_last_changed_time = 1000.0

        assert tracker.should_start_job is False

        fake_clock.advance(16)
        assert tracker.should_start_job is True

    def test_should_start_job_false_while_player_joining(self, tracker: LobbyStateTracker, fake_clock):
        tracker.start_immediately_when_full = False
        tracker.joined_count = 1
        tracker.joining_count = 1
        fake_clock.step = 0
        fake_clock.set(1000.0)
        tracker.team_status_last_changed_time = 0.0

        assert tracker.should_start_job is False

    def test_should_start_job_false_without_joined_players(self, tracker: LobbyStateTracker, fake_clock):
        tracker.start_immediately_when_full = False
        tracker.joined_count = 0
        tracker.joining_count = 0
        fake_clock.step = 0
        fake_clock.set(1000.0)
        tracker.team_status_last_changed_time = 0.0

        assert tracker.should_start_job is False


class TestWaitForRespawnInAgency:
    """``wait_for_respawn_in_agency``。"""

    def test_success(self, wf: JobWorkflowHarness):
        wf.screen.is_respawned_in_agency.return_value = True

        wf.workflow.wait_for_respawn_in_agency()  # 不应抛出异常

        wf.screen.is_respawned_in_agency.assert_called()

    def test_timeout_raises_operation_timeout(self, wf: JobWorkflowHarness):
        with (
            patch.object(wf.workflow, "wait_for_state", return_value=False) as wait,
            pytest.raises(OperationTimeout) as excinfo,
        ):
            wf.workflow.wait_for_respawn_in_agency()

        assert excinfo.value.context is OperationTimeoutContext.RESPAWN_IN_AGENCY
        wait.assert_called_once_with(
            wf.screen.is_respawned_in_agency, timeout=wf.workflow.config.respawnInAgencyTimeout
        )


class TestFindJobPoint:
    """``_find_job_point`` 螺旋搜索。"""

    def test_returns_immediately_when_marker_found(self, wf: JobWorkflowHarness):
        wf.screen.is_job_marker_found.return_value = True

        wf.workflow._find_job_point()

        wf.screen.is_job_marker_found.assert_called_once_with()
        wf.action.walk_forward.assert_not_called()
        wf.action.walk_left.assert_not_called()

    def test_found_during_search(self, wf: JobWorkflowHarness):
        wf.screen.is_job_marker_found.side_effect = [False, False, True]

        wf.workflow._find_job_point()

        wf.action.walk_forward.assert_called_once_with(wf.workflow.config.moveTimeFindJob)
        wf.action.walk_left.assert_called_once_with(wf.workflow.config.moveTimeFindJob)

    def test_not_found_raises_ui_element_not_found(self, wf: JobWorkflowHarness):
        wf.screen.is_job_marker_found.return_value = False

        with pytest.raises(UIElementNotFound) as excinfo:
            wf.workflow._find_job_point()

        assert excinfo.value.element_not_found is UIElement.JOB_TRIGGER_POINT
        # 搜索模式: 前 1 + 前 3, 左 1 + 左 3, 后 2, 右 2
        assert wf.action.walk_forward.call_count == 4
        assert wf.action.walk_left.call_count == 4
        assert wf.action.walk_backward.call_count == 2
        assert wf.action.walk_right.call_count == 2
        wf.action.walk_forward.assert_called_with(wf.workflow.config.moveTimeFindJob)


class TestNavigateFromBedToJobPoint:
    """``navigate_from_bed_to_job_point`` 的两种移动方式。"""

    def test_manual_move_uses_bot_owner(self, wf: JobWorkflowHarness):
        wf.workflow.config.manualMoveToPoint = True
        with patch.object(wf.workflow, "_find_job_point") as find_job_point:
            wf.workflow.navigate_from_bed_to_job_point()

        wf.action.go_job_point_from_bed_by_bot_owner.assert_called_once_with()
        wf.action.go_job_point_from_bed.assert_not_called()
        find_job_point.assert_called_once_with()

    def test_automatic_move_uses_gamepad_sequence(self, wf: JobWorkflowHarness):
        wf.workflow.config.manualMoveToPoint = False
        with patch.object(wf.workflow, "_find_job_point") as find_job_point:
            wf.workflow.navigate_from_bed_to_job_point()

        wf.action.go_job_point_from_bed.assert_called_once_with()
        wf.action.go_job_point_from_bed_by_bot_owner.assert_not_called()
        find_job_point.assert_called_once_with()


class TestEnterAndWaitForJobPanel:
    """``enter_and_wait_for_job_panel``。"""

    def test_success_presses_three_times(self, wf: JobWorkflowHarness):
        with patch.object(wf.workflow, "wait_for_state", return_value=True) as wait:
            wf.workflow.enter_and_wait_for_job_panel()

        assert wf.action.launch_job_setup_panel.call_count == 3
        wait.assert_called_once_with(wf.screen.is_on_job_panel, timeout=60)

    def test_timeout_raises_operation_timeout(self, wf: JobWorkflowHarness):
        with (
            patch.object(wf.workflow, "wait_for_state", return_value=False),
            pytest.raises(OperationTimeout) as excinfo,
        ):
            wf.workflow.enter_and_wait_for_job_panel()

        assert excinfo.value.context is OperationTimeoutContext.JOB_SETUP_PANEL_OPEN
        assert wf.action.launch_job_setup_panel.call_count == 3


class TestTryToStartJob:
    """``_try_to_start_job``。"""

    def test_success_on_third_check(self, wf: JobWorkflowHarness):
        wf.screen.is_job_starting.side_effect = [False, False, True]

        assert wf.workflow._try_to_start_job() is True
        assert wf.action.confirm.call_count == 2
        # 启动成功时不应再去检查面板
        wf.screen.is_on_job_panel.assert_not_called()

    @pytest.mark.parametrize("success_index", [0, 1, 2])
    def test_success_on_any_check(self, wf: JobWorkflowHarness, success_index: int):
        results = [False, False, False]
        results[success_index] = True
        wf.screen.is_job_starting.side_effect = results

        assert wf.workflow._try_to_start_job() is True

    def test_failure_but_still_on_panel_returns_false(self, wf: JobWorkflowHarness):
        wf.screen.is_job_starting.return_value = False
        wf.screen.is_on_job_panel.return_value = True

        assert wf.workflow._try_to_start_job() is False
        assert wf.screen.is_job_starting.call_count == 3

    def test_failure_and_left_panel_raises(self, wf: JobWorkflowHarness):
        wf.screen.is_job_starting.return_value = False
        wf.screen.is_on_job_panel.return_value = False

        with pytest.raises(UIElementNotFound) as excinfo:
            wf.workflow._try_to_start_job()

        assert excinfo.value.element_not_found is UIElement.JOB_SETUP_PANEL

    def test_message_send_failure_is_ignored(self, wf: JobWorkflowHarness):
        wf.send_message.side_effect = RuntimeError("Steam 后端不可用")
        wf.screen.is_job_starting.return_value = True

        assert wf.workflow._try_to_start_job() is True


class TestSetupWaitStartJob:
    """``setup_wait_start_job`` 的等待、发车与各种超时。"""

    def test_full_lobby_starts_immediately(self, wf: JobWorkflowHarness):
        wf.screen.get_job_setup_status.return_value = (True, 0, 3, 0)

        with patch.object(wf.workflow, "_try_to_start_job", return_value=True) as start:
            wf.workflow.setup_wait_start_job()

        wf.action.setup_job_panel.assert_called_once_with()
        start.assert_called_once_with()
        wf.send_message.assert_any_call(wf.workflow.config.msgOpenJobPanel)
        wf.send_message.assert_any_call(wf.workflow.config.msgTeamFull)
        # 满员消息整个等待过程只发送一次
        assert wf.send_message.mock_calls.count(call(wf.workflow.config.msgTeamFull)) == 1

    def test_starts_after_normal_delay(self, wf: JobWorkflowHarness):
        wf.workflow.lobby_tracker.start_immediately_when_full = False
        wf.workflow.lobby_tracker.normal_start_delay = 0
        wf.screen.get_job_setup_status.return_value = (True, 0, 1, 0)

        with patch.object(wf.workflow, "_try_to_start_job", return_value=True) as start:
            wf.workflow.setup_wait_start_job()

        start.assert_called_once_with()
        assert call(wf.workflow.config.msgTeamFull) not in wf.send_message.mock_calls

    def test_start_failure_continues_waiting(self, wf: JobWorkflowHarness):
        wf.workflow.lobby_tracker.start_immediately_when_full = False
        wf.workflow.lobby_tracker.normal_start_delay = 0
        wf.screen.get_job_setup_status.return_value = (True, 0, 1, 0)

        with patch.object(wf.workflow, "_try_to_start_job", side_effect=[False, True]) as start:
            wf.workflow.setup_wait_start_job()

        assert start.call_count == 2

    def test_open_job_panel_message_failure_is_ignored(self, wf: JobWorkflowHarness):
        wf.send_message.side_effect = RuntimeError("Steam 后端不可用")
        wf.screen.get_job_setup_status.return_value = (True, 0, 3, 0)

        with patch.object(wf.workflow, "_try_to_start_job", return_value=True):
            wf.workflow.setup_wait_start_job()  # 不应抛出异常

        wf.action.setup_job_panel.assert_called_once_with()

    def test_standby_player_raises_unexpected_game_state(self, wf: JobWorkflowHarness):
        wf.screen.get_job_setup_status.return_value = (True, 0, 1, 1)

        with pytest.raises(UnexpectedGameState) as excinfo:
            wf.workflow.setup_wait_start_job()

        assert excinfo.value.expected == GameState.JOB_PANEL_2
        assert excinfo.value.actual_state == GameState.BAD_JOB_PANEL_STANDBY_PLAYER

    def test_left_job_panel_raises_ui_element_not_found(self, wf: JobWorkflowHarness):
        wf.screen.get_job_setup_status.return_value = (False, -1, -1, -1)

        with pytest.raises(UIElementNotFound) as excinfo:
            wf.workflow.setup_wait_start_job()

        assert excinfo.value.element_not_found is UIElement.JOB_SETUP_PANEL
        assert wf.screen.get_job_setup_status.call_count == 2

    def test_wait_timeout_raises_teammate(self, wf: JobWorkflowHarness):
        wf.workflow.lobby_tracker.wait_timeout = 0
        wf.screen.get_job_setup_status.return_value = (True, 0, 0, 0)

        with pytest.raises(OperationTimeout) as excinfo:
            wf.workflow.setup_wait_start_job()

        assert excinfo.value.context is OperationTimeoutContext.TEAMMATE
        wf.send_message.assert_any_call(wf.workflow.config.msgMatchPanelTimeout)

    def test_joining_timeout_raises_player_join(self, wf: JobWorkflowHarness):
        wf.workflow.lobby_tracker.joining_timeout = 0
        wf.screen.get_job_setup_status.return_value = (True, 1, 0, 0)

        with pytest.raises(OperationTimeout) as excinfo:
            wf.workflow.setup_wait_start_job()

        assert excinfo.value.context is OperationTimeoutContext.PLAYER_JOIN
        wf.send_message.assert_any_call(wf.workflow.config.msgPlayerJoiningTimeout)


class TestHandlePostJobStart:
    """``handle_post_job_start`` 的加载与两次卡单。"""

    def test_happy_path_glitches_twice(self, wf: JobWorkflowHarness):
        with patch.object(wf.workflow, "wait_for_state", side_effect=[True, True]) as wait:
            wf.workflow.handle_post_job_start()

        assert wait.call_count == 2
        assert wf.process.suspend.call_count == 2
        wf.process.suspend.assert_called_with(wf.workflow.config.suspendGTATime)

    def test_panel_disappear_timeout(self, wf: JobWorkflowHarness):
        with (
            patch.object(wf.workflow, "wait_for_state", return_value=False),
            pytest.raises(OperationTimeout) as excinfo,
        ):
            wf.workflow.handle_post_job_start()

        assert excinfo.value.context is OperationTimeoutContext.JOB_SETUP_PANEL_DISAPPEAR
        wf.process.suspend.assert_not_called()

    def test_character_land_timeout_recovers_with_extra_glitch(self, wf: JobWorkflowHarness):
        with patch.object(wf.workflow, "wait_for_state", side_effect=[True, False, True]):
            wf.workflow.handle_post_job_start()

        # 面板消失卡单 + 落地超时补卡单 + 落地成功后再卡单
        assert wf.process.suspend.call_count == 3

    def test_character_land_timeout_twice_raises(self, wf: JobWorkflowHarness):
        with (
            patch.object(wf.workflow, "wait_for_state", side_effect=[True, False, False]),
            pytest.raises(OperationTimeout) as excinfo,
        ):
            wf.workflow.handle_post_job_start()

        assert excinfo.value.context is OperationTimeoutContext.CHARACTER_LAND
        assert wf.process.suspend.call_count == 2


class TestVerifyMissionStatusAfterGlitch:
    """``verify_mission_status_after_glitch``。"""

    def test_in_mission_sends_nothing(self, wf: JobWorkflowHarness):
        wf.screen.is_job_started.return_value = True

        wf.workflow.verify_mission_status_after_glitch()

        wf.send_message.assert_not_called()
        wf.screen.is_on_scoreboard.assert_not_called()

    def test_failed_mission_with_scoreboard_sends_message(self, wf: JobWorkflowHarness):
        wf.screen.is_job_started.return_value = False
        wf.screen.is_on_scoreboard.return_value = True

        wf.workflow.verify_mission_status_after_glitch()

        wf.send_message.assert_called_once_with(wf.workflow.config.msgDetectedSB)

    def test_failed_mission_without_scoreboard_only_warns(self, wf: JobWorkflowHarness):
        wf.screen.is_job_started.return_value = False
        wf.screen.is_on_scoreboard.return_value = False

        wf.workflow.verify_mission_status_after_glitch()

        wf.send_message.assert_not_called()
