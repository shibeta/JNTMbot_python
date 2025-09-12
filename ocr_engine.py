import win32gui
import win32ui
import win32api
import win32con
import win32print
import numpy as np
from rapidocr import RapidOCR, EngineType, LangDet, LangRec, ModelType, OCRVersion
import threading
from time import sleep

from logger import get_logger

GLogger = get_logger("ocr_engine")


# 全局变量，用于存储初始化后的 OCR 引擎实例，避免重复加载模型
GOCREngine = None

# 用于确保 OCR 引擎只被初始化一次的锁
_init_lock = threading.Lock()


class GDIScreenshotContext:
    """
    一个上下文管理器，用于安全地处理GDI截图所需的资源。
    它封装了所有GDI句柄的获取和释放逻辑。
    """

    def __init__(self, width, height):
        if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
            raise ValueError(f"截图尺寸必须是正整数。收到的 width={width}, height={height}")

        self._width = width
        self._height = height
        self.hwindc = None
        self.srcdc = None
        self.memdc = None
        self.bmp = None

    def __enter__(self):
        # 获取桌面句柄和DC
        hdesktop = win32gui.GetDesktopWindow()
        self.hwindc = win32gui.GetWindowDC(hdesktop)
        self.srcdc = win32ui.CreateDCFromHandle(self.hwindc)

        # 创建内存DC和位图
        self.memdc = self.srcdc.CreateCompatibleDC()
        self.bmp = win32ui.CreateBitmap()
        self.bmp.CreateCompatibleBitmap(self.srcdc, self._width, self._height)

        # 将位图选入内存DC
        self.memdc.SelectObject(self.bmp)

        # 返回需要被使用的核心对象
        return self.srcdc, self.memdc, self.bmp

    def __exit__(self, exc_type, exc_val, exc_tb):
        # 按照与创建相反的顺序进行清理
        if self.bmp:
            win32gui.DeleteObject(self.bmp.GetHandle())
        if self.memdc:
            self.memdc.DeleteDC()
        if self.srcdc:
            self.srcdc.DeleteDC()
        if self.hwindc:
            # GetWindowDC 获取的DC需要使用 ReleaseDC
            hdesktop = win32gui.GetDesktopWindow()
            win32gui.ReleaseDC(hdesktop, self.hwindc)


class OCREngine:
    """
    使用 rapidocr-onnxruntime 库封装 OCR 功能。
    """

    def __init__(self):
        """
        初始化 RapidOCR 引擎。
        模型加载过程可能需要几秒钟。
        """
        GLogger.info("正在初始化 OCR 引擎，可能需要一些时间...")
        self.engine = RapidOCR(
            params={  # 从 https://github.com/davidLi17/JiNiTaiMeiBot 抄的参数
                "Global.log_level": "error",
                "Global.use_cls": False,
                "Global.max_side_len": 1024,
                "EngineConfig.onnxruntime.intra_op_num_threads": 1,
                "Det.engine_type": EngineType.ONNXRUNTIME,
                "Det.lang_type": LangDet.CH,
                "Det.model_type": ModelType.MOBILE,
                "Det.ocr_version": OCRVersion.PPOCRV5,
                "Det.thresh": 0.3,
                "Det.box_thresh": 0.5,
                "Det.unclip_ratio": 1.6,
                "Rec.engine_type": EngineType.ONNXRUNTIME,
                "Rec.lang_type": LangRec.CH,
                "Rec.model_type": ModelType.MOBILE,
                "Rec.ocr_version": OCRVersion.PPOCRV5,
            }
        )
        GLogger.warning("OCR 引擎初始化完成。")

    def _capture_window_area(
        self, hwnd: int, x: float, y: float, w: float, h: float, include_title_bar: bool = False
    ) -> np.ndarray | None:
        """
        截取指定窗口的特定区域。

        Args:
            hwnd: 目标窗口的句柄。
            x, y: 截图区域左上角的相对坐标 (0.0 to 1.0)。
            w, h: 截图区域的相对宽度和高度 (0.0 to 1.0)。
            include_title_bar: 是否将标题栏和边框计算在内。
                True: 基于完整窗口截图
                False: 基于客户区截图 (排除标题栏和边框)

        Returns:
            一个 BGR 格式的 NumPy 数组，如果失败则返回 None。
        """
        try:
            # 将要截图的窗口置于前台
            if hwnd != win32gui.GetForegroundWindow():
                win32gui.SetForegroundWindow(hwnd)
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                sleep(0.15)

            # 计算DPI缩放比例
            proportion = round(
                win32print.GetDeviceCaps(win32gui.GetDC(0), win32con.DESKTOPHORZRES)
                / win32api.GetSystemMetrics(0),
                2,
            )

            # 获取绝对坐标
            if include_title_bar:
                # 包含标题栏和边框的完整窗口
                client_left, client_top, client_right, client_bottom = win32gui.GetWindowRect(hwnd)
            else:
                # 不包含标题栏和边框的客户区
                # GetClientRect只能获取相对坐标
                client_rect = win32gui.GetClientRect(hwnd)
                client_width = client_rect[2] - client_rect[0]
                client_height = client_rect[3] - client_rect[1]

                # 获取客户区左上角的绝对坐标
                client_left, client_top = win32gui.ClientToScreen(hwnd, (0, 0))
                # 计算客户区的绝对坐标
                client_right = client_left + client_width
                client_bottom = client_top + client_height

            # 处理缩放
            client_left = int(client_left * proportion)
            client_top = int(client_top * proportion)
            client_right = int(client_right * proportion)
            client_bottom = int(client_bottom * proportion)
            # print(client_left, client_top, client_right, client_bottom)

            # 计算截图区域的绝对坐标
            client_width = client_right - client_left
            client_height = client_bottom - client_top

            grab_left = client_left + int(x * client_width)
            grab_top = client_top + int(y * client_height)
            grab_width = int(w * client_width)
            grab_height = int(h * client_height)
            # grab_right = grab_left + int(w * client_width)
            # grab_bottom = grab_top + int(h * client_height)
            # print(grab_left,grab_top,grab_width,grab_height)

            # TODO 截图失败: screen grab failed
            # # 使用pillow截图
            # screenshot = ImageGrab.grab(bbox=(grab_left, grab_top, grab_right, grab_bottom))

            # 验证截图尺寸
            if grab_width <= 0 or grab_height <= 0:
                GLogger.warning(f"计算出的截图尺寸无效: w = {grab_width} 像素, h = {grab_height} 像素")
                return None

            # 使用 GDI 截图
            with GDIScreenshotContext(grab_width, grab_height) as (srcdc, memdc, bmp):
                memdc.BitBlt(
                    (0, 0), (grab_width, grab_height), srcdc, (grab_left, grab_top), win32con.SRCCOPY
                )
                signed_ints_array = bmp.GetBitmapBits(True)
                screenshot_img_np = np.frombuffer(signed_ints_array, dtype='uint8')
                # 将 1D 数组重塑为 4通道 图像 (BGRA/BGRX)
                screenshot_img_np.shape = (grab_height, grab_width, 4)
                # 丢弃不需要的 alpha/padding 通道，仅保留 BGR
                # 用 np.ascontiguousarray 确保内存是连续的，提升性能?
                return np.ascontiguousarray(screenshot_img_np[:, :, :3])
            
        except Exception as e:
            GLogger.error(f"截图失败: {e}")
            return None

    def ocr(
        self,
        hwnd: int,
        x: float = 0,
        y: float = 0,
        w: float = 0.5,
        h: float = 0.5,
        include_title_bar: bool = False,
    ) -> str:
        """
        对指定窗口的特定区域进行 OCR 识别。

        Args:
            hwnd: 目标窗口句柄。
            x, y: 截图区域左上角的相对坐标 (0.0 to 1.0)。
            w, h: 截图区域的相对宽度和高度 (0.0 to 1.0)。
            include_title_bar: 是否将标题栏和边框计算在内。
                True: 基于完整窗口截图
                False: 基于客户区截图 (排除标题栏和边框)

        Returns:
            识别出的所有文本拼接成的字符串。
        """
        # 截图
        GLogger.debug(
            f"开始对句柄为{hwnd}的窗口截图，{"" if include_title_bar else "不"}包括标题栏。截图范围左上角相对坐标为({x}, {y})，右下角相对坐标为({x+w}, {y+h})。"
        )
        screenshot_np = self._capture_window_area(hwnd, x, y, w, h, include_title_bar)
        GLogger.debug("截图完成。")
        if screenshot_np is None:
            return ""

        # 调用 OCR 引擎进行识别
        GLogger.debug("开始对截图进行 OCR。")
        result = self.engine(screenshot_np, use_det=True, use_cls=False, use_rec=True)
        GLogger.debug("OCR 完成。")

        # 处理空结果
        if result is None or result.txts is None:
            return ""

        # 拼接所有识别到的文本
        recognized_text = "".join(result.txts)
        GLogger.debug(recognized_text)

        return recognized_text


def get_ocr_engine():
    """
    获取全局唯一的 OCREngine 实例。
    使用双重检查锁定模式确保线程安全。
    """
    global GOCREngine
    if GOCREngine is None:
        with _init_lock:
            if GOCREngine is None:
                GOCREngine = OCREngine()
    return GOCREngine


# --- 使用示例 ---
if __name__ == "__main__":
    # 找一个窗口来测试，例如记事本。请先手动打开一个记事本窗口。
    hwnd = win32gui.FindWindow("Notepad", None)

    if not hwnd:
        print("错误: 未找到记事本窗口。请打开一个记事本窗口并输入一些中英文文字以进行测试。")
    else:
        print(f"成功找到记事本窗口，句柄: {hwnd}")

        # 获取 OCR 引擎实例
        # 第一次调用会初始化模型
        ocr_engine = get_ocr_engine()

        print("\n--- OCR 功能演示 ---")
        print("将在3秒后对记事本窗口的左上角 50% x 50% 区域进行识别...")
        import time

        time.sleep(3)

        # 对记事本窗口的左上角一半区域进行 OCR
        # 这对应 C++ 中的 ocrUTF(hWnd, 0, 0, 0.5f, 0.5f)
        text = ocr_engine.ocr(hwnd, x=0, y=0, w=0.5, h=0.5)

        print("-" * 20)
        print(f"识别结果: {text}")
        print("-" * 20)
