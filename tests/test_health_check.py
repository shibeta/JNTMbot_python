"""``health_check.HealthMonitor`` 的单元测试。

``HealthMonitor`` 是一个 ``threading.Thread`` 子类，测试中绝不 ``start()`` 真实线程：
要么直接调用 ``_perform_check`` 等内部方法，要么直接调用 ``run()`` 并通过 patch
``is_exiting`` / ``sleep`` 精确控制循环次数。``fake_clock`` 的 ``step`` 被设为 0，
因此 ``elapsed`` 完全由桩函数决定，不依赖真实时间。
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import health_check as hc

SYSTEM_TIME = 1_700_000_000.0
EXPECTED_FORMATTED_TIME = datetime.fromtimestamp(SYSTEM_TIME).strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture
def make_monitor(config, fake_clock):
    """构造 HealthMonitor，并把所有与时间有关的输入变成可控的桩。"""
    fake_clock.set(1000.0)
    fake_clock.step = 0  # 固定时钟，elapsed 完全由 elapsed_seconds 决定

    def factory(
        elapsed_seconds: float = 0.0,
        exit_on_unhealthy: bool = False,
        suppress: object = None,
        threshold_minutes: int = 60,
        check_interval_minutes: int = 10,
    ) -> SimpleNamespace:
        config.healthCheckSteamChatTimeoutThreshold = threshold_minutes
        config.healthCheckInterval = check_interval_minutes
        config.enableExitOnUnhealthy = exit_on_unhealthy

        get_system_time = MagicMock(name="get_last_send_system_time", return_value=SYSTEM_TIME)
        get_monotonic_time = MagicMock(name="get_last_send_monotonic_time", return_value=1000.0 - elapsed_seconds)
        exit_func = MagicMock(name="exit_func")
        push_func = MagicMock(name="push_func")

        monitor = hc.HealthMonitor(
            config,
            get_system_time,
            get_monotonic_time,
            exit_func,
            push_func,
            suppress,
        )
        return SimpleNamespace(
            monitor=monitor,
            push=push_func,
            exit_func=exit_func,
            get_system_time=get_system_time,
            get_monotonic_time=get_monotonic_time,
            config=config,
        )

    return factory


class TestInit:
    def test_reads_config(self, make_monitor):
        env = make_monitor(threshold_minutes=30, check_interval_minutes=5, exit_on_unhealthy=True)

        assert env.monitor.check_interval == 5
        assert env.monitor.steam_chat_timeout_threshold == 30
        assert env.monitor.exit_on_unhealthy is True
        assert env.monitor._is_healthy_on_last_check is True
        assert env.monitor.enable_steam_chat_timeout is True

    def test_is_daemon_thread(self, make_monitor):
        env = make_monitor()

        assert env.monitor.daemon is True
        assert env.monitor.name == "HealthMonitorThread"


class TestPerformCheck:
    def test_healthy_does_not_notify(self, make_monitor):
        env = make_monitor(elapsed_seconds=600, threshold_minutes=60)

        env.monitor._perform_check()

        env.push.assert_not_called()
        env.exit_func.assert_not_called()
        assert env.monitor._is_healthy_on_last_check is True

    def test_becomes_unhealthy_sends_notification(self, make_monitor):
        env = make_monitor(elapsed_seconds=61 * 60, threshold_minutes=60)

        env.monitor._perform_check()

        env.push.assert_called_once()
        title, message = env.push.call_args.args
        assert title == "状态变为不健康"
        assert "Bot 超过 60 分钟未向 Steam 发送消息" in message
        assert EXPECTED_FORMATTED_TIME in message
        assert env.monitor._is_healthy_on_last_check is False

    def test_becomes_unhealthy_exits_when_configured(self, make_monitor):
        env = make_monitor(elapsed_seconds=61 * 60, exit_on_unhealthy=True)

        env.monitor._perform_check()

        env.exit_func.assert_called_once()

    def test_becomes_unhealthy_does_not_exit_by_default(self, make_monitor):
        env = make_monitor(elapsed_seconds=61 * 60, exit_on_unhealthy=False)

        env.monitor._perform_check()

        env.exit_func.assert_not_called()

    def test_stays_unhealthy_does_not_repeat_notification(self, make_monitor):
        env = make_monitor(elapsed_seconds=61 * 60)
        env.monitor._is_healthy_on_last_check = False

        env.monitor._perform_check()

        env.push.assert_not_called()
        assert env.monitor._is_healthy_on_last_check is False

    def test_stays_unhealthy_still_exits_when_configured(self, make_monitor):
        env = make_monitor(elapsed_seconds=61 * 60, exit_on_unhealthy=True)
        env.monitor._is_healthy_on_last_check = False

        env.monitor._perform_check()

        env.exit_func.assert_called_once()

    def test_recovers_sends_notification(self, make_monitor):
        env = make_monitor(elapsed_seconds=10, threshold_minutes=60)
        env.monitor._is_healthy_on_last_check = False

        env.monitor._perform_check()

        env.push.assert_called_once_with("状态恢复健康", "现在一切正常。")
        assert env.monitor._is_healthy_on_last_check is True

    def test_disabled_steam_check_skips_elapsed_lookup(self, make_monitor):
        env = make_monitor()
        env.monitor.enable_steam_chat_timeout = False

        env.monitor._perform_check()

        env.get_monotonic_time.assert_not_called()
        env.push.assert_not_called()


class TestSuppressCheck:
    def test_suppress_true_skips_check(self, make_monitor):
        suppress = MagicMock(name="suppress", return_value=True)
        env = make_monitor(suppress=suppress)

        env.monitor._perform_check()

        env.get_monotonic_time.assert_not_called()
        env.push.assert_not_called()
        assert env.monitor._is_healthy_on_last_check is True

    def test_suppress_exception_is_ignored(self, make_monitor):
        suppress = MagicMock(name="suppress", side_effect=RuntimeError("查询模式失败"))
        env = make_monitor(suppress=suppress)

        env.monitor._perform_check()  # 不应抛出异常

        env.get_monotonic_time.assert_called_once()

    def test_no_suppress_func_runs_check(self, make_monitor):
        env = make_monitor()

        env.monitor._perform_check()

        env.get_monotonic_time.assert_called_once()


class TestNotificationHelpers:
    def test_send_notification_forwards_to_push_func(self, make_monitor):
        env = make_monitor()

        env.monitor._send_notification("标题", "正文")

        env.push.assert_called_once_with("标题", "正文")

    def test_on_healthy_does_nothing(self, make_monitor):
        env = make_monitor()

        env.monitor._on_healthy()

        env.push.assert_not_called()
        env.exit_func.assert_not_called()

    @pytest.mark.parametrize("exit_on_unhealthy", [True, False])
    def test_on_unhealthy_respects_exit_flag(self, make_monitor, exit_on_unhealthy: bool):
        env = make_monitor(exit_on_unhealthy=exit_on_unhealthy)

        env.monitor._on_unhealthy(["SteamChatTimeout"])

        assert env.exit_func.called is exit_on_unhealthy
        env.push.assert_not_called()

    def test_on_unhealthy_does_not_mutate_caller_list(self, make_monitor):
        env = make_monitor()
        reasons = ["SteamChatTimeout"]

        env.monitor._on_unhealthy(reasons)

        assert reasons == ["SteamChatTimeout"]

    def test_on_become_unhealthy_with_unknown_reason(self, make_monitor):
        env = make_monitor()

        env.monitor._on_become_unhealthy(["未知原因A"])

        _, message = env.push.call_args.args
        assert "未知原因: 未知原因A" in message

    def test_on_become_unhealthy_without_reason(self, make_monitor):
        env = make_monitor()

        env.monitor._on_become_unhealthy([])

        _, message = env.push.call_args.args
        assert message == "未提供错误原因"

    def test_on_become_unhealthy_does_not_mutate_caller_list(self, make_monitor):
        env = make_monitor()
        reasons = ["SteamChatTimeout"]

        env.monitor._on_become_unhealthy(reasons)

        assert reasons == ["SteamChatTimeout"]


class TestRunLoop:
    def test_performs_check_after_sleep(self, make_monitor, no_sleep: MagicMock):
        env = make_monitor(check_interval_minutes=7)
        env.monitor._perform_check = MagicMock(name="_perform_check")

        with patch.object(hc, "is_exiting", side_effect=[False, True]):
            env.monitor.run()

        no_sleep.assert_called_once_with(7 * 60)
        env.monitor._perform_check.assert_called_once()

    def test_exits_when_sleep_is_interrupted(self, make_monitor, no_sleep: MagicMock):
        env = make_monitor()
        env.monitor._perform_check = MagicMock(name="_perform_check")
        no_sleep.return_value = False

        with patch.object(hc, "is_exiting", return_value=False):
            env.monitor.run()

        env.monitor._perform_check.assert_not_called()

    def test_skips_loop_when_already_exiting(self, make_monitor, no_sleep: MagicMock):
        env = make_monitor()
        env.monitor._perform_check = MagicMock(name="_perform_check")

        with patch.object(hc, "is_exiting", return_value=True):
            env.monitor.run()

        no_sleep.assert_not_called()
        env.monitor._perform_check.assert_not_called()
