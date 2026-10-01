"""``windows_utils.py`` 的单元测试。

所有 Windows API（``win32gui`` / ``win32api`` / ``win32process`` / ``win32clipboard`` /
``winreg`` / ``ctypes``）以及 ``psutil``、``subprocess`` 都在 ``windows_utils`` 模块命名
空间内被 mock，测试不会碰触真实窗口、进程、剪贴板或子进程。
"""

from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import psutil
import pytest
import win32clipboard

import windows_utils
from windows_utils import (
    ClipboardScope,
    ResumeException,
    SuspendException,
    close_window,
    enable_dpi_awareness,
    ensure_window_thread_resumed,
    exec_command_detached,
    find_window,
    get_document_fold_path,
    get_primary_monitor_dpi_scale,
    get_process_name,
    get_steam_exe_path,
    get_system_proxy,
    get_window_dpi_scale,
    get_window_thread_id,
    get_window_title,
    is_window_handler_exist,
    kill_processes,
    open_thread_handle,
    restore_minimized_window,
    resume_process,
    resume_thread,
    set_active_window,
    set_top_window,
    suspend_process_for_duration,
    suspend_thread,
    suspend_window_thread_for_duration,
    unset_top_window,
)


@pytest.fixture
def win32gui():
    """把 ``windows_utils.win32gui`` 整体替换为 mock，默认窗口有效。"""
    with patch("windows_utils.win32gui") as mock_gui:
        mock_gui.IsWindow.return_value = 1
        yield mock_gui


class TestSimpleQueries:
    def test_is_window_handler_exist_zero(self):
        assert is_window_handler_exist(0) is False

    def test_is_window_handler_exist_true(self, win32gui):
        assert is_window_handler_exist(123) is True
        win32gui.IsWindow.assert_called_once_with(123)

    def test_is_window_handler_exist_false(self, win32gui):
        win32gui.IsWindow.return_value = 0

        assert is_window_handler_exist(123) is False

    def test_is_window_handler_exist_swallows_exception(self, win32gui):
        win32gui.IsWindow.side_effect = OSError("坏句柄")

        assert is_window_handler_exist(123) is False

    def test_get_window_title_zero(self):
        assert get_window_title(0) is None

    def test_get_window_title_ok(self, win32gui):
        win32gui.GetWindowText.return_value = "Grand Theft Auto V"

        assert get_window_title(42) == "Grand Theft Auto V"

    def test_get_window_title_exception(self, win32gui):
        win32gui.GetWindowText.side_effect = OSError("窗口已关闭")

        assert get_window_title(42) is None

    def test_get_process_name_zero(self):
        assert get_process_name(0) is None

    def test_get_process_name_ok(self):
        with patch("windows_utils.psutil.Process") as mock_process:
            mock_process.return_value.name.return_value = "GTA5_Enhanced.exe"

            assert get_process_name(99) == "GTA5_Enhanced.exe"

    def test_get_process_name_exception(self):
        with patch("windows_utils.psutil.Process", side_effect=psutil.NoSuchProcess(99)):
            assert get_process_name(99) is None


class TestGetWindowThreadId:
    def test_requires_int(self):
        with pytest.raises(TypeError, match="整数"):
            get_window_thread_id("123")

    def test_zero_returns_none(self):
        assert get_window_thread_id(0) is None

    def test_returns_thread_id(self):
        with patch("windows_utils.win32process") as mock_process:
            mock_process.GetWindowThreadProcessId.return_value = (555, 666)

            assert get_window_thread_id(42) == 555
            mock_process.GetWindowThreadProcessId.assert_called_once_with(42)

    def test_zero_thread_id_returns_none(self):
        with patch("windows_utils.win32process") as mock_process:
            mock_process.GetWindowThreadProcessId.return_value = (0, 666)

            assert get_window_thread_id(42) is None

    def test_exception_returns_none(self):
        with patch("windows_utils.win32process") as mock_process:
            mock_process.GetWindowThreadProcessId.side_effect = OSError("窗口没了")

            assert get_window_thread_id(42) is None


class TestDpiHelpers:
    @pytest.mark.parametrize("version", [(10, 0, 19045), (6, 3, 9600)])
    def test_enable_dpi_awareness_modern(self, monkeypatch: pytest.MonkeyPatch, version):
        mock_ctypes = MagicMock()
        monkeypatch.setattr(windows_utils, "ctypes", mock_ctypes)
        monkeypatch.setattr("sys.getwindowsversion", lambda: version)

        assert enable_dpi_awareness() is True

        mock_ctypes.windll.shcore.SetProcessDpiAwareness.assert_called_once_with(2)
        mock_ctypes.windll.user32.SetProcessDPIAware.assert_not_called()

    @pytest.mark.parametrize("version", [(6, 1, 7601), (6, 2, 9200)])
    def test_enable_dpi_awareness_legacy(self, monkeypatch: pytest.MonkeyPatch, version):
        mock_ctypes = MagicMock()
        monkeypatch.setattr(windows_utils, "ctypes", mock_ctypes)
        monkeypatch.setattr("sys.getwindowsversion", lambda: version)

        assert enable_dpi_awareness() is True

        mock_ctypes.windll.user32.SetProcessDPIAware.assert_called_once()
        mock_ctypes.windll.shcore.SetProcessDpiAwareness.assert_not_called()

    def test_enable_dpi_awareness_failure(self, monkeypatch: pytest.MonkeyPatch):
        mock_ctypes = MagicMock()
        mock_ctypes.windll.shcore.SetProcessDpiAwareness.side_effect = OSError("无权限")
        monkeypatch.setattr(windows_utils, "ctypes", mock_ctypes)
        monkeypatch.setattr("sys.getwindowsversion", lambda: (10, 0, 19045))

        assert enable_dpi_awareness() is False

    @pytest.mark.parametrize(
        ("dpi", "expected"),
        [
            (96, 1.0),
            (120, 1.25),
            (144, 1.5),
        ],
    )
    def test_get_window_dpi_scale(self, monkeypatch: pytest.MonkeyPatch, dpi: int, expected: float):
        mock_ctypes = MagicMock()
        mock_ctypes.c_uint.side_effect = lambda *a, **k: SimpleNamespace(value=dpi)
        mock_ctypes.byref.side_effect = lambda obj: obj
        mock_ctypes.windll.shcore.GetDpiForMonitor.return_value = 0
        monkeypatch.setattr(windows_utils, "ctypes", mock_ctypes)
        with patch("windows_utils.win32api") as mock_api:
            mock_api.MonitorFromWindow.return_value = 1

            assert get_window_dpi_scale(42) == expected

    @pytest.mark.parametrize("hwnd", [0, None, "42"])
    def test_get_window_dpi_scale_invalid_hwnd(self, hwnd):
        assert get_window_dpi_scale(hwnd) == 1.0

    def test_get_window_dpi_scale_api_failure(self, monkeypatch: pytest.MonkeyPatch):
        mock_ctypes = MagicMock()
        mock_ctypes.c_uint.side_effect = lambda *a, **k: SimpleNamespace(value=120)
        mock_ctypes.byref.side_effect = lambda obj: obj
        mock_ctypes.windll.shcore.GetDpiForMonitor.return_value = 1
        monkeypatch.setattr(windows_utils, "ctypes", mock_ctypes)
        with patch("windows_utils.win32api"):
            assert get_window_dpi_scale(42) == 1.0

    def test_get_window_dpi_scale_exception(self, monkeypatch: pytest.MonkeyPatch):
        mock_ctypes = MagicMock()
        mock_ctypes.windll.shcore.GetDpiForMonitor.side_effect = OSError("shcore 不可用")
        monkeypatch.setattr(windows_utils, "ctypes", mock_ctypes)
        with patch("windows_utils.win32api"):
            assert get_window_dpi_scale(42) == 1.0

    def test_get_primary_monitor_dpi_scale(self):
        with patch("windows_utils.win32gui") as mock_gui, patch("windows_utils.win32print") as mock_print:
            mock_gui.GetDC.return_value = 100
            mock_print.GetDeviceCaps.return_value = 120

            assert get_primary_monitor_dpi_scale() == 1.25

            mock_gui.GetDC.assert_called_once_with(0)
            mock_print.GetDeviceCaps.assert_called_once_with(100, windows_utils.win32con.LOGPIXELSX)
            mock_gui.ReleaseDC.assert_called_once_with(0, 100)

    def test_get_primary_monitor_dpi_scale_no_hdc(self):
        with patch("windows_utils.win32gui") as mock_gui, patch("windows_utils.win32print") as mock_print:
            mock_gui.GetDC.return_value = 0
            mock_print.GetDeviceCaps.return_value = 96

            assert get_primary_monitor_dpi_scale() == 1.0

            mock_gui.ReleaseDC.assert_not_called()


class TestFindWindow:
    def test_requires_class_or_title(self):
        with pytest.raises(ValueError, match="窗口类名或窗口标题"):
            find_window()

    def test_not_found(self):
        with patch("windows_utils.win32gui") as mock_gui:
            mock_gui.FindWindow.return_value = 0

            assert find_window("cls", "title") is None

    def test_pid_zero(self):
        with patch("windows_utils.win32gui") as mock_gui, patch("windows_utils.win32process") as mock_process:
            mock_gui.FindWindow.return_value = 123
            mock_process.GetWindowThreadProcessId.return_value = (1, 0)

            assert find_window("cls", "title") is None

    def test_found(self):
        with patch("windows_utils.win32gui") as mock_gui, patch("windows_utils.win32process") as mock_process:
            mock_gui.FindWindow.return_value = 123
            mock_process.GetWindowThreadProcessId.return_value = (1, 456)

            assert find_window("cls", "title") == (123, 456)
            mock_gui.FindWindow.assert_called_once_with("cls", "title")


class TestThreadHandle:
    def test_open_and_close(self):
        with patch("windows_utils.win32api") as mock_api:
            mock_api.OpenThread.return_value = 42

            with open_thread_handle(7) as handle:
                assert handle == 42

            mock_api.OpenThread.assert_called_once_with(windows_utils.THREAD_SUSPEND_RESUME, False, 7)
            mock_api.CloseHandle.assert_called_once_with(42)

    def test_open_failure_raises_value_error(self):
        with patch("windows_utils.win32api") as mock_api:
            mock_api.OpenThread.return_value = 0

            with pytest.raises(ValueError, match="打开线程"), open_thread_handle(7):
                pass

            mock_api.CloseHandle.assert_not_called()

    def test_handle_closed_on_body_exception(self):
        with patch("windows_utils.win32api") as mock_api:
            mock_api.OpenThread.return_value = 42

            with pytest.raises(RuntimeError), open_thread_handle(7):
                raise RuntimeError("业务异常")

            mock_api.CloseHandle.assert_called_once_with(42)


@contextmanager
def _fake_thread_handle(tid: int):
    yield "thread-handle"


class TestSuspendResumeThread:
    def test_suspend_thread(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(windows_utils, "open_thread_handle", _fake_thread_handle)
        with patch("windows_utils.win32process") as mock_process:
            mock_process.SuspendThread.return_value = 0

            assert suspend_thread(7) == 0
            mock_process.SuspendThread.assert_called_once_with("thread-handle")

    def test_suspend_thread_failure(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(windows_utils, "open_thread_handle", _fake_thread_handle)
        with patch("windows_utils.win32process") as mock_process:
            mock_process.SuspendThread.return_value = -1

            with pytest.raises(SuspendException):
                suspend_thread(7)

    def test_suspend_thread_wraps_open_failure(self):
        def broken_handle(tid):
            raise ValueError("打不开线程")

        with (
            patch("windows_utils.open_thread_handle", broken_handle),
            pytest.raises(SuspendException, match="挂起线程"),
        ):
            suspend_thread(7)

    def test_resume_thread(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(windows_utils, "open_thread_handle", _fake_thread_handle)
        with patch("windows_utils.win32process") as mock_process:
            mock_process.ResumeThread.return_value = 2

            assert resume_thread(7) == 2

    def test_resume_thread_failure(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(windows_utils, "open_thread_handle", _fake_thread_handle)
        with patch("windows_utils.win32process") as mock_process:
            mock_process.ResumeThread.return_value = -1

            with pytest.raises(ResumeException):
                resume_thread(7)


class TestSuspendWindowThreadForDuration:
    def test_invalid_window(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(windows_utils, "get_window_thread_id", lambda hwnd: None)

        with pytest.raises(ValueError, match="未找到窗口"):
            suspend_window_thread_for_duration(42, 1)

    def test_zero_thread_id(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(windows_utils, "get_window_thread_id", lambda hwnd: 0)

        with pytest.raises(ValueError):
            suspend_window_thread_for_duration(42, 1)

    def test_suspend_then_resume(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(windows_utils, "get_window_thread_id", lambda hwnd: 555)
        suspend = MagicMock()
        resume = MagicMock()
        sleep = MagicMock()
        monkeypatch.setattr(windows_utils, "suspend_thread", suspend)
        monkeypatch.setattr(windows_utils, "resume_thread", resume)
        monkeypatch.setattr(windows_utils, "sleep_stoppable", sleep)

        suspend_window_thread_for_duration(42, 13)

        suspend.assert_called_once_with(555)
        sleep.assert_called_once_with(13)
        resume.assert_called_once_with(555)

    def test_suspend_failure_aborts(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(windows_utils, "get_window_thread_id", lambda hwnd: 555)
        monkeypatch.setattr(windows_utils, "suspend_thread", MagicMock(side_effect=SuspendException("失败")))
        resume = MagicMock()
        monkeypatch.setattr(windows_utils, "resume_thread", resume)

        with pytest.raises(SuspendException):
            suspend_window_thread_for_duration(42, 1)

        resume.assert_not_called()

    def test_resume_failure_propagates(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(windows_utils, "get_window_thread_id", lambda hwnd: 555)
        monkeypatch.setattr(windows_utils, "suspend_thread", MagicMock())
        monkeypatch.setattr(windows_utils, "resume_thread", MagicMock(side_effect=ResumeException("恢复失败")))
        monkeypatch.setattr(windows_utils, "sleep_stoppable", MagicMock())

        with pytest.raises(ResumeException):
            suspend_window_thread_for_duration(42, 1)


class TestEnsureWindowThreadResumed:
    def test_invalid_window(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(windows_utils, "get_window_thread_id", lambda hwnd: None)

        with pytest.raises(ValueError, match="未找到窗口"):
            ensure_window_thread_resumed(42)

    def test_already_resumed(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(windows_utils, "get_window_thread_id", lambda hwnd: 555)
        resume = MagicMock(return_value=0)
        monkeypatch.setattr(windows_utils, "resume_thread", resume)

        ensure_window_thread_resumed(42)

        resume.assert_called_once_with(555)

    def test_resumed_after_retry(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(windows_utils, "get_window_thread_id", lambda hwnd: 555)
        resume = MagicMock(side_effect=[1, 0])
        monkeypatch.setattr(windows_utils, "resume_thread", resume)
        monkeypatch.setattr(windows_utils, "sleep_stoppable", MagicMock())

        ensure_window_thread_resumed(42)

        assert resume.call_count == 2

    def test_gives_up_after_max_attempts(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(windows_utils, "get_window_thread_id", lambda hwnd: 555)
        resume = MagicMock(return_value=1)
        monkeypatch.setattr(windows_utils, "resume_thread", resume)
        monkeypatch.setattr(windows_utils, "sleep_stoppable", MagicMock())

        with pytest.raises(ResumeException, match="未能恢复线程"):
            ensure_window_thread_resumed(42)

        assert resume.call_count == 5

    def test_wraps_lower_level_failure(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(windows_utils, "get_window_thread_id", lambda hwnd: 555)
        monkeypatch.setattr(windows_utils, "resume_thread", MagicMock(side_effect=ResumeException("API 挂了")))

        with pytest.raises(ResumeException, match="底层API调用失败"):
            ensure_window_thread_resumed(42)


class TestProcessSuspendResume:
    def test_suspend_process_success(self, monkeypatch: pytest.MonkeyPatch):
        mock_process = MagicMock()
        monkeypatch.setattr(windows_utils.psutil, "Process", MagicMock(return_value=mock_process))
        resume = MagicMock()
        sleep = MagicMock()
        monkeypatch.setattr(windows_utils, "resume_process", resume)
        monkeypatch.setattr(windows_utils, "sleep_stoppable", sleep)

        suspend_process_for_duration(99, 13)

        mock_process.suspend.assert_called_once()
        sleep.assert_called_once_with(13)
        resume.assert_called_once_with(99)

    def test_suspend_missing_process(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(windows_utils.psutil, "Process", MagicMock(side_effect=psutil.NoSuchProcess(99)))
        resume = MagicMock()
        monkeypatch.setattr(windows_utils, "resume_process", resume)

        with pytest.raises(ValueError, match="未找到 PID"):
            suspend_process_for_duration(99, 13)

        # 即使抛异常，finally 也会尝试恢复
        resume.assert_called_once_with(99)

    def test_suspend_wraps_other_errors(self, monkeypatch: pytest.MonkeyPatch):
        mock_process = MagicMock()
        mock_process.suspend.side_effect = RuntimeError("内核拒绝")
        monkeypatch.setattr(windows_utils.psutil, "Process", MagicMock(return_value=mock_process))
        monkeypatch.setattr(windows_utils, "resume_process", MagicMock())

        with pytest.raises(SuspendException, match="挂起进程"):
            suspend_process_for_duration(99, 13)

    def test_resume_missing_process(self):
        with (
            patch("windows_utils.psutil.Process", side_effect=psutil.NoSuchProcess(99)),
            pytest.raises(ValueError, match="未找到 PID"),
        ):
            resume_process(99)

    def test_resume_process_closed_during_resume(self, monkeypatch: pytest.MonkeyPatch):
        mock_process = MagicMock()
        mock_process.resume.side_effect = psutil.NoSuchProcess(99)
        monkeypatch.setattr(windows_utils.psutil, "Process", MagicMock(return_value=mock_process))

        resume_process(99)  # 进程已关闭，静默返回

    @pytest.mark.parametrize(
        "status",
        [psutil.STATUS_RUNNING, psutil.STATUS_SLEEPING, psutil.STATUS_DISK_SLEEP, "parked"],
    )
    def test_resume_process_healthy_status(self, monkeypatch: pytest.MonkeyPatch, status: str):
        mock_process = MagicMock()
        mock_process.status.return_value = status
        monkeypatch.setattr(windows_utils.psutil, "Process", MagicMock(return_value=mock_process))
        monkeypatch.setattr(windows_utils, "sleep_stoppable", MagicMock())

        resume_process(99)

        mock_process.resume.assert_called_once()

    def test_resume_process_retries_when_stopped(self, monkeypatch: pytest.MonkeyPatch):
        mock_process = MagicMock()
        mock_process.status.side_effect = [psutil.STATUS_STOPPED, psutil.STATUS_RUNNING]
        monkeypatch.setattr(windows_utils.psutil, "Process", MagicMock(return_value=mock_process))
        monkeypatch.setattr(windows_utils, "sleep_stoppable", MagicMock())

        resume_process(99)

        assert mock_process.resume.call_count == 2

    @pytest.mark.parametrize("status", [psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD])
    def test_resume_process_rejects_dead_process(self, monkeypatch: pytest.MonkeyPatch, status: str):
        mock_process = MagicMock()
        mock_process.status.return_value = status
        monkeypatch.setattr(windows_utils.psutil, "Process", MagicMock(return_value=mock_process))
        monkeypatch.setattr(windows_utils, "sleep_stoppable", MagicMock())

        with pytest.raises(ResumeException, match="僵尸或死亡"):
            resume_process(99)

    def test_resume_process_gives_up_after_retries(self, monkeypatch: pytest.MonkeyPatch):
        mock_process = MagicMock()
        mock_process.status.return_value = psutil.STATUS_STOPPED
        monkeypatch.setattr(windows_utils.psutil, "Process", MagicMock(return_value=mock_process))
        monkeypatch.setattr(windows_utils, "sleep_stoppable", MagicMock())

        with pytest.raises(ResumeException, match="无法恢复进程"):
            resume_process(99, max_retries=3)

    def test_resume_process_disappears_during_check(self, monkeypatch: pytest.MonkeyPatch):
        mock_process = MagicMock()
        mock_process.status.side_effect = psutil.NoSuchProcess(99)
        monkeypatch.setattr(windows_utils.psutil, "Process", MagicMock(return_value=mock_process))
        monkeypatch.setattr(windows_utils, "sleep_stoppable", MagicMock())

        resume_process(99)  # 静默返回


class TestKillProcesses:
    def test_kills_each_process_name(self):
        with patch("windows_utils.subprocess.run") as mock_run:
            kill_processes(["a.exe", "b.exe"])

        assert mock_run.call_args_list[0].args[0] == ["taskkill", "/F", "/IM", "a.exe", "/T"]
        assert mock_run.call_args_list[1].args[0] == ["taskkill", "/F", "/IM", "b.exe", "/T"]
        assert mock_run.call_args_list[0].kwargs == {"check": True, "capture_output": True, "text": True}

    def test_missing_process_is_ignored(self):
        with patch("windows_utils.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(128, "taskkill")

            kill_processes(["a.exe"])  # 不应抛出异常

    def test_other_return_code_only_warns(self):
        with patch("windows_utils.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "taskkill", stderr="拒绝访问")

            kill_processes(["a.exe"])  # 不应抛出异常

    def test_taskkill_not_found(self):
        with (
            patch("windows_utils.subprocess.run", side_effect=FileNotFoundError),
            pytest.raises(Exception, match="taskkill"),
        ):
            kill_processes(["a.exe"])

    def test_unknown_error_is_swallowed(self):
        with patch("windows_utils.subprocess.run", side_effect=RuntimeError("奇怪错误")):
            kill_processes(["a.exe"])  # 不应抛出异常


class TestCloseAndWindowState:
    def test_close_window_invalid(self, win32gui):
        win32gui.IsWindow.return_value = 0

        with pytest.raises(ValueError, match="未找到句柄"):
            close_window(42)

    def test_close_window_posts_message(self, win32gui):
        close_window(42)

        win32gui.PostMessage.assert_called_once_with(42, windows_utils.WM_CLOSE, 0, 0)

    def test_set_active_window_invalid(self, win32gui):
        win32gui.IsWindow.return_value = 0

        set_active_window(42)

        win32gui.ShowWindow.assert_not_called()
        win32gui.SetForegroundWindow.assert_not_called()

    def test_set_active_window_restores_and_focuses(self, win32gui, monkeypatch: pytest.MonkeyPatch):
        win32gui.IsIconic.return_value = True
        win32gui.GetForegroundWindow.return_value = 1
        sleep = MagicMock()
        monkeypatch.setattr(windows_utils, "sleep_smart", sleep)

        set_active_window(42)

        win32gui.ShowWindow.assert_called_once_with(42, windows_utils.SW_RESTORE)
        sleep.assert_called_once_with(0.2)
        win32gui.SetForegroundWindow.assert_called_once_with(42)

    def test_set_active_window_skips_foreground_when_already_active(self, win32gui):
        win32gui.IsIconic.return_value = False
        win32gui.GetForegroundWindow.return_value = 42

        set_active_window(42)

        win32gui.SetForegroundWindow.assert_not_called()

    def test_set_active_window_wraps_error(self, win32gui):
        win32gui.IsIconic.side_effect = OSError("窗口消失")

        with pytest.raises(Exception, match="激活窗口"):
            set_active_window(42)

    def test_restore_minimized_window_invalid(self, win32gui):
        win32gui.IsWindow.return_value = 0

        assert restore_minimized_window(42) is False

    def test_restore_minimized_window_not_iconic(self, win32gui):
        win32gui.IsIconic.return_value = False

        assert restore_minimized_window(42) is False
        win32gui.ShowWindow.assert_not_called()

    def test_restore_minimized_window_iconic(self, win32gui):
        win32gui.IsIconic.return_value = True

        assert restore_minimized_window(42) is True
        win32gui.ShowWindow.assert_called_once_with(42, windows_utils.SW_RESTORE)

    def test_restore_minimized_window_wraps_error(self, win32gui):
        win32gui.IsIconic.side_effect = OSError("窗口消失")

        with pytest.raises(Exception, match="恢复窗口"):
            restore_minimized_window(42)

    def test_set_top_window_invalid(self, win32gui):
        win32gui.IsWindow.return_value = 0

        set_top_window(42)

        win32gui.SetWindowPos.assert_not_called()

    def test_set_top_window(self, win32gui, monkeypatch: pytest.MonkeyPatch):
        win32gui.IsIconic.return_value = False
        monkeypatch.setattr(windows_utils, "restore_minimized_window", MagicMock(return_value=False))

        set_top_window(42)

        win32gui.SetWindowPos.assert_called_once_with(
            42,
            windows_utils.HWND_TOPMOST,
            0,
            0,
            0,
            0,
            windows_utils.SWP_NOMOVE
            | windows_utils.SWP_NOSIZE
            | windows_utils.SWP_SHOWWINDOW
            | windows_utils.SWP_NOACTIVATE,
        )

    def test_set_top_window_restores_first(self, win32gui, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(windows_utils, "restore_minimized_window", MagicMock(return_value=True))
        sleep = MagicMock()
        monkeypatch.setattr(windows_utils, "sleep_smart", sleep)

        set_top_window(42)

        sleep.assert_called_once_with(0.2)

    def test_set_top_window_wraps_error(self, win32gui):
        win32gui.SetWindowPos.side_effect = OSError("失败")

        with pytest.raises(Exception, match="置顶窗口"):
            set_top_window(42)

    def test_unset_top_window_invalid(self, win32gui):
        win32gui.IsWindow.return_value = 0

        unset_top_window(42)

        win32gui.SetWindowPos.assert_not_called()

    def test_unset_top_window(self, win32gui):
        unset_top_window(42)

        win32gui.SetWindowPos.assert_called_once_with(
            42,
            windows_utils.HWND_NOTOPMOST,
            0,
            0,
            0,
            0,
            windows_utils.SWP_NOMOVE
            | windows_utils.SWP_NOSIZE
            | windows_utils.SWP_SHOWWINDOW
            | windows_utils.SWP_NOACTIVATE,
        )

    def test_unset_top_window_wraps_error(self, win32gui):
        win32gui.SetWindowPos.side_effect = OSError("失败")

        with pytest.raises(Exception, match="取消置顶窗口"):
            unset_top_window(42)


class TestPathAndProxyHelpers:
    def test_get_document_fold_path_success(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        mock_ctypes = MagicMock()
        mock_ctypes.create_unicode_buffer.return_value.value = str(tmp_path)
        monkeypatch.setattr(windows_utils, "ctypes", mock_ctypes)

        assert get_document_fold_path() == tmp_path
        mock_ctypes.windll.shell32.SHGetFolderPathW.assert_called_once()
        args = mock_ctypes.windll.shell32.SHGetFolderPathW.call_args.args
        assert args[0] is None
        assert args[1] == 5
        assert args[3] == 0

    def test_get_document_fold_path_fallback(self, monkeypatch: pytest.MonkeyPatch):
        mock_ctypes = MagicMock()
        mock_ctypes.windll.shell32.SHGetFolderPathW.side_effect = OSError("API 失败")
        monkeypatch.setattr(windows_utils, "ctypes", mock_ctypes)

        assert get_document_fold_path() == Path.home() / "Documents"

    def test_get_steam_exe_path_success(self):
        with patch("windows_utils.winreg") as mock_winreg:
            mock_winreg.QueryValueEx.return_value = ("C:\\Steam\\steam.exe", 1)

            assert get_steam_exe_path() == "C:\\Steam\\steam.exe"
            mock_winreg.OpenKey.assert_called_once_with(mock_winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
            mock_winreg.CloseKey.assert_called_once()

    def test_get_steam_exe_path_missing_key(self):
        with patch("windows_utils.winreg") as mock_winreg:
            mock_winreg.OpenKey.side_effect = FileNotFoundError

            assert get_steam_exe_path() is None

    def test_get_steam_exe_path_unknown_error(self):
        with patch("windows_utils.winreg") as mock_winreg:
            mock_winreg.OpenKey.side_effect = OSError("注册表损坏")

            assert get_steam_exe_path() is None

    def test_get_system_proxy_prefers_http(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(windows_utils, "getproxies", lambda: {"http": "http://a", "socks": "socks5://b"})

        assert get_system_proxy() == "http://a"

    def test_get_system_proxy_falls_back_to_socks(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(windows_utils, "getproxies", lambda: {"socks": "socks5://b"})

        assert get_system_proxy() == "socks5://b"

    def test_get_system_proxy_none(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(windows_utils, "getproxies", dict)

        assert get_system_proxy() is None

    def test_get_system_proxy_hides_node_env_proxy(self, monkeypatch: pytest.MonkeyPatch):
        seen = {}

        def fake_getproxies():
            seen["during"] = os.environ.get("NODE_USE_ENV_PROXY")
            return {"http": "http://a"}

        monkeypatch.setenv("NODE_USE_ENV_PROXY", "1")
        monkeypatch.setattr(windows_utils, "getproxies", fake_getproxies)

        assert get_system_proxy() == "http://a"
        assert seen["during"] is None
        assert os.environ.get("NODE_USE_ENV_PROXY") == "1"

    def test_exec_command_detached(self):
        with patch("windows_utils.subprocess.Popen") as mock_popen:
            exec_command_detached(["explorer.exe", "steam://rungameid/1"])

        mock_popen.assert_called_once_with(
            ["explorer.exe", "steam://rungameid/1"],
            shell=False,
            creationflags=subprocess.CREATE_BREAKAWAY_FROM_JOB,
            close_fds=True,
        )

    def test_exec_command_detached_wraps_error(self):
        with (
            patch("windows_utils.subprocess.Popen", side_effect=OSError("找不到")),
            pytest.raises(Exception, match="执行命令"),
        ):
            exec_command_detached(["notepad.exe"])


class TestClipboardScopeFormats:
    def test_unsupported_single_formats(self):
        scope = ClipboardScope()

        assert scope._should_skip_format(win32clipboard.CF_BITMAP) is True
        assert scope._should_skip_format(win32clipboard.CF_DSPTEXT) is True

    def test_unsupported_gdi_range(self):
        scope = ClipboardScope()

        assert scope._should_skip_format(ClipboardScope.CF_GDIOBJFIRST) is True
        assert scope._should_skip_format(ClipboardScope.CF_GDIOBJLAST) is True

    def test_supported_formats(self):
        scope = ClipboardScope()

        assert scope._should_skip_format(win32clipboard.CF_TEXT) is False
        assert scope._should_skip_format(win32clipboard.CF_UNICODETEXT) is False
        assert scope._should_skip_format(ClipboardScope.CF_GDIOBJLAST + 1) is False


class TestClipboardScopeBackupRestore:
    def test_backup_enumerates_and_stores(self):
        with patch("windows_utils.win32clipboard") as mock_clipboard:
            mock_clipboard.EnumClipboardFormats.side_effect = [13, 1, 0]
            mock_clipboard.GetClipboardData.side_effect = ["文本", b"bytes"]
            scope = ClipboardScope()

            scope._backup()

        assert scope.backup_success is True
        assert scope.backup_data == {13: "文本", 1: b"bytes"}
        mock_clipboard.OpenClipboard.assert_called_once()
        mock_clipboard.CloseClipboard.assert_called_once()

    def test_backup_skips_unsupported_and_broken_formats(self):
        with patch("windows_utils.win32clipboard") as mock_clipboard:
            mock_clipboard.EnumClipboardFormats.side_effect = [
                win32clipboard.CF_BITMAP,
                13,
                1,
                0,
            ]
            mock_clipboard.GetClipboardData.side_effect = ["文本", ValueError("内存被锁")]
            scope = ClipboardScope()

            scope._backup()

        assert scope.backup_data == {13: "文本"}

    def test_backup_fails_when_clipboard_locked(self):
        with patch("windows_utils.win32clipboard") as mock_clipboard:
            mock_clipboard.OpenClipboard.side_effect = OSError("被占用")
            scope = ClipboardScope(max_retries=3, retry_interval=0)

            with pytest.raises(Exception, match="无法打开剪贴板"):
                scope._backup()

            assert mock_clipboard.OpenClipboard.call_count == 3
            mock_clipboard.CloseClipboard.assert_not_called()

    def test_restore_noop_without_backup(self):
        with patch("windows_utils.win32clipboard") as mock_clipboard:
            scope = ClipboardScope()

            scope._restore()

        mock_clipboard.EmptyClipboard.assert_not_called()
        mock_clipboard.SetClipboardData.assert_not_called()

    def test_restore_writes_back_all_formats(self):
        with patch("windows_utils.win32clipboard") as mock_clipboard:
            order = []
            mock_clipboard.EmptyClipboard.side_effect = lambda: order.append("empty")
            mock_clipboard.SetClipboardData.side_effect = lambda fmt, data: order.append(("set", fmt))
            scope = ClipboardScope()
            scope.backup_success = True
            scope.backup_data = {13: "文本", 1: b"bytes"}

            scope._restore()

        assert order[0] == "empty"
        assert ("set", 13) in order
        assert ("set", 1) in order
        mock_clipboard.CloseClipboard.assert_called_once()

    def test_restore_tolerates_single_format_failure(self):
        with patch("windows_utils.win32clipboard") as mock_clipboard:
            mock_clipboard.SetClipboardData.side_effect = [ValueError("不支持"), None]
            scope = ClipboardScope()
            scope.backup_success = True
            scope.backup_data = {13: "文本", 1: b"bytes"}

            scope._restore()  # 不应抛出异常

        assert mock_clipboard.SetClipboardData.call_count == 2

    def test_enter_and_exit_restore(self, monkeypatch: pytest.MonkeyPatch):
        scope = ClipboardScope()
        backup = MagicMock()
        restore = MagicMock()
        monkeypatch.setattr(scope, "_backup", backup)
        monkeypatch.setattr(scope, "_restore", restore)
        sleep = MagicMock()
        monkeypatch.setattr(windows_utils, "sleep_smart", sleep)

        with scope as entered:
            assert entered is scope

        backup.assert_called_once()
        restore.assert_not_called()  # backup_success 为 False

    def test_exit_restores_after_successful_backup(self, monkeypatch: pytest.MonkeyPatch):
        scope = ClipboardScope()
        scope.backup_success = True
        restore = MagicMock()
        monkeypatch.setattr(scope, "_restore", restore)
        sleep = MagicMock()
        monkeypatch.setattr(windows_utils, "sleep_smart", sleep)

        scope.__exit__(None, None, None)

        sleep.assert_called_once_with(0.05)
        restore.assert_called_once()

    def test_enter_swallows_backup_failure(self, monkeypatch: pytest.MonkeyPatch):
        scope = ClipboardScope()
        monkeypatch.setattr(scope, "_backup", MagicMock(side_effect=OSError("读不了")))

        assert scope.__enter__() is scope

    def test_exit_swallows_restore_failure(self, monkeypatch: pytest.MonkeyPatch):
        scope = ClipboardScope()
        scope.backup_success = True
        monkeypatch.setattr(scope, "_restore", MagicMock(side_effect=OSError("写不了")))
        monkeypatch.setattr(windows_utils, "sleep_smart", MagicMock())

        scope.__exit__(None, None, None)  # 不应抛出异常

    def test_preserve_clipboard_decorator(self, monkeypatch: pytest.MonkeyPatch):
        events = []

        class FakeScope:
            def __enter__(self):
                events.append("enter")
                return self

            def __exit__(self, *exc_info):
                events.append("exit")

        decorator = ClipboardScope._preserve_clipboard_decorator
        monkeypatch.setattr(windows_utils, "ClipboardScope", FakeScope)

        @decorator
        def do_work(value):
            events.append("work")
            return value * 2

        assert do_work(21) == 42
        assert events == ["enter", "work", "exit"]
