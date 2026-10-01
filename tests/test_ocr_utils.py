"""``ocr_utils`` 的单元测试。

截屏与 OCR 都依赖 Windows GDI / ctypes，这里把 ``win32gui``、``win32ui``、
``windll`` 以及 OCR 子进程 ``OcrAPI`` 全部替换成 mock，保证测试在任何环境下都不会
真的截屏、调用 Windows API 或启动 RapidOCR 子进程。
"""

from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import numpy as np
import pytest
from PIL import Image

import ocr_utils
from ocr_utils import OCREngine, OcrError, WindowCapturer

WIN_81_VERSION = (10, 0, 19045)
WIN_7_VERSION = (6, 1, 7601)


@pytest.fixture
def win():
    """把 ocr_utils 依赖的 Windows GDI 接口整体替换成 mock。"""
    gui = MagicMock(name="win32gui")
    ui = MagicMock(name="win32ui")
    windll = MagicMock(name="windll")
    with (
        patch.object(ocr_utils, "win32gui", gui),
        patch.object(ocr_utils, "win32ui", ui),
        patch.object(ocr_utils, "windll", windll),
    ):
        yield SimpleNamespace(gui=gui, ui=ui, windll=windll)


@pytest.fixture
def make_capturer(win, monkeypatch):
    """构造 WindowCapturer 的工厂，避免真实的 DPI Awareness 设置。"""
    created: list[WindowCapturer] = []

    def _make(dpi_aware: bool = True, hw_accel: bool = True) -> WindowCapturer:
        monkeypatch.setattr(ocr_utils, "enable_dpi_awareness", MagicMock(return_value=dpi_aware))
        version = WIN_81_VERSION if hw_accel else WIN_7_VERSION
        monkeypatch.setattr(ocr_utils.sys, "getwindowsversion", MagicMock(return_value=version))
        capturer = WindowCapturer()
        created.append(capturer)
        return capturer

    yield _make

    # 在被 mock 的 win32gui 下清理 GDI 资源，避免 __del__ 触发真实 API
    for capturer in created:
        capturer._cleanup_gdi_cache()


@pytest.fixture
def window_ok(monkeypatch):
    """让窗口有效性检查通过，且窗口未被最小化。"""
    monkeypatch.setattr(ocr_utils, "is_window_handler_exist", MagicMock(return_value=True))
    monkeypatch.setattr(ocr_utils, "restore_minimized_window", MagicMock(return_value=False))


def _configure_capture_success(win, width: int = 2, height: int = 2, bgra: bytes = b"") -> None:
    """配置一次成功的截屏所需的所有 mock 返回值。"""
    win.gui.GetClientRect.return_value = (0, 0, width, height)
    win.windll.user32.PrintWindow.return_value = 1
    win.ui.CreateBitmap.return_value.GetBitmapBits.return_value = bgra


class TestWindowCapturerInit:
    """构造时会设置 DPI Awareness 状态与位图硬件加速支持标志。"""

    def test_success_with_hw_acceleration(self, win, monkeypatch):
        monkeypatch.setattr(ocr_utils, "enable_dpi_awareness", MagicMock(return_value=True))
        monkeypatch.setattr(ocr_utils.sys, "getwindowsversion", MagicMock(return_value=WIN_81_VERSION))

        capturer = WindowCapturer()

        assert capturer.dpi_awareness is True
        assert capturer.printwindow_support_hw_acceleration is True
        capturer._cleanup_gdi_cache()

    def test_dpi_awareness_failure_is_recorded(self, win, monkeypatch):
        monkeypatch.setattr(ocr_utils, "enable_dpi_awareness", MagicMock(return_value=False))
        monkeypatch.setattr(ocr_utils.sys, "getwindowsversion", MagicMock(return_value=WIN_7_VERSION))

        capturer = WindowCapturer()

        assert capturer.dpi_awareness is False
        assert capturer.printwindow_support_hw_acceleration is False
        capturer._cleanup_gdi_cache()

    def test_hw_acceleration_disabled_on_old_windows(self, win, monkeypatch):
        monkeypatch.setattr(ocr_utils, "enable_dpi_awareness", MagicMock(return_value=True))
        monkeypatch.setattr(ocr_utils.sys, "getwindowsversion", MagicMock(return_value=(6, 2, 9200)))

        capturer = WindowCapturer()

        assert capturer.printwindow_support_hw_acceleration is False
        capturer._cleanup_gdi_cache()

    def test_gdi_cache_starts_empty(self, make_capturer):
        capturer = make_capturer()

        assert capturer._cached_hwnd is None
        assert capturer._cached_width == 0
        assert capturer._cached_height == 0
        assert capturer._memdc is None
        assert capturer._bmp is None


class TestCalculateWindowMetrics:
    """窗口尺寸与 PrintWindow 标志的计算。"""

    def test_window_rect_with_hw_acceleration(self, win, make_capturer):
        capturer = make_capturer(dpi_aware=True, hw_accel=True)
        win.gui.GetWindowRect.return_value = (0, 0, 800, 600)

        assert capturer._calculate_window_metrics(123, include_title_bar=True) == (800, 600, 2)
        win.gui.GetWindowRect.assert_called_once_with(123)
        win.gui.GetClientRect.assert_not_called()

    def test_client_rect_with_hw_acceleration(self, win, make_capturer):
        capturer = make_capturer(dpi_aware=True, hw_accel=True)
        win.gui.GetClientRect.return_value = (0, 0, 640, 480)

        assert capturer._calculate_window_metrics(123, include_title_bar=False) == (640, 480, 3)
        win.gui.GetClientRect.assert_called_once_with(123)

    def test_window_rect_without_hw_acceleration(self, win, make_capturer):
        capturer = make_capturer(dpi_aware=True, hw_accel=False)
        win.gui.GetWindowRect.return_value = (0, 0, 100, 200)

        assert capturer._calculate_window_metrics(1, include_title_bar=True) == (100, 200, 0)

    def test_client_rect_without_hw_acceleration(self, win, make_capturer):
        capturer = make_capturer(dpi_aware=True, hw_accel=False)
        win.gui.GetClientRect.return_value = (0, 0, 100, 200)

        assert capturer._calculate_window_metrics(1, include_title_bar=False) == (100, 200, 1)

    def test_non_dpi_aware_applies_monitor_scale(self, win, make_capturer, monkeypatch):
        capturer = make_capturer(dpi_aware=False, hw_accel=True)
        monkeypatch.setattr(ocr_utils, "get_primary_monitor_dpi_scale", MagicMock(return_value=1.5))
        win.gui.GetClientRect.return_value = (0, 0, 100, 200)

        assert capturer._calculate_window_metrics(1, include_title_bar=False) == (150, 300, 3)

    def test_non_dpi_aware_truncates_scaled_size(self, win, make_capturer, monkeypatch):
        capturer = make_capturer(dpi_aware=False, hw_accel=True)
        monkeypatch.setattr(ocr_utils, "get_primary_monitor_dpi_scale", MagicMock(return_value=1.25))
        win.gui.GetClientRect.return_value = (0, 0, 101, 102)

        assert capturer._calculate_window_metrics(1, include_title_bar=False) == (126, 127, 3)

    @pytest.mark.parametrize("rect", [(0, 0, 0, 100), (0, 0, 100, 0), (0, 0, -5, 100)])
    def test_invalid_physical_size_raises(self, win, make_capturer, rect):
        capturer = make_capturer(dpi_aware=True, hw_accel=True)
        win.gui.GetClientRect.return_value = rect

        with pytest.raises(Exception, match="窗口物理尺寸无效"):
            capturer._calculate_window_metrics(1, include_title_bar=False)


class TestGdiCache:
    """GDI 资源缓存的建立与清理。"""

    def test_initialize_gdi_cache_creates_and_releases_dc(self, win, make_capturer):
        capturer = make_capturer()
        win.gui.GetWindowDC.return_value = 4321
        srcdc = win.ui.CreateDCFromHandle.return_value
        memdc = srcdc.CreateCompatibleDC.return_value
        bitmap = win.ui.CreateBitmap.return_value
        old_bitmap = memdc.SelectObject.return_value

        capturer._initialize_gdi_cache(123, 20, 10)

        win.gui.GetWindowDC.assert_called_once_with(123)
        win.ui.CreateDCFromHandle.assert_called_once_with(4321)
        bitmap.CreateCompatibleBitmap.assert_called_once_with(srcdc, 20, 10)
        memdc.SelectObject.assert_called_once_with(bitmap)
        srcdc.DeleteDC.assert_called_once_with()
        win.gui.ReleaseDC.assert_called_once_with(123, 4321)

        assert capturer._memdc is memdc
        assert capturer._bmp is bitmap
        assert capturer._old_bmp is old_bitmap
        assert (capturer._cached_hwnd, capturer._cached_width, capturer._cached_height) == (123, 20, 10)

    def test_initialize_gdi_cache_releases_dc_on_failure(self, win, make_capturer):
        capturer = make_capturer()
        win.gui.GetWindowDC.return_value = 4321
        win.ui.CreateDCFromHandle.side_effect = OSError("创建 DC 失败")

        with pytest.raises(OSError):
            capturer._initialize_gdi_cache(123, 20, 10)

        win.gui.ReleaseDC.assert_called_once_with(123, 4321)

    def test_cleanup_gdi_cache(self, win, make_capturer):
        capturer = make_capturer()
        capturer._cached_hwnd = 1
        capturer._cached_width = 2
        capturer._cached_height = 3
        memdc = MagicMock(name="memdc")
        bitmap = MagicMock(name="bitmap")
        old_bitmap = MagicMock(name="old_bitmap")
        capturer._memdc = memdc
        capturer._bmp = bitmap
        capturer._old_bmp = old_bitmap

        capturer._cleanup_gdi_cache()

        memdc.SelectObject.assert_called_once_with(old_bitmap)
        memdc.DeleteDC.assert_called_once_with()
        bitmap.GetHandle.assert_called_once_with()
        win.gui.DeleteObject.assert_called_once_with(bitmap.GetHandle.return_value)
        assert capturer._memdc is None
        assert capturer._bmp is None
        assert capturer._cached_hwnd is None
        assert capturer._cached_width == 0
        assert capturer._cached_height == 0

    def test_cleanup_gdi_cache_is_idempotent(self, win, make_capturer):
        capturer = make_capturer()

        capturer._cleanup_gdi_cache()  # 不应抛出异常


class TestCaptureWindow:
    """整窗截图的成功与失败路径。"""

    def test_invalid_hwnd_raises_and_cleans_cache(self, win, make_capturer, monkeypatch):
        capturer = make_capturer()
        monkeypatch.setattr(ocr_utils, "is_window_handler_exist", MagicMock(return_value=False))

        with pytest.raises(Exception, match="窗口句柄 999 无效"):
            capturer.capture_window(999)

        assert capturer._cached_hwnd is None

    def test_success_returns_rgb_numpy_array(self, win, make_capturer, window_ok):
        capturer = make_capturer(dpi_aware=True, hw_accel=True)
        bgra = bytes(
            [
                1,
                2,
                3,
                0,  # 第 0 行第 0 列: B=1 G=2 R=3
                4,
                5,
                6,
                0,  # 第 0 行第 1 列
                7,
                8,
                9,
                0,  # 第 1 行第 0 列
                10,
                11,
                12,
                0,  # 第 1 行第 1 列
            ]
        )
        _configure_capture_success(win, width=2, height=2, bgra=bgra)

        result = capturer.capture_window(123)

        assert isinstance(result, np.ndarray)
        assert result.shape == (2, 2, 3)
        assert result.flags["C_CONTIGUOUS"]
        assert result.tolist() == [
            [[3, 2, 1], [6, 5, 4]],
            [[9, 8, 7], [12, 11, 10]],
        ]
        win.windll.user32.PrintWindow.assert_called_once_with(123, capturer._memdc.GetSafeHdc.return_value, 3)

    def test_restore_minimized_window_sleeps(self, win, make_capturer, monkeypatch, no_sleep):
        capturer = make_capturer(dpi_aware=True, hw_accel=True)
        monkeypatch.setattr(ocr_utils, "is_window_handler_exist", MagicMock(return_value=True))
        monkeypatch.setattr(ocr_utils, "restore_minimized_window", MagicMock(return_value=True))
        _configure_capture_success(win, bgra=bytes(2 * 2 * 4))

        capturer.capture_window(123)

        assert call(0.2) in no_sleep.call_args_list

    def test_same_window_reuses_gdi_cache(self, win, make_capturer, window_ok):
        capturer = make_capturer(dpi_aware=True, hw_accel=True)
        _configure_capture_success(win, width=4, height=4, bgra=bytes(4 * 4 * 4))

        capturer.capture_window(123)
        capturer.capture_window(123)

        win.gui.GetWindowDC.assert_called_once_with(123)
        win.ui.CreateBitmap.assert_called_once_with()

    def test_changed_size_rebuilds_gdi_cache(self, win, make_capturer, window_ok):
        capturer = make_capturer(dpi_aware=True, hw_accel=True)
        _configure_capture_success(win, width=4, height=4, bgra=bytes(4 * 4 * 4))
        capturer.capture_window(123)

        win.gui.GetClientRect.return_value = (0, 0, 5, 4)
        win.ui.CreateBitmap.return_value.GetBitmapBits.return_value = bytes(5 * 4 * 4)
        capturer.capture_window(123)

        assert win.gui.GetWindowDC.call_count == 2
        assert win.ui.CreateBitmap.call_count == 2

    def test_changed_hwnd_rebuilds_gdi_cache(self, win, make_capturer, window_ok):
        capturer = make_capturer(dpi_aware=True, hw_accel=True)
        _configure_capture_success(win, width=4, height=4, bgra=bytes(4 * 4 * 4))
        capturer.capture_window(123)

        capturer.capture_window(456)

        assert win.gui.GetWindowDC.call_count == 2

    def test_printwindow_failure_raises_and_cleans_cache(self, win, make_capturer, window_ok):
        capturer = make_capturer(dpi_aware=True, hw_accel=True)
        _configure_capture_success(win, width=2, height=2, bgra=bytes(2 * 2 * 4))
        win.windll.user32.PrintWindow.return_value = 0

        with pytest.raises(Exception, match="PrintWindow API 调用失败"):
            capturer.capture_window(123)

        assert capturer._cached_hwnd is None
        assert capturer._bmp is None

    def test_missing_gdi_resources_raises(self, win, make_capturer, window_ok):
        capturer = make_capturer(dpi_aware=True, hw_accel=True)
        _configure_capture_success(win, width=2, height=2, bgra=bytes(2 * 2 * 4))
        capturer.capture_window(123)
        # 缓存仍然命中，但 GDI 资源被外部清空了
        capturer._bmp = None

        with pytest.raises(Exception, match="GDI 资源未正确初始化"):
            capturer.capture_window(123)


class TestCaptureWindowArea:
    """区域截图的参数校验与裁剪。"""

    @pytest.mark.parametrize(
        ("left", "top", "width", "height"),
        [
            (-0.1, 0, 1, 1),
            (0, -0.1, 1, 1),
            (0, 0, 1.1, 1),
            (0, 0, 1, 1.1),
        ],
    )
    def test_out_of_range_raises_value_error(self, make_capturer, left, top, width, height):
        capturer = make_capturer()

        with pytest.raises(ValueError, match=r"相对坐标和尺寸必须在 0\.0 到 1\.0 之间"):
            capturer.capture_window_area(123, left, top, width, height)

    def test_left_plus_width_over_one_raises(self, make_capturer):
        capturer = make_capturer()

        with pytest.raises(ValueError, match=r"的和不能超过 1\.0"):
            capturer.capture_window_area(123, 0.6, 0.0, 0.5, 1.0)

    def test_top_plus_height_over_one_raises(self, make_capturer):
        capturer = make_capturer()

        with pytest.raises(ValueError, match=r"的和不能超过 1\.0"):
            capturer.capture_window_area(123, 0.0, 0.6, 1.0, 0.5)

    def test_zero_pixel_size_raises(self, make_capturer, monkeypatch):
        capturer = make_capturer()
        monkeypatch.setattr(capturer, "capture_window", MagicMock(return_value=np.zeros((100, 100, 3), dtype=np.uint8)))

        with pytest.raises(ValueError, match="计算出的截图区域尺寸无效"):
            capturer.capture_window_area(123, 0.0, 0.0, 0.001, 0.5)

    def test_crops_expected_region(self, make_capturer, monkeypatch):
        capturer = make_capturer()
        full = np.arange(10 * 10 * 3, dtype=np.uint8).reshape((10, 10, 3))
        capture_mock = MagicMock(return_value=full)
        monkeypatch.setattr(capturer, "capture_window", capture_mock)

        result = capturer.capture_window_area(123, 0.2, 0.1, 0.3, 0.2, include_title_bar=True)

        np.testing.assert_array_equal(result, full[1:3, 2:5])
        capture_mock.assert_called_once_with(123, True)


class TestToPng:
    """numpy 数组到 PNG 字节流的转换。"""

    def test_returns_valid_png_bytes(self):
        image_np = np.zeros((4, 6, 3), dtype=np.uint8)

        png_bytes = WindowCapturer.to_png(image_np)

        assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        with Image.open(BytesIO(png_bytes)) as image:
            assert image.format == "PNG"
            assert image.size == (6, 4)


class TestOcrEngineInit:
    """OCR 引擎的初始化与子进程启动。"""

    def test_missing_executable_raises_file_not_found(self, monkeypatch):
        monkeypatch.setattr(ocr_utils.os.path, "exists", MagicMock(return_value=False))
        thread_cls = MagicMock(name="Thread")
        monkeypatch.setattr(ocr_utils.threading, "Thread", thread_cls)

        with pytest.raises(FileNotFoundError, match="未找到OCR引擎"):
            OCREngine("--args")

        # 即使失败也创建了紧急关闭线程
        thread_cls.return_value.start.assert_called_once_with()

    def test_success_creates_api_and_capturer(self, monkeypatch):
        monkeypatch.setattr(ocr_utils.os.path, "exists", MagicMock(return_value=True))
        monkeypatch.setattr(ocr_utils.threading, "Thread", MagicMock(name="Thread"))
        api_cls = MagicMock(name="OcrAPI")
        capturer_cls = MagicMock(name="WindowCapturer")
        monkeypatch.setattr(ocr_utils, "OcrAPI", api_cls)
        monkeypatch.setattr(ocr_utils, "WindowCapturer", capturer_cls)

        engine = OCREngine("--det=xxx")

        api_cls.assert_called_once_with(ocr_utils.OCR_EXECUTABLE_PATH, argsStr="--det=xxx")
        assert engine.api is api_cls.return_value
        assert engine.args == "--det=xxx"
        assert engine.screen_capturer is capturer_cls.return_value

    def test_emergency_killer_thread_is_daemon(self, monkeypatch):
        monkeypatch.setattr(ocr_utils.os.path, "exists", MagicMock(return_value=True))
        thread_cls = MagicMock(name="Thread")
        monkeypatch.setattr(ocr_utils.threading, "Thread", thread_cls)
        monkeypatch.setattr(ocr_utils, "OcrAPI", MagicMock(name="OcrAPI"))
        monkeypatch.setattr(ocr_utils, "WindowCapturer", MagicMock(name="WindowCapturer"))

        OCREngine("--args")

        _, kwargs = thread_cls.call_args
        assert kwargs["daemon"] is True
        assert kwargs["target"].__name__ == "instant_kill_rapidocr"


def _make_bare_engine() -> OCREngine:
    """绕过 __init__ 构造一个只带 mock 组件的 OCREngine。"""
    engine = OCREngine.__new__(OCREngine)
    engine.args = "--args"
    engine.api = MagicMock(name="api")
    engine.screen_capturer = MagicMock(name="screen_capturer")
    return engine


class TestOcrEngineShutdownAndRestart:
    def test_shutdown_stops_api(self):
        engine = _make_bare_engine()

        engine.shutdown()

        engine.api.stop.assert_called_once_with()

    def test_shutdown_swallows_exception(self):
        engine = _make_bare_engine()
        engine.api.stop.side_effect = RuntimeError("进程已死")

        engine.shutdown()  # 不应抛出异常

    def test_restart_recreates_api(self, monkeypatch):
        engine = _make_bare_engine()
        old_api = engine.api
        api_cls = MagicMock(name="OcrAPI")
        monkeypatch.setattr(ocr_utils, "OcrAPI", api_cls)

        engine.restart()

        old_api.stop.assert_called_once_with()
        api_cls.assert_called_once_with(ocr_utils.OCR_EXECUTABLE_PATH, argsStr="--args")
        assert engine.api is api_cls.return_value

    def test_restart_tolerates_stop_failure(self, monkeypatch):
        engine = _make_bare_engine()
        engine.api.stop.side_effect = RuntimeError("关不掉")
        monkeypatch.setattr(ocr_utils, "OcrAPI", MagicMock(name="OcrAPI"))

        engine.restart()  # 不应抛出异常

    def test_restart_raises_ocr_error_when_recreate_fails(self, monkeypatch):
        engine = _make_bare_engine()
        monkeypatch.setattr(ocr_utils, "OcrAPI", MagicMock(side_effect=RuntimeError("启动失败")))

        with pytest.raises(OcrError, match="重启 OCR 引擎失败"):
            engine.restart()


class TestGetPhysicalRect:
    def test_window_rect(self, win):
        engine = _make_bare_engine()
        win.gui.GetWindowRect.return_value = (10, 20, 110, 220)

        assert engine._get_physical_rect(123, include_title_bar=True) == (10, 20, 110, 220)
        win.gui.GetWindowRect.assert_called_once_with(123)
        win.gui.GetClientRect.assert_not_called()

    def test_client_rect(self, win):
        engine = _make_bare_engine()
        win.gui.GetClientRect.return_value = (0, 0, 50, 60)
        win.gui.ClientToScreen.return_value = (100, 200)

        assert engine._get_physical_rect(123, include_title_bar=False) == (100, 200, 150, 260)
        win.gui.ClientToScreen.assert_called_once_with(123, (0, 0))

    def test_failure_wrapped_in_exception(self, win):
        engine = _make_bare_engine()
        win.gui.GetWindowRect.side_effect = OSError("窗口没了")

        with pytest.raises(Exception, match="获取物理坐标失败"):
            engine._get_physical_rect(123, include_title_bar=True)


class TestOcrWindow:
    """OCR 结果解析与错误转换。"""

    def test_joins_all_recognized_text(self):
        engine = _make_bare_engine()
        engine.api.runBytes.return_value = {
            "code": 100,
            "data": [{"text": "别惹"}, {"text": "德瑞"}],
        }

        assert engine.ocr_window(123, left=0.1, top=0.2, width=0.3, height=0.4) == "别惹德瑞"
        engine.screen_capturer.capture_window_area.assert_called_once_with(123, 0.1, 0.2, 0.3, 0.4, False)
        engine.screen_capturer.to_png.assert_called_once_with(engine.screen_capturer.capture_window_area.return_value)
        engine.api.runBytes.assert_called_once_with(engine.screen_capturer.to_png.return_value)

    def test_code_100_with_empty_data_returns_empty_string(self):
        engine = _make_bare_engine()
        engine.api.runBytes.return_value = {"code": 100, "data": []}

        assert engine.ocr_window(123) == ""

    def test_code_101_returns_empty_string(self):
        engine = _make_bare_engine()
        engine.api.runBytes.return_value = {"code": 101, "data": "no text"}

        assert engine.ocr_window(123) == ""

    def test_unknown_code_returns_empty_string(self):
        engine = _make_bare_engine()
        engine.api.runBytes.return_value = {"code": 500, "data": "内部错误"}

        assert engine.ocr_window(123) == ""

    def test_none_result_returns_empty_string(self):
        """后端无返回结果（JSON ``null``）时应记录错误并返回空串，而不是崩溃。"""
        engine = _make_bare_engine()
        engine.api.runBytes.return_value = None

        assert engine.ocr_window(123) == ""

    def test_non_dict_result_returns_empty_string(self):
        """返回结果不是字典时同样应返回空串。"""
        engine = _make_bare_engine()
        engine.api.runBytes.return_value = "not a dict"

        assert engine.ocr_window(123) == ""

    def test_runbytes_failure_raises_ocr_error(self):
        engine = _make_bare_engine()
        engine.api.runBytes.side_effect = RuntimeError("子进程崩溃")

        with pytest.raises(OcrError, match="OCR 后端出错"):
            engine.ocr_window(123)

    def test_capture_value_error_propagates(self):
        engine = _make_bare_engine()
        engine.screen_capturer.capture_window_area.side_effect = ValueError("坐标非法")

        with pytest.raises(ValueError, match="坐标非法"):
            engine.ocr_window(123)

    def test_include_title_bar_is_passed_through(self):
        engine = _make_bare_engine()
        engine.api.runBytes.return_value = {"code": 101, "data": ""}

        engine.ocr_window(123, left=0, top=0, width=1, height=1, include_title_bar=True)

        engine.screen_capturer.capture_window_area.assert_called_once_with(123, 0, 0, 1, 1, True)
