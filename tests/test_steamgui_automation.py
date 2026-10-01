"""``steamgui_automation`` 的单元测试。

``SteamAutomation`` 通过 ``uiautomation`` 操作真实的 Steam 聊天窗口，所有 UI 调用都
必须被 mock。这里不会真正构造 ``SteamAutomation``（其 ``__init__`` 会去查找窗口），
而是用 ``__new__`` 创建实例后手动注入属性。

两个装饰器的注意事项：

- ``_preserve_focus_decorator`` 会在运行时调用 ``auto.GetForegroundWindow()``，因此
  必须 patch 模块级 ``auto``。
- ``ClipboardScope._preserve_clipboard_decorator`` 定义在 ``windows_utils`` 中，其
  ``wrapper`` 在**运行时**通过 ``windows_utils`` 的模块全局名查找 ``ClipboardScope``，
  所以必须 ``patch("windows_utils.ClipboardScope")`` 才能避免真实剪贴板操作。
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, call, patch

import pytest

from steamgui_automation import SteamAutomation


@pytest.fixture(autouse=True)
def never_touch_real_ui():
    """兜底保护：任何用例都不会碰到真实 ``uiautomation``。"""
    with patch("steamgui_automation.auto"):
        yield


@pytest.fixture
def automation() -> SteamAutomation:
    """未执行 ``__init__`` 的 SteamAutomation，所有属性手动注入。"""
    instance = SteamAutomation.__new__(SteamAutomation)
    instance.window_title_substring = "蠢人帮"
    instance.last_steam_chat_window_control = None
    instance.last_send_button_control = None
    instance.last_send_monotonic_time = 0.0
    instance.last_send_system_time = 0.0
    return instance


class TestInit:
    def test_init_sets_fields_and_verifies_window(self):
        with patch.object(SteamAutomation, "verify_steam_chat_window") as verify:
            instance = SteamAutomation("蠢人帮")

        assert instance.window_title_substring == "蠢人帮"
        assert instance.last_steam_chat_window_control is None
        assert instance.last_send_button_control is None
        verify.assert_called_once_with()

    def test_init_propagates_verify_failure(self):
        with (
            patch.object(SteamAutomation, "verify_steam_chat_window", side_effect=Exception("找不到窗口")),
            pytest.raises(Exception, match="找不到窗口"),
        ):
            SteamAutomation("蠢人帮")


class TestSetKeyboardFocus:
    """``_set_keyboard_focus`` 的三种分支。"""

    def test_already_focused(self):
        control = MagicMock(name="control")
        control.HasKeyboardFocus = True

        assert SteamAutomation._set_keyboard_focus(control) is True
        control.SetFocus.assert_not_called()

    def test_focus_gained_after_setfocus(self):
        control = MagicMock(name="control")
        control.HasKeyboardFocus = False
        control.SetFocus.side_effect = lambda: setattr(control, "HasKeyboardFocus", True)

        assert SteamAutomation._set_keyboard_focus(control) is True
        control.SetFocus.assert_called_once_with()
        control.Click.assert_not_called()

    def test_falls_back_to_click_when_still_unfocused(self):
        control = MagicMock(name="control")
        control.HasKeyboardFocus = False

        with patch("steamgui_automation.auto") as auto:
            auto.GetCursorPos.return_value = (10, 20)
            result = SteamAutomation._set_keyboard_focus(control)

        assert result is False
        control.SetFocus.assert_called_once_with()
        control.Click.assert_called_once_with(simulateMove=False)
        auto.SetCursorPos.assert_called_once_with(10, 20)


class TestClickControlSeamlessly:
    def test_restores_cursor_position(self):
        control = MagicMock(name="control")

        with patch("steamgui_automation.auto") as auto:
            auto.GetCursorPos.return_value = (100, 200)
            SteamAutomation._click_control_seamlessly(control)

        control.Click.assert_called_once_with(simulateMove=False)
        auto.SetCursorPos.assert_called_once_with(100, 200)


class TestFindSteamChatWindow:
    """聊天窗口查找与缓存。"""

    def test_uses_valid_cache(self, automation: SteamAutomation):
        cached = MagicMock(name="cached")
        cached.Exists.return_value = True
        cached.Name = "蠢人帮 - Steam 聊天"
        automation.last_steam_chat_window_control = cached

        with patch("steamgui_automation.auto") as auto:
            result = automation.find_steam_chat_window()

        assert result is cached
        auto.WindowControl.assert_not_called()

    def test_searches_when_cache_is_none(self, automation: SteamAutomation):
        found = MagicMock(name="found")
        found.Exists.return_value = True

        with patch("steamgui_automation.auto") as auto:
            auto.WindowControl.return_value = found
            result = automation.find_steam_chat_window()

        assert result is found
        auto.WindowControl.assert_called_once_with(searchDepth=1, SubName="蠢人帮")
        assert automation.last_steam_chat_window_control is found

    def test_invalid_cache_triggers_search_and_clears_send_button(self, automation: SteamAutomation):
        stale = MagicMock(name="stale")
        stale.Exists.return_value = True
        stale.Name = "完全不相干的窗口"
        automation.last_steam_chat_window_control = stale
        automation.last_send_button_control = MagicMock(name="stale_button")

        found = MagicMock(name="found")
        found.Exists.return_value = True

        with patch("steamgui_automation.auto") as auto:
            auto.WindowControl.return_value = found
            result = automation.find_steam_chat_window()

        assert result is found
        assert automation.last_send_button_control is None

    def test_raises_when_window_not_found(self, automation: SteamAutomation):
        missing = MagicMock(name="missing")
        missing.Exists.return_value = False

        with patch("steamgui_automation.auto") as auto:
            auto.WindowControl.return_value = missing
            with pytest.raises(Exception, match="未找到标题包含"):
                automation.find_steam_chat_window()


class TestFindInputField:
    """文本输入框查找与发送按钮缓存。"""

    def test_uses_cached_send_button(self, automation: SteamAutomation):
        window = MagicMock(name="window")
        button = MagicMock(name="button")
        button.Exists.return_value = True
        button.Name = "发送"
        input_field = MagicMock(name="input_field")
        input_field.Exists.return_value = True
        button.GetPreviousSiblingControl.return_value = input_field
        automation.last_send_button_control = button

        result = automation.find_input_field(window)

        assert result is input_field
        window.ButtonControl.assert_not_called()
        window.SwitchToThisWindow.assert_called_once_with()

    def test_searches_send_button_when_no_cache(self, automation: SteamAutomation):
        window = MagicMock(name="window")
        button = MagicMock(name="button")
        button.Exists.return_value = True
        input_field = MagicMock(name="input_field")
        input_field.Exists.return_value = True
        button.GetPreviousSiblingControl.return_value = input_field
        window.ButtonControl.return_value = button

        result = automation.find_input_field(window)

        assert result is input_field
        window.ButtonControl.assert_called_once_with(Name="发送")
        assert automation.last_send_button_control is button

    def test_stale_send_button_cache_is_refreshed(self, automation: SteamAutomation):
        window = MagicMock(name="window")
        stale = MagicMock(name="stale_button")
        stale.Exists.return_value = True
        stale.Name = "别的按钮"
        automation.last_send_button_control = stale

        button = MagicMock(name="button")
        button.Exists.return_value = True
        input_field = MagicMock(name="input_field")
        input_field.Exists.return_value = True
        button.GetPreviousSiblingControl.return_value = input_field
        window.ButtonControl.return_value = button

        result = automation.find_input_field(window)

        assert result is input_field
        window.ButtonControl.assert_called_once_with(Name="发送")

    def test_raises_when_send_button_missing(self, automation: SteamAutomation):
        window = MagicMock(name="window")
        missing = MagicMock(name="missing")
        missing.Exists.return_value = False
        window.ButtonControl.return_value = missing

        with pytest.raises(Exception, match="未找到辅助定位文本输入框用的发送按钮"):
            automation.find_input_field(window)

    def test_raises_when_send_button_is_none(self, automation: SteamAutomation):
        window = MagicMock(name="window")
        window.ButtonControl.return_value = None

        with pytest.raises(Exception, match="未找到辅助定位文本输入框用的发送按钮"):
            automation.find_input_field(window)

    def test_raises_when_input_field_missing(self, automation: SteamAutomation):
        window = MagicMock(name="window")
        button = MagicMock(name="button")
        button.Exists.return_value = True
        button.GetPreviousSiblingControl.return_value = None
        window.ButtonControl.return_value = button

        with pytest.raises(Exception, match="未找到文本输入框"):
            automation.find_input_field(window)

    def test_raises_when_input_field_not_exists(self, automation: SteamAutomation):
        window = MagicMock(name="window")
        button = MagicMock(name="button")
        button.Exists.return_value = True
        input_field = MagicMock(name="input_field")
        input_field.Exists.return_value = False
        button.GetPreviousSiblingControl.return_value = input_field
        window.ButtonControl.return_value = button

        with pytest.raises(Exception, match="未找到文本输入框"):
            automation.find_input_field(window)


class TestVerifySteamChatWindow:
    def test_success(self, automation: SteamAutomation):
        chat_window = MagicMock(name="chat_window")
        automation.find_steam_chat_window = MagicMock(return_value=chat_window)
        automation.find_input_field = MagicMock(return_value=MagicMock(name="input_field"))

        automation.verify_steam_chat_window()

        automation.find_input_field.assert_called_once_with(chat_window)

    def test_raises_when_window_missing(self, automation: SteamAutomation):
        automation.find_steam_chat_window = MagicMock(side_effect=Exception("未找到窗口"))
        automation.find_input_field = MagicMock()

        with pytest.raises(Exception, match="未找到窗口"):
            automation.verify_steam_chat_window()

        automation.find_input_field.assert_not_called()

    def test_raises_when_input_field_missing(self, automation: SteamAutomation):
        automation.find_steam_chat_window = MagicMock(return_value=MagicMock(name="chat_window"))
        automation.find_input_field = MagicMock(side_effect=Exception("未找到文本输入框"))

        with pytest.raises(Exception, match="未找到文本输入框"):
            automation.verify_steam_chat_window()


class TestSendMessageToSteamChatWindow:
    """剪贴板粘贴发送消息。"""

    @pytest.fixture
    def prepared(self, automation: SteamAutomation):
        """准备好窗口/输入框/focus 的桩，并 patch 掉剪贴板作用域与 auto。"""
        input_field = MagicMock(name="input_field")
        automation.find_steam_chat_window = MagicMock(return_value=MagicMock(name="chat_window"))
        automation.find_input_field = MagicMock(return_value=input_field)
        automation._set_keyboard_focus = MagicMock(return_value=True)

        with (
            patch("steamgui_automation.auto") as auto,
            patch("windows_utils.ClipboardScope") as clipboard_scope,
        ):
            yield automation, input_field, auto, clipboard_scope

    def test_empty_message_returns_early(self, automation: SteamAutomation):
        automation.find_steam_chat_window = MagicMock()

        with (
            patch("steamgui_automation.auto"),
            patch("windows_utils.ClipboardScope"),
        ):
            automation.send_message_to_steam_chat_window("")

        automation.find_steam_chat_window.assert_not_called()

    def test_happy_path_pastes_and_sends(self, prepared):
        automation, input_field, auto, _ = prepared

        automation.send_message_to_steam_chat_window("你好")

        auto.SetClipboardText.assert_called_once_with("你好")
        assert input_field.SendKeys.call_args_list == [
            call("{Ctrl}v", charMode=True),
            call("{Enter}", charMode=True),
            call("{Enter}", charMode=True),
        ]
        assert automation._set_keyboard_focus.call_count == 2

    def test_clipboard_failure_falls_back_to_typing(self, prepared):
        automation, input_field, auto, _ = prepared
        auto.SetClipboardText.side_effect = Exception("剪贴板被占用")

        automation.send_message_to_steam_chat_window("你好")

        assert input_field.SendKeys.call_args_list == [
            call(text="你好", charMode=True),
            call("{Enter}", charMode=True),
            call("{Enter}", charMode=True),
        ]

    def test_focus_failure_raises(self, prepared):
        automation, _, _, _ = prepared
        automation._set_keyboard_focus = MagicMock(return_value=False)

        with pytest.raises(Exception, match="激活文本输入框失败"):
            automation.send_message_to_steam_chat_window("你好")

    def test_uses_clipboard_scope(self, prepared):
        automation, _, _, clipboard_scope = prepared

        automation.send_message_to_steam_chat_window("你好")

        clipboard_scope.assert_called_once_with()


class TestSendGroupMessage:
    """``send_group_message`` 的计时重置与异常包装。"""

    def test_empty_message_resets_timer_only(self, automation: SteamAutomation):
        automation.reset_send_timer = MagicMock()
        automation.send_message_to_steam_chat_window = MagicMock()

        automation.send_group_message("")

        automation.reset_send_timer.assert_called_once_with()
        automation.send_message_to_steam_chat_window.assert_not_called()

    def test_success_resets_timer(self, automation: SteamAutomation):
        automation.reset_send_timer = MagicMock()
        automation.send_message_to_steam_chat_window = MagicMock()

        automation.send_group_message("你好")

        automation.send_message_to_steam_chat_window.assert_called_once_with("你好")
        automation.reset_send_timer.assert_called_once_with()

    def test_failure_is_wrapped(self, automation: SteamAutomation):
        automation.send_message_to_steam_chat_window = MagicMock(side_effect=RuntimeError("窗口消失了"))

        with pytest.raises(Exception, match="使用 Steam GUI 向群组发送消息时出错"):
            automation.send_group_message("你好")


class TestLoginStatusAndTimers:
    def test_get_login_status_always_logged_out(self, automation: SteamAutomation):
        assert automation.get_login_status() == {"loggedIn": False, "name": ""}

    def test_get_last_send_times(self, automation: SteamAutomation):
        automation.last_send_monotonic_time = 11.0
        automation.last_send_system_time = 22.0

        assert automation.get_last_send_monotonic_time() == 11.0
        assert automation.get_last_send_system_time() == 22.0

    def test_reset_send_timer_updates_both_timestamps(self, automation: SteamAutomation):
        before_wall = time.time()

        automation.reset_send_timer()

        assert automation.last_send_monotonic_time > 0
        assert automation.last_send_system_time >= before_wall
