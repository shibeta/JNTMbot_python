import os
import sys
import threading
from PIL import Image
import io
import win32gui
import win32ui
import numpy as np
from ctypes import windll

from app_lifecycle import sleep_smart as sleep, _exit_event
from RapidOCR_api import OcrAPI
from windows_utils import (
    is_window_handler_exist,
    restore_minimized_window,
    enable_dpi_awareness,
    get_primary_monitor_dpi_scale,
)
from logger import get_logger

logger = get_logger(__name__)

# 设置 RapidOCR-json.exe 的绝对或相对路径
# 例如: r"C:\path\to\RapidOCR-json.exe"
OCR_EXECUTABLE_PATH = os.path.join(os.getcwd(), "RapidOCR-json.exe")

# RapidOCR 进程锁，防止多线程时出现问题
rapidocr_lock = threading.Lock()


class WindowCapturer:
    """
    基于 PrintWindow 捕获窗口内容，支持被遮挡窗口和高DPI环境。
    """

    def __init__(self):
        """
        初始化 PrintWindow 必须的一些配置。
        """
        # 启用 DPI Aware 以用于在截图时自动计算 DPI 缩放
        if enable_dpi_awareness():
            self.dpi_awareness = True
        else:
            logger.warning("设置 DPI Awareness 失败，将使用传统方式计算 DPI 缩放")
            self.dpi_awareness = False

        # 检查系统版本以确定是否支持 PW_RENDERFULLCONTENT
        version = sys.getwindowsversion()[:2]
        if version >= (6, 3):
            # Windows 8.1+
            self.printwindow_support_hw_acceleration = True
        else:
            self.printwindow_support_hw_acceleration = False

        # GDI 资源缓存
        self._cached_hwnd = None  # 缓存的目标窗口句柄
        self._cached_width = 0  # 缓存的目标窗口宽度
        self._cached_height = 0  # 缓存的目标窗口高度
        self._memdc = None  # 缓存的从显示器创建的 CompatibleDC
        self._bmp = None  # 缓存的位图对象
        self._old_bmp = None  # _memdc 中最初的 Object ，用于释放 _memdc

    def __del__(self):
        """确保对象销毁时释放资源"""
        self._cleanup_gdi_cache()

    def _cleanup_gdi_cache(self):
        """清理缓存的 GDI 资源"""
        if self._memdc is not None:
            if self._old_bmp is not None:
                self._memdc.SelectObject(self._old_bmp)
            self._memdc.DeleteDC()
            self._memdc = None
        if self._bmp is not None:
            win32gui.DeleteObject(self._bmp.GetHandle())
            self._bmp = None
        self._cached_width = 0
        self._cached_height = 0
        self._cached_hwnd = None

    def _calculate_window_metrics(self, hwnd: int, include_title_bar: bool) -> tuple:
        """
        计算窗口尺寸和所需的 PrintWindow 标志
        :return: (window_width, window_height, print_flags)
        """
        if include_title_bar:
            window_rect = win32gui.GetWindowRect(hwnd)
            print_flags = 2 if self.printwindow_support_hw_acceleration else 0
        else:
            window_rect = win32gui.GetClientRect(hwnd)
            print_flags = 3 if self.printwindow_support_hw_acceleration else 1

        if self.dpi_awareness:
            window_width = window_rect[2] - window_rect[0]
            window_height = window_rect[3] - window_rect[1]
        else:
            proportion = get_primary_monitor_dpi_scale()
            window_width = int((window_rect[2] - window_rect[0]) * proportion)
            window_height = int((window_rect[3] - window_rect[1]) * proportion)

        if window_width <= 0 or window_height <= 0:
            raise Exception("窗口物理尺寸无效，无法截图。")

        return window_width, window_height, print_flags

    def _initialize_gdi_cache(self, hwnd: int, width: int, height: int):
        """
        重建 GDI 资源缓存
        """
        hwindc = None
        srcdc = None

        try:
            hwindc = win32gui.GetWindowDC(hwnd)
            srcdc = win32ui.CreateDCFromHandle(hwindc)
            self._memdc = srcdc.CreateCompatibleDC()
            self._bmp = win32ui.CreateBitmap()
            self._bmp.CreateCompatibleBitmap(srcdc, width, height)
            self._old_bmp = self._memdc.SelectObject(self._bmp)

        finally:
            if srcdc is not None:
                srcdc.DeleteDC()
            if hwindc is not None:
                win32gui.ReleaseDC(hwnd, hwindc)

        # 更新缓存标志
        self._cached_hwnd = hwnd
        self._cached_width = width
        self._cached_height = height

    def capture_window(self, hwnd: int, include_title_bar: bool = False):
        """
        使用 Windows User32.dll 的 PrintWindow 捕获一个窗口，返回 numpy 数组。

        :param hwnd: 要捕获的窗口句柄
        :type hwnd: int
        :param include_title_bar: 是否包含标题栏
        :type include_title_bar: bool
        :return: numpy 数组格式的图片
        :raises ``Exception``: 截图失败
        """
        try:
            # 判断窗口是否有效
            if not win32gui.IsWindow(hwnd):
                self._cleanup_gdi_cache()
                raise Exception(f"窗口句柄 {hwnd} 无效或已关闭。")

            # 将窗口取消最小化
            if restore_minimized_window(hwnd):
                sleep(0.2)

            # 计算窗口尺寸
            window_width, window_height, print_flags = self._calculate_window_metrics(hwnd, include_title_bar)

            # 目标窗口或窗口尺寸变化时，重建 GDI 资源缓存
            if (
                self._cached_hwnd != hwnd
                or self._cached_width != window_width
                or self._cached_height != window_height
            ):
                logger.debug("截图目标窗口发生变化，重建 GDI 资源缓存。")
                # 清理
                self._cleanup_gdi_cache()
                # 重建
                self._initialize_gdi_cache(hwnd, window_width, window_height)

            # 检查位图对象和 memdc 对象
            if self._bmp is None or self._memdc is None:
                raise Exception("GDI 资源未正确初始化。")

            # 调用 printWindow 截取整个窗口
            if windll.user32.PrintWindow(hwnd, self._memdc.GetSafeHdc(), print_flags) == 0:
                raise Exception("PrintWindow API 调用失败。")

            # 从位图对象中提取位图数据 (1D)
            bmp_bits = self._bmp.GetBitmapBits(True)
            # 将 1D 数组重塑为 4通道 numpy数组 (BGRA)
            bgra_array = np.frombuffer(bmp_bits, dtype=np.uint8).reshape((window_height, window_width, 4))
            # 丢弃不需要的 alpha/padding 通道，仅保留 RGB
            rgb_array = bgra_array[:, :, 2::-1]
            # 用 np.ascontiguousarray 确保内存是连续的，避免出现 bug
            return np.ascontiguousarray(rgb_array)

        except Exception as e:
            self._cleanup_gdi_cache()
            raise e

    def capture_window_area(
        self, hwnd: int, left: float, top: float, width: float, height: float, include_title_bar: bool = False
    ):
        """
        使用 Windows User32.dll 的 PrintWindow 对一个窗口进行区域截图，返回 numpy 数组。

        :param hwnd: 要截图的窗口句柄
        :type hwnd: int
        :param left: 截图区域左上角的相对横坐标 (0.0 to 1.0)。
        :type left: float
        :param top: 截图区域左上角的相对纵坐标 (0.0 to 1.0)。
        :type top: float
        :param width: 截图区域的相对宽度 (0.0 to 1.0)。超过
        :type width: float
        :param height: 截图区域的相对高度 (0.0 to 1.0)。
        :type height: float
        :param include_title_bar: 是否包含标题栏
        :type include_title_bar: bool
        :return: numpy 数组格式的图片
        :rtype: numpy.ndarray
        :raises ``ValueError``: 传入的坐标或长宽有误
        :raises ``Exception``: 截图失败
        """
        if not all(0.0 <= val <= 1.0 for val in [left, top, width, height]):
            raise ValueError("相对坐标和尺寸必须在 0.0 到 1.0 之间。")
        if left + width > 1.0:
            raise ValueError(f"参数 'left' ({left}) + 'width' ({width}) 的和不能超过 1.0")
        if top + height > 1.0:
            raise ValueError(f"参数 'top' ({top}) + 'height' ({height}) 的和不能超过 1.0")

        full_image_np = self.capture_window(hwnd, include_title_bar)
        base_height, base_width, _ = full_image_np.shape

        pixel_left = int(left * base_width)
        pixel_top = int(top * base_height)
        pixel_width = int(width * base_width)
        pixel_height = int(height * base_height)
        if pixel_width <= 0 or pixel_height <= 0:
            raise ValueError("计算出的截图区域尺寸无效。")

        cropped_image_np = full_image_np[
            pixel_top : pixel_top + pixel_height, pixel_left : pixel_left + pixel_width
        ]

        # debug: 保存截图以便排查问题
        # pil_image = Image.fromarray(cropped_image_np)
        # os.makedirs("screenshots", exist_ok=True)
        # save_path = os.path.join("screenshots", f"{datetime.now().strftime("%Y-%m-%d_%H_%M_%S")}.png")
        # pil_image.save(save_path)

        return cropped_image_np

    @staticmethod
    def to_png(image_np: np.ndarray) -> bytes:
        """
        将 RGB 的 numpy 数组转换为 PNG 字节对象。

        :param image_np: numpy 数组格式的图片，格式为 RGB
        :type image_np: np.ndarray
        :return: 字节对象存储的 PNG 图片
        :rtype: bytes
        """
        pil_image = Image.fromarray(image_np)
        byte_stream = io.BytesIO()
        pil_image.save(byte_stream, format="PNG")

        # debug: 保存截图以便排查问题
        # os.makedirs("screenshots", exist_ok=True)
        # save_path = os.path.join("screenshots", f"{datetime.now().strftime("%Y-%m-%d_%H_%M_%S")}.png")
        # pil_image.save(save_path)

        return byte_stream.getvalue()


class OCREngine:
    """
    使用 RapidOCR_api.py 与 C++ 可执行程序通信，以实现高性能OCR功能。
    """

    def __init__(self, args: str):
        """
        初始化 OcrAPI，它会启动并管理一个 RapidOCR-json.exe 子进程。
        """
        logger.info("正在初始化 OCR 引擎...")

        # 使用哨兵进程确保程序退出时 OCR 引擎立即被关闭
        # atexit.register(self.shutdown)
        def instant_kill_rapidocr():
            # 通过等待信号量实现的挂起基本不耗费性能
            _exit_event.wait()
            try:
                # 不申请锁以尽快杀死子进程，无需等待现有 OCR 动作完成
                # 代价是现有的 OCR 动作会因为 Popen 被关闭而抛出异常
                # stop() 方法本身调用 Popen.stop() 方法，不需要申请锁
                self.api.stop()
            finally:
                pass

        self.emergency_killer_thread = threading.Thread(
            target=instant_kill_rapidocr, daemon=True, name="OcrEmergencyKiller"
        )
        self.emergency_killer_thread.start()

        # 检查 OCR 引擎可执行文件是否存在
        if not os.path.exists(OCR_EXECUTABLE_PATH):
            logger.error(f"OCR 引擎可执行文件不存在，请检查路径配置: {OCR_EXECUTABLE_PATH}")
            raise FileNotFoundError(f"未找到OCR引擎: {OCR_EXECUTABLE_PATH}")

        logger.info(f"使用以下参数启动 OCR 引擎: {args}")

        with rapidocr_lock:
            self.api = OcrAPI(OCR_EXECUTABLE_PATH, argsStr=args)

        # 初始化截图引擎
        self.screen_capturer = WindowCapturer()

        logger.warning("OCR 引擎初始化完成。")

    def shutdown(self):
        """
        关闭 RapidOCR-json.exe 子进程。
        """
        try:
            with rapidocr_lock:
                self.api.stop()
        except Exception as e:
            logger.error(f"关闭 OCR 引擎时出错: {e}")

    def _get_physical_rect(self, hwnd: int, include_title_bar: bool) -> tuple[int, int, int, int]:
        """
        辅助函数：获取窗口或客户区的指定区域的物理像素坐标

        :param hwnd: 目标窗口的句柄。
        :param include_title_bar: 是否将标题栏和边框计算在内。(True: 基于完整窗口计算 False: 基于客户区计算 (排除标题栏和边框))
        :return: 一个有4个元素的元组，对应窗口或客户区左上右下的物理像素坐标。
        :raises ``Exception``: 获取物理坐标失败
        """
        try:
            if include_title_bar:
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            else:
                client_rect = win32gui.GetClientRect(hwnd)
                client_width = client_rect[2] - client_rect[0]
                client_height = client_rect[3] - client_rect[1]
                left, top = win32gui.ClientToScreen(hwnd, (0, 0))
                right = left + client_width
                bottom = top + client_height
            return left, top, right, bottom
        except Exception as e:
            raise Exception(f"获取物理坐标失败: {e}") from e

    def ocr_window(
        self,
        hwnd: int,
        left: float = 0,
        top: float = 0,
        width: float = 1,
        height: float = 1,
        include_title_bar: bool = False,
    ) -> str:
        """
        对指定窗口的特定区域进行 OCR 识别。

        :param hwnd: 目标窗口句柄。
        :param left: 截图区域左上角的相对横坐标 (0.0 to 1.0)。
        :param top: 截图区域左上角的相对纵坐标 (0.0 to 1.0)。
        :param width: 截图区域的相对宽度 (0.0 to 1.0)。
        :param height: 截图区域的相对高度 (0.0 to 1.0)。
        :param include_title_bar: 是否将标题栏和边框计算在内。(True: 基于完整窗口截图 False: 基于客户区截图 (排除标题栏和边框))
        :return: 识别出的所有文本拼接成的字符串。
        :raises ``ValueError``: 提供的窗口句柄无效。
        """
        if not is_window_handler_exist(hwnd):
            logger.error(f"要截图的窗口 {hwnd} 是一个无效的窗口句柄。")
            raise ValueError(f"无效的窗口句柄: {hwnd}")

        try:
            # 截图
            # logger.debug(
            #     f"开始对窗口 {hwnd} 截图，{'不' if not include_title_bar else ''}包括标题栏，截图范围 {left}, {top}, {width}, {height} 。"
            # )
            screenshot_np = self.screen_capturer.capture_window_area(
                hwnd, left, top, width, height, include_title_bar
            )
            logger.debug(f"截图完成。")
            screenshot_png = self.screen_capturer.to_png(screenshot_np)

            # 调用 OcrAPI 的 runBytes 方法进行识别
            # logger.debug("将截图字节流发送到 C++ 引擎进行 OCR。")
            with rapidocr_lock:
                result = self.api.runBytes(screenshot_png)
            # logger.debug("从 C++ 引擎收到 OCR 结果。")

            # 解析返回的 JSON 结果
            if result and result.get("code") == 100:
                if not result.get("data"):
                    logger.debug("OCR 识别结果为空。")
                    return ""
                # 拼接所有识别到的文本
                recognized_text = "".join([line["text"] for line in result["data"]])
                logger.debug(f"OCR 识别结果: {recognized_text}")
                return recognized_text
            elif result and result.get("code") == 101:
                logger.debug("图片中未识别出文字。")
                return ""
            else:
                error_msg = result.get("data", "未知错误") if result else "无返回结果"
                logger.error(f"OCR 识别失败。代码: {result.get('code', 'N/A')}, 信息: {error_msg}")
                return ""

        except Exception as e:
            logger.error(f"执行 OCR 过程中发生异常: {e}")
            return ""


# --- 使用示例 (与您原文件中的 main 部分相同) ---
if __name__ == "__main__":
    # 找一个窗口来测试，例如记事本。请先手动打开一个记事本窗口。
    hwnd = win32gui.FindWindow("notepad", None)

    if not hwnd:
        print("错误: 未找到记事本窗口。请打开一个记事本窗口并输入一些中英文文字以进行测试。")
    else:
        print(f"成功找到记事本窗口，句柄: {hwnd}")

        # 在第一次调用时，会启动 C++ 子进程并初始化模型
        my_ocr_engine = OCREngine(
            r'--models=".\models" --det=ch_PP-OCRv4_det_infer.onnx --cls=ch_ppocr_mobile_v2.0_cls_infer.onnx --rec=rec_ch_PP-OCRv4_infer.onnx --keys=dict_chinese.txt --padding=70 --maxSideLen=1024 --boxScoreThresh=0.5 --boxThresh=0.3 --unClipRatio=1.6 --doAngle=0 --mostAngle=0 --numThread=1'
        )

        print("\n--- OCR 功能演示 ---")
        print("将在3秒后对记事本窗口的左上角 50% x 50% 区域进行识别...")
        import time

        time.sleep(3)

        # 对记事本窗口的左上角一半区域进行 OCR
        text = my_ocr_engine.ocr_window(hwnd, left=0, top=0, width=0.5, height=0.5)

        print("-" * 20)
        print(f"识别结果: {text}")
        print("-" * 20)
