"""``paths`` / ``logger`` / ``argument_parser`` 的单元测试。

这三个模块都在导入时执行副作用（``logger`` 会创建日志目录、注册全局 handler），
因此用例只做只读断言，并在需要改动日志状态时用 ``monkeypatch`` 隔离，保证不污染
其他测试。
"""

from __future__ import annotations

import argparse
import logging
import sys
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import argument_parser as argument_parser_module
import logger as logger_module
import paths

# ---------------------------------------------------------------------------
# paths
# ---------------------------------------------------------------------------


class TestGetBaseDir:
    def test_source_run_uses_file_directory(self, monkeypatch):
        monkeypatch.delattr(paths.sys, "frozen", raising=False)

        result = paths.get_base_dir()

        assert result == paths.Path(paths.__file__).resolve().parent

    def test_frozen_run_uses_executable_directory(self, monkeypatch):
        fake_executable = r"C:\Games\Bot\JNTMbot.exe"
        monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
        monkeypatch.setattr(paths.sys, "executable", fake_executable)

        result = paths.get_base_dir()

        assert result == paths.Path(fake_executable).resolve().parent
        assert result != paths.Path(paths.__file__).resolve().parent


class TestDerivedConstants:
    def test_log_paths(self):
        assert paths.LOG_DIR == paths.BASE_DIR / "logs"
        assert paths.LOG_FILE_PATH == paths.LOG_DIR / "app.log"

    def test_executable_paths(self):
        assert paths.OCR_EXECUTABLE_PATH == paths.BASE_DIR / "RapidOCR-json.exe"
        assert paths.STEAM_BOT_EXECUTABLE_PATH == paths.BASE_DIR / "steam_bot.exe"
        assert paths.STEAM_BOT_SCRIPT_PATH == paths.BASE_DIR / "steam_bot" / "server.js"
        assert paths.DEFAULT_CONFIG_PATH == paths.BASE_DIR / "config.yaml"

    def test_vigembus_driver_candidates(self):
        candidates = paths.VIGEMBUS_DRIVER_PATH_CANDIDATES

        assert isinstance(candidates, tuple)
        assert len(candidates) == 2
        assert candidates[0] == paths.BASE_DIR / "虚拟手柄驱动ViGEmBusSetup_x64.msi"
        assert candidates[1] == paths.BASE_DIR / "assets" / "虚拟手柄驱动ViGEmBusSetup_x64.msi"
        for candidate in candidates:
            assert candidate.is_relative_to(paths.BASE_DIR)


# ---------------------------------------------------------------------------
# logger
# ---------------------------------------------------------------------------


def _make_record(name: str, level: int) -> logging.LogRecord:
    return logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg="测试日志",
        args=None,
        exc_info=None,
    )


class TestUIautomationFilter:
    @pytest.mark.parametrize(
        ("name", "level", "expected"),
        [
            ("comtypes.client", logging.DEBUG, False),
            ("comtypes.client", logging.INFO, False),
            ("comtypes.client", logging.WARNING, True),
            ("comtypes.client", logging.ERROR, True),
            ("some.other.logger", logging.DEBUG, True),
            ("logger", logging.DEBUG, True),
        ],
    )
    def test_filter(self, name: str, level: int, expected: bool):
        filter_ = logger_module.UIautomationFilter()

        assert bool(filter_.filter(_make_record(name, level))) is expected


@contextmanager
def _stub_logging(*handler_names: str):
    """在极小的作用域内替换 ``logging.getLogger``。

    只在 with 块内生效，避免 pytest 自带的 logging 插件在用例 teardown 时拿到
    假 logger 而崩溃，也不会污染全局日志状态。
    """
    handlers = {name: SimpleNamespace(name=name, setLevel=MagicMock()) for name in handler_names}
    root_logger = SimpleNamespace(handlers=list(handlers.values()), warning=MagicMock())
    get_logger = MagicMock(name="getLogger", return_value=root_logger)
    with patch.object(logger_module.logging, "getLogger", get_logger):
        yield SimpleNamespace(root=root_logger, **handlers)


class TestSetLoglevel:
    def test_sets_console_handler_level(self):
        with _stub_logging("file", "console") as env:
            logger_module.set_loglevel("debug")

        env.console.setLevel.assert_called_once_with("DEBUG")
        env.file.setLevel.assert_not_called()
        env.root.warning.assert_not_called()

    @pytest.mark.parametrize("level", ["INFO", "WARNING", "ERROR", "CRITICAL"])
    def test_accepts_all_valid_levels(self, level: str):
        with _stub_logging("console") as env:
            logger_module.set_loglevel(level)

        env.console.setLevel.assert_called_once_with(level)

    @pytest.mark.parametrize("level", ["verbose", "TRACE", "", None])
    def test_invalid_level_raises_value_error(self, level):
        with _stub_logging("console") as env, pytest.raises((ValueError, AttributeError)):
            logger_module.set_loglevel(level)

        env.console.setLevel.assert_not_called()

    def test_warns_when_console_handler_missing(self):
        with _stub_logging("file") as env:
            logger_module.set_loglevel("INFO")

        env.file.setLevel.assert_not_called()
        env.root.warning.assert_called_once()


class TestGetLogger:
    def test_returns_named_logger(self):
        assert logger_module.get_logger("some.module") is logging.getLogger("some.module")


class TestDefaultLoggingConfig:
    def test_config_shape(self):
        config = logger_module.DEFAULT_LOGGING_CONFIG

        assert config["version"] == 1
        assert config["disable_existing_loggers"] is False
        assert set(config["handlers"]) == {"console", "file"}
        assert config["handlers"]["file"]["filename"] == str(paths.LOG_FILE_PATH)
        assert config["root"]["handlers"] == ["console", "file"]


# ---------------------------------------------------------------------------
# argument_parser
# ---------------------------------------------------------------------------


class TestArgumentParser:
    def test_default_config_path(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["JNTMbot.py"])

        result = argument_parser_module.ArgumentParser().parse()

        assert result == {"config_file_path": "config.yaml"}

    def test_separate_value_form(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["JNTMbot.py", "--config-file", "custom.yaml"])

        result = argument_parser_module.ArgumentParser().parse()

        assert result == {"config_file_path": "custom.yaml"}

    def test_equals_form(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["JNTMbot.py", "--config-file=other.yaml"])

        result = argument_parser_module.ArgumentParser().parse()

        assert result == {"config_file_path": "other.yaml"}

    def test_argument_error_is_exported(self):
        assert argument_parser_module.ArgumentError is argparse.ArgumentError
        assert argument_parser_module.__all__ == ["ArgumentError", "ArgumentParser"]
