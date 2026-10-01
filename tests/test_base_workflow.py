"""``gta_automator._base_workflow`` 的单元测试。

``_BaseWorkflow`` 是所有工作流的公共基类，这里用 ``MagicMock`` 注入
``screen``/``action``/``process`` 三个底层依赖，验证通用子流程的行为与异常路径，
并使用 ``tmp_path`` 验证真实文件处理逻辑。
"""

from __future__ import annotations

import struct
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from gta_automator import _base_workflow as base_module
from gta_automator._base_workflow import _BaseWorkflow
from gta_automator.exception import GameState, UIElement, UIElementNotFound, UnexpectedGameState


@pytest.fixture
def deps() -> SimpleNamespace:
    """三个底层依赖的 mock 集合。默认「不在警告页面」，避免干扰其它断言。"""
    screen = MagicMock(name="GameScreen")
    action = MagicMock(name="GameAction")
    process = MagicMock(name="GameProcess")
    screen.is_on_warning_page.return_value = False
    return SimpleNamespace(screen=screen, action=action, process=process)


@pytest.fixture
def workflow(deps: SimpleNamespace, config) -> _BaseWorkflow:
    return _BaseWorkflow(deps.screen, deps.action, deps.process, config)


class TestOpenPauseMenu:
    def test_opens_menu_with_single_press(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.screen.is_on_pause_menu.return_value = True

        workflow.open_pause_menu()

        deps.action.open_or_close_pause_menu.assert_called_once_with()

    def test_presses_twice_when_menu_was_closed(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.screen.is_on_pause_menu.side_effect = [False, True]

        workflow.open_pause_menu()

        assert deps.action.open_or_close_pause_menu.call_count == 2

    def test_raises_when_menu_never_opens(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.screen.is_on_pause_menu.return_value = False

        with pytest.raises(UIElementNotFound) as excinfo:
            workflow.open_pause_menu()

        assert excinfo.value.element_not_found is UIElement.PAUSE_MENU
        assert deps.action.open_or_close_pause_menu.call_count == 2

    def test_handles_warning_page_before_pressing(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.screen.is_on_pause_menu.return_value = True

        with patch.object(workflow, "handle_warning_page") as handle_warning:
            parent = MagicMock()
            parent.attach_mock(handle_warning, "handle_warning_page")
            parent.attach_mock(deps.action.open_or_close_pause_menu, "open_or_close_pause_menu")

            workflow.open_pause_menu()

        assert parent.mock_calls == [call.handle_warning_page(), call.open_or_close_pause_menu()]


class TestCheckIfInOnlinemode:
    def test_returns_true_when_menu_can_open_and_close(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.screen.is_on_online_pause_menu.side_effect = [True, False]

        assert workflow.check_if_in_onlinemode() is True
        assert deps.action.open_or_close_pause_menu.call_count == 2

    def test_returns_false_when_menu_stays_open(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.screen.is_on_online_pause_menu.return_value = True

        assert workflow.check_if_in_onlinemode(max_retries=2) is False
        # 每轮都会按下打开和关闭各一次
        assert deps.action.open_or_close_pause_menu.call_count == 4

    def test_returns_false_when_menu_never_opens(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.screen.is_on_online_pause_menu.return_value = False

        assert workflow.check_if_in_onlinemode(max_retries=3) is False
        assert deps.action.open_or_close_pause_menu.call_count == 3

    def test_recovers_on_second_attempt(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.screen.is_on_online_pause_menu.side_effect = [
            False,  # 第一轮：没打开
            True,  # 第二轮：打开
            False,  # 第二轮：又关上了，确认在在线模式
        ]

        assert workflow.check_if_in_onlinemode() is True


class TestCheckIfInStorymode:
    def test_returns_true_when_menu_can_open_and_close(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.screen.is_on_story_pause_menu.side_effect = [True, False]

        assert workflow.check_if_in_storymode() is True
        assert deps.action.open_or_close_pause_menu.call_count == 2

    def test_returns_false_when_menu_stays_open(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.screen.is_on_story_pause_menu.return_value = True

        assert workflow.check_if_in_storymode(max_retries=2) is False
        assert deps.action.open_or_close_pause_menu.call_count == 4

    def test_returns_false_when_menu_never_opens(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.screen.is_on_story_pause_menu.return_value = False

        assert workflow.check_if_in_storymode() is False
        assert deps.action.open_or_close_pause_menu.call_count == 3


class TestGlitchSinglePlayerSession:
    def test_suspends_process_for_configured_duration(self, workflow: _BaseWorkflow, deps: SimpleNamespace, config):
        config.suspendGTATime = 42

        workflow.glitch_single_player_session()

        deps.process.suspend.assert_called_once_with(42)


class TestHandleWarningPage:
    def test_returns_false_when_not_on_warning_page(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.screen.is_on_warning_page.return_value = False

        assert workflow.handle_warning_page() is False
        deps.action.confirm.assert_not_called()

    def test_confirms_warning_page(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.screen.is_on_warning_page.return_value = True

        assert workflow.handle_warning_page() is True
        deps.action.confirm.assert_called_once_with()

    def test_passes_ocr_text_through(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.screen.is_on_warning_page.return_value = False

        workflow.handle_warning_page("一段 OCR 文本")

        deps.screen.is_on_warning_page.assert_called_once_with("一段 OCR 文本")


class TestExitJobPanel:
    def test_exits_from_second_page(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.screen.ocr_game_window.return_value = "第二页文本"
        deps.screen.is_on_second_job_setup_page.return_value = True

        workflow.exit_job_panel()

        deps.screen.ocr_game_window.assert_called_once_with(0, 0, 1, 1)
        deps.action.exit_job_panel_from_second_page.assert_called_once_with()
        deps.action.exit_job_panel_from_first_page.assert_not_called()

    def test_exits_from_first_page(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.screen.ocr_game_window.return_value = "第一页文本"
        deps.screen.is_on_second_job_setup_page.return_value = False
        deps.screen.is_on_first_job_setup_page.return_value = True

        workflow.exit_job_panel()

        deps.action.exit_job_panel_from_first_page.assert_called_once_with()
        deps.action.exit_job_panel_from_second_page.assert_not_called()

    def test_does_nothing_when_not_on_panel(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.screen.ocr_game_window.return_value = "自由模式"
        deps.screen.is_on_second_job_setup_page.return_value = False
        deps.screen.is_on_first_job_setup_page.return_value = False

        workflow.exit_job_panel()

        deps.action.exit_job_panel_from_first_page.assert_not_called()
        deps.action.exit_job_panel_from_second_page.assert_not_called()

    def test_handles_warning_page_before_exiting(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.screen.ocr_game_window.return_value = "自由模式"
        deps.screen.is_on_second_job_setup_page.return_value = False
        deps.screen.is_on_first_job_setup_page.return_value = False

        with patch.object(workflow, "handle_warning_page") as handle_warning:
            workflow.exit_job_panel()

        handle_warning.assert_called_once_with()


class TestWaitForState:
    def test_returns_true_when_check_passes(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.process.is_pid_vaild.return_value = True
        check = MagicMock(name="check", return_value=True)

        assert workflow.wait_for_state(check, timeout=10) is True
        check.assert_called_once_with()

    def test_returns_false_on_timeout(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.process.is_pid_vaild.return_value = True
        check = MagicMock(name="check", return_value=False)

        assert workflow.wait_for_state(check, timeout=5) is False
        assert check.call_count > 0

    def test_raises_when_game_not_started(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.process.is_pid_vaild.return_value = False
        check = MagicMock(name="check", return_value=True)

        with pytest.raises(UnexpectedGameState) as excinfo:
            workflow.wait_for_state(check, timeout=10)

        assert excinfo.value.expected is GameState.ON
        assert excinfo.value.actual_state is GameState.OFF
        check.assert_not_called()

    def test_skips_game_check_when_flag_is_false(self, workflow: _BaseWorkflow, deps: SimpleNamespace):
        deps.process.is_pid_vaild.return_value = False
        check = MagicMock(name="check", return_value=True)

        assert workflow.wait_for_state(check, timeout=10, game_has_started=False) is True
        deps.process.is_pid_vaild.assert_not_called()

    def test_uses_configured_check_interval(self, workflow: _BaseWorkflow, deps: SimpleNamespace, no_sleep: MagicMock):
        deps.process.is_pid_vaild.return_value = True
        check = MagicMock(name="check", return_value=True)

        workflow.wait_for_state(check, timeout=10, check_interval=0.25)

        no_sleep.assert_not_called()  # 第一次检查就成功，不会休眠


def _chunk(value: int, payload: bytes = b"\xaa" * 6) -> bytes:
    """构造一个 8 字节块：前 2 字节为小端序无符号短整数。"""
    return struct.pack("<H", value) + payload


class TestCleanPcsettingBin:
    def test_keeps_small_values_and_drops_large_ones(self, workflow: _BaseWorkflow, tmp_path):
        keep_1 = _chunk(100)
        drop_850 = _chunk(850)
        keep_849 = _chunk(849)
        keep_0 = _chunk(0)
        trailing = b"\x01\x02\x03\x04"  # 不足 8 字节的尾巴应被丢弃
        target = tmp_path / "pc_settings.bin"
        target.write_bytes(keep_1 + drop_850 + keep_849 + keep_0 + trailing)

        workflow.clean_pcsetting_bin(target)

        assert target.read_bytes() == keep_1 + keep_849 + keep_0

    def test_drops_everything_when_all_values_are_large(self, workflow: _BaseWorkflow, tmp_path):
        target = tmp_path / "pc_settings.bin"
        target.write_bytes(_chunk(850) + _chunk(65535))

        workflow.clean_pcsetting_bin(target)

        assert target.read_bytes() == b""

    def test_raises_when_file_missing(self, workflow: _BaseWorkflow, tmp_path):
        with pytest.raises(FileNotFoundError):
            workflow.clean_pcsetting_bin(tmp_path / "not_exist.bin")

    def test_raises_when_path_is_directory(self, workflow: _BaseWorkflow, tmp_path):
        directory = tmp_path / "a_directory"
        directory.mkdir()

        with pytest.raises(FileNotFoundError):
            workflow.clean_pcsetting_bin(directory)


def _make_profiles_dir(root, save_dirs: dict[str, bytes | None]):
    """在 ``root`` 下构造 ``Rockstar Games/GTAV Enhanced/Profiles`` 目录树。

    :param save_dirs: 存档目录名 -> ``pc_settings.bin`` 内容，``None`` 表示不创建文件
    :return: Profiles 目录的 Path
    """
    profiles = root / "Rockstar Games" / "GTAV Enhanced" / "Profiles"
    profiles.mkdir(parents=True)
    for name, content in save_dirs.items():
        savedir = profiles / name
        savedir.mkdir()
        if content is not None:
            (savedir / "pc_settings.bin").write_bytes(content)
    return profiles


class TestFixBadPcsetting:
    @pytest.fixture
    def fake_documents(self, tmp_path, monkeypatch):
        """把「我的文档」重定向到 tmp_path。"""
        monkeypatch.setattr(base_module, "get_document_fold_path", lambda: tmp_path)
        return tmp_path

    def test_returns_when_profiles_directory_missing(self, workflow: _BaseWorkflow, fake_documents, tmp_path):
        with patch.object(_BaseWorkflow, "clean_pcsetting_bin") as clean:
            workflow.fix_bad_pcsetting()  # 不应抛出异常

        clean.assert_not_called()

    def test_cleans_every_save_with_settings_file(self, workflow: _BaseWorkflow, fake_documents):
        profiles = _make_profiles_dir(fake_documents, {"save_a": _chunk(1), "save_b": _chunk(1)})

        with patch.object(_BaseWorkflow, "clean_pcsetting_bin") as clean:
            workflow.fix_bad_pcsetting()

        assert clean.call_count == 2
        called_paths = {item.args[0] for item in clean.call_args_list}
        assert called_paths == {profiles / "save_a" / "pc_settings.bin", profiles / "save_b" / "pc_settings.bin"}

    def test_skips_save_without_settings_file(self, workflow: _BaseWorkflow, fake_documents):
        profiles = _make_profiles_dir(fake_documents, {"with_file": _chunk(1), "without_file": None})

        with patch.object(_BaseWorkflow, "clean_pcsetting_bin") as clean:
            workflow.fix_bad_pcsetting()

        clean.assert_called_once_with(profiles / "with_file" / "pc_settings.bin")

    @pytest.mark.parametrize(
        "exception",
        [FileNotFoundError("文件不见了"), OSError("磁盘错误"), RuntimeError("未知错误")],
    )
    def test_continues_after_clean_failure(self, workflow: _BaseWorkflow, fake_documents, exception: Exception):
        _make_profiles_dir(fake_documents, {"save_a": _chunk(1), "save_b": _chunk(1)})

        with patch.object(_BaseWorkflow, "clean_pcsetting_bin", side_effect=exception) as clean:
            workflow.fix_bad_pcsetting()  # 单个存档失败不应中断整体流程

        assert clean.call_count == 2

    def test_cleans_remaining_save_after_first_fails(self, workflow: _BaseWorkflow, fake_documents):
        _make_profiles_dir(fake_documents, {"save_a": _chunk(1), "save_b": _chunk(1)})

        with patch.object(_BaseWorkflow, "clean_pcsetting_bin", side_effect=[OSError("坏盘"), None]) as clean:
            workflow.fix_bad_pcsetting()

        assert clean.call_count == 2
