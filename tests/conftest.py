"""pytest 全局配置与共享 fixture。

本项目是一个 Windows 游戏自动化脚本，正常运行时会产生大量副作用（按键/手柄模拟、
窗口操作、截屏、网络请求、进程操作、文件写入）。单元测试必须在任何环境（包括无头
CI/CD）下都**不触发任何真实副作用**，因此本文件用 autouse fixture 主动拦截所有危险
的底层调用：

- 所有 ``sleep`` 变体（避免测试耗时极长）
- ``atexit.register``（避免虚拟手柄/游戏进程的清理回调在测试进程退出时乱跑）
- ``requests`` 全部方法（避免真实网络请求，需要时由用例自行 mock）
- ``subprocess.run`` / ``subprocess.Popen``（避免真实启动子进程）
- ``builtins.input``（避免交互式输入阻塞测试）
- ``time.monotonic``（换成可手动推进的假时钟，避免轮询逻辑忙等真实时间）

需要真实行为的用例可以在测试内部再次 patch 对应对象覆盖这些拦截。
"""

from __future__ import annotations

import atexit
import importlib
import subprocess
import sys
import time
from unittest.mock import MagicMock

import pytest
import requests

# 所有需要被替换为「无操作」的睡眠端点，格式为 ``模块名.属性名``。
# 由于各模块使用 ``from app_lifecycle import sleep_smart as sleep`` 直接导入，
# 只 patch ``app_lifecycle`` 无法影响已经绑定的名字，必须逐个模块替换。
_SLEEP_TARGETS = (
    "app_lifecycle.sleep_smart",
    "app_lifecycle.sleep_stoppable",
    "gta_automator.sleep",
    "gta_automator._base_workflow.sleep",
    "gta_automator.game_action.sleep",
    "gta_automator.job_workflow.sleep",
    "gta_automator.lifecycle_workflow.sleep",
    "gta_automator.online_workflow.sleep",
    "gamepad_utils.sleep",
    "health_check.sleep",
    "keyboard_utils.sleep",
    "main.sleep_smart",
    "ocr_utils.sleep",
    "steambot_utils.sleep",
    "steamgui_automation.sleep",
    "windows_utils.sleep_smart",
    "windows_utils.sleep_stoppable",
)

# 这些模块在导入时就会产生副作用（例如 main.py 会调用 init_lifecycle_manager()
# 注册真实的 Windows 控制台回调），因此只有在它们已经被用例导入过时才去 patch。
_NEVER_AUTO_IMPORT = frozenset({"main"})


class FakeClock:
    """可手动控制的假单调时钟。

    默认每次读取都会前进 ``step`` 秒，这样基于 ``time.monotonic()`` 的超时轮询
    会在有限次迭代后自然结束，不会真的等待超时时长。需要精确控制时间的用例可以把
    ``step`` 设为 0 并配合 :meth:`advance` 使用。
    """

    def __init__(self, start: float = 1000.0, step: float = 1.0):
        self.now = float(start)
        self.step = float(step)

    def monotonic(self) -> float:
        self.now += self.step
        return self.now

    def advance(self, seconds: float) -> float:
        """主动向前推进指定秒数。"""
        self.now += float(seconds)
        return self.now

    def set(self, value: float) -> None:
        """直接设定当前时间。"""
        self.now = float(value)


def _patch_optional_attr(monkeypatch: pytest.MonkeyPatch, dotted_target: str, value: object) -> None:
    """patch 一个 ``模块.属性``，模块不存在时静默跳过。"""
    module_name, _, attribute = dotted_target.rpartition(".")
    module = sys.modules.get(module_name)
    if module is None:
        if module_name in _NEVER_AUTO_IMPORT:
            return
        try:
            module = importlib.import_module(module_name)
        except Exception:  # pragma: no cover - 缺少可选依赖时跳过
            return
    if hasattr(module, attribute):
        monkeypatch.setattr(module, attribute, value)


@pytest.fixture(autouse=True)
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """把 ``time.monotonic`` 替换成假时钟，避免忙等真实时间。"""
    clock = FakeClock()
    monkeypatch.setattr(time, "monotonic", clock.monotonic)
    return clock


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """拦截所有睡眠函数，并返回被安装的 mock 供用例断言。"""
    fake_sleep = MagicMock(name="sleep", return_value=True)
    for target in _SLEEP_TARGETS:
        _patch_optional_attr(monkeypatch, target, fake_sleep)
    return fake_sleep


@pytest.fixture(autouse=True)
def block_atexit(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """阻止对象在构造时注册真实的 atexit 回调。"""
    mock_register = MagicMock(name="atexit.register")
    monkeypatch.setattr(atexit, "register", mock_register)
    return mock_register


@pytest.fixture(autouse=True)
def block_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认禁止真实网络请求；需要时用例自行 patch ``requests.xxx`` 覆盖。"""

    def _forbidden(*args, **kwargs):
        raise AssertionError("测试中禁止发起真实网络请求，请先 mock requests")

    for method in ("get", "post", "put", "patch", "delete", "request", "head"):
        if hasattr(requests, method):
            monkeypatch.setattr(requests, method, _forbidden)


@pytest.fixture(autouse=True)
def block_subprocess(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认禁止真实启动子进程；需要时用例自行 patch 覆盖。"""

    def _forbidden(*args, **kwargs):
        raise AssertionError("测试中禁止执行真实子进程，请先 mock subprocess")

    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)


@pytest.fixture(autouse=True)
def safe_input(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """把 ``input()`` 替换成立即返回空字符串的 mock，避免交互阻塞。"""
    mock_input = MagicMock(name="input", return_value="")
    monkeypatch.setattr("builtins.input", mock_input)
    return mock_input


@pytest.fixture
def config():
    """一个使用默认值构造的 Config 实例。"""
    from config import Config

    return Config()


@pytest.fixture
def ocr_mock() -> MagicMock:
    """符合 ``OcrFuncProtocol`` 的 OCR 桩函数，默认识别不出任何文本。"""
    return MagicMock(name="ocr_func", return_value="")
