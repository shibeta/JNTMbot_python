"""``keyboard_utils`` 的单元测试。

``KeyboardSimulator`` 底层封装 ``pynput.keyboard.Controller``，``HotKeyManager``
封装 ``pynput.keyboard.GlobalHotKeys``。这里通过 patch 这两个类来彻底隔离真实
的键盘输入与热键监听线程，保证测试不会触发任何物理按键或后台监听。
"""

from __future__ import annotations

from unittest.mock import ANY, MagicMock, call, patch

import pytest

import keyboard_utils as kb_module

# ---------------------------------------------------------------------------
# KeyboardSimulator
# ---------------------------------------------------------------------------


@pytest.fixture
def controller() -> MagicMock:
    """被 patch 掉的 ``pynput.keyboard.Controller`` 实例。"""
    with patch.object(kb_module, "Controller") as controller_cls:
        yield controller_cls.return_value


@pytest.fixture
def simulator(controller: MagicMock) -> kb_module.KeyboardSimulator:
    return kb_module.KeyboardSimulator()


class TestKeyboardSimulatorInit:
    def test_creates_controller_and_empty_state(self, controller: MagicMock):
        simulator = kb_module.KeyboardSimulator()

        assert simulator._controller is controller
        assert simulator.pressed_keys == set()


class TestPress:
    def test_press_forwards_to_controller(self, simulator, controller: MagicMock):
        simulator.press("a")

        controller.press.assert_called_once_with("a")
        assert simulator.pressed_keys == {"a"}

    def test_press_same_key_twice_keeps_single_entry(self, simulator, controller: MagicMock):
        simulator.press("a")
        simulator.press("a")

        assert controller.press.call_count == 2
        assert simulator.pressed_keys == {"a"}

    def test_press_multiple_keys(self, simulator, controller: MagicMock):
        simulator.press("a")
        simulator.press("b")

        assert simulator.pressed_keys == {"a", "b"}


class TestRelease:
    def test_release_forwards_to_controller_and_removes_key(self, simulator, controller: MagicMock):
        simulator.press("a")

        simulator.release("a")

        controller.release.assert_called_once_with("a")
        assert simulator.pressed_keys == set()

    def test_release_unknown_key_still_calls_controller(self, simulator, controller: MagicMock):
        simulator.release("z")

        controller.release.assert_called_once_with("z")
        assert simulator.pressed_keys == set()

    def test_release_removes_key_even_if_controller_raises(self, simulator, controller: MagicMock):
        simulator.press("a")
        controller.release.side_effect = RuntimeError("底层释放失败")

        with pytest.raises(RuntimeError):
            simulator.release("a")

        # finally 分支必须保证状态被清理，避免按键卡住
        assert simulator.pressed_keys == set()


class TestClick:
    def test_click_single_key(self, simulator, controller: MagicMock, no_sleep: MagicMock):
        simulator.click("a")

        assert controller.mock_calls == [call.press("a"), call.release("a")]
        no_sleep.assert_called_once_with(0.09)

    def test_click_uses_custom_milliseconds(self, simulator, controller: MagicMock, no_sleep: MagicMock):
        simulator.click("a", milliseconds=500)

        no_sleep.assert_called_once_with(0.5)

    def test_click_multiple_keys_presses_in_order_releases_in_reverse(self, simulator):
        simulator._controller = MagicMock(name="controller")

        simulator.click(["ctrl", "shift", "c"])

        assert simulator._controller.mock_calls == [
            call.press("ctrl"),
            call.press("shift"),
            call.press("c"),
            call.release("c"),
            call.release("shift"),
            call.release("ctrl"),
        ]

    def test_click_accepts_tuple(self, simulator):
        simulator._controller = MagicMock(name="controller")

        simulator.click(("ctrl", "c"))

        assert simulator._controller.mock_calls == [
            call.press("ctrl"),
            call.press("c"),
            call.release("c"),
            call.release("ctrl"),
        ]

    def test_click_empty_list_does_nothing(self, simulator, controller: MagicMock, no_sleep: MagicMock):
        simulator.click([])

        controller.press.assert_not_called()
        controller.release.assert_not_called()
        no_sleep.assert_not_called()


class TestHotkey:
    def test_hotkey_without_keys_does_nothing(self, simulator):
        with patch.object(simulator, "click") as click:
            simulator.hotkey()

        click.assert_not_called()

    def test_hotkey_forwards_to_click(self, simulator):
        with patch.object(simulator, "click") as click:
            simulator.hotkey("ctrl", "c", milliseconds=200)

        click.assert_called_once_with(("ctrl", "c"), milliseconds=200)

    def test_hotkey_actually_presses_and_releases(self, simulator):
        simulator._controller = MagicMock(name="controller")

        simulator.hotkey("ctrl", "c")

        assert simulator._controller.mock_calls == [
            call.press("ctrl"),
            call.press("c"),
            call.release("c"),
            call.release("ctrl"),
        ]


class TestReleaseAll:
    def test_releases_all_pressed_keys_and_clears_state(self, simulator, controller: MagicMock):
        simulator.press("a")
        simulator.press("b")

        simulator.release_all()

        assert sorted(controller.release.call_args_list) == [call("a"), call("b")]
        assert simulator.pressed_keys == set()

    def test_single_release_failure_is_swallowed(self, simulator, controller: MagicMock, capsys):
        simulator.press("a")
        simulator.press("b")
        controller.release.side_effect = [RuntimeError("boom"), None]

        simulator.release_all()  # 不应抛出异常

        assert simulator.pressed_keys == set()
        assert "释放按键失败" in capsys.readouterr().out

    def test_release_all_without_pressed_keys(self, simulator, controller: MagicMock):
        simulator.release_all()

        controller.release.assert_not_called()


class TestPressedKeys:
    def test_returns_a_copy(self, simulator):
        simulator.press("a")

        snapshot = simulator.pressed_keys
        snapshot.add("z")

        assert simulator.pressed_keys == {"a"}


class TestTypeString:
    def test_types_each_character(self, simulator, controller: MagicMock, no_sleep: MagicMock):
        simulator.type_string("ab")

        assert controller.mock_calls == [
            call.press("a"),
            call.release("a"),
            call.press("b"),
            call.release("b"),
        ]
        assert no_sleep.call_args_list == [call(0.01)] * 4

    def test_empty_string_does_nothing(self, simulator, controller: MagicMock, no_sleep: MagicMock):
        simulator.type_string("")

        controller.press.assert_not_called()
        no_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# HotKeyManager
# ---------------------------------------------------------------------------


@pytest.fixture
def global_hotkeys() -> MagicMock:
    """被 patch 掉的 ``pynput.keyboard.GlobalHotKeys`` 类。"""
    with patch.object(kb_module, "GlobalHotKeys") as hotkeys_cls:
        yield hotkeys_cls


class TestHotKeyManagerInit:
    def test_defaults(self):
        manager = kb_module.HotKeyManager()

        assert manager.enable is True
        assert manager.debounce_interval == 0.1
        assert manager._hotkeys == {}
        assert manager._listener is None

    def test_custom_parameters(self):
        manager = kb_module.HotKeyManager(enable=False, debounce_interval=1.5)

        assert manager.enable is False
        assert manager.debounce_interval == 1.5


class TestAddHotkey:
    def test_add_registers_wrapper_and_starts_listener(self, global_hotkeys: MagicMock):
        manager = kb_module.HotKeyManager(enable=True)
        callback = MagicMock(name="callback")

        manager.add_hotkey("<ctrl>+<f9>", callback)

        assert set(manager._hotkeys) == {"<ctrl>+<f9>"}
        assert callable(manager._hotkeys["<ctrl>+<f9>"])
        global_hotkeys.assert_called_once_with(hotkeys=manager._hotkeys)
        global_hotkeys.return_value.start.assert_called_once()
        assert manager._listener is global_hotkeys.return_value

    def test_auto_update_false_does_not_start_listener(self, global_hotkeys: MagicMock):
        manager = kb_module.HotKeyManager(enable=True)

        manager.add_hotkey("hk", MagicMock(), auto_update=False)

        global_hotkeys.assert_not_called()
        assert manager._listener is None

    def test_add_when_disabled_does_not_start_listener(self, global_hotkeys: MagicMock):
        manager = kb_module.HotKeyManager(enable=False)

        manager.add_hotkey("hk", MagicMock())

        global_hotkeys.assert_not_called()
        assert manager._listener is None

    def test_second_add_restarts_existing_listener(self, global_hotkeys: MagicMock):
        manager = kb_module.HotKeyManager(enable=True)
        manager.add_hotkey("hk-1", MagicMock())
        first_listener = manager._listener

        manager.add_hotkey("hk-2", MagicMock())

        first_listener.stop.assert_called_once()
        first_listener.join.assert_called_once_with(2.0)
        assert global_hotkeys.call_count == 2

    def test_overwriting_hotkey_reuses_same_dict(self, global_hotkeys: MagicMock):
        manager = kb_module.HotKeyManager(enable=False)
        manager.add_hotkey("hk", MagicMock(), auto_update=False)
        first_wrapper = manager._hotkeys["hk"]

        manager.add_hotkey("hk", MagicMock(), auto_update=False)

        assert set(manager._hotkeys) == {"hk"}
        assert manager._hotkeys["hk"] is not first_wrapper


class TestDebounce:
    def test_rapid_second_trigger_is_ignored(self, fake_clock):
        manager = kb_module.HotKeyManager(enable=False, debounce_interval=5.0)
        callback = MagicMock(name="callback")
        manager.add_hotkey("hk", callback, auto_update=False)
        wrapper = manager._hotkeys["hk"]

        with patch.object(kb_module.threading, "Thread") as thread_cls:
            wrapper()
            wrapper()

        thread_cls.assert_called_once_with(target=ANY, daemon=True, name="HotkeyTask_hk")
        thread_cls.return_value.start.assert_called_once()

        # 真正执行被派发的回调
        thread_cls.call_args.kwargs["target"]()
        callback.assert_called_once()

    def test_trigger_after_debounce_interval_runs_again(self, fake_clock):
        manager = kb_module.HotKeyManager(enable=False, debounce_interval=5.0)
        callback = MagicMock(name="callback")
        manager.add_hotkey("hk", callback, auto_update=False)
        wrapper = manager._hotkeys["hk"]

        with patch.object(kb_module.threading, "Thread") as thread_cls:
            wrapper()
            fake_clock.advance(10)
            wrapper()

        assert thread_cls.call_count == 2

    def test_custom_debounce_zero_allows_repeat(self, fake_clock):
        manager = kb_module.HotKeyManager(enable=False, debounce_interval=100.0)
        manager.add_hotkey("hk", MagicMock(), debounce=0.0, auto_update=False)
        wrapper = manager._hotkeys["hk"]

        with patch.object(kb_module.threading, "Thread") as thread_cls:
            wrapper()
            wrapper()

        assert thread_cls.call_count == 2

    def test_callback_exception_is_swallowed_and_logged(self, fake_clock):
        manager = kb_module.HotKeyManager(enable=False)
        manager.add_hotkey("hk", MagicMock(side_effect=RuntimeError("回调炸了")), auto_update=False)
        wrapper = manager._hotkeys["hk"]

        with patch.object(kb_module.threading, "Thread") as thread_cls:
            wrapper()

        with patch.object(kb_module, "logger") as mock_logger:
            thread_cls.call_args.kwargs["target"]()  # 不应抛出异常

        mock_logger.error.assert_called_once()


class TestRemoveAndClear:
    def test_remove_hotkey_pops_and_refreshes(self, global_hotkeys: MagicMock):
        manager = kb_module.HotKeyManager(enable=True)
        manager.add_hotkey("hk-1", MagicMock())
        manager.add_hotkey("hk-2", MagicMock())
        listener_before = manager._listener
        listener_before.reset_mock()

        manager.remove_hotkey("hk-1")

        assert set(manager._hotkeys) == {"hk-2"}
        listener_before.stop.assert_called_once()

    def test_remove_last_hotkey_stops_listener(self, global_hotkeys: MagicMock):
        manager = kb_module.HotKeyManager(enable=True)
        manager.add_hotkey("hk", MagicMock())

        manager.remove_hotkey("hk")

        assert manager._hotkeys == {}
        assert manager._listener is None

    def test_remove_unknown_hotkey_does_not_raise(self, global_hotkeys: MagicMock):
        manager = kb_module.HotKeyManager(enable=True)
        manager.add_hotkey("hk", MagicMock())

        manager.remove_hotkey("不存在的热键")

        assert set(manager._hotkeys) == {"hk"}

    def test_remove_when_disabled_does_not_touch_listener(self, global_hotkeys: MagicMock):
        manager = kb_module.HotKeyManager(enable=False)
        manager.add_hotkey("hk", MagicMock(), auto_update=False)

        manager.remove_hotkey("hk")

        global_hotkeys.assert_not_called()
        assert manager._hotkeys == {}

    def test_clear_hotkey_removes_all(self, global_hotkeys: MagicMock):
        manager = kb_module.HotKeyManager(enable=True)
        manager.add_hotkey("hk-1", MagicMock())
        manager.add_hotkey("hk-2", MagicMock())

        manager.clear_hotkey()

        assert manager._hotkeys == {}
        assert manager._listener is None


class TestStartStopUpdate:
    def test_start_enables_and_starts_listener(self, global_hotkeys: MagicMock):
        manager = kb_module.HotKeyManager(enable=False)
        manager.add_hotkey("hk", MagicMock(), auto_update=False)

        manager.start()

        assert manager.enable is True
        assert manager._listener is global_hotkeys.return_value
        global_hotkeys.return_value.start.assert_called_once()

    def test_stop_disables_and_stops_listener(self, global_hotkeys: MagicMock):
        manager = kb_module.HotKeyManager(enable=True)
        manager.add_hotkey("hk", MagicMock())
        listener = manager._listener

        manager.stop()

        assert manager.enable is False
        assert manager._listener is None
        listener.stop.assert_called_once()
        listener.join.assert_called_once_with(2.0)

    def test_update_listener_refreshes_when_enabled(self, global_hotkeys: MagicMock):
        manager = kb_module.HotKeyManager(enable=True)
        manager.add_hotkey("hk", MagicMock())

        with patch.object(manager, "_update_listener_unsafe") as update:
            manager.update_listener()

        update.assert_called_once()

    def test_update_listener_does_nothing_when_disabled(self, global_hotkeys: MagicMock):
        manager = kb_module.HotKeyManager(enable=False)

        with patch.object(manager, "_update_listener_unsafe") as update:
            manager.update_listener()

        update.assert_not_called()


class TestUpdateListenerUnsafe:
    def test_creates_listener_when_enabled_and_has_hotkeys(self, global_hotkeys: MagicMock):
        manager = kb_module.HotKeyManager(enable=True)
        manager._hotkeys["hk"] = MagicMock()

        manager._update_listener_unsafe()

        global_hotkeys.assert_called_once_with(hotkeys=manager._hotkeys)
        global_hotkeys.return_value.start.assert_called_once()

    def test_clears_listener_when_disabled(self, global_hotkeys: MagicMock):
        manager = kb_module.HotKeyManager(enable=True)
        manager.add_hotkey("hk", MagicMock())
        listener = manager._listener
        manager.enable = False

        manager._update_listener_unsafe()

        assert manager._listener is None
        listener.stop.assert_called_once()

    def test_clears_listener_when_no_hotkeys(self, global_hotkeys: MagicMock):
        manager = kb_module.HotKeyManager(enable=True)
        manager.add_hotkey("hk", MagicMock())
        manager._hotkeys.clear()

        manager._update_listener_unsafe()

        assert manager._listener is None

    def test_does_not_join_when_called_from_listener_thread(self, global_hotkeys: MagicMock):
        manager = kb_module.HotKeyManager(enable=True)
        manager.add_hotkey("hk", MagicMock())
        listener = manager._listener

        with patch.object(kb_module.threading, "current_thread", return_value=listener):
            manager._update_listener_unsafe()

        listener.stop.assert_called_once()
        listener.join.assert_not_called()

    def test_stop_failure_is_tolerated(self, global_hotkeys: MagicMock):
        manager = kb_module.HotKeyManager(enable=True)
        manager.add_hotkey("hk", MagicMock())
        listener = manager._listener
        listener.stop.side_effect = RuntimeError("停止失败")

        manager._update_listener_unsafe()  # 不应抛出异常

        # 旧监听器停止失败后，仍然会创建新的监听器
        assert global_hotkeys.call_count == 2
