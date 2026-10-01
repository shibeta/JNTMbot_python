"""``gta_automator.GTAAutomator`` 的单元测试。

``GTAAutomator`` 会在构造时创建 ``GameProcess`` / ``GameScreen`` / ``GameAction``
以及 4 个工作流，因此必须在构造前把 ``gta_automator`` 包命名空间中的这些符号全部
patch 成 ``MagicMock``，否则会触碰真实窗口、进程与虚拟手柄。
"""

from __future__ import annotations

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from gta_automator import GTAAutomator
from gta_automator.constant import BotMode, PlayerLevel
from gta_automator.exception import (
    GameState,
    OperationTimeout,
    OperationTimeoutContext,
    UIElement,
    UIElementNotFound,
    UnexpectedGameState,
)

# 构造 GTAAutomator 前必须被替换的符号
_CONSTRUCTED_SYMBOLS = (
    "GameProcess",
    "GameScreen",
    "GameAction",
    "LifecycleWorkflow",
    "OnlineWorkflow",
    "JobWorkflow",
    "GamepadSimulator",
)


@pytest.fixture
def make_automator(config, ocr_mock):
    """返回一个构造 GTAAutomator 的工厂，同时暴露所有被注入的 mock。"""

    def _make(gamepad=None):
        with ExitStack() as stack:
            patched = {name: stack.enter_context(patch(f"gta_automator.{name}")) for name in _CONSTRUCTED_SYMBOLS}
            send_steam = MagicMock(name="send_steam_message_func")
            push = MagicMock(name="push_message_func")
            automator = GTAAutomator(config, ocr_mock, send_steam, push, gamepad)

            mocks = SimpleNamespace(
                **patched,
                process=patched["GameProcess"].return_value,
                screen=patched["GameScreen"].return_value,
                action=patched["GameAction"].return_value,
                lifecycle=patched["LifecycleWorkflow"].return_value,
                online=patched["OnlineWorkflow"].return_value,
                job=patched["JobWorkflow"].return_value,
                gamepad=patched["GamepadSimulator"].return_value,
                send_steam=send_steam,
                push=push,
            )
        return automator, mocks

    return _make


@pytest.fixture
def harness(make_automator):
    return make_automator()


class TestInit:
    def test_creates_gamepad_when_not_provided(self, harness, config):
        _, mocks = harness

        mocks.GamepadSimulator.assert_called_once_with()
        mocks.GameAction.assert_called_once_with(mocks.gamepad, config)

    def test_uses_injected_gamepad(self, make_automator, config):
        injected = MagicMock(name="injected_gamepad")

        _, mocks = make_automator(gamepad=injected)

        mocks.GamepadSimulator.assert_not_called()
        mocks.GameAction.assert_called_once_with(injected, config)

    def test_workflows_are_wired_with_dependencies(self, harness, config, ocr_mock):
        _, mocks = harness

        mocks.GameProcess.assert_called_once_with()
        mocks.GameScreen.assert_called_once_with(ocr_mock, mocks.process)
        mocks.LifecycleWorkflow.assert_called_once_with(mocks.screen, mocks.action, mocks.process, config)
        mocks.OnlineWorkflow.assert_called_once_with(mocks.screen, mocks.action, mocks.process, config)
        mocks.JobWorkflow.assert_called_once_with(mocks.screen, mocks.action, mocks.process, config, mocks.send_steam)

    def test_workflow_attributes_are_the_constructed_instances(self, harness):
        automator, mocks = harness

        assert automator.lifecycle_workflow is mocks.lifecycle
        assert automator.online_workflow is mocks.online
        assert automator.job_workflow is mocks.job

    def test_initial_state_from_config(self, harness, config):
        automator, mocks = harness

        assert automator.bot_mode is BotMode.DRE
        assert automator.push_message is mocks.push
        assert automator.bad_sport_check_interval == config.badSportCheckInterval
        assert automator.recovery_on_dodgy_player == config.autoReduceBadSportOnDodgyPlayer
        assert automator._recovery_total_duration == config.recoveryTotalDuration
        assert automator._recovery_chunk_size == config.recoveryChunkSize
        assert automator._recovery_target_timestamp is None
        assert automator._last_clean_player_verified_timestamp is None


class TestIsInRecoveryMode:
    def test_false_in_dre_mode(self, harness):
        automator, _ = harness

        assert automator.is_in_recovery_mode() is False

    def test_true_in_recovery_mode(self, harness):
        automator, _ = harness
        automator.bot_mode = BotMode.RECOVERY

        assert automator.is_in_recovery_mode() is True


class TestSetup:
    def test_game_ready_does_not_restart(self, harness):
        automator, mocks = harness
        mocks.lifecycle.is_game_ready.return_value = True

        assert automator.setup() is False
        mocks.lifecycle.restart.assert_not_called()

    def test_game_not_ready_restarts(self, harness):
        automator, mocks = harness
        mocks.lifecycle.is_game_ready.return_value = False

        assert automator.setup() is True
        mocks.lifecycle.restart.assert_called_once_with()


class TestRunOneCycle:
    def test_dre_mode_dispatches_with_restart_flag(self, harness):
        automator, _ = harness
        automator.bot_mode = BotMode.DRE
        with (
            patch.object(automator, "setup", return_value=True) as setup,
            patch.object(automator, "_run_dre_cycle") as run_dre,
            patch.object(automator, "_run_recovery_cycle") as run_recovery,
        ):
            automator.run_one_cycle()

        setup.assert_called_once_with()
        run_dre.assert_called_once_with(True)
        run_recovery.assert_not_called()

    def test_recovery_mode_dispatches_to_recovery(self, harness):
        automator, _ = harness
        automator.bot_mode = BotMode.RECOVERY
        with (
            patch.object(automator, "setup", return_value=False),
            patch.object(automator, "_run_dre_cycle") as run_dre,
            patch.object(automator, "_run_recovery_cycle") as run_recovery,
        ):
            automator.run_one_cycle()

        run_dre.assert_not_called()
        run_recovery.assert_called_once_with()


class TestShouldCheckBadSport:
    def test_true_when_game_restarted(self, harness):
        automator, _ = harness
        automator._last_clean_player_verified_timestamp = 0.0

        assert automator._should_check_bad_sport(True) is True

    def test_true_on_first_run(self, harness):
        automator, _ = harness

        assert automator._should_check_bad_sport(False) is True

    def test_true_when_interval_exceeded(self, harness, fake_clock):
        automator, _ = harness
        automator._last_clean_player_verified_timestamp = fake_clock.now - automator.bad_sport_check_interval - 10

        assert automator._should_check_bad_sport(False) is True

    def test_false_when_interval_not_exceeded(self, harness, fake_clock):
        automator, _ = harness
        automator._last_clean_player_verified_timestamp = fake_clock.now

        assert automator._should_check_bad_sport(False) is False


class TestPerformBadSportCheck:
    def test_clean_player_updates_timestamp(self, harness, fake_clock):
        automator, mocks = harness
        mocks.online.get_bad_sport_level.return_value = PlayerLevel.CLEAN
        fake_clock.step = 0
        fake_clock.set(5000.0)

        automator._perform_bad_sport_check()

        assert automator._last_clean_player_verified_timestamp == 5000.0

    def test_dodgy_player_raises(self, harness):
        automator, mocks = harness
        mocks.online.get_bad_sport_level.return_value = PlayerLevel.DODGY

        with pytest.raises(UnexpectedGameState) as excinfo:
            automator._perform_bad_sport_check()

        assert excinfo.value.expected is GameState.CLEAN_PLAYER_LEVEL
        assert excinfo.value.actual_state is GameState.DODGY_PLAYER_LEVEL
        mocks.lifecycle.shutdown.assert_not_called()
        assert automator._last_clean_player_verified_timestamp is None

    def test_bad_sport_player_raises(self, harness):
        automator, mocks = harness
        mocks.online.get_bad_sport_level.return_value = PlayerLevel.BAD_SPORT

        with pytest.raises(UnexpectedGameState) as excinfo:
            automator._perform_bad_sport_check()

        assert excinfo.value.actual_state is GameState.BAD_SPORT_LEVEL
        mocks.lifecycle.shutdown.assert_not_called()

    def test_unknown_level_raises_bad_sport(self, harness):
        automator, mocks = harness
        mocks.online.get_bad_sport_level.return_value = PlayerLevel.UNKNOWN

        with pytest.raises(UnexpectedGameState) as excinfo:
            automator._perform_bad_sport_check()

        assert excinfo.value.actual_state is GameState.BAD_SPORT_LEVEL

    def test_indicator_not_found_shuts_down_and_raises(self, harness):
        automator, mocks = harness
        mocks.online.get_bad_sport_level.side_effect = UIElementNotFound(UIElement.BAD_SPORT_LEVEL_INDICATOR)

        with pytest.raises(UIElementNotFound):
            automator._perform_bad_sport_check()

        mocks.lifecycle.shutdown.assert_called_once_with()

    def test_other_ui_element_not_found_does_not_shut_down(self, harness):
        automator, mocks = harness
        mocks.online.get_bad_sport_level.side_effect = UIElementNotFound(UIElement.PAUSE_MENU)

        with pytest.raises(UIElementNotFound):
            automator._perform_bad_sport_check()

        mocks.lifecycle.shutdown.assert_not_called()


class TestRunDreCycle:
    def _disable_bad_sport_check(self, automator):
        return patch.object(automator, "_should_check_bad_sport", return_value=False)

    def test_happy_path_order_with_bad_sport_check(self, harness):
        automator, mocks = harness
        manager = MagicMock()
        perform_check = MagicMock()
        with (
            patch.object(automator, "_should_check_bad_sport", return_value=True),
            patch.object(automator, "_perform_bad_sport_check", perform_check),
            patch.object(automator, "play_dre_job") as play_job,
        ):
            manager.attach_mock(perform_check, "_perform_bad_sport_check")
            manager.attach_mock(mocks.online.start_new_match, "start_new_match")
            manager.attach_mock(mocks.job.wait_for_respawn_in_agency, "wait_for_respawn_in_agency")

            automator._run_dre_cycle(True)

        assert [name for name, _, _ in manager.mock_calls] == [
            "_perform_bad_sport_check",
            "start_new_match",
            "wait_for_respawn_in_agency",
        ]
        play_job.assert_called_once_with()

    def test_happy_path_skips_check_when_not_needed(self, harness):
        automator, mocks = harness
        manager = MagicMock()
        manager.attach_mock(mocks.online.start_new_match, "start_new_match")
        manager.attach_mock(mocks.job.wait_for_respawn_in_agency, "wait_for_respawn_in_agency")

        with self._disable_bad_sport_check(automator), patch.object(automator, "play_dre_job"):
            automator._run_dre_cycle(False)

        assert [name for name, _, _ in manager.mock_calls] == ["start_new_match", "wait_for_respawn_in_agency"]
        mocks.online.get_bad_sport_level.assert_not_called()

    def test_dodgy_player_switches_to_recovery(self, harness):
        automator, mocks = harness
        automator.recovery_on_dodgy_player = True
        with (
            patch.object(automator, "_should_check_bad_sport", return_value=True),
            patch.object(
                automator,
                "_perform_bad_sport_check",
                side_effect=UnexpectedGameState(GameState.CLEAN_PLAYER_LEVEL, GameState.DODGY_PLAYER_LEVEL),
            ),
            patch.object(automator, "play_dre_job") as play_job,
        ):
            automator._run_dre_cycle(True)

        assert automator.bot_mode is BotMode.RECOVERY
        assert automator._recovery_target_timestamp is None
        mocks.push.assert_called_once()
        assert "问题玩家" in mocks.push.call_args.args[0]
        mocks.online.start_new_match.assert_not_called()
        mocks.lifecycle.shutdown.assert_not_called()
        play_job.assert_not_called()

    def test_dodgy_player_shuts_down_when_recovery_disabled(self, harness):
        automator, mocks = harness
        automator.recovery_on_dodgy_player = False
        with (
            patch.object(automator, "_should_check_bad_sport", return_value=True),
            patch.object(
                automator,
                "_perform_bad_sport_check",
                side_effect=UnexpectedGameState(GameState.CLEAN_PLAYER_LEVEL, GameState.DODGY_PLAYER_LEVEL),
            ),
            pytest.raises(UnexpectedGameState) as excinfo,
        ):
            automator._run_dre_cycle(True)

        assert excinfo.value.actual_state is GameState.DODGY_PLAYER_LEVEL
        mocks.lifecycle.shutdown.assert_called_once_with()
        assert automator.bot_mode is BotMode.DRE

    def test_bad_sport_player_shuts_down(self, harness):
        automator, mocks = harness
        automator.recovery_on_dodgy_player = True
        with (
            patch.object(automator, "_should_check_bad_sport", return_value=True),
            patch.object(
                automator,
                "_perform_bad_sport_check",
                side_effect=UnexpectedGameState(GameState.CLEAN_PLAYER_LEVEL, GameState.BAD_SPORT_LEVEL),
            ),
            pytest.raises(UnexpectedGameState) as excinfo,
        ):
            automator._run_dre_cycle(True)

        assert excinfo.value.actual_state is GameState.BAD_SPORT_LEVEL
        mocks.lifecycle.shutdown.assert_called_once_with()
        assert automator.bot_mode is BotMode.DRE

    def test_switch_session_failure_shuts_down(self, harness):
        automator, mocks = harness
        mocks.online.start_new_match.side_effect = UnexpectedGameState(
            {GameState.ONLINE_FREEMODE, GameState.IN_MISSION}, GameState.UNKNOWN
        )

        with self._disable_bad_sport_check(automator), pytest.raises(UnexpectedGameState):
            automator._run_dre_cycle(False)

        mocks.lifecycle.shutdown.assert_called_once_with()

    def test_other_unexpected_state_does_not_shut_down(self, harness):
        automator, mocks = harness
        mocks.online.start_new_match.side_effect = UnexpectedGameState(GameState.ONLINE_PAUSED, GameState.UNKNOWN)

        with self._disable_bad_sport_check(automator), pytest.raises(UnexpectedGameState):
            automator._run_dre_cycle(False)

        mocks.lifecycle.shutdown.assert_not_called()

    def test_respawn_timeout_shuts_down(self, harness):
        automator, mocks = harness
        mocks.job.wait_for_respawn_in_agency.side_effect = OperationTimeout(OperationTimeoutContext.RESPAWN_IN_AGENCY)

        with self._disable_bad_sport_check(automator), pytest.raises(OperationTimeout):
            automator._run_dre_cycle(False)

        mocks.lifecycle.shutdown.assert_called_once_with()

    def test_other_operation_timeout_does_not_shut_down(self, harness):
        automator, mocks = harness
        mocks.job.wait_for_respawn_in_agency.side_effect = OperationTimeout(
            OperationTimeoutContext.JOB_SETUP_PANEL_OPEN
        )

        with self._disable_bad_sport_check(automator), pytest.raises(OperationTimeout):
            automator._run_dre_cycle(False)

        mocks.lifecycle.shutdown.assert_not_called()


class TestPlayDreJob:
    def test_happy_path_order(self, harness):
        automator, mocks = harness
        manager = MagicMock()
        steps = (
            "navigate_from_bed_to_job_point",
            "enter_and_wait_for_job_panel",
            "setup_wait_start_job",
            "handle_post_job_start",
            "verify_mission_status_after_glitch",
        )
        for step in steps:
            manager.attach_mock(getattr(mocks.job, step), step)

        automator.play_dre_job()

        assert [name for name, _, _ in manager.mock_calls] == list(steps)

    def test_job_panel_timeout_recovers_to_online_mode(self, harness):
        automator, mocks = harness
        mocks.job.enter_and_wait_for_job_panel.side_effect = OperationTimeout(
            OperationTimeoutContext.JOB_SETUP_PANEL_OPEN
        )
        mocks.lifecycle.check_if_in_onlinemode.return_value = True

        automator.play_dre_job()

        mocks.job.exit_job_panel.assert_called_once_with()
        mocks.lifecycle.shutdown.assert_not_called()
        mocks.job.setup_wait_start_job.assert_not_called()

    def test_job_panel_timeout_not_online_shuts_down(self, harness):
        automator, mocks = harness
        mocks.job.enter_and_wait_for_job_panel.side_effect = OperationTimeout(
            OperationTimeoutContext.JOB_SETUP_PANEL_OPEN
        )
        mocks.lifecycle.check_if_in_onlinemode.return_value = False

        with pytest.raises(OperationTimeout):
            automator.play_dre_job()

        mocks.lifecycle.shutdown.assert_called_once_with()

    def test_setup_wait_start_job_timeout_exits_panel(self, harness):
        automator, mocks = harness
        mocks.job.setup_wait_start_job.side_effect = OperationTimeout(OperationTimeoutContext.TEAMMATE)

        automator.play_dre_job()

        mocks.job.exit_job_panel.assert_called_once_with()
        mocks.job.handle_post_job_start.assert_not_called()

    def test_standby_player_exits_panel(self, harness):
        automator, mocks = harness
        mocks.job.setup_wait_start_job.side_effect = UnexpectedGameState(
            GameState.JOB_PANEL_2, GameState.BAD_JOB_PANEL_STANDBY_PLAYER
        )

        automator.play_dre_job()

        mocks.job.exit_job_panel.assert_called_once_with()
        mocks.job.handle_post_job_start.assert_not_called()

    def test_other_unexpected_state_propagates(self, harness):
        automator, mocks = harness
        mocks.job.setup_wait_start_job.side_effect = UnexpectedGameState(GameState.ON, GameState.OFF)

        with pytest.raises(UnexpectedGameState):
            automator.play_dre_job()

        mocks.job.exit_job_panel.assert_not_called()

    def test_job_setup_panel_missing_exits_panel(self, harness):
        automator, mocks = harness
        mocks.job.setup_wait_start_job.side_effect = UIElementNotFound(UIElement.JOB_SETUP_PANEL)

        automator.play_dre_job()

        mocks.job.exit_job_panel.assert_called_once_with()

    def test_other_ui_element_missing_propagates(self, harness):
        automator, mocks = harness
        mocks.job.setup_wait_start_job.side_effect = UIElementNotFound(UIElement.PAUSE_MENU)

        with pytest.raises(UIElementNotFound):
            automator.play_dre_job()

        mocks.job.exit_job_panel.assert_not_called()

    @pytest.mark.parametrize(
        "context",
        [
            OperationTimeoutContext.JOB_SETUP_PANEL_DISAPPEAR,
            OperationTimeoutContext.CHARACTER_LAND,
        ],
    )
    def test_post_job_start_timeout_glitches_and_switches_session(self, harness, context):
        automator, mocks = harness
        mocks.job.handle_post_job_start.side_effect = OperationTimeout(context)

        automator.play_dre_job()

        mocks.online.glitch_single_player_session.assert_called_once_with()
        mocks.online.start_new_match.assert_called_once_with()
        mocks.job.wait_for_respawn_in_agency.assert_called_once_with()
        mocks.job.verify_mission_status_after_glitch.assert_not_called()
        mocks.lifecycle.shutdown.assert_not_called()

    def test_post_job_start_timeout_switch_session_failure_shuts_down(self, harness):
        automator, mocks = harness
        mocks.job.handle_post_job_start.side_effect = OperationTimeout(OperationTimeoutContext.CHARACTER_LAND)
        mocks.online.start_new_match.side_effect = UnexpectedGameState(
            {GameState.ONLINE_FREEMODE, GameState.IN_MISSION}, GameState.UNKNOWN
        )

        with pytest.raises(UnexpectedGameState):
            automator.play_dre_job()

        mocks.lifecycle.shutdown.assert_called_once_with()
        mocks.job.verify_mission_status_after_glitch.assert_not_called()

    def test_post_job_start_timeout_respawn_timeout_shuts_down(self, harness):
        automator, mocks = harness
        mocks.job.handle_post_job_start.side_effect = OperationTimeout(
            OperationTimeoutContext.JOB_SETUP_PANEL_DISAPPEAR
        )
        mocks.job.wait_for_respawn_in_agency.side_effect = OperationTimeout(OperationTimeoutContext.RESPAWN_IN_AGENCY)

        with pytest.raises(OperationTimeout):
            automator.play_dre_job()

        mocks.lifecycle.shutdown.assert_called_once_with()

    def test_other_post_job_start_timeout_is_reraised(self, harness):
        """只有 JOB_SETUP_PANEL_DISAPPEAR / CHARACTER_LAND 才走卡单切战局，其他超时直接向上抛。"""
        automator, mocks = harness
        mocks.job.handle_post_job_start.side_effect = OperationTimeout(OperationTimeoutContext.TEAMMATE)

        with pytest.raises(OperationTimeout) as excinfo:
            automator.play_dre_job()

        assert excinfo.value.context is OperationTimeoutContext.TEAMMATE
        mocks.online.glitch_single_player_session.assert_not_called()
        mocks.online.start_new_match.assert_not_called()
        mocks.job.verify_mission_status_after_glitch.assert_not_called()


class TestRunRecoveryCycle:
    def test_first_run_initializes_timer_and_afk(self, harness, config, fake_clock):
        automator, mocks = harness
        fake_clock.step = 0
        mocks.online.get_bad_sport_level.return_value = PlayerLevel.CLEAN

        automator._run_recovery_cycle()

        assert automator._recovery_target_timestamp == fake_clock.now + config.recoveryTotalDuration
        mocks.online.afk.assert_called_once_with(config.recoveryChunkSize)

    def test_dodgy_player_still_afk(self, harness, config, fake_clock):
        automator, mocks = harness
        fake_clock.step = 0
        mocks.online.get_bad_sport_level.return_value = PlayerLevel.DODGY

        automator._run_recovery_cycle()

        mocks.online.afk.assert_called_once_with(config.recoveryChunkSize)

    def test_chunk_clamped_to_remaining_time(self, harness, fake_clock):
        automator, mocks = harness
        fake_clock.step = 0
        automator._recovery_target_timestamp = fake_clock.now + 100
        mocks.online.get_bad_sport_level.return_value = PlayerLevel.CLEAN

        automator._run_recovery_cycle()

        mocks.online.afk.assert_called_once_with(100)

    def test_completion_switches_back_to_dre(self, harness, fake_clock):
        automator, mocks = harness
        fake_clock.step = 0
        automator.bot_mode = BotMode.RECOVERY
        automator._recovery_target_timestamp = fake_clock.now - 1

        automator._run_recovery_cycle()

        assert automator.bot_mode is BotMode.DRE
        assert automator._recovery_target_timestamp is None
        mocks.push.assert_called_once()
        mocks.online.afk.assert_not_called()
        mocks.online.get_bad_sport_level.assert_not_called()

    def test_bad_sport_player_shuts_down(self, harness, fake_clock):
        automator, mocks = harness
        fake_clock.step = 0
        automator.bot_mode = BotMode.RECOVERY
        automator._recovery_target_timestamp = fake_clock.now + 1000
        mocks.online.get_bad_sport_level.return_value = PlayerLevel.BAD_SPORT

        with pytest.raises(UnexpectedGameState) as excinfo:
            automator._run_recovery_cycle()

        assert excinfo.value.expected is GameState.CLEAN_PLAYER_LEVEL
        assert excinfo.value.actual_state is GameState.BAD_SPORT_LEVEL
        mocks.lifecycle.shutdown.assert_called_once_with()
        assert automator._recovery_target_timestamp is None
        mocks.online.afk.assert_not_called()

    def test_indicator_not_found_shuts_down(self, harness, fake_clock):
        automator, mocks = harness
        fake_clock.step = 0
        automator.bot_mode = BotMode.RECOVERY
        automator._recovery_target_timestamp = fake_clock.now + 1000
        mocks.online.get_bad_sport_level.side_effect = UIElementNotFound(UIElement.BAD_SPORT_LEVEL_INDICATOR)

        with pytest.raises(UIElementNotFound):
            automator._run_recovery_cycle()

        mocks.lifecycle.shutdown.assert_called_once_with()

    def test_other_ui_element_not_found_does_not_shut_down(self, harness, fake_clock):
        automator, mocks = harness
        fake_clock.step = 0
        automator.bot_mode = BotMode.RECOVERY
        automator._recovery_target_timestamp = fake_clock.now + 1000
        mocks.online.get_bad_sport_level.side_effect = UIElementNotFound(UIElement.PAUSE_MENU)

        with pytest.raises(UIElementNotFound):
            automator._run_recovery_cycle()

        mocks.lifecycle.shutdown.assert_not_called()

    def test_afk_failure_restores_chunk_to_target(self, harness, config, fake_clock):
        automator, mocks = harness
        fake_clock.step = 0
        automator.bot_mode = BotMode.RECOVERY
        automator._recovery_target_timestamp = fake_clock.now + 100000
        target_before = automator._recovery_target_timestamp
        mocks.online.get_bad_sport_level.return_value = PlayerLevel.CLEAN
        mocks.online.afk.side_effect = UnexpectedGameState(
            {GameState.ONLINE_FREEMODE, GameState.IN_MISSION}, GameState.UNKNOWN
        )

        with pytest.raises(UnexpectedGameState):
            automator._run_recovery_cycle()

        assert automator._recovery_target_timestamp == target_before + config.recoveryChunkSize
        assert automator.bot_mode is BotMode.RECOVERY
