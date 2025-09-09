import win32gui
import win32api
import win32con
import win32print
from PIL import Image, ImageGrab
from rapidocr import RapidOCR
import threading
from time import sleep

from logger import setup_logger

GLogger = setup_logger("ocr_engine")


# 全局变量，用于存储初始化后的 OCR 引擎实例，避免重复加载模型
GOCREngine = None

# 用于确保 OCR 引擎只被初始化一次的锁
_init_lock = threading.Lock()


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
        self.engine = RapidOCR(params={"Global.log_level": "error"})
        GLogger.warning("OCR 引擎初始化完成。")

    def _capture_window_area(
        self, hwnd: int, x: float, y: float, w: float, h: float, include_title_bar: bool = False
    ) -> Image.Image | None:
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
            一个 PIL.Image.Image 对象，如果失败则返回 None。
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
            grab_right = grab_left + int(w * client_width)
            grab_bottom = grab_top + int(h * client_height)
            # print(grab_left,grab_top,grab_width,grab_height)

            # 使用pillow截图
            screenshot = ImageGrab.grab(bbox=(grab_left, grab_top, grab_right, grab_bottom))

            return screenshot

        except Exception as e:
            GLogger.error(f"截图失败: {e}")
            return None

    def ocr(self, hwnd: int, x: float = 0, y: float = 0, w: float = 0.5, h: float = 0.5) -> str:
        """
        对指定窗口的特定区域进行 OCR 识别。

        Args:
            hwnd: 目标窗口句柄。
            x, y, w, h: 截图区域的相对坐标和大小。

        Returns:
            识别出的所有文本拼接成的字符串。
        """
        # 截图
        screenshot = self._capture_window_area(hwnd, x, y, w, h)
        if not screenshot:
            return ""

        # # 调用 OCR 引擎进行识别
        result = self.engine(screenshot, use_det=True, use_cls=False, use_rec=True)

        # 处理空结果
        if result is None or result.txts is None:
            return ""

        # 拼接所有识别到的文本
        # print(result.txts)
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
