"""``gta_automator.game_action`` 的单元测试。

``GameAction`` 只是把游戏内动作翻译成手柄指令，因此这里用一个 ``MagicMock`` 作为
虚拟手柄，断言按键、摇杆方向与持续时间序列是否与预期一致。
"""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from gamepad_utils import Button, JoystickDirection
from gta_automator.game_action import GameAction


@pytest.fixture
def gamepad() -> MagicMock:
    return MagicMock(name="GamepadSimulator")


@pytest.fixture
def action(gamepad: MagicMock, config) -> GameAction:
    return GameAction(gamepad, config)


class TestWalkAndRun:
    """八个移动方法对应的摇杆方向。"""

    @pytest.mark.parametrize(
        ("method_name", "direction"),
        [
            ("walk_left", JoystickDirection.HALF_LEFT),
            ("walk_right", JoystickDirection.HALF_RIGHT),
            ("walk_forward", JoystickDirection.HALF_UP),
            ("walk_backward", JoystickDirection.HALF_DOWN),
            ("run_left", JoystickDirection.FULL_LEFT),
            ("run_right", JoystickDirection.FULL_RIGHT),
            ("run_forward", JoystickDirection.FULL_UP),
            ("run_backward", JoystickDirection.FULL_DOWN),
        ],
    )
    def test_joystick_direction_and_duration(self, action: GameAction, gamepad: MagicMock, method_name, direction):
        getattr(action, method_name)(1500)

        gamepad.hold_left_joystick.assert_called_once_with(direction, 1500)
        gamepad.click_button.assert_not_called()


class TestMenuNavigation:
    """菜单操作按下的按键与等待时长。"""

    @pytest.mark.parametrize(
        ("method_name", "button", "delay"),
        [
            ("confirm", Button.A, 1),
            ("back", Button.B, 1),
            ("up", Button.DPAD_UP, 0.5),
            ("down", Button.DPAD_DOWN, 0.5),
            ("left", Button.DPAD_LEFT, 0.5),
            ("right", Button.DPAD_RIGHT, 0.5),
            ("previous_page", Button.LEFT_SHOULDER, 2),
            ("next_page", Button.RIGHT_SHOULDER, 2),
            ("open_or_close_pause_menu", Button.MENU, 2),
            ("open_onlinemode_info_panel", Button.DPAD_DOWN, 1),
        ],
    )
    def test_button_and_delay(self, action: GameAction, gamepad: MagicMock, no_sleep, method_name, button, delay):
        getattr(action, method_name)()

        gamepad.click_button.assert_called_once_with(button)
        assert call(delay) in no_sleep.call_args_list

    def test_navigate_to_storymode_tab_in_mainmenu(self, action: GameAction, gamepad: MagicMock):
        action.navigate_to_storymode_tab_in_mainmenu()

        assert gamepad.click_button.call_args_list == [call(Button.RIGHT_SHOULDER)] * 3

    def test_navigate_to_online_tab_in_storymode(self, action: GameAction, gamepad: MagicMock):
        action.navigate_to_online_tab_in_storymode()

        assert gamepad.click_button.call_args_list == [
            call(Button.RIGHT_SHOULDER),
            call(Button.RIGHT_SHOULDER),
            call(Button.RIGHT_SHOULDER),
            call(Button.RIGHT_SHOULDER),
            call(Button.RIGHT_SHOULDER),
            call(Button.A),
            call(Button.DPAD_UP),
            call(Button.A),
        ]

    def test_navigate_to_switch_session_tab_in_online_pausemenu(self, action: GameAction, gamepad: MagicMock):
        action.navigate_to_switch_session_tab_in_online_pausemenu()

        assert gamepad.click_button.call_args_list == [
            call(Button.RIGHT_SHOULDER),
            call(Button.A),
            call(Button.DPAD_UP),
            call(Button.DPAD_UP),
            call(Button.DPAD_UP),
            call(Button.DPAD_UP),
            call(Button.DPAD_UP),
            call(Button.A),
        ]

    def test_navigate_to_player_list_tab_in_online_pausemenu(self, action: GameAction, gamepad: MagicMock):
        action.navigate_to_player_list_tab_in_online_pausemenu()

        assert gamepad.click_button.call_args_list == [
            call(Button.RIGHT_SHOULDER),
            call(Button.A),
            call(Button.DPAD_DOWN),
            call(Button.DPAD_DOWN),
            call(Button.DPAD_DOWN),
            call(Button.DPAD_DOWN),
            call(Button.A),
        ]

    def test_enter_invite_only_session(self, action: GameAction, gamepad: MagicMock):
        action.enter_invite_only_session()

        assert gamepad.click_button.call_args_list == [call(Button.DPAD_DOWN), call(Button.A), call(Button.A)]


class TestJobPointNavigation:
    def test_go_job_point_from_bed_by_bot_owner_waits(self, action: GameAction, gamepad: MagicMock, no_sleep):
        result = action.go_job_point_from_bed_by_bot_owner()

        assert result is None
        assert call(60) in no_sleep.call_args_list
        gamepad.hold_left_joystick.assert_not_called()

    def test_go_job_point_from_bed_uses_config_timings(self, action: GameAction, gamepad: MagicMock, config):
        action.go_job_point_from_bed()

        assert gamepad.hold_left_joystick.call_args_list == [
            call(JoystickDirection.FULL_LEFTUP, config.walkToPillarTime),
            call(JoystickDirection.FULL_RIGHT, config.walkToBedroomEntranceTime),
            call(JoystickDirection.HALF_RIGHTDOWN, config.exitBedroomDoorBackTime),
            call(JoystickDirection.HALF_RIGHTUP, config.exitBedroomDoorForwardTime),
            call(JoystickDirection.FULL_RIGHT, config.walkToStairwellTime),
            call(JoystickDirection.FULL_UP, config.enterStairwellTime),
            call(JoystickDirection.FULL_DOWN, config.goDownFirstStairFlightTime),
            call(JoystickDirection.FULL_RIGHTUP, config.crossStairLandingTime),
            call(JoystickDirection.FULL_LEFT, config.goDownSecondStairFlightTime),
            call(JoystickDirection.HALF_LEFTDOWN, config.exitStairwellTime),
            call(JoystickDirection.FULL_LEFTDOWN, config.crossAisleTime),
        ]

    def test_launch_job_setup_panel(self, action: GameAction, gamepad: MagicMock):
        action.launch_job_setup_panel()

        gamepad.click_button.assert_called_once_with(Button.DPAD_RIGHT, 110)

    def test_setup_job_panel(self, action: GameAction, gamepad: MagicMock):
        action.setup_job_panel()

        assert gamepad.click_button.call_args_list == [
            call(Button.DPAD_UP),
            call(Button.A),
            call(Button.DPAD_LEFT),
            call(Button.DPAD_UP),
        ]

    def test_exit_job_panel_from_first_page(self, action: GameAction, gamepad: MagicMock):
        action.exit_job_panel_from_first_page()

        assert gamepad.click_button.call_args_list == [call(Button.B), call(Button.A)]

    def test_exit_job_panel_from_second_page(self, action: GameAction, gamepad: MagicMock):
        action.exit_job_panel_from_second_page()

        assert gamepad.click_button.call_args_list == [call(Button.B), call(Button.B), call(Button.A)]

    def test_action_uses_injected_gamepad(self, config):
        gamepad = MagicMock(name="InjectedGamepad")
        action = GameAction(gamepad, config)

        assert action.gamepad is gamepad
        assert action.config is config
