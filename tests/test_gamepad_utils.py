"""``gamepad_utils`` 的单元测试。

虚拟手柄会真实地操纵 ViGEmBus 驱动，因此这里把 ``vgamepad.VX360Gamepad``、
``subprocess`` 等全部替换成 mock；驱动安装流程通过 patch ``input``/``install_driver``
验证，绝不真的执行 ``msiexec`` 或重启程序。
"""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

import gamepad_utils
from gamepad_utils import (
    Button,
    GamepadError,
    GamepadInitError,
    GamepadSimulator,
    JoystickDirection,
    Macro,
    MacroEvent,
    TriggerPressure,
)

PAD_METHODS = (
    "reset",
    "update",
    "press_button",
    "release_button",
    "left_joystick_float",
    "right_joystick_float",
    "left_trigger_float",
    "right_trigger_float",
)

# 在 pad_factory 打补丁之前先保存真实类，供 MagicMock(spec=...) 使用
REAL_GAMEPAD_CLASS = gamepad_utils.vg.VX360Gamepad


@pytest.fixture
def pad_factory():
    """拦截 ``vgamepad.VX360Gamepad`` 的创建，返回创建用的工厂 mock。"""
    with patch.object(gamepad_utils.vg, "VX360Gamepad") as factory:
        yield factory


@pytest.fixture
def sim(pad_factory) -> GamepadSimulator:
    """已初始化的 GamepadSimulator，其 pad 为 mock。

    MagicMock 默认没有 ``__name__``，而源码在重试日志中会访问它，这里补上以避免
    在测试重试逻辑时抛出无关的 AttributeError。
    """
    instance = GamepadSimulator()
    for method_name in PAD_METHODS:
        getattr(instance.pad, method_name).__name__ = method_name
    # 清除初始化期间（reset + 唤醒 A 键）产生的调用记录，方便断言
    instance.pad.reset_mock()
    return instance


class TestConstants:
    """手柄按键与方向常量映射。"""

    def test_button_matches_vgamepad_values(self):
        assert Button.A == gamepad_utils.vg.XUSB_BUTTON.XUSB_GAMEPAD_A
        assert Button.B == gamepad_utils.vg.XUSB_BUTTON.XUSB_GAMEPAD_B
        assert Button.START == gamepad_utils.vg.XUSB_BUTTON.XUSB_GAMEPAD_START
        assert Button.MENU == Button.START
        assert Button.SELECT == Button.BACK

    def test_joystick_directions(self):
        assert JoystickDirection.CENTER == (0.0, 0.0)
        assert JoystickDirection.FULL_UP == (0.0, 1.0)
        assert JoystickDirection.FULL_LEFTDOWN == (-1.0, -1.0)
        assert JoystickDirection.HALF_LEFT == (-0.7, 0.0)

    def test_trigger_pressures(self):
        assert TriggerPressure.released == 0.0
        assert TriggerPressure.full == 1.0

    def test_exception_hierarchy(self):
        assert issubclass(GamepadInitError, GamepadError)
        assert issubclass(GamepadError, Exception)


class TestDriverPath:
    """ViGEmBus 驱动安装包路径查找。"""

    def test_returns_first_existing_path(self, monkeypatch, tmp_path):
        missing = tmp_path / "missing.msi"
        existing = tmp_path / "driver.msi"
        existing.write_bytes(b"msi")
        monkeypatch.setattr(gamepad_utils, "VIGEMBUS_DRIVER_PATH_LIST", (missing, existing))

        assert gamepad_utils.get_vbus_driver_path() == existing

    def test_returns_none_when_nothing_exists(self, monkeypatch, tmp_path):
        monkeypatch.setattr(gamepad_utils, "VIGEMBUS_DRIVER_PATH_LIST", (tmp_path / "a.msi", tmp_path / "b.msi"))

        assert gamepad_utils.get_vbus_driver_path() is None


class TestInstallDriver:
    """驱动安装（``msiexec``）的返回值处理。"""

    @pytest.mark.parametrize("returncode", [0, 3010])
    def test_success_returncodes(self, returncode):
        with patch.object(gamepad_utils.subprocess, "run") as run:
            run.return_value = MagicMock(returncode=returncode)

            assert gamepad_utils.install_driver("driver.msi") is True
            run.assert_called_once_with(["msiexec", "/package", "driver.msi"], shell=False)

    def test_unexpected_returncode_returns_false(self):
        with patch.object(gamepad_utils.subprocess, "run") as run:
            run.return_value = MagicMock(returncode=1603)

            assert gamepad_utils.install_driver("driver.msi") is False

    def test_exception_returns_false(self):
        with patch.object(gamepad_utils.subprocess, "run") as run:
            run.side_effect = OSError("找不到 msiexec")

            assert gamepad_utils.install_driver("driver.msi") is False


class TestSetupVigembusDriver:
    """驱动安装引导流程（永远不返回，只会抛异常或重启程序）。"""

    def test_user_cancels(self, safe_input, monkeypatch):
        safe_input.return_value = "n"
        install = MagicMock(name="install_driver")
        monkeypatch.setattr(gamepad_utils, "install_driver", install)

        with pytest.raises(GamepadInitError, match="用户取消"):
            gamepad_utils.setup_vigembus_driver()

        install.assert_not_called()

    def test_driver_file_not_found(self, safe_input, monkeypatch):
        safe_input.return_value = "y"
        monkeypatch.setattr(gamepad_utils, "get_vbus_driver_path", MagicMock(return_value=None))

        with pytest.raises(GamepadInitError, match="未找到 ViGEmBus 驱动安装文件"):
            gamepad_utils.setup_vigembus_driver()

    def test_install_success_restarts_program(self, safe_input, monkeypatch):
        safe_input.return_value = "y"
        monkeypatch.setattr(gamepad_utils, "get_vbus_driver_path", MagicMock(return_value="driver.msi"))
        monkeypatch.setattr(gamepad_utils, "install_driver", MagicMock(return_value=True))
        restart = MagicMock(name="restart_program")
        monkeypatch.setattr(gamepad_utils, "restart_program", restart)

        with pytest.raises(GamepadInitError, match="重启程序失败"):
            gamepad_utils.setup_vigembus_driver()

        restart.assert_called_once_with()

    def test_install_failure(self, safe_input, monkeypatch):
        safe_input.return_value = "y"
        monkeypatch.setattr(gamepad_utils, "get_vbus_driver_path", MagicMock(return_value="driver.msi"))
        monkeypatch.setattr(gamepad_utils, "install_driver", MagicMock(return_value=False))

        with pytest.raises(GamepadInitError, match="ViGEmBus 驱动安装失败"):
            gamepad_utils.setup_vigembus_driver()


class TestMacroEvent:
    """单个宏事件的比较与表示。"""

    def test_repr(self):
        event = MacroEvent(time_ms=120, action_name="press_button", params=["A"])

        assert repr(event) == "TimelineEvent(time=120ms, action='press_button', params=['A'])"

    def test_ordering_by_time(self):
        early = MacroEvent(10, "a", [])
        late = MacroEvent(20, "b", [])

        assert early < late
        assert early == MacroEvent(10, "other", [99])
        assert late > early
        assert early <= MacroEvent(10, "a", [])
        assert late >= early

    def test_comparison_with_other_types_is_not_implemented(self):
        event = MacroEvent(10, "a", [])

        assert event.__eq__(5) is NotImplemented
        assert event.__lt__("x") is NotImplemented
        assert event != 5


class TestMacroContainer:
    """Macro 的容器行为与时间轴操作。"""

    def test_empty_macro(self):
        macro = Macro()

        assert len(macro) == 0
        assert list(macro) == []
        assert macro.get_duration_ms() == 0
        assert repr(macro) == "<Macro with 0 events, duration: 0ms>"

    def test_add_action_sorts_and_supports_chaining(self):
        macro = Macro()

        result = macro.add_action(30, "c", []).add_action(10, "a", []).add_action(20, "b", [])

        assert result is macro
        assert [event.time_ms for event in macro] == [10, 20, 30]
        assert [event.action_name for event in macro] == ["a", "b", "c"]
        assert macro.get_duration_ms() == 30

    def test_init_from_existing_events(self):
        events = [MacroEvent(0, "a", []), MacroEvent(5, "b", [])]

        macro = Macro(events)

        assert len(macro) == 2
        assert macro.get_duration_ms() == 5

    def test_copy_is_independent(self):
        macro = Macro().press_button(0, Button.A)
        cloned = macro.copy()

        cloned.add_action(100, "extra", [])

        assert len(macro) == 1
        assert len(cloned) == 2

    def test_time_shift_without_offset_aligns_to_zero(self):
        macro = Macro().press_button(50, Button.A).release_button(80, Button.A)

        shifted = macro.time_shift()

        assert [event.time_ms for event in shifted] == [0, 30]
        # 原宏不变
        assert [event.time_ms for event in macro] == [50, 80]

    def test_time_shift_with_positive_offset(self):
        macro = Macro().press_button(50, Button.A)

        shifted = macro.time_shift(20)

        assert [event.time_ms for event in shifted] == [70]

    def test_time_shift_drops_negative_events(self):
        macro = Macro().press_button(10, Button.A).release_button(30, Button.A)

        shifted = macro.time_shift(-20)

        assert [event.time_ms for event in shifted] == [10]

    def test_time_shift_empty_macro_raises_index_error(self):
        with pytest.raises(IndexError):
            Macro().time_shift()

    def test_append_requires_macro(self):
        with pytest.raises(TypeError):
            Macro().append([MacroEvent(0, "a", [])])

    def test_append_with_delay(self):
        first = Macro().press_button(0, Button.A).release_button(10, Button.A)
        second = Macro().press_button(0, Button.B).release_button(5, Button.B)

        merged = first.append(second, delay_ms=20)

        assert [event.time_ms for event in merged] == [0, 10, 30, 35]
        assert [event.action_name for event in merged] == [
            "press_button",
            "release_button",
            "press_button",
            "release_button",
        ]
        # 原宏不受影响
        assert len(first) == 2
        assert len(second) == 2

    def test_filter_keeps_matching_events(self):
        macro = Macro().press_button(0, Button.A).press_button(10, Button.A).press_button(20, Button.A)

        filtered = macro.filter(lambda event: event.time_ms >= 10)

        assert [event.time_ms for event in filtered] == [10, 20]
        assert len(macro) == 3


class TestMacroActions:
    """基础动作与组合动作生成的事件序列。"""

    def test_press_and_release_button(self):
        macro = Macro().press_button(0, Button.A).release_button(50, Button.A)

        assert (macro._events[0].action_name, macro._events[0].params) == ("press_button", [Button.A])
        assert (macro._events[1].action_name, macro._events[1].params) == ("release_button", [Button.A])

    def test_move_joysticks(self):
        macro = Macro().move_left_joystick(0, (0.5, 0.6)).move_right_joystick(10, (-0.5, -0.6))

        assert (macro._events[0].action_name, macro._events[0].params) == ("left_joystick_float", [0.5, 0.6])
        assert (macro._events[1].action_name, macro._events[1].params) == ("right_joystick_float", [-0.5, -0.6])

    def test_press_triggers(self):
        macro = Macro().press_left_trigger(0, 0.4).press_right_trigger(10, 1.0)

        assert (macro._events[0].action_name, macro._events[0].params) == ("left_trigger_float", [0.4])
        assert (macro._events[1].action_name, macro._events[1].params) == ("right_trigger_float", [1.0])

    def test_click_button_creates_press_and_release(self):
        macro = Macro().click_button(100, Button.A, 50)

        assert [event.time_ms for event in macro] == [100, 150]
        assert [event.action_name for event in macro] == ["press_button", "release_button"]

    def test_hold_left_joystick_returns_to_center(self):
        macro = Macro().hold_left_joystick(0, JoystickDirection.FULL_UP, 200)

        assert [event.time_ms for event in macro] == [0, 200]
        assert [event.action_name for event in macro] == ["left_joystick_float", "left_joystick_float"]
        assert macro._events[0].params == [0.0, 1.0]
        assert macro._events[1].params == [0.0, 0.0]

    def test_hold_right_joystick_returns_to_center(self):
        macro = Macro().hold_right_joystick(0, JoystickDirection.FULL_LEFT, 100)

        assert macro._events[0].params == [-1.0, 0.0]
        assert macro._events[1].params == [0.0, 0.0]

    def test_hold_triggers_release_at_end(self):
        macro = Macro().hold_left_trigger(0, 0.6, 100).hold_right_trigger(200, 0.8, 50)

        assert [event.action_name for event in macro] == [
            "left_trigger_float",
            "left_trigger_float",
            "right_trigger_float",
            "right_trigger_float",
        ]
        assert [event.time_ms for event in macro] == [0, 100, 200, 250]
        assert macro._events[1].params == [TriggerPressure.released]
        assert macro._events[3].params == [TriggerPressure.released]


class TestGamepadSimulatorInit:
    """虚拟手柄的创建与初始化。"""

    def test_init_resets_and_wakes_up_pad(self, pad_factory, block_atexit):
        instance = GamepadSimulator()
        pad = pad_factory.return_value

        pad.reset.assert_called_once_with()
        # 按下 A 再松开 A：分别走 pad.press_button 与 pad.release_button
        assert pad.press_button.call_args_list == [call(Button.A)]
        assert pad.release_button.call_args_list == [call(Button.A)]
        assert pad.update.call_count == 3  # reset 1 次 + 按下 A 1 次 + 松开 A 1 次
        assert instance.pad is pad

    def test_init_registers_atexit_reset(self, pad_factory, block_atexit):
        GamepadSimulator()

        block_atexit.assert_called_once()
        assert block_atexit.call_args.args[0].__func__ is GamepadSimulator.reset

    def test_init_failure_raises_gamepad_error(self, pad_factory):
        pad_factory.side_effect = RuntimeError("未安装 ViGEmBus 驱动")

        with pytest.raises(GamepadError, match="初始化虚拟手柄时出错"):
            GamepadSimulator()


class TestExecuteWithRetry:
    """底层调用失败后的自动重试。"""

    def test_succeeds_after_first_failure(self, sim):
        attempts = []

        def flaky(*args):
            attempts.append(args)
            if len(attempts) == 1:
                raise RuntimeError("第一次失败")
            return "ok"

        result = sim._execute_with_retry(flaky, 1, 2)

        assert result is None  # 封装方法不返回被调用函数的返回值
        assert attempts == [(1, 2), (1, 2)]

    def test_raises_last_exception_when_all_attempts_fail(self, sim):
        calls = []

        def always_fails():
            calls.append(1)
            raise ValueError("一直失败")

        with pytest.raises(ValueError, match="一直失败"):
            sim._execute_with_retry(always_fails)

        assert len(calls) == gamepad_utils.GAMEPAD_OPERATION_RETRIES + 1


class TestReset:
    def test_reset_calls_pad(self, sim):
        sim.reset()

        sim.pad.reset.assert_called_with()
        sim.pad.update.assert_called_with()

    def test_reset_swallows_exceptions(self, sim):
        sim.pad.reset.side_effect = RuntimeError("手柄断开")

        sim.reset()  # 不应抛出异常


class TestButtonOperations:
    def test_press_button(self, sim):
        sim.press_button(Button.X)

        sim.pad.press_button.assert_called_once_with(Button.X)
        sim.pad.update.assert_called_once_with()

    def test_press_button_wraps_error(self, sim):
        sim.pad.press_button.side_effect = RuntimeError("USB 错误")

        with pytest.raises(GamepadError, match="按下按钮"):
            sim.press_button(Button.X)

    def test_release_button_delegates_to_pad_release_button(self, sim):
        """``release_button`` 应调用底层的 ``pad.release_button``，而不是再按一次。"""
        sim.release_button(Button.B)

        sim.pad.release_button.assert_called_once_with(Button.B)
        sim.pad.press_button.assert_not_called()

    def test_release_button_wraps_error(self, sim):
        sim.pad.release_button.side_effect = RuntimeError("USB 错误")

        with pytest.raises(GamepadError, match="松开按钮"):
            sim.release_button(Button.B)

    def test_click_button_presses_sleeps_and_releases(self, sim, no_sleep):
        sim.click_button(Button.A, 250)

        assert sim.pad.press_button.call_args_list == [call(Button.A)]
        assert sim.pad.release_button.call_args_list == [call(Button.A)]
        assert call(0.25) in no_sleep.call_args_list
        assert sim.pad.update.call_count == 2

    def test_click_button_releases_even_when_press_fails(self, sim):
        sim.pad.press_button.side_effect = RuntimeError("USB 错误")

        with pytest.raises(GamepadError):
            sim.click_button(Button.A, 10)

        assert sim.pad.press_button.call_count >= 2

    def test_update_pad_wraps_error(self, sim):
        sim.pad.update.side_effect = RuntimeError("驱动无响应")

        with pytest.raises(GamepadError, match="更新手柄状态失败"):
            sim.move_left_joystick(JoystickDirection.CENTER)


class TestJoystickOperations:
    def test_move_left_joystick(self, sim):
        sim.move_left_joystick((0.5, -0.5))

        sim.pad.left_joystick_float.assert_called_once_with(0.5, -0.5)
        sim.pad.update.assert_called_once_with()

    def test_move_left_joystick_wraps_error(self, sim):
        sim.pad.left_joystick_float.side_effect = RuntimeError("USB 错误")

        with pytest.raises(GamepadError, match="移动左摇杆"):
            sim.move_left_joystick((0.5, 0.5))

    def test_hold_left_joystick_returns_to_center(self, sim, no_sleep):
        sim.hold_left_joystick((1.0, 1.0), 100)

        assert sim.pad.left_joystick_float.call_args_list == [call(1.0, 1.0), call(0.0, 0.0)]
        assert call(0.1) in no_sleep.call_args_list

    def test_return_left_joystick_to_center(self, sim):
        sim.return_left_joystick_to_center()

        sim.pad.left_joystick_float.assert_called_once_with(0.0, 0.0)

    def test_move_right_joystick(self, sim):
        sim.move_right_joystick((-0.5, 0.5))

        sim.pad.right_joystick_float.assert_called_once_with(-0.5, 0.5)

    def test_move_right_joystick_wraps_error(self, sim):
        sim.pad.right_joystick_float.side_effect = RuntimeError("USB 错误")

        with pytest.raises(GamepadError, match="移动右摇杆"):
            sim.move_right_joystick((0.5, 0.5))

    def test_hold_right_joystick_returns_to_center(self, sim):
        sim.hold_right_joystick((1.0, -1.0), 50)

        assert sim.pad.right_joystick_float.call_args_list == [call(1.0, -1.0), call(0.0, 0.0)]

    def test_return_right_joystick_to_center(self, sim):
        sim.return_right_joystick_to_center()

        sim.pad.right_joystick_float.assert_called_once_with(0.0, 0.0)


class TestTriggerOperations:
    def test_press_left_trigger(self, sim):
        sim.press_left_trigger(0.7)

        sim.pad.left_trigger_float.assert_called_once_with(0.7)

    def test_press_left_trigger_wraps_error(self, sim):
        sim.pad.left_trigger_float.side_effect = RuntimeError("USB 错误")

        with pytest.raises(GamepadError, match="按压左扳机"):
            sim.press_left_trigger(0.7)

    def test_release_left_trigger(self, sim):
        sim.release_left_trigger()

        sim.pad.left_trigger_float.assert_called_once_with(TriggerPressure.released)

    def test_hold_left_trigger(self, sim, no_sleep):
        sim.hold_left_trigger(0.6, 100)

        assert sim.pad.left_trigger_float.call_args_list == [call(0.6), call(0.0)]
        assert call(0.1) in no_sleep.call_args_list

    def test_press_right_trigger_delegates_to_right_trigger(self, sim):
        """``press_right_trigger`` 应调用底层的右扳机，而不是右摇杆。"""
        sim.press_right_trigger(0.7)

        sim.pad.right_trigger_float.assert_called_once_with(0.7)
        sim.pad.right_joystick_float.assert_not_called()

    def test_press_right_trigger_wraps_error(self, sim):
        sim.pad.right_trigger_float.side_effect = RuntimeError("USB 错误")

        with pytest.raises(GamepadError, match="按压右扳机"):
            sim.press_right_trigger(0.7)

    def test_release_right_trigger(self, sim):
        sim.release_right_trigger()

        sim.pad.right_trigger_float.assert_called_once_with(TriggerPressure.released)

    def test_hold_right_trigger(self, sim, no_sleep):
        sim.hold_right_trigger(0.6, 100)

        assert sim.pad.right_trigger_float.call_args_list == [call(0.6), call(0.0)]
        sim.pad.right_joystick_float.assert_not_called()

    def test_hold_left_joystick_wraps_error(self, sim):
        sim.pad.left_joystick_float.side_effect = RuntimeError("USB 错误")

        with pytest.raises(GamepadError, match="移动左摇杆"):
            sim.hold_left_joystick((0.5, 0.5), 100)


class TestPlayMacro:
    def test_empty_macro_does_nothing(self, sim):
        sim.pad.reset_mock()

        sim.play_macro(Macro())

        sim.pad.press_button.assert_not_called()
        sim.pad.reset.assert_not_called()

    def test_executes_events_on_pad(self, sim):
        macro = Macro().press_button(0, Button.A).release_button(10, Button.A)
        sim.pad.reset_mock()

        sim.play_macro(macro)

        sim.pad.press_button.assert_called_once_with(Button.A)
        sim.pad.release_button.assert_called_once_with(Button.A)

    def test_unknown_action_is_ignored(self, sim):
        sim.pad = MagicMock(spec=REAL_GAMEPAD_CLASS)
        macro = Macro().add_action(0, "no_such_action", [])

        sim.play_macro(macro)  # 不应抛出异常

        sim.pad.update.assert_called()

    def test_reset_at_end_by_default(self, sim):
        sim.pad.reset_mock()

        sim.play_macro(Macro().press_button(0, Button.A))

        sim.pad.reset.assert_called_once_with()

    def test_reset_can_be_disabled(self, sim):
        sim.pad.reset_mock()

        sim.play_macro(Macro().press_button(0, Button.A), reset_at_end=False)

        sim.pad.reset.assert_not_called()

    def test_reset_still_happens_on_exception(self, sim):
        sim.pad.press_button.side_effect = RuntimeError("播放出错")
        sim.pad.reset_mock()

        with pytest.raises(RuntimeError, match="播放出错"):
            sim.play_macro(Macro().press_button(0, Button.A))

        sim.pad.reset.assert_called_once_with()

    def test_events_executed_in_timestamp_order(self, sim):
        macro = Macro().press_button(30, Button.B).press_button(10, Button.A)
        sim.pad.reset_mock()

        sim.play_macro(macro)

        assert sim.pad.press_button.call_args_list == [call(Button.A), call(Button.B)]
