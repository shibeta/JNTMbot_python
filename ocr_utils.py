import os
import sys
import threading
import time
import atexit
from PIL import Image
import io
import win32gui
import win32ui
import numpy as np
from ctypes import windll

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
        hwindc = None
        srcdc = None
        memdc = None
        bmp = None
        old_bmp = None
        try:
            # 将窗口取消最小化
            if restore_minimized_window(hwnd):
                time.sleep(0.2)

            if include_title_bar:
                window_rect = win32gui.GetWindowRect(hwnd)
                if self.printwindow_support_hw_acceleration:
                    print_flags = 2  # PW_RENDERFULLCONTENT
                else:
                    print_flags = None  # no flags
            else:
                window_rect = win32gui.GetClientRect(hwnd)
                if self.printwindow_support_hw_acceleration:
                    print_flags = 3  # PW_CLIENTONLY | PW_RENDERFULLCONTENT
                else:
                    print_flags = 1  # PW_CLIENTONLY

            if self.dpi_awareness:
                # 启用 DPI 感知时，获取的分辨率就是实际分辨率
                window_width = window_rect[2] - window_rect[0]
                window_height = window_rect[3] - window_rect[1]
            else:
                # 未启用时，需要手动乘上缩放比
                proportion = get_primary_monitor_dpi_scale()
                window_width = (window_rect[2] - window_rect[0]) * proportion
                window_height = (window_rect[3] - window_rect[1]) * proportion

            if window_width <= 0 or window_height <= 0:
                raise Exception("窗口物理尺寸无效，无法截图。")

            hwindc = win32gui.GetWindowDC(hwnd)
            srcdc = win32ui.CreateDCFromHandle(hwindc)
            memdc = srcdc.CreateCompatibleDC()
            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(srcdc, window_width, window_height)
            old_bmp = memdc.SelectObject(bmp)

            if windll.user32.PrintWindow(hwnd, memdc.GetSafeHdc(), print_flags) == 0:
                raise Exception("PrintWindow API 调用失败。")

            bmp_bits = bmp.GetBitmapBits(True)
            # 从位图初始化numpy数组
            # 将 1D 数组重塑为 4通道 图像 (RGBA)
            screenshot_img_np = np.frombuffer(bmp_bits, dtype="uint8").reshape(
                window_height, window_width, 4
            )[:, :, [2, 1, 0, 3]]
            # 丢弃不需要的 alpha/padding 通道，仅保留 RGB
            # 用 np.ascontiguousarray 确保内存是连续的，避免出现 bug
            return np.ascontiguousarray(screenshot_img_np[:, :, :3])
        finally:
            # 释放 GDI 资源
            if memdc is not None:
                if old_bmp is not None:
                    memdc.SelectObject(old_bmp)
                memdc.DeleteDC()
            if bmp is not None:
                win32gui.DeleteObject(bmp.GetHandle())
            if srcdc is not None:
                srcdc.DeleteDC()
            if hwindc is not None:
                win32gui.ReleaseDC(hwnd, hwindc)

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
        # pil_image.save("debug_screenshot.png")

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
        # pil_image = Image.fromarray(cropped_image_np)
        # pil_image.save("debug_screenshot.png")

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

        # 确保程序退出时 OCR 引擎被关闭
        atexit.register(self.shutdown)

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
        if hasattr(self, "api") and self.api:
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
