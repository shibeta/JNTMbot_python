"""``config.py`` 的单元测试。

覆盖配置默认值校验、YAML 值类型强制转换、配置文件的创建/补全/保存，
以及 ``main()`` 生成配置模板的行为。所有文件读写都发生在 ``tmp_path`` 中。
"""

from __future__ import annotations

import dataclasses
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import config
from config import Config, ConfigManager, ConfigParseError, ConfigValidationError


def _schema_by_name() -> dict:
    return {spec.name: spec for spec in Config._schema_fields()}


class TestConfigDefaults:
    """默认配置必须是合法且完整的。"""

    def test_default_config_is_valid(self):
        Config().validate()  # 不应抛出异常

    def test_schema_covers_all_yaml_fields(self):
        names = [spec.name for spec in Config._schema_fields()]

        assert "debug" in names
        assert "config_filepath" not in names, "运行期状态不应写入配置文件"
        assert len(names) == 55

    @pytest.mark.parametrize(
        ("field", "expected"),
        [
            ("gameAppId", 3240220),
            ("steamBotPort", 13091),
            ("healthCheckInterval", 10),
            ("startOnAllJoined", True),
            ("manualMoveToPoint", False),
            ("recoveryChunkSize", 600),
        ],
    )
    def test_default_values(self, field: str, expected):
        assert getattr(Config(), field) == expected


class TestConfigFilePathRuntimeState:
    """``config_filepath`` 是运行期状态，由 ``__post_init__`` 初始化，不是 dataclass 字段。"""

    def test_default_is_base_dir_config_yaml(self):
        cfg = Config()

        assert isinstance(cfg.config_filepath, Path)
        assert cfg.config_filepath == config.BASE_DIR / "config.yaml"

    def test_is_not_a_dataclass_field(self):
        assert "config_filepath" not in {spec.name for spec in dataclasses.fields(Config)}

    def test_is_not_accepted_by_constructor(self):
        with pytest.raises(TypeError):
            Config(config_filepath=Path("X:/cfg.yaml"))

    def test_is_per_instance_state(self):
        """``__post_init__`` 每次构造都会重新赋默认值，实例之间互不影响。"""
        first, second = Config(), Config()

        first.config_filepath = Path("X:/first.yaml")

        assert first.config_filepath == Path("X:/first.yaml")
        assert second.config_filepath == config.BASE_DIR / "config.yaml"

    def test_reads_base_dir_at_construction_time(self, tmp_path: Path, monkeypatch):
        """``BASE_DIR`` 在构造时才被读取，因此可以被 monkeypatch 影响。"""
        monkeypatch.setattr(config, "BASE_DIR", tmp_path)

        assert Config().config_filepath == tmp_path / "config.yaml"


class TestConfigValidation:
    """``Config.validate()`` 的类型与取值范围检查。"""

    @pytest.mark.parametrize(
        ("field", "value", "keyword"),
        [
            ("steamBotHost", "", "不能为空"),
            ("steamBotToken", "   ", "不能为空"),
            ("steamBotPort", 0, "不能小于 1"),
            ("steamBotPort", 70000, "不能大于 65535"),
            ("steamBotProxy", "bad-proxy", "代理地址"),
            ("gameAppId", "abc", "应为整数"),
            ("healthCheckInterval", 0, "不能小于 1"),
            ("suspendGTATime", -1, "不能小于 0"),
            ("walkToPillarTime", 1.5, "应为整数"),
            ("debug", "yes", "应为布尔值"),
        ],
    )
    def test_single_invalid_field(self, field: str, value, keyword: str):
        cfg = Config()
        setattr(cfg, field, value)

        with pytest.raises(ConfigValidationError) as excinfo:
            cfg.validate()

        assert field in str(excinfo.value)
        assert keyword in str(excinfo.value)

    def test_valid_proxy_values(self):
        for value in ("", "system", "http://127.0.0.1:8080", "socks5h://127.0.0.1:1080"):
            cfg = Config()
            cfg.steamBotProxy = value
            cfg.validate()

    def test_all_problems_reported_at_once(self):
        cfg = Config()
        cfg.config_filepath = Path("X:/some/config.yaml")
        cfg.steamBotPort = 0
        cfg.steamBotHost = ""
        cfg.steamBotProxy = "bad"
        cfg.useAlterMessagingMethod = True
        cfg.AlterMessagingMethodWindowTitle = ""

        with pytest.raises(ConfigValidationError) as excinfo:
            cfg.validate()

        message = str(excinfo.value)
        assert "4 处不合法配置" in message
        assert "steamBotHost" in message
        assert "steamBotPort" in message
        assert "steamBotProxy" in message
        assert "AlterMessagingMethodWindowTitle" in message
        assert "some" in message and "config.yaml" in message

    def test_alter_messaging_window_title_ok_when_not_using_alt_method(self):
        cfg = Config()
        cfg.useAlterMessagingMethod = False
        cfg.AlterMessagingMethodWindowTitle = ""

        cfg.validate()  # 未启用备用发送方式时标题可以为空


class TestCoerceValue:
    """``_coerce_value`` 只修正常见的书写错误，不做静默兜底。"""

    @pytest.mark.parametrize(
        ("field", "raw", "expected"),
        [
            ("debug", "true", True),
            ("debug", " off ", False),
            ("steamBotPort", "13091", 13091),
            ("suspendGTATime", 13091.0, 13091),
            ("steamGroupId", 12345, "12345"),
            ("debug", True, True),
            ("steamBotPort", 13, 13),
        ],
    )
    def test_coercion(self, field: str, raw, expected):
        spec = _schema_by_name()[field]

        value, note = config._coerce_value(spec, raw)

        assert value == expected
        if value != raw or type(value) is not type(raw):
            assert note is not None
        else:
            assert note is None

    def test_unknown_string_number_stays_for_validation(self):
        spec = _schema_by_name()["steamBotPort"]

        value, note = config._coerce_value(spec, "abc")

        assert value == "abc"
        assert note is None


class TestValidationHelpers:
    """类型判断与取值校验辅助函数的边界行为。"""

    def test_check_digits_rejects_negative_app_id(self):
        """``_check_digits`` 对 int 字段实际起到「非负」校验作用，是可达的检查。

        只有值本身类型就不对（例如 ``"abc"``）时，才会先被更准确的类型错误拦下。
        """
        cfg = Config()
        cfg.gameAppId = -5

        with pytest.raises(ConfigValidationError) as excinfo:
            cfg.validate()

        assert "gameAppId" in str(excinfo.value)
        assert "必须全部由数字组成" in str(excinfo.value)

    def test_declared_kind_returns_none_for_unrelated_types(self):
        @dataclasses.dataclass
        class Sample:
            items: list[str] = dataclasses.field(default_factory=list)

        assert config._declared_kind(dataclasses.fields(Sample)[0]) is None

    @pytest.mark.parametrize(
        ("value", "kind", "expected"),
        [
            (True, bool, True),
            (True, int, False),  # bool 是 int 的子类，但不应被当成数字
            (1, float, True),  # 整数可用于浮点数配置项
            (1.5, int, False),  # 浮点数不算 int（交由 _coerce_value 处理）
            ("x", str, True),
            (1, str, False),
        ],
    )
    def test_matches_type(self, value, kind, expected):
        assert config._matches_type(value, kind) is expected

    def test_coerce_value_returns_untouched_when_unconvertible(self):
        """无法转换的值原样返回，交给 ``validate()`` 统一报错。"""
        spec = _schema_by_name()["debug"]  # 期望 bool

        value, note = config._coerce_value(spec, ["not", "a", "bool"])

        assert value == ["not", "a", "bool"]
        assert note is None


class TestConfigManagerLoad:
    """配置文件的新建、补全与保存。"""

    def test_creates_file_with_defaults_when_missing(self, tmp_path: Path):
        path = tmp_path / "config.yaml"

        cfg = ConfigManager(path).load()

        assert path.is_file()
        assert cfg.steamBotPort == 13091
        content = path.read_text(encoding="utf-8")
        assert content.startswith("# 本文件由 config.py 生成")
        for spec in Config._schema_fields():
            assert f"{spec.name}:" in content

    def test_reload_existing_file_does_not_rewrite(self, tmp_path: Path):
        path = tmp_path / "config.yaml"
        ConfigManager(path).load()
        first_content = path.read_text(encoding="utf-8")

        manager = ConfigManager(path)
        manager.load()

        assert manager._needs_write is False
        assert manager._is_new_file is False
        assert path.read_text(encoding="utf-8") == first_content

    def test_empty_file_is_treated_as_new(self, tmp_path: Path):
        path = tmp_path / "config.yaml"
        path.write_text("", encoding="utf-8")

        manager = ConfigManager(path)
        cfg = manager.load()

        assert manager._is_new_file is True
        assert cfg.debug is False
        assert path.read_text(encoding="utf-8").startswith("# 本文件由 config.py 生成")

    def test_missing_keys_are_inserted_in_declaration_order(self, tmp_path: Path):
        path = tmp_path / "config.yaml"
        path.write_text("debug: true\n# 请保留这条注释\nmsgTeamFull: 自定义消息\n", encoding="utf-8")

        cfg = ConfigManager(path).load()

        assert cfg.debug is True
        assert cfg.msgTeamFull == "自定义消息"
        # 未提供的键使用默认值
        assert cfg.steamBotHost == "127.0.0.1"

        lines = path.read_text(encoding="utf-8").splitlines()
        debug_index = lines.index("debug: true")
        host_index = next(i for i, line in enumerate(lines) if line.startswith("steamBotHost:"))
        port_index = next(i for i, line in enumerate(lines) if line.startswith("steamBotPort:"))
        assert debug_index < host_index < port_index
        assert "# 请保留这条注释" in lines
        assert "msgTeamFull: 自定义消息" in lines

    def test_unknown_keys_are_preserved(self, tmp_path: Path):
        path = tmp_path / "config.yaml"
        path.write_text("debug: true\nlegacyKey: 1\n", encoding="utf-8")

        ConfigManager(path).load()

        assert "legacyKey: 1" in path.read_text(encoding="utf-8")

    def test_value_coercion_marks_file_for_rewrite(self, tmp_path: Path):
        path = tmp_path / "config.yaml"
        path.write_text('debug: "true"\nsteamBotPort: "13091"\n', encoding="utf-8")

        manager = ConfigManager(path)
        cfg = manager.load()

        assert cfg.debug is True
        assert cfg.steamBotPort == 13091
        assert manager._needs_write is True
        # 原始文档的值不会被就地改写（保留引号），因此下次加载会再次转换
        assert 'debug: "true"' in path.read_text(encoding="utf-8")

    def test_unconvertible_value_fails_validation(self, tmp_path: Path):
        path = tmp_path / "config.yaml"
        path.write_text('steamBotPort: "abc"\n', encoding="utf-8")

        with pytest.raises(ConfigValidationError) as excinfo:
            ConfigManager(path).load()

        assert "steamBotPort" in str(excinfo.value)
        assert str(path) in str(excinfo.value)

    def test_config_filepath_is_set_on_result(self, tmp_path: Path):
        path = tmp_path / "config.yaml"

        cfg = ConfigManager(path).load()

        assert cfg.config_filepath == path.resolve()

    def test_commented_values_are_preserved(self, tmp_path: Path):
        path = tmp_path / "config.yaml"
        path.write_text("# 顶层注释\ndebug: true\n", encoding="utf-8")

        ConfigManager(path).load()

        assert "# 顶层注释" in path.read_text(encoding="utf-8")


class TestConfigManagerErrors:
    """读取与保存的异常路径。"""

    def test_top_level_sequence_is_rejected(self, tmp_path: Path):
        path = tmp_path / "config.yaml"
        path.write_text("- a\n- b\n", encoding="utf-8")

        with pytest.raises(ConfigParseError, match="键值对"):
            ConfigManager(path).load()

    def test_invalid_yaml_is_rejected(self, tmp_path: Path):
        path = tmp_path / "config.yaml"
        path.write_text("debug: [1, 2\n", encoding="utf-8")

        with pytest.raises(ConfigParseError, match="YAML"):
            ConfigManager(path).load()

    def test_directory_path_is_rejected(self, tmp_path: Path):
        with pytest.raises(ConfigParseError, match="文件夹"):
            ConfigManager(tmp_path).load()

    def test_read_oserror_is_wrapped(self, tmp_path: Path):
        path = tmp_path / "config.yaml"

        with patch("builtins.open", side_effect=OSError("磁盘炸了")), pytest.raises(ConfigParseError, match="无法读取"):
            ConfigManager(path).load()

    def test_save_returns_false_on_oserror(self, tmp_path: Path):
        path = tmp_path / "config.yaml"
        manager = ConfigManager(path)
        manager.load()

        with patch("builtins.open", side_effect=OSError("只读文件系统")):
            assert manager.save() is False

    def test_raises_when_directory_cannot_be_created(self, tmp_path: Path):
        """父目录不存在时写文件失败，save() 返回 False。"""
        manager = ConfigManager(tmp_path / "missing_dir" / "config.yaml")
        manager._is_new_file = True
        manager._raw_document["debug"] = False

        assert manager.save() is False


class TestResolvePath:
    """``ConfigManager._resolve_path`` 的路径解析规则。"""

    def test_relative_path_is_based_on_base_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(config, "BASE_DIR", tmp_path)

        resolved = ConfigManager._resolve_path("sub/config.yaml")

        assert resolved == (tmp_path / "sub" / "config.yaml").resolve()

    def test_absolute_path_is_kept(self, tmp_path: Path):
        absolute = tmp_path / "config.yaml"

        assert ConfigManager._resolve_path(absolute) == absolute.resolve()

    def test_user_home_is_expanded(self):
        resolved = ConfigManager._resolve_path("~/x.yaml")

        assert "~" not in str(resolved)
        assert resolved.is_absolute()

    def test_default_path_uses_base_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(config, "BASE_DIR", tmp_path)

        assert ConfigManager().config_filepath == (tmp_path / "config.yaml").resolve()


class TestMain:
    """``config.main()`` 生成/更新配置文件。"""

    def test_regenerates_example_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
        monkeypatch.setattr(config, "BASE_DIR", tmp_path)
        example = tmp_path / "config.yaml.example"
        example.write_text("旧内容", encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["config.py"])

        assert config.main() == 0

        content = example.read_text(encoding="utf-8")
        assert "旧内容" not in content
        assert "本文件由 config.py 生成" in content
        assert "已重新生成配置文件" in capsys.readouterr().out

    def test_updates_given_target_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
        target = tmp_path / "custom.yaml"
        target.write_text("debug: true\n", encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["config.py", str(target)])

        assert config.main() == 0

        assert "已更新配置文件" in capsys.readouterr().out
        assert "steamBotPort:" in target.read_text(encoding="utf-8")
