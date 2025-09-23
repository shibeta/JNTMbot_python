import win32gui
import numpy as np
from rapidocr import RapidOCR, EngineType, LangDet, LangRec, ModelType, OCRVersion
import threading
from time import sleep
import mss

from process_utils import is_window_handler_exist, set_top_window, unset_top_window
from logger import get_logger

logger = get_logger("ocr_engine")


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
        logger.info("正在初始化 OCR 引擎，可能需要一些时间...")
        self.engine = RapidOCR(
            params={  # 从 https://github.com/davidLi17/JiNiTaiMeiBot 抄的参数
                "Global.log_level": "debug",  # RapidOCR默认会修改全局日志最低等级为info
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
        self.sct = mss.mss()
        logger.warning("OCR 引擎初始化完成。")

    def _get_physical_rect(self, hwnd: int, include_title_bar: bool) -> tuple[int, int, int, int]:
        """
        辅助函数：获取窗口或客户区的指定区域的物理像素坐标

        :param hwnd: 目标窗口的句柄。
        :param include_title_bar: 是否将标题栏和边框计算在内。(True: 基于完整窗口计算 False: 基于客户区计算 (排除标题栏和边框))
        :return: 一个有4个元素的元组，对应窗口或客户区左上右下的物理像素坐标。
        :raise ``Exception``: 获取物理坐标失败
        """
        try:

            if include_title_bar:
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                logger.debug("指定包含边框，将整个窗口视为客户区。")
            else:
                client_rect = win32gui.GetClientRect(hwnd)
                client_width = client_rect[2] - client_rect[0]
                client_height = client_rect[3] - client_rect[1]

                left, top = win32gui.ClientToScreen(hwnd, (0, 0))
                right = left + client_width
                bottom = top + client_height
                logger.debug(
                    f"指定仅包含客户区，客户区大小: {client_width} * {client_height}。左上角坐标({left},{top})，右下角坐标({right},{bottom})。"
                )

            return left, top, right, bottom
        except Exception as e:
            raise Exception(f"获取物理坐标失败: {e}") from e

    def _capture_window_area_mss(
        self, hwnd: int, left: float, top: float, width: float, height: float, include_title_bar: bool = False
    ) -> np.ndarray:
        """
        截取指定窗口的特定区域。

        :param hwnd: 目标窗口的句柄。
        :param left: 截图区域左上角的相对横坐标 (0.0 to 1.0)。
        :param top: 截图区域左上角的相对纵坐标 (0.0 to 1.0)。
        :param width: 截图区域的相对宽度 (0.0 to 1.0)。
        :param height: 截图区域的相对高度 (0.0 to 1.0)。
        :param include_title_bar: 是否将标题栏和边框计算在内。(True: 基于完整窗口截图 False: 基于客户区截图 (排除标题栏和边框))
        :return: 一个 BGR 格式的 NumPy 数组。
        :raise ``Exception``: 截图失败
        """
        try:
            logger.debug(
                f"开始对句柄为{hwnd}的窗口截图，{'' if include_title_bar else '不'}包括标题栏。截图范围左上角相对坐标为({left}, {top})，右下角相对坐标为({left+width}, {top+height})。"
            )
            # 将要截图的窗口置顶
            set_top_window(hwnd)
            sleep(0.2)  # 等待窗口重绘

            # DEBUG: 输出窗口原始大小
            window_left, window_top, window_right, window_bottom = win32gui.GetWindowRect(hwnd)
            logger.debug(
                f"传入的窗口大小: {window_right-window_left} * {window_bottom-window_top}。左上角坐标({window_left},{window_top})，右下角坐标({window_right},{window_bottom})。"
            )

            # 获取窗口物理坐标
            rect = self._get_physical_rect(hwnd, include_title_bar)
            if not rect:
                raise Exception("获取窗口物理坐标失败")

            phys_left, phys_top, phys_right, phys_bottom = rect
            phys_width = phys_right - phys_left
            phys_height = phys_bottom - phys_top

            # 基于物理尺寸计算截图区域
            grab_left = phys_left + int(left * phys_width)
            grab_top = phys_top + int(top * phys_height)
            grab_width = int(width * phys_width)
            grab_height = int(height * phys_height)
            logger.debug(
                f"截图区域大小: {grab_width} * {grab_height}。左上角坐标({grab_left},{grab_top})，右下角坐标({grab_left+grab_width},{grab_top+grab_height})。"
            )

            # 验证截图尺寸
            if grab_width <= 0 or grab_height <= 0:
                logger.warning(f"计算出的截图尺寸无效: w = {grab_width} 像素, h = {grab_height} 像素")
                return None

            # 使用mss截图
            grab_area = {"top": grab_top, "left": grab_left, "width": grab_width, "height": grab_height}
            sct_img = self.sct.grab(grab_area)

            # 取消截图窗口的置顶
            try:
                unset_top_window(hwnd)
            except Exception:
                # 取消置顶窗口出错也无所谓
                pass

            # 转换为NumPy数组
            img_np = np.frombuffer(sct_img.raw, dtype=np.uint8).reshape((sct_img.height, sct_img.width, 4))
            # 丢弃 alpha 通道，并确保内存连续
            return np.ascontiguousarray(img_np[:, :, :3])

        except Exception as e:
            raise Exception(f"截图失败: {e}") from e

    def ocr(
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
        """
        # 检查窗口句柄是否有效
        if not is_window_handler_exist(hwnd):
            logger.error(f"要截图的窗口{hwnd}是一个无效的窗口句柄。")
            return ""

        # 截图
        logger.debug(f"开始对句柄为{hwnd}的窗口截图。")
        # 使用mss截图
        screenshot_np = self._capture_window_area_mss(hwnd, left, top, width, height, include_title_bar)
        logger.debug("截图完成。")
        if screenshot_np is None:
            return ""

        # 调用 OCR 引擎进行识别
        logger.debug("开始对截图进行 OCR 识别。")
        result = self.engine(screenshot_np, use_det=True, use_cls=False, use_rec=True)
        logger.debug("OCR 完成。")

        # 处理空结果
        if result is None or result.txts is None:
            logger.debug("OCR 识别结果为空。")
            return ""

        # 拼接所有识别到的文本
        recognized_text = "".join(result.txts)
        logger.debug(f"OCR 识别结果: {recognized_text}")

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
        text = ocr_engine.ocr(hwnd, left=0, top=0, width=0.5, height=0.5)

        print("-" * 20)
        print(f"识别结果: {text}")
        print("-" * 20)
