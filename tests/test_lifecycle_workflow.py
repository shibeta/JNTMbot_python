"""``gta_automator.lifecycle_workflow`` 的单元测试。

覆盖游戏启动、关闭、重启以及进入在线模式的完整状态机 ``LifecycleWorkflow``。

所有底层依赖（``screen`` / ``action`` / ``process``）均用 ``MagicMock`` 注入，
``exec_command_detached`` 也在模块命名空间内被 mock，休眠由 autouse fixture 拦截，
因此不会有任何真实的窗口、进程或 Steam 操作发生。
"""

from __future__ import annotations

from typing import NamedTuple
from unittest.mock import MagicMock, patch

import pytest

from gta_automator import lifecycle_workflow as lw_module
from gta_automator.exception import (
    GameState,
    OperationTimeout,
    OperationTimeoutContext,
    UIElement,
    UIElementNotFound,
    UnexpectedGameState,
)
from gta_automator.lifecycle_workflow import LifecycleWorkflow


class LifecycleHarness(NamedTuple):
    """把 LifecycleWorkflow 及其全部依赖打包，方便用例断言。"""

    workflow: LifecycleWorkflow
    screen: MagicMock
    action: MagicMock
    process: MagicMock


@pytest.fixture
def wf(config) -> LifecycleHarness:
    screen = MagicMock(name="screen")
    # 默认不在警告页面，避免 handle_warning_page 误判
    screen.is_on_warning_page.return_value = False
    action = MagicMock(name="action")
    process = MagicMock(name="process")
    workflow = LifecycleWorkflow(screen, action, process, config)
    return LifecycleHarness(workflow, screen, action, process)


class TestIsGameReady:
    """``is_game_ready`` 的游戏状态判定。"""

    def test_returns_false_without_valid_window(self, wf: LifecycleHarness):
        wf.process.is_hwnd_valid.return_value = False

        assert wf.workflow.is_game_ready() is False
        wf.process.resume.assert_not_called()

    def test_returns_true_when_already_online(self, wf: LifecycleHarness):
        wf.process.is_hwnd_valid.return_value = True
        with (
            patch.object(wf.workflow, "handle_warning_page", return_value=False) as warning,
            patch.object(wf.workflow, "check_if_in_onlinemode", return_value=True) as check,
            patch.object(wf.workflow, "exit_job_panel") as exit_panel,
        ):
            assert wf.workflow.is_game_ready() is True

        wf.process.resume.assert_called_once_with()
        warning.assert_called_once_with()
        check.assert_called_once_with()
        exit_panel.assert_not_called()

    def test_exits_job_panel_then_checks_online_again(self, wf: LifecycleHarness):
        wf.process.is_hwnd_valid.return_value = True
        with (
            patch.object(wf.workflow, "handle_warning_page", return_value=False),
            patch.object(wf.workflow, "check_if_in_onlinemode", side_effect=[False, True]),
            patch.object(wf.workflow, "exit_job_panel") as exit_panel,
        ):
            assert wf.workflow.is_game_ready() is True

        exit_panel.assert_called_once_with()

    def test_returns_false_when_never_online(self, wf: LifecycleHarness):
        wf.process.is_hwnd_valid.return_value = True
        with (
            patch.object(wf.workflow, "handle_warning_page", return_value=False),
            patch.object(wf.workflow, "check_if_in_onlinemode", side_effect=[False, False]) as check,
            patch.object(wf.workflow, "exit_job_panel"),
        ):
            assert wf.workflow.is_game_ready() is False

        assert check.call_count == 2

    def test_unexpected_game_state_is_swallowed(self, wf: LifecycleHarness):
        wf.process.is_hwnd_valid.return_value = True
        with (
            patch.object(wf.workflow, "handle_warning_page", return_value=False),
            patch.object(
                wf.workflow,
                "check_if_in_onlinemode",
                side_effect=UnexpectedGameState(GameState.ON, GameState.OFF),
            ),
        ):
            assert wf.workflow.is_game_ready() is False


class TestShutdown:
    """``shutdown`` 的常规退出与强制退出分支。"""

    def test_skips_when_game_not_started(self, wf: LifecycleHarness):
        wf.process.is_game_started.return_value = False

        wf.workflow.shutdown()

        wf.process.request_exit.assert_not_called()
        wf.screen.is_on_exit_confirm_page.assert_not_called()
        wf.process.update_info.assert_called_once_with()
        wf.process.kill.assert_not_called()

    def test_normal_exit_path(self, wf: LifecycleHarness):
        wf.process.is_game_started.side_effect = [True, False]
        wf.screen.is_on_exit_confirm_page.return_value = True
        with patch.object(wf.workflow, "wait_for_state", side_effect=[True, True]) as wait:
            wf.workflow.shutdown()

        assert wait.call_count == 2
        wf.process.request_exit.assert_called_once_with()
        wf.action.confirm.assert_called_once_with()
        wf.process.update_info.assert_called_once_with()
        wf.process.kill.assert_not_called()

    def test_process_close_timeout_falls_back_to_force_shutdown(self, wf: LifecycleHarness):
        wf.process.is_game_started.side_effect = [True, True]
        wf.screen.is_on_exit_confirm_page.return_value = True
        with patch.object(wf.workflow, "wait_for_state", side_effect=[True, False]):
            wf.workflow.shutdown()  # UnexpectedGameState 被内部捕获

        wf.process.update_info.assert_called_once_with()
        wf.process.kill.assert_called_once_with()

    def test_missing_exit_confirm_page_falls_back_to_force_shutdown(self, wf: LifecycleHarness):
        wf.process.is_game_started.side_effect = [True, True]
        wf.screen.is_on_exit_confirm_page.return_value = False
        with patch.object(wf.workflow, "wait_for_state") as wait:
            wf.workflow.shutdown()

        wait.assert_not_called()
        wf.process.kill.assert_called_once_with()

    def test_missing_exit_confirm_button_falls_back_to_force_shutdown(self, wf: LifecycleHarness):
        wf.process.is_game_started.side_effect = [True, True]
        wf.screen.is_on_exit_confirm_page.return_value = True
        with patch.object(wf.workflow, "wait_for_state", return_value=False):
            wf.workflow.shutdown()

        wf.process.update_info.assert_called_once_with()
        wf.process.kill.assert_called_once_with()

    def test_update_info_called_even_if_status_check_raises(self, wf: LifecycleHarness):
        wf.process.is_game_started.side_effect = [RuntimeError("窗口查询失败"), False]

        wf.workflow.shutdown()

        wf.process.update_info.assert_called_once_with()
        wf.process.kill.assert_not_called()

    def test_force_shutdown_kills_process(self, wf: LifecycleHarness):
        wf.workflow.force_shutdown()

        wf.process.kill.assert_called_once_with()


class TestLaunch:
    """``launch`` 的异常分支与关闭策略。"""

    def test_happy_path(self, wf: LifecycleHarness):
        with (
            patch.object(wf.workflow, "start_via_steam") as start,
            patch.object(wf.workflow, "enter_storymode_from_mainmenu") as story,
            patch.object(wf.workflow, "enter_onlinemode_from_storymode") as online,
            patch.object(wf.workflow, "shutdown") as shutdown,
        ):
            wf.workflow.launch()

        start.assert_called_once_with()
        story.assert_called_once_with()
        online.assert_called_once_with()
        shutdown.assert_not_called()

    def test_start_failure_shuts_down(self, wf: LifecycleHarness):
        with (
            patch.object(
                wf.workflow,
                "start_via_steam",
                side_effect=OperationTimeout(OperationTimeoutContext.GAME_WINDOW_STARTUP),
            ),
            patch.object(wf.workflow, "enter_storymode_from_mainmenu") as story,
            patch.object(wf.workflow, "shutdown") as shutdown,
        ):
            wf.workflow.launch()

        shutdown.assert_called_once_with()
        story.assert_not_called()

    def test_storymode_failure_shuts_down(self, wf: LifecycleHarness):
        with (
            patch.object(wf.workflow, "start_via_steam"),
            patch.object(
                wf.workflow,
                "enter_storymode_from_mainmenu",
                side_effect=OperationTimeout(OperationTimeoutContext.STORY_MODE_LOAD),
            ),
            patch.object(wf.workflow, "enter_onlinemode_from_storymode") as online,
            patch.object(wf.workflow, "shutdown") as shutdown,
        ):
            wf.workflow.launch()

        shutdown.assert_called_once_with()
        online.assert_not_called()

    def test_bad_pcsetting_shuts_down_and_repairs(self, wf: LifecycleHarness):
        with (
            patch.object(wf.workflow, "start_via_steam"),
            patch.object(wf.workflow, "enter_storymode_from_mainmenu"),
            patch.object(
                wf.workflow,
                "enter_onlinemode_from_storymode",
                side_effect=UnexpectedGameState(GameState.ONLINE_FREEMODE, GameState.BAD_PCSETTING_BIN),
            ),
            patch.object(wf.workflow, "shutdown") as shutdown,
            patch.object(wf.workflow, "fix_bad_pcsetting") as fix,
        ):
            wf.workflow.launch()

        shutdown.assert_called_once_with()
        fix.assert_called_once_with()

    def test_other_unexpected_state_only_shuts_down(self, wf: LifecycleHarness):
        with (
            patch.object(wf.workflow, "start_via_steam"),
            patch.object(wf.workflow, "enter_storymode_from_mainmenu"),
            patch.object(
                wf.workflow,
                "enter_onlinemode_from_storymode",
                side_effect=UnexpectedGameState(GameState.ONLINE_FREEMODE, GameState.MAIN_MENU),
            ),
            patch.object(wf.workflow, "shutdown") as shutdown,
            patch.object(wf.workflow, "fix_bad_pcsetting") as fix,
        ):
            wf.workflow.launch()

        shutdown.assert_called_once_with()
        fix.assert_not_called()

    def test_game_automator_exception_shuts_down(self, wf: LifecycleHarness):
        with (
            patch.object(wf.workflow, "start_via_steam"),
            patch.object(wf.workflow, "enter_storymode_from_mainmenu"),
            patch.object(
                wf.workflow,
                "enter_onlinemode_from_storymode",
                side_effect=OperationTimeout(OperationTimeoutContext.JOIN_ONLINE_SESSION),
            ),
            patch.object(wf.workflow, "shutdown") as shutdown,
        ):
            wf.workflow.launch()

        shutdown.assert_called_once_with()


class TestRestart:
    """``restart`` 的重试与失败处理。"""

    def test_force_restart_uses_force_shutdown(self, wf: LifecycleHarness):
        wf.process.is_game_started.return_value = True
        with (
            patch.object(wf.workflow, "force_shutdown") as force,
            patch.object(wf.workflow, "shutdown") as normal,
            patch.object(wf.workflow, "launch") as launch,
        ):
            wf.workflow.restart(force=True)

        # 进入循环前先强制关闭一次，循环内每次尝试前再强制关闭一次
        assert force.call_count == 2
        normal.assert_not_called()
        launch.assert_called_once_with()

    def test_normal_restart_uses_shutdown(self, wf: LifecycleHarness):
        wf.process.is_game_started.return_value = True
        with (
            patch.object(wf.workflow, "force_shutdown") as force,
            patch.object(wf.workflow, "shutdown") as normal,
            patch.object(wf.workflow, "launch"),
        ):
            wf.workflow.restart(force=False)

        normal.assert_called_once_with()
        force.assert_called_once_with()

    def test_success_on_first_attempt(self, wf: LifecycleHarness):
        wf.workflow.config.restartGTAConsecutiveFailThreshold = 3
        wf.process.is_game_started.return_value = True
        with (
            patch.object(wf.workflow, "force_shutdown"),
            patch.object(wf.workflow, "shutdown"),
            patch.object(wf.workflow, "launch") as launch,
        ):
            wf.workflow.restart(force=True)

        launch.assert_called_once_with()

    def test_succeeds_after_retries(self, wf: LifecycleHarness):
        wf.workflow.config.restartGTAConsecutiveFailThreshold = 3
        wf.process.is_game_started.side_effect = [False, False, True]
        with (
            patch.object(wf.workflow, "force_shutdown") as force,
            patch.object(wf.workflow, "shutdown"),
            patch.object(wf.workflow, "launch") as launch,
        ):
            wf.workflow.restart(force=True)

        assert launch.call_count == 3
        # 1 次循环前的强制关闭 + 3 次尝试前的强制关闭
        assert force.call_count == 4

    def test_all_attempts_failed_raises(self, wf: LifecycleHarness):
        wf.workflow.config.restartGTAConsecutiveFailThreshold = 2
        wf.process.is_game_started.return_value = False
        with (
            patch.object(wf.workflow, "force_shutdown") as force,
            patch.object(wf.workflow, "shutdown") as normal,
            patch.object(wf.workflow, "launch") as launch,
            pytest.raises(UnexpectedGameState) as excinfo,
        ):
            wf.workflow.restart(force=True)

        assert excinfo.value.expected == GameState.ON
        assert excinfo.value.actual_state == GameState.UNKNOWN
        assert launch.call_count == 2
        # 1 次循环前的强制关闭 + 2 次尝试前的强制关闭
        assert force.call_count == 3
        normal.assert_not_called()

    def test_all_attempts_failed_but_game_running_shuts_down(self, wf: LifecycleHarness):
        wf.workflow.config.restartGTAConsecutiveFailThreshold = 2
        wf.process.is_game_started.side_effect = [False, False, True]
        with (
            patch.object(wf.workflow, "force_shutdown"),
            patch.object(wf.workflow, "shutdown") as normal,
            patch.object(wf.workflow, "launch"),
            pytest.raises(UnexpectedGameState),
        ):
            wf.workflow.restart(force=True)

        normal.assert_called_once_with()

    def test_threshold_below_one_still_tries_once(self, wf: LifecycleHarness):
        wf.workflow.config.restartGTAConsecutiveFailThreshold = 0
        wf.process.is_game_started.return_value = False
        with (
            patch.object(wf.workflow, "force_shutdown"),
            patch.object(wf.workflow, "shutdown"),
            patch.object(wf.workflow, "launch") as launch,
            pytest.raises(UnexpectedGameState),
        ):
            wf.workflow.restart(force=True)

        launch.assert_called_once_with()


class TestStartViaSteam:
    """``start_via_steam`` 的启动命令与信息刷新。"""

    def test_already_running_only_updates_info(self, wf: LifecycleHarness):
        wf.process.is_game_started.return_value = True
        with patch.object(lw_module, "exec_command_detached") as exec_cmd:
            wf.workflow.start_via_steam()

        exec_cmd.assert_not_called()
        wf.process.update_info.assert_called_once_with()

    def test_launches_through_steam_when_not_running(self, wf: LifecycleHarness):
        wf.process.is_game_started.return_value = False
        with (
            patch.object(lw_module, "exec_command_detached") as exec_cmd,
            patch.object(wf.workflow, "wait_for_window_showup") as wait_showup,
            patch.object(wf.workflow, "process_main_menu_loading") as menu_loading,
        ):
            wf.workflow.start_via_steam()

        exec_cmd.assert_called_once_with(["explorer.exe", f"steam://rungameid/{wf.workflow.config.gameAppId}"])
        wait_showup.assert_called_once_with()
        wf.process.update_info.assert_called_once_with()
        menu_loading.assert_called_once_with()


class TestWaitForWindowShowup:
    """``wait_for_window_showup``。"""

    def test_success(self, wf: LifecycleHarness):
        with patch.object(wf.workflow, "wait_for_state", return_value=True) as wait:
            wf.workflow.wait_for_window_showup()

        wait.assert_called_once_with(wf.process.is_game_started, 300, 10, False)

    def test_timeout(self, wf: LifecycleHarness):
        with (
            patch.object(wf.workflow, "wait_for_state", return_value=False),
            pytest.raises(OperationTimeout) as excinfo,
        ):
            wf.workflow.wait_for_window_showup()

        assert excinfo.value.context is OperationTimeoutContext.GAME_WINDOW_STARTUP


class TestProcessMainMenuLoading:
    """``process_main_menu_loading`` 的页面处理。"""

    def test_returns_when_main_menu_loaded(self, wf: LifecycleHarness):
        wf.screen.ocr_game_window.return_value = "主菜单文本"
        wf.screen.is_on_mainmenu.return_value = True

        wf.workflow.process_main_menu_loading()

        wf.screen.ocr_game_window.assert_called_once_with(0.5, 0.8, 0.5, 0.2)
        wf.action.confirm.assert_not_called()

    def test_confirms_brightness_or_warning_page(self, wf: LifecycleHarness):
        wf.screen.is_on_mainmenu.side_effect = [False, True]
        wf.screen.is_on_mainmenu_brightness_or_warning_page.return_value = True

        wf.workflow.process_main_menu_loading()

        wf.action.confirm.assert_called_once_with()

    def test_confirms_gtaplus_advertisement_page(self, wf: LifecycleHarness):
        wf.screen.is_on_mainmenu.side_effect = [False, True]
        wf.screen.is_on_mainmenu_brightness_or_warning_page.return_value = False
        wf.screen.is_on_mainmenu_gtaplus_advertisement_page.return_value = True

        wf.workflow.process_main_menu_loading()

        wf.action.confirm.assert_called_once_with()

    def test_timeout(self, wf: LifecycleHarness):
        wf.screen.is_on_mainmenu.return_value = False
        wf.screen.is_on_mainmenu_brightness_or_warning_page.return_value = False
        wf.screen.is_on_mainmenu_gtaplus_advertisement_page.return_value = False

        with pytest.raises(OperationTimeout) as excinfo:
            wf.workflow.process_main_menu_loading()

        assert excinfo.value.context is OperationTimeoutContext.MAIN_MENU_LOAD


class TestEnterStorymodeFromMainmenu:
    """``enter_storymode_from_mainmenu``。"""

    def test_logged_out_raises(self, wf: LifecycleHarness):
        wf.screen.is_on_mainmenu_logout.return_value = True

        with pytest.raises(UnexpectedGameState) as excinfo:
            wf.workflow.enter_storymode_from_mainmenu()

        assert excinfo.value.expected == GameState.MAIN_MENU
        assert excinfo.value.actual_state == GameState.OFFLINE
        wf.action.navigate_to_storymode_tab_in_mainmenu.assert_not_called()

    def test_story_mode_page_missing_raises(self, wf: LifecycleHarness):
        wf.screen.is_on_mainmenu_logout.return_value = False
        wf.screen.is_on_mainmenu_storymode_page.return_value = False

        with pytest.raises(UIElementNotFound) as excinfo:
            wf.workflow.enter_storymode_from_mainmenu()

        assert excinfo.value.element_not_found is UIElement.STORY_MODE_MENU
        wf.action.navigate_to_storymode_tab_in_mainmenu.assert_called_once_with()
        wf.action.confirm.assert_not_called()

    def test_happy_path(self, wf: LifecycleHarness):
        wf.screen.is_on_mainmenu_logout.return_value = False
        wf.screen.is_on_mainmenu_storymode_page.return_value = True
        with patch.object(wf.workflow, "wait_for_storymode_load") as wait_load:
            wf.workflow.enter_storymode_from_mainmenu()

        wf.action.navigate_to_storymode_tab_in_mainmenu.assert_called_once_with()
        wf.action.confirm.assert_called_once_with()
        wait_load.assert_called_once_with()


class TestWaitForStorymodeLoad:
    """``wait_for_storymode_load``。"""

    def test_success(self, wf: LifecycleHarness):
        with patch.object(wf.workflow, "wait_for_state", return_value=True) as wait:
            wf.workflow.wait_for_storymode_load()

        wait.assert_called_once_with(wf.workflow.check_if_in_storymode, 120, 5)

    def test_timeout(self, wf: LifecycleHarness):
        with (
            patch.object(wf.workflow, "wait_for_state", return_value=False),
            pytest.raises(OperationTimeout) as excinfo,
        ):
            wf.workflow.wait_for_storymode_load()

        assert excinfo.value.context is OperationTimeoutContext.STORY_MODE_LOAD


class TestNavigateToGoOnlineMenu:
    """``navigate_to_go_online_menu`` 的导航与恢复策略。"""

    def test_success_on_first_attempt(self, wf: LifecycleHarness):
        wf.screen.is_on_go_online_menu.return_value = True
        with patch.object(wf.workflow, "open_pause_menu") as open_menu:
            wf.workflow.navigate_to_go_online_menu()

        wf.action.navigate_to_online_tab_in_storymode.assert_called_once_with()
        open_menu.assert_not_called()
        wf.action.back.assert_not_called()

    def test_success_after_recovery(self, wf: LifecycleHarness):
        wf.screen.is_on_go_online_menu.side_effect = [False, False, True]
        with patch.object(wf.workflow, "open_pause_menu") as open_menu:
            wf.workflow.navigate_to_go_online_menu()

        assert wf.action.navigate_to_online_tab_in_storymode.call_count == 3
        assert wf.action.back.call_count == 6
        assert open_menu.call_count == 2

    def test_all_attempts_failed_raises(self, wf: LifecycleHarness):
        wf.screen.is_on_go_online_menu.return_value = False
        with (
            patch.object(wf.workflow, "open_pause_menu") as open_menu,
            pytest.raises(UIElementNotFound) as excinfo,
        ):
            wf.workflow.navigate_to_go_online_menu()

        assert excinfo.value.element_not_found is UIElement.ONLINE_MODE_TAB
        assert wf.action.navigate_to_online_tab_in_storymode.call_count == 3
        assert wf.action.back.call_count == 9
        assert open_menu.call_count == 3


class TestEnterOnlinemodeFromStorymode:
    """``enter_onlinemode_from_storymode`` 的调用顺序。"""

    def test_call_order(self, wf: LifecycleHarness):
        parent = MagicMock(name="call_order")
        with (
            patch.object(wf.workflow, "open_pause_menu") as open_menu,
            patch.object(wf.workflow, "navigate_to_go_online_menu") as nav_menu,
            patch.object(wf.workflow, "process_online_loading") as loading,
        ):
            parent.attach_mock(open_menu, "open_pause_menu")
            parent.attach_mock(nav_menu, "navigate_to_go_online_menu")
            parent.attach_mock(wf.action, "action")
            parent.attach_mock(loading, "process_online_loading")

            wf.workflow.enter_onlinemode_from_storymode()

        assert [entry[0] for entry in parent.mock_calls] == [
            "open_pause_menu",
            "navigate_to_go_online_menu",
            "action.enter_invite_only_session",
            "process_online_loading",
        ]


class TestProcessOnlineLoading:
    """``process_online_loading`` 的各种意外状态。"""

    @pytest.fixture
    def idle_screen(self, wf: LifecycleHarness) -> LifecycleHarness:
        """让屏幕既不在坏档警告页，也不在主菜单。"""
        wf.screen.is_on_bad_pcsetting_warning_page.return_value = False
        wf.screen.is_on_mainmenu.return_value = False
        return wf

    def test_returns_when_online(self, wf: LifecycleHarness, idle_screen: LifecycleHarness):
        with (
            patch.object(wf.workflow, "handle_warning_page", return_value=False),
            patch.object(wf.workflow, "handle_online_service_policy_page", return_value=False),
            patch.object(wf.workflow, "check_if_in_onlinemode", return_value=True) as check,
        ):
            wf.workflow.process_online_loading()

        check.assert_called_once_with()

    def test_bad_pcsetting_raises(self, wf: LifecycleHarness, idle_screen: LifecycleHarness):
        wf.screen.is_on_bad_pcsetting_warning_page.return_value = True

        with pytest.raises(UnexpectedGameState) as excinfo:
            wf.workflow.process_online_loading()

        assert excinfo.value.expected == GameState.ONLINE_FREEMODE
        assert excinfo.value.actual_state == GameState.BAD_PCSETTING_BIN

    def test_back_to_main_menu_raises(self, wf: LifecycleHarness, idle_screen: LifecycleHarness):
        wf.screen.is_on_mainmenu.return_value = True
        with (
            patch.object(wf.workflow, "handle_warning_page", return_value=False),
            patch.object(wf.workflow, "handle_online_service_policy_page", return_value=False),
            pytest.raises(UnexpectedGameState) as excinfo,
        ):
            wf.workflow.process_online_loading()

        assert excinfo.value.expected == GameState.ONLINE_FREEMODE
        assert excinfo.value.actual_state == GameState.MAIN_MENU

    def test_warning_page_handled_then_online(self, wf: LifecycleHarness, idle_screen: LifecycleHarness):
        with (
            patch.object(wf.workflow, "handle_warning_page", side_effect=[True, False]) as warning,
            patch.object(wf.workflow, "handle_online_service_policy_page", return_value=False),
            patch.object(wf.workflow, "check_if_in_onlinemode", return_value=True),
        ):
            wf.workflow.process_online_loading()

        assert warning.call_count == 2

    def test_service_policy_page_handled_then_online(self, wf: LifecycleHarness, idle_screen: LifecycleHarness):
        with (
            patch.object(wf.workflow, "handle_warning_page", return_value=False),
            patch.object(wf.workflow, "handle_online_service_policy_page", side_effect=[True, False]) as policy,
            patch.object(wf.workflow, "check_if_in_onlinemode", return_value=True),
        ):
            wf.workflow.process_online_loading()

        assert policy.call_count == 2

    def test_timeout_raises_join_online_session(self, wf: LifecycleHarness, idle_screen: LifecycleHarness):
        wf.workflow.config.onlineModeLoadingTimeout = 10
        with (
            patch.object(wf.workflow, "handle_warning_page", return_value=False),
            patch.object(wf.workflow, "handle_online_service_policy_page", return_value=False),
            patch.object(wf.workflow, "check_if_in_onlinemode", return_value=False),
            pytest.raises(OperationTimeout) as excinfo,
        ):
            wf.workflow.process_online_loading()

        assert excinfo.value.context is OperationTimeoutContext.JOIN_ONLINE_SESSION
        wf.process.suspend.assert_not_called()

    def test_glitches_after_two_minutes(self, wf: LifecycleHarness, idle_screen: LifecycleHarness):
        wf.workflow.config.onlineModeLoadingTimeout = 130
        with (
            patch.object(wf.workflow, "handle_warning_page", return_value=False),
            patch.object(wf.workflow, "handle_online_service_policy_page", return_value=False),
            patch.object(wf.workflow, "check_if_in_onlinemode", return_value=False),
            pytest.raises(OperationTimeout) as excinfo,
        ):
            wf.workflow.process_online_loading()

        assert excinfo.value.context is OperationTimeoutContext.JOIN_ONLINE_SESSION
        wf.process.suspend.assert_called_once_with(wf.workflow.config.suspendGTATime)


class TestHandleOnlineServicePolicyPage:
    """``handle_online_service_policy_page`` 的页面分支。"""

    def test_not_on_policy_page_returns_false(self, wf: LifecycleHarness):
        wf.screen.is_on_online_service_policy_page.return_value = False

        assert wf.workflow.handle_online_service_policy_page("普通文本") is False
        wf.action.confirm.assert_not_called()

    def test_download_timeout_raises(self, wf: LifecycleHarness):
        wf.screen.is_on_online_service_policy_page.return_value = True
        with (
            patch.object(wf.workflow, "wait_for_state", return_value=False),
            pytest.raises(OperationTimeout) as excinfo,
        ):
            wf.workflow.handle_online_service_policy_page("在线服务政策")

        assert excinfo.value.context is OperationTimeoutContext.DOWNLOAD_POLICY

    def test_privacy_policy_branch(self, wf: LifecycleHarness):
        wf.screen.is_on_online_service_policy_page.side_effect = [True, False]
        wf.screen.is_on_privacy_policy_page.return_value = True
        with patch.object(wf.workflow, "wait_for_state", return_value=True):
            assert wf.workflow.handle_online_service_policy_page("在线服务政策") is True

        wf.action.back.assert_called_once_with()
        assert wf.action.down.call_count == 3
        assert wf.action.confirm.call_count == 3

    def test_term_of_service_branch(self, wf: LifecycleHarness):
        wf.screen.is_on_online_service_policy_page.side_effect = [True, False]
        wf.screen.is_on_privacy_policy_page.return_value = False
        wf.screen.is_on_term_of_service_page.return_value = True
        with patch.object(wf.workflow, "wait_for_state", return_value=True):
            assert wf.workflow.handle_online_service_policy_page("在线服务政策") is True

        wf.action.back.assert_called_once_with()
        assert wf.action.down.call_count == 2
        assert wf.action.confirm.call_count == 3

    def test_still_on_policy_page_after_confirm(self, wf: LifecycleHarness):
        wf.screen.is_on_online_service_policy_page.return_value = True
        with patch.object(wf.workflow, "wait_for_state", return_value=True):
            assert wf.workflow.handle_online_service_policy_page("在线服务政策") is True

        wf.action.back.assert_not_called()
        assert wf.action.down.call_count == 1
        assert wf.action.confirm.call_count == 3

    def test_unknown_policy_page_raises(self, wf: LifecycleHarness):
        wf.screen.is_on_online_service_policy_page.side_effect = [True, False]
        wf.screen.is_on_privacy_policy_page.return_value = False
        wf.screen.is_on_term_of_service_page.return_value = False
        with (
            patch.object(wf.workflow, "wait_for_state", return_value=True),
            pytest.raises(UnexpectedGameState) as excinfo,
        ):
            wf.workflow.handle_online_service_policy_page("在线服务政策")

        assert excinfo.value.expected == GameState.ONLINE_SERVICE_POLICY_PAGE
        assert excinfo.value.actual_state == GameState.UNKNOWN


class TestJoinSessionThroughSteam:
    """``join_session_through_steam`` 的参数校验与启动。"""

    def test_game_not_started_raises(self, wf: LifecycleHarness):
        wf.process.is_game_started.return_value = False

        with pytest.raises(UnexpectedGameState) as excinfo:
            wf.workflow.join_session_through_steam("abcd")

        assert excinfo.value.expected == GameState.ON
        assert excinfo.value.actual_state == GameState.OFF

    @pytest.mark.parametrize(
        "steam_jvp",
        [
            "",
            "abc",
            "中文",
            "abcd; drop",
            "not valid!",
            "%3D",
            "ab%3D",
        ],
    )
    def test_invalid_steam_jvp_raises_value_error(self, wf: LifecycleHarness, steam_jvp: str):
        wf.process.is_game_started.return_value = True
        with patch.object(lw_module, "exec_command_detached") as exec_cmd, pytest.raises(ValueError):
            wf.workflow.join_session_through_steam(steam_jvp)

        exec_cmd.assert_not_called()

    @pytest.mark.parametrize("steam_jvp", ["abcd", "ab%3D%3D", "YWJjZA%3D%3D"])
    def test_valid_steam_jvp_launches_url(self, wf: LifecycleHarness, steam_jvp: str):
        wf.process.is_game_started.return_value = True
        with (
            patch.object(lw_module, "exec_command_detached") as exec_cmd,
            patch.object(wf.workflow, "process_online_loading") as loading,
        ):
            wf.workflow.join_session_through_steam(steam_jvp)

        expected_url = f"steam://rungame/{wf.workflow.config.gameAppId}/76561199074735990/-steamjvp={steam_jvp}"
        exec_cmd.assert_called_once_with(["explorer.exe", expected_url])
        loading.assert_called_once_with()
