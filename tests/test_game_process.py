"""``gta_automator.game_process`` 的单元测试。

所有 Windows API / 进程操作（``find_window``、``resume_process``、
``suspend_process_for_duration``、``kill_processes``、``close_window``）都在
``gta_automator.game_process`` 模块命名空间内被 mock，保证不会碰到真实窗口或进程。
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from gta_automator import game_process as gp_module
from gta_automator.constant import (
    GTA_ASSOCIATED_PROCESS_NAMES,
    GTA_PROCESS_NAME,
    GTA_WINDOW_CLASS_NAME,
    GTA_WINDOW_TITLE,
)
from gta_automator.game_process import GameProcess
from windows_utils import ResumeException, SuspendException

DEFAULT_WINDOW = (111, 222)


@pytest.fixture
def mocks():
    """把 GameProcess 依赖的所有底层函数替换成 mock，并让窗口查找默认成功。"""
    with (
        patch.object(gp_module, "find_window") as find_window,
        patch.object(gp_module, "get_window_title") as get_window_title,
        patch.object(gp_module, "get_process_name") as get_process_name,
        patch.object(gp_module, "kill_processes") as kill_processes,
        patch.object(gp_module, "close_window") as close_window,
        patch.object(gp_module, "resume_process") as resume_process,
        patch.object(gp_module, "suspend_process_for_duration") as suspend_process_for_duration,
    ):
        find_window.return_value = DEFAULT_WINDOW
        yield {
            "find_window": find_window,
            "get_window_title": get_window_title,
            "get_process_name": get_process_name,
            "kill_processes": kill_processes,
            "close_window": close_window,
            "resume_process": resume_process,
            "suspend_process_for_duration": suspend_process_for_duration,
        }


@pytest.fixture
def process(mocks) -> GameProcess:
    """一个已找到窗口（hwnd=111, pid=222）且已完成初始化的 GameProcess。"""
    return GameProcess()


class TestInit:
    def test_discovers_running_window(self, mocks):
        process = GameProcess()

        assert process.hwnd == 111
        assert process.pid == 222
        mocks["find_window"].assert_called_once_with(GTA_WINDOW_CLASS_NAME, GTA_WINDOW_TITLE)
        mocks["resume_process"].assert_called_once_with(222)

    def test_no_window_found_sets_none_and_skips_resume(self, mocks):
        mocks["find_window"].return_value = None

        process = GameProcess()

        assert process.hwnd is None
        assert process.pid is None
        mocks["resume_process"].assert_not_called()

    def test_init_with_explicit_hwnd_and_pid_skips_search(self, mocks):
        """传入 hwnd/pid 时应直接采用，不再搜索窗口（也不会被搜索结果覆盖）。"""
        process = GameProcess(hwnd=1, pid=2)

        assert (process.hwnd, process.pid) == (1, 2)
        mocks["find_window"].assert_not_called()
        mocks["resume_process"].assert_called_once_with(2)

    @pytest.mark.parametrize(("hwnd", "pid"), [(1, None), (None, 2)])
    def test_init_with_partial_args_falls_back_to_search(self, mocks, hwnd, pid):
        """只传其中一个时仍会搜索窗口补全信息。"""
        mocks["find_window"].return_value = (7, 8)

        process = GameProcess(hwnd=hwnd, pid=pid)

        assert (process.hwnd, process.pid) == (7, 8)
        mocks["find_window"].assert_called_once()


class TestUpdateInfo:
    def test_update_with_explicit_values(self, process: GameProcess, mocks):
        mocks["find_window"].reset_mock()

        process.update_info(hwnd=5, pid=6)

        assert (process.hwnd, process.pid) == (5, 6)
        mocks["find_window"].assert_not_called()

    @pytest.mark.parametrize(
        ("hwnd", "pid"),
        [(5, None), (None, 6), (None, None)],
    )
    def test_update_with_partial_values_falls_back_to_search(self, process: GameProcess, mocks, hwnd, pid):
        mocks["find_window"].return_value = (9, 10)
        mocks["find_window"].reset_mock()

        process.update_info(hwnd=hwnd, pid=pid)

        assert (process.hwnd, process.pid) == (9, 10)
        mocks["find_window"].assert_called_once()

    def test_update_clears_info_when_window_disappears(self, process: GameProcess, mocks):
        mocks["find_window"].return_value = None

        process.update_info()

        assert process.hwnd is None
        assert process.pid is None


class TestSuspend:
    def test_suspend_calls_process_suspend(self, process: GameProcess, mocks):
        process.suspend(13)

        mocks["suspend_process_for_duration"].assert_called_once_with(222, 13)

    def test_suspend_skipped_without_pid(self, mocks):
        mocks["find_window"].return_value = None
        process = GameProcess()

        process.suspend(13)

        mocks["suspend_process_for_duration"].assert_not_called()

    def test_value_error_triggers_info_refresh(self, process: GameProcess, mocks):
        mocks["suspend_process_for_duration"].side_effect = ValueError("无效 pid")
        mocks["find_window"].reset_mock()

        process.suspend(1)

        mocks["find_window"].assert_called_once()

    def test_suspend_exception_is_logged_not_raised(self, process: GameProcess, mocks):
        mocks["suspend_process_for_duration"].side_effect = SuspendException("挂起失败")

        process.suspend(1)  # 不应抛出异常

        assert process.pid == 222

    def test_resume_exception_triggers_kill(self, process: GameProcess, mocks):
        mocks["suspend_process_for_duration"].side_effect = ResumeException("恢复失败")

        process.suspend(1)

        mocks["kill_processes"].assert_called_once_with(GTA_ASSOCIATED_PROCESS_NAMES)
        assert process.pid is None


class TestResume:
    def test_resume_calls_process_resume(self, mocks):
        process = GameProcess()  # __init__ 中已经 resume 过一次

        process.resume()

        assert mocks["resume_process"].call_args_list == [((222,), {}), ((222,), {})]

    def test_resume_without_pid_does_nothing(self, mocks):
        mocks["find_window"].return_value = None
        process = GameProcess()

        process.resume()

        mocks["resume_process"].assert_not_called()

    def test_value_error_is_swallowed(self, mocks):
        process = GameProcess()
        mocks["resume_process"].side_effect = ValueError("进程已关闭")

        process.resume()  # 不应抛出异常

        mocks["kill_processes"].assert_not_called()

    def test_resume_exception_triggers_kill(self, mocks):
        process = GameProcess()
        mocks["resume_process"].side_effect = ResumeException("恢复失败")

        process.resume()

        mocks["kill_processes"].assert_called_once_with(GTA_ASSOCIATED_PROCESS_NAMES)


class TestKill:
    def test_kill_kills_and_clears_state(self, process: GameProcess, mocks):
        process.kill()

        mocks["kill_processes"].assert_called_once_with(GTA_ASSOCIATED_PROCESS_NAMES)
        assert process.hwnd is None
        assert process.pid is None


class TestRequestExit:
    def test_request_exit_closes_window(self, process: GameProcess, mocks):
        process.request_exit()

        mocks["close_window"].assert_called_once_with(111)

    def test_request_exit_without_hwnd_does_nothing(self, mocks):
        mocks["find_window"].return_value = None
        process = GameProcess()

        process.request_exit()

        mocks["close_window"].assert_not_called()

    def test_request_exit_wraps_exception(self, process: GameProcess, mocks):
        mocks["close_window"].side_effect = OSError("PostMessage 失败")

        with pytest.raises(Exception, match="触发 alt\\+f4 退出失败"):
            process.request_exit()


class TestStateChecks:
    def test_is_game_started_true(self, mocks):
        assert GameProcess.is_game_started() is True

    def test_is_game_started_false(self, mocks):
        mocks["find_window"].return_value = None

        assert GameProcess.is_game_started() is False

    def test_is_hwnd_valid_true(self, process: GameProcess, mocks):
        mocks["get_window_title"].return_value = GTA_WINDOW_TITLE

        assert process.is_hwnd_valid() is True
        mocks["get_window_title"].assert_called_once_with(111)

    @pytest.mark.parametrize(
        ("hwnd", "title_result", "expected"),
        [
            (111, "其他窗口", False),
            (111, None, False),
            (None, GTA_WINDOW_TITLE, False),
            (0, GTA_WINDOW_TITLE, False),
        ],
    )
    def test_is_hwnd_valid_false(self, process: GameProcess, mocks, hwnd, title_result, expected):
        process.hwnd = hwnd
        mocks["get_window_title"].return_value = title_result

        assert process.is_hwnd_valid() is expected

    def test_is_pid_vaild_true(self, process: GameProcess, mocks):
        mocks["get_process_name"].return_value = GTA_PROCESS_NAME

        assert process.is_pid_vaild() is True
        mocks["get_process_name"].assert_called_once_with(222)

    @pytest.mark.parametrize(
        ("pid", "name_result", "expected"),
        [
            (222, "notepad.exe", False),
            (222, None, False),
            (None, GTA_PROCESS_NAME, False),
            (0, GTA_PROCESS_NAME, False),
        ],
    )
    def test_is_pid_vaild_false(self, process: GameProcess, mocks, pid, name_result, expected):
        process.pid = pid
        mocks["get_process_name"].return_value = name_result

        assert process.is_pid_vaild() is expected


def test_atexit_resume_registered(mocks, block_atexit: MagicMock):
    """对象构造时应把 resume 注册到 atexit，避免程序退出时游戏被挂起。"""
    GameProcess()

    block_atexit.assert_called_once()
    assert block_atexit.call_args.args[0].__func__ is GameProcess.resume


def test_atexit_resume_restores_suspended_process(mocks, block_atexit: MagicMock):
    """atexit 回调执行时应真的去恢复进程。"""
    GameProcess()
    mocks["resume_process"].reset_mock()

    callback = block_atexit.call_args.args[0]
    callback()

    mocks["resume_process"].assert_called_once_with(222)
