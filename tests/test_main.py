"""``main`` 的单元测试。

``main.py`` 在导入时会执行 ``init_lifecycle_manager()``（真实 Windows API 调用），
因此所有用例都在 patch 环境中导入该模块，并把 ``main`` 的全部外部依赖替换成 mock。
主循环是 ``while True``，测试必须保证它一定会通过返回值退出（默认让
``run_one_cycle`` 抛出「恶意玩家」异常直接返回 2）。
"""

from __future__ import annotations

import importlib
import sys
from functools import partial
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from argument_parser import ArgumentError
from gamepad_utils import GamepadInitError
from gta_automator.exception import GameState, UnexpectedGameState
from ocr_utils import OcrError


def _bad_sport_error() -> UnexpectedGameState:
    return UnexpectedGameState(GameState.CLEAN_PLAYER_LEVEL, GameState.BAD_SPORT_LEVEL)


@pytest.fixture
def main_module():
    """在屏蔽 Windows API 与 atexit 的环境下导入 main 模块。"""
    sys.modules.pop("main", None)
    with patch("ctypes.windll", MagicMock()), patch("atexit.register", MagicMock()):
        module = importlib.import_module("main")
    yield module
    sys.modules.pop("main", None)


@pytest.fixture
def main_env(main_module, config) -> SimpleNamespace:
    """把 main 的所有外部依赖替换成 mock，并提供一组合理的默认返回值。"""
    with (
        patch.object(main_module, "ArgumentParser") as argument_parser_cls,
        patch.object(main_module, "ConfigManager") as config_manager_cls,
        patch.object(main_module, "HotKeyManager") as hotkey_cls,
        patch.object(main_module, "OCREngine") as ocr_engine_cls,
        patch.object(main_module, "SteamBot") as steam_bot_cls,
        patch.object(main_module, "SteamAutomation") as steam_automation_cls,
        patch.object(main_module, "UniPush") as uni_push_cls,
        patch.object(main_module, "GTAAutomator") as automator_cls,
        patch.object(main_module, "HealthMonitor") as health_monitor_cls,
        patch.object(main_module, "set_loglevel") as set_loglevel,
        patch.object(main_module, "sleep_smart") as sleep_smart,
        patch.object(main_module, "subprocess") as subprocess_module,
    ):
        argument_parser_cls.return_value.parse.return_value = {"config_file_path": "config.yaml"}
        config_manager_cls.return_value.load.return_value = config
        ocr_engine_cls.return_value.ocr_window = MagicMock(name="ocr_window")
        steam_bot_cls.return_value.get_login_status.return_value = {"loggedIn": True, "name": "测试Bot"}
        automator_cls.return_value.is_in_recovery_mode.return_value = False
        # 主循环默认立即以「恶意玩家」异常退出，保证测试不会死循环
        automator_cls.return_value.run_one_cycle.side_effect = [_bad_sport_error()]

        yield SimpleNamespace(
            module=main_module,
            config=config,
            argument_parser_cls=argument_parser_cls,
            config_manager_cls=config_manager_cls,
            hotkey_cls=hotkey_cls,
            ocr_engine_cls=ocr_engine_cls,
            steam_bot_cls=steam_bot_cls,
            steam_automation_cls=steam_automation_cls,
            uni_push_cls=uni_push_cls,
            automator_cls=automator_cls,
            health_monitor_cls=health_monitor_cls,
            hotkey=hotkey_cls.return_value,
            ocr_engine=ocr_engine_cls.return_value,
            steam_bot=steam_bot_cls.return_value,
            steam_automation=steam_automation_cls.return_value,
            push=uni_push_cls.return_value,
            automator=automator_cls.return_value,
            health_monitor=health_monitor_cls.return_value,
            set_loglevel=set_loglevel,
            sleep_smart=sleep_smart,
            subprocess=subprocess_module,
        )


class TestInterruptDecorator:
    def test_returns_wrapped_value(self, main_module):
        @main_module.interrupt_decorator
        def func():
            return 42

        assert func() == 42

    def test_keyboard_interrupt_triggers_exit(self, main_module):
        with patch.object(main_module, "trigger_exit") as trigger_exit:

            @main_module.interrupt_decorator
            def func():
                raise KeyboardInterrupt

            with pytest.raises(SystemExit) as excinfo:
                func()

        assert excinfo.value.code == 0
        trigger_exit.assert_called_once_with("用户手动中断")

    def test_other_exception_exits_with_code_1(self, main_module):
        @main_module.interrupt_decorator
        def func():
            raise RuntimeError("boom")

        with pytest.raises(SystemExit) as excinfo:
            func()

        assert excinfo.value.code == 1


class TestHappyPath:
    def test_wires_all_components(self, main_env):
        result = main_env.module.main()

        assert result == 2
        main_env.subprocess.run.assert_called_once_with("title 鸡你太美", shell=True, check=False)
        main_env.ocr_engine_cls.assert_called_once_with(main_env.config.ocrArgs)
        main_env.steam_bot_cls.assert_called_once_with(main_env.config)
        main_env.uni_push_cls.assert_called_once_with(main_env.config, "测试Bot")
        main_env.automator_cls.assert_called_once_with(
            main_env.config,
            main_env.ocr_engine.ocr_window,
            main_env.steam_bot.send_group_message,
            main_env.push.push_message,
        )
        main_env.set_loglevel.assert_called_once_with(log_level="INFO")

    def test_registers_pause_and_exit_hotkeys(self, main_env):
        main_env.module.main()

        calls = main_env.hotkey.add_hotkey.call_args_list
        assert len(calls) == 2
        assert calls[0].args[0] == "<ctrl>+<f9>"
        assert calls[0].args[1] is main_env.module.toggle_pause

        assert calls[1].args[0] == "<ctrl>+<f10>"
        exit_callback = calls[1].args[1]
        assert isinstance(exit_callback, partial)
        assert exit_callback.func is main_env.module.trigger_exit
        assert exit_callback.args == ("触发退出热键",)

    def test_debug_mode_sets_debug_loglevel(self, main_env):
        main_env.config.debug = True

        main_env.module.main()

        main_env.set_loglevel.assert_called_once_with(log_level="DEBUG")

    def test_successful_cycle_resets_error_counter(self, main_env):
        main_env.automator.run_one_cycle.side_effect = [None, _bad_sport_error()]

        result = main_env.module.main()

        assert result == 2
        main_env.sleep_smart.assert_not_called()


class TestSteamBackendSelection:
    def test_uses_steam_bot_by_default(self, main_env):
        assert main_env.config.useAlterMessagingMethod is False

        main_env.module.main()

        main_env.steam_bot_cls.assert_called_once_with(main_env.config)
        main_env.steam_automation_cls.assert_not_called()

    def test_uses_steam_automation_when_configured(self, main_env):
        main_env.config.useAlterMessagingMethod = True
        main_env.config.AlterMessagingMethodWindowTitle = "蠢人帮"

        result = main_env.module.main()

        assert result == 2
        main_env.steam_automation_cls.assert_called_once_with("蠢人帮")
        main_env.steam_bot_cls.assert_not_called()
        main_env.automator_cls.assert_called_once_with(
            main_env.config,
            main_env.ocr_engine.ocr_window,
            main_env.steam_automation.send_group_message,
            main_env.push.push_message,
        )


class TestHealthCheckWiring:
    def test_monitor_started_when_enabled(self, main_env):
        main_env.config.enableHealthCheck = True

        main_env.module.main()

        main_env.health_monitor_cls.assert_called_once()
        args = main_env.health_monitor_cls.call_args.args
        assert args[0] is main_env.config
        assert args[1] is main_env.steam_bot.get_last_send_system_time
        assert args[2] is main_env.steam_bot.get_last_send_monotonic_time
        assert args[3].func is main_env.module.trigger_exit
        assert args[3].args == ("触发 BOT 不健康自动退出",)
        assert args[4] is main_env.push.push_message
        assert callable(args[5])
        main_env.health_monitor.start.assert_called_once()

    def test_monitor_not_created_when_disabled(self, main_env):
        main_env.config.enableHealthCheck = False

        main_env.module.main()

        main_env.health_monitor_cls.assert_not_called()

    def test_suppress_check_reflects_recovery_mode(self, main_env):
        main_env.config.enableHealthCheck = True
        main_env.module.main()
        should_suppress = main_env.health_monitor_cls.call_args.args[5]

        main_env.automator.is_in_recovery_mode.return_value = True
        assert should_suppress() is True

        main_env.automator.is_in_recovery_mode.return_value = False
        assert should_suppress() is False

    def test_suppress_check_swallows_exception(self, main_env):
        main_env.config.enableHealthCheck = True
        main_env.module.main()
        should_suppress = main_env.health_monitor_cls.call_args.args[5]

        main_env.automator.is_in_recovery_mode.side_effect = RuntimeError("查询失败")

        assert should_suppress() is False


class TestMainLoopErrorHandling:
    def test_retries_with_exponential_backoff(self, main_env):
        main_env.config.mainLoopConsecutiveErrorThreshold = 5
        main_env.config.pushActivationDelay = 1000  # 运行时间不足以触发推送
        main_env.automator.run_one_cycle.side_effect = [
            RuntimeError("第一次错误"),
            RuntimeError("第二次错误"),
            _bad_sport_error(),
        ]

        result = main_env.module.main()

        assert result == 2
        assert main_env.sleep_smart.call_args_list == [call(10), call(20)]
        # 只有恶意玩家那次会推送
        assert main_env.push.push_message.call_count == 1

    def test_exceeds_threshold_returns_1_and_pushes(self, main_env):
        main_env.config.mainLoopConsecutiveErrorThreshold = 0
        main_env.config.pushActivationDelay = 0
        main_env.automator.run_one_cycle.side_effect = RuntimeError("一直失败")

        result = main_env.module.main()

        assert result == 1
        main_env.push.push_message.assert_called_once()
        assert main_env.push.push_message.call_args.args[0] == "超过连续失败阈值，程序退出"
        main_env.sleep_smart.assert_not_called()

    def test_exceeds_threshold_before_activation_delay_does_not_push(self, main_env):
        main_env.config.mainLoopConsecutiveErrorThreshold = 0
        main_env.config.pushActivationDelay = 1000
        main_env.automator.run_one_cycle.side_effect = RuntimeError("一直失败")

        result = main_env.module.main()

        assert result == 1
        main_env.push.push_message.assert_not_called()

    @pytest.mark.parametrize("actual", [GameState.BAD_SPORT_LEVEL, GameState.DODGY_PLAYER_LEVEL])
    def test_bad_player_level_exits_with_2(self, main_env, actual: GameState):
        main_env.automator.run_one_cycle.side_effect = UnexpectedGameState(GameState.CLEAN_PLAYER_LEVEL, actual)

        result = main_env.module.main()

        assert result == 2
        main_env.push.push_message.assert_called_once()
        assert actual.value in main_env.push.push_message.call_args.args[0]

    def test_ocr_error_restarts_engine(self, main_env):
        main_env.config.mainLoopConsecutiveErrorThreshold = 10
        main_env.automator.run_one_cycle.side_effect = [OcrError("引擎挂了"), _bad_sport_error()]

        result = main_env.module.main()

        assert result == 2
        main_env.ocr_engine.restart.assert_called_once()

    def test_ocr_restart_failure_is_logged_and_loop_continues(self, main_env):
        main_env.config.mainLoopConsecutiveErrorThreshold = 10
        main_env.ocr_engine.restart.side_effect = OcrError("重启也失败了")
        main_env.automator.run_one_cycle.side_effect = [OcrError("引擎挂了"), _bad_sport_error()]

        result = main_env.module.main()

        assert result == 2
        main_env.ocr_engine.restart.assert_called_once()

    def test_generic_error_does_not_restart_ocr(self, main_env):
        main_env.config.mainLoopConsecutiveErrorThreshold = 10
        main_env.automator.run_one_cycle.side_effect = [RuntimeError("普通错误"), _bad_sport_error()]

        main_env.module.main()

        main_env.ocr_engine.restart.assert_not_called()


class TestInitializationFailures:
    def test_argument_parse_failure_returns_3(self, main_env):
        main_env.argument_parser_cls.return_value.parse.side_effect = ArgumentError(argument=None, message="未知参数")

        assert main_env.module.main() == 3
        main_env.ocr_engine_cls.assert_not_called()

    def test_config_load_failure_returns_4(self, main_env):
        main_env.config_manager_cls.return_value.load.side_effect = RuntimeError("配置损坏")

        assert main_env.module.main() == 4
        main_env.ocr_engine_cls.assert_not_called()

    def test_ocr_engine_failure_returns_5(self, main_env):
        main_env.ocr_engine_cls.side_effect = RuntimeError("缺少 RapidOCR-json.exe")

        assert main_env.module.main() == 5
        main_env.steam_bot_cls.assert_not_called()

    @pytest.mark.parametrize("error", [ValueError("token 无效"), RuntimeError("无法连接后端")])
    def test_steam_bot_failure_returns_6(self, main_env, error: Exception):
        main_env.steam_bot_cls.side_effect = error

        assert main_env.module.main() == 6

    def test_steam_automation_failure_returns_7(self, main_env):
        main_env.config.useAlterMessagingMethod = True
        main_env.steam_automation_cls.side_effect = RuntimeError("找不到聊天窗口")

        assert main_env.module.main() == 7
        main_env.uni_push_cls.assert_not_called()

    def test_push_init_failure_returns_8(self, main_env):
        main_env.uni_push_cls.side_effect = ValueError("推送配置无效")

        assert main_env.module.main() == 8
        main_env.automator_cls.assert_not_called()

    def test_gamepad_init_failure_returns_9(self, main_env):
        main_env.automator_cls.side_effect = GamepadInitError("没有安装 ViGEmBus")

        assert main_env.module.main() == 9
        main_env.health_monitor_cls.assert_not_called()
