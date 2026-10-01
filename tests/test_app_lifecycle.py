"""``app_lifecycle`` 的单元测试。

该模块用两个模块级 ``threading.Event`` 保存全局退出/暂停状态，用例之间必须完全
独立，因此每个用例都通过 ``monkeypatch`` 换上全新的事件对象。所有真实休眠都被
conftest 替换；涉及真实等待的用例只使用毫秒级时长。
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import app_lifecycle as al

# conftest 的 autouse fixture 会把 app_lifecycle.sleep_* 替换成 mock 以避免真实休眠。
# 测试睡眠封装本身时必须使用真实的函数，因此在收集阶段（patch 生效之前）先绑定引用。
from app_lifecycle import sleep_smart as real_sleep_smart
from app_lifecycle import sleep_stoppable as real_sleep_stoppable


@pytest.fixture
def events(monkeypatch) -> SimpleNamespace:
    """把模块级全局事件替换成每次全新的对象。"""
    exit_event = threading.Event()
    pause_event = threading.Event()
    cleanup_event = threading.Event()
    monkeypatch.setattr(al, "_exit_event", exit_event)
    monkeypatch.setattr(al, "_pause_event", pause_event)
    monkeypatch.setattr(al, "_cleanup_done_event", cleanup_event)
    return SimpleNamespace(exit=exit_event, pause=pause_event, cleanup=cleanup_event)


class _StubEvent:
    """可精确控制 ``is_set`` / ``wait`` 行为的事件替身。"""

    def __init__(self, is_set: bool = False, set_after_waits: int | None = None):
        self._is_set = is_set
        self._set_after_waits = set_after_waits
        self.wait_calls = 0

    def is_set(self) -> bool:
        return self._is_set

    def set(self) -> None:
        self._is_set = True

    def clear(self) -> None:
        self._is_set = False

    def wait(self, timeout: float | None = None) -> bool:
        self.wait_calls += 1
        if self._set_after_waits is not None and self.wait_calls >= self._set_after_waits:
            self._is_set = True
        return self._is_set


# ---------------------------------------------------------------------------
# 信号控制 API
# ---------------------------------------------------------------------------


class TestExitSignal:
    def test_trigger_exit_sets_event(self, events):
        al.trigger_exit("测试原因")

        assert events.exit.is_set() is True
        assert al.is_exiting() is True

    def test_trigger_exit_logs_reason(self, events):
        with patch.object(al, "logger") as mock_logger:
            al.trigger_exit("磁盘满了")

        mock_logger.warning.assert_called_once()
        assert "磁盘满了" in mock_logger.warning.call_args.args[0]

    def test_trigger_exit_empty_reason_is_not_logged(self, events):
        with patch.object(al, "logger") as mock_logger:
            al.trigger_exit("")

        mock_logger.warning.assert_not_called()
        assert events.exit.is_set() is True

    def test_trigger_exit_is_idempotent(self, monkeypatch, events):
        monkeypatch.setattr(al._thread, "interrupt_main", MagicMock())
        al.trigger_exit("第一次")

        with patch.object(al, "logger") as mock_logger:
            al.trigger_exit("第二次")

        # 已经进入退出流程，第二次应当直接返回
        mock_logger.warning.assert_not_called()
        al._thread.interrupt_main.assert_not_called()

    def test_trigger_exit_from_main_thread_does_not_interrupt(self, monkeypatch, events):
        interrupt_main = MagicMock(name="interrupt_main")
        monkeypatch.setattr(al._thread, "interrupt_main", interrupt_main)

        al.trigger_exit("主线程退出")

        interrupt_main.assert_not_called()

    def test_trigger_exit_from_worker_thread_interrupts_main(self, monkeypatch, events):
        interrupt_main = MagicMock(name="interrupt_main")
        monkeypatch.setattr(al._thread, "interrupt_main", interrupt_main)
        finished = threading.Event()

        def worker():
            al.trigger_exit("子线程退出")
            finished.set()

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=5)

        assert finished.is_set()
        assert events.exit.is_set() is True
        interrupt_main.assert_called_once()

    def test_is_exiting_false_by_default(self, events):
        assert al.is_exiting() is False


class TestPauseSignal:
    def test_toggle_pause_sets_then_clears(self, events):
        al.toggle_pause()

        assert events.pause.is_set() is True
        assert al.is_paused() is True

        al.toggle_pause()

        assert events.pause.is_set() is False
        assert al.is_paused() is False

    def test_toggle_pause_logs(self, events):
        with patch.object(al, "logger") as mock_logger:
            al.toggle_pause()
            al.toggle_pause()

        assert mock_logger.warning.call_count == 2

    def test_is_paused_false_by_default(self, events):
        assert al.is_paused() is False


# ---------------------------------------------------------------------------
# 程序重启
# ---------------------------------------------------------------------------


class TestRestartProgram:
    @pytest.fixture
    def restart_mocks(self, monkeypatch):
        exitfuncs = MagicMock(name="_run_exitfuncs")
        execl = MagicMock(name="os.execl")
        monkeypatch.setattr(al.atexit, "_run_exitfuncs", exitfuncs)
        monkeypatch.setattr(al.os, "execl", execl)
        return SimpleNamespace(exitfuncs=exitfuncs, execl=execl)

    def test_runs_exitfuncs_and_execl_with_argv(self, monkeypatch, restart_mocks):
        monkeypatch.delattr(al.sys, "frozen", raising=False)
        monkeypatch.setattr(al.sys, "argv", ["prog", "--flag", "value"])

        al.restart_program()

        restart_mocks.exitfuncs.assert_called_once()
        restart_mocks.execl.assert_called_once_with(al.sys.executable, al.sys.executable, "prog", "--flag", "value")

    def test_frozen_skips_argv0(self, monkeypatch, restart_mocks):
        monkeypatch.setattr(al.sys, "frozen", True, raising=False)
        monkeypatch.setattr(al.sys, "argv", ["prog.exe", "--flag"])

        al.restart_program()

        restart_mocks.execl.assert_called_once_with(al.sys.executable, al.sys.executable, "--flag")

    def test_exitfunc_exception_is_swallowed(self, monkeypatch, restart_mocks):
        monkeypatch.delattr(al.sys, "frozen", raising=False)
        monkeypatch.setattr(al.sys, "argv", ["prog"])
        restart_mocks.exitfuncs.side_effect = RuntimeError("回调炸了")

        al.restart_program()  # 不应抛出异常

        restart_mocks.execl.assert_called_once()

    def test_execl_failure_notifies_and_exits(self, monkeypatch, restart_mocks, safe_input):
        monkeypatch.delattr(al.sys, "frozen", raising=False)
        monkeypatch.setattr(al.sys, "argv", ["prog"])
        restart_mocks.execl.side_effect = OSError("无法启动新进程")

        with pytest.raises(SystemExit) as excinfo:
            al.restart_program()

        assert excinfo.value.code == 1
        safe_input.assert_called_once()

    def test_broken_streams_are_tolerated(self, monkeypatch, restart_mocks):
        """stdout/stderr 没有 flush 属性（pythonw / 无控制台）时不应崩溃。"""
        monkeypatch.delattr(al.sys, "frozen", raising=False)
        monkeypatch.setattr(al.sys, "argv", ["prog"])
        monkeypatch.setattr(al.sys, "stdout", object())
        monkeypatch.setattr(al.sys, "stderr", object())

        al.restart_program()

        restart_mocks.execl.assert_called_once()


# ---------------------------------------------------------------------------
# 睡眠函数封装族
# ---------------------------------------------------------------------------


class TestSleepStoppable:
    def test_returns_true_after_normal_sleep(self, events):
        assert real_sleep_stoppable(0.001) is True

    def test_returns_false_when_exit_event_already_set(self, events):
        events.exit.set()

        assert real_sleep_stoppable(10) is False

    def test_returns_false_when_exit_during_sleep(self, events, monkeypatch):
        def wait_and_exit(timeout=None):
            events.exit.set()
            return True

        monkeypatch.setattr(events.exit, "wait", wait_and_exit)

        assert real_sleep_stoppable(10) is False


class TestSleepSmart:
    def test_returns_true_after_normal_sleep(self, events):
        assert real_sleep_smart(0.001) is True

    def test_returns_false_when_exit_event_already_set(self, events):
        events.exit.set()

        assert real_sleep_smart(10) is False

    def test_pause_does_not_consume_remaining_time(self, monkeypatch):
        """暂停期间计时器不前进：不能调用 time.monotonic 去扣减 remaining。"""
        exit_event = _StubEvent(set_after_waits=1)
        pause_event = _StubEvent(is_set=True)
        monkeypatch.setattr(al, "_exit_event", exit_event)
        monkeypatch.setattr(al, "_pause_event", pause_event)
        monotonic = MagicMock(name="monotonic", return_value=0.0)
        monkeypatch.setattr(al.time, "monotonic", monotonic)

        assert real_sleep_smart(5) is False

        assert exit_event.wait_calls == 1
        monotonic.assert_not_called()

    def test_pause_then_resume_still_completes(self, monkeypatch):
        """暂停期间反复轮询，退出信号到来后立即返回 False。"""
        exit_event = _StubEvent(set_after_waits=3)
        pause_event = _StubEvent(is_set=True)
        monkeypatch.setattr(al, "_exit_event", exit_event)
        monkeypatch.setattr(al, "_pause_event", pause_event)

        assert real_sleep_smart(5) is False
        assert exit_event.wait_calls == 3


# ---------------------------------------------------------------------------
# Windows 事件拦截
# ---------------------------------------------------------------------------


class TestWindowsEventHandler:
    def test_mark_cleanup_done_sets_event(self, events):
        al._mark_cleanup_done()

        assert events.cleanup.is_set() is True

    def test_console_ctrl_handler_close_event(self, events):
        events.cleanup.set()

        result = al._console_ctrl_handler(2)

        assert result is True
        assert events.exit.is_set() is True

    def test_console_ctrl_handler_ignores_other_events(self, events):
        result = al._console_ctrl_handler(1)

        assert result is False
        assert events.exit.is_set() is False

    def test_console_ctrl_handler_waits_for_cleanup(self, monkeypatch, events):
        """关闭事件处理函数应等待清理完成（此处用假的 event 记录等待行为）。"""
        waits = []

        def wait(timeout=None):
            waits.append(timeout)
            return True

        monkeypatch.setattr(events.cleanup, "wait", wait)
        events.exit.set()  # 避免重复设置

        assert al._console_ctrl_handler(2) is True
        assert waits == [4.5]


class TestInitLifecycleManager:
    def test_registers_atexit_and_console_handler(self, monkeypatch, block_atexit):
        handler_routine_cls = MagicMock(name="HandlerRoutine")
        handler = handler_routine_cls.return_value
        winfunctype = MagicMock(name="WINFUNCTYPE", return_value=handler_routine_cls)
        windll = MagicMock(name="windll")

        monkeypatch.setattr(al.ctypes, "WINFUNCTYPE", winfunctype)
        monkeypatch.setattr(al.ctypes, "windll", windll)
        monkeypatch.setattr(al, "_win_handler_ref", None)

        al.init_lifecycle_manager()

        block_atexit.assert_called_once_with(al._mark_cleanup_done)
        winfunctype.assert_called_once_with(al.wintypes.BOOL, al.wintypes.DWORD)
        handler_routine_cls.assert_called_once_with(al._console_ctrl_handler)
        windll.kernel32.SetConsoleCtrlHandler.assert_called_once_with(handler, True)
        assert al._win_handler_ref is handler
