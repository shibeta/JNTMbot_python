import os
import threading
import time
from typing import Optional
import mss
from mss import tools
import win32gui

from RapidOCR_api import OcrAPI
from windows_utils import is_window_handler_exist, set_top_window, unset_top_window
from logger import get_logger

logger = get_logger(__name__)

# 设置 RapidOCR-json.exe 的绝对或相对路径
# 例如: r"C:\path\to\RapidOCR-json.exe"
OCR_EXECUTABLE_PATH = os.path.join(os.getcwd(), "RapidOCR-json.exe")

# python-mss 截图锁，防止多线程时出现问题
mss_lock = threading.Lock()

# RapidOCR 进程锁，防止多线程时出现问题
rapidocr_lock = threading.Lock()


class OCREngine:
    """
    使用 RapidOCR_api.py 与 C++ 可执行程序通信，以实现高性能OCR功能。
    """

    def __init__(self, args: Optional[str] = None):
        """
        初始化 OcrAPI，它会启动并管理一个 RapidOCR-json.exe 子进程。
        """
        logger.info("正在初始化 OCR 引擎...")
        # 检查 OCR_EXECUTABLE_PATH 是否存在
        if not os.path.exists(OCR_EXECUTABLE_PATH):
            logger.error(f"OCR 引擎可执行文件不存在，请检查路径配置: {OCR_EXECUTABLE_PATH}")
            raise FileNotFoundError(f"未找到OCR引擎: {OCR_EXECUTABLE_PATH}")

        if args is None:
            logger.warning("未提供启动参数，不使用参数启动 OCR 引擎。")
        else:
            logger.info(f"使用以下参数启动 OCR 引擎: {args}")
        
        # 初始化 mss 截图器
        with mss_lock:
            self.sct = mss.mss()

        # 初始化 RapidOCR
        with rapidocr_lock:
            self.api = OcrAPI(OCR_EXECUTABLE_PATH, argsStr=args if args else "")
        
        logger.warning("OCR 引擎初始化完成。")

    def __del__(self):
        """
        在对象销毁时，确保子进程被关闭。
        """
        logger.info("正在关闭 OCR 引擎...")
        if self.api:
            with rapidocr_lock:
                self.api.stop()
        logger.info("成功关闭 OCR 引擎。")

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

    def _capture_window_area_mss(
        self, hwnd: int, left: float, top: float, width: float, height: float, include_title_bar: bool = False
    ) -> Optional[bytes]:
        """
        使用 python-mss 截取指定窗口的特定区域。

        :param hwnd: 目标窗口的句柄。
        :param left: 截图区域左上角的相对横坐标 (0.0 to 1.0)。
        :param top: 截图区域左上角的相对纵坐标 (0.0 to 1.0)。
        :param width: 截图区域的相对宽度 (0.0 to 1.0)。
        :param height: 截图区域的相对高度 (0.0 to 1.0)。
        :param include_title_bar: 是否将标题栏和边框计算在内。(True: 基于完整窗口截图 False: 基于客户区截图 (排除标题栏和边框))
        :return: 返回截图的 PNG 字节流。
        :raises ``Exception``: 截图失败
        """
        try:
            set_top_window(hwnd)
            time.sleep(0.1)

            rect = self._get_physical_rect(hwnd, include_title_bar)
            if not rect:
                raise Exception("获取窗口物理坐标失败")

            phys_left, phys_top, phys_right, phys_bottom = rect
            phys_width = phys_right - phys_left
            phys_height = phys_bottom - phys_top

            grab_left = phys_left + int(left * phys_width)
            grab_top = phys_top + int(top * phys_height)
            grab_width = int(width * phys_width)
            grab_height = int(height * phys_height)

            if grab_width <= 0 or grab_height <= 0:
                logger.warning(f"计算出的截图尺寸无效: w={grab_width}, h={grab_height}")
                return None

            grab_area = {"top": grab_top, "left": grab_left, "width": grab_width, "height": grab_height}

            with mss_lock:
                sct_img = self.sct.grab(grab_area)

            # debug: 保存截图以便排查问题
            # tools.to_png(sct_img.rgb, sct_img.size, output="debug_screenshot.png")

            return tools.to_png(sct_img.rgb, sct_img.size)

        except Exception as e:
            raise Exception(f"截图失败: {e}") from e

        finally:
            # 取消置顶窗口
            try:
                unset_top_window(hwnd)
            except Exception:
                pass

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
            screenshot_png = self._capture_window_area_mss(hwnd, left, top, width, height, include_title_bar)
            if screenshot_png is None:
                return ""

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
    hwnd = win32gui.FindWindow("Notepad", None)

    if not hwnd:
        print("错误: 未找到记事本窗口。请打开一个记事本窗口并输入一些中英文文字以进行测试。")
    else:
        print(f"成功找到记事本窗口，句柄: {hwnd}")

        # 在第一次调用时，会启动 C++ 子进程并初始化模型
        my_ocr_engine = OCREngine(r'--models=".\models" --det=ch_PP-OCRv4_det_infer.onnx --cls=ch_ppocr_mobile_v2.0_cls_infer.onnx --rec=rec_ch_PP-OCRv4_infer.onnx --keys=dict_chinese.txt --padding=70 --maxSideLen=1024 --boxScoreThresh=0.5 --boxThresh=0.3 --unClipRatio=1.6 --doAngle=0 --mostAngle=0 --numThread=1')

        print("\n--- OCR 功能演示 ---")
        print("将在3秒后对记事本窗口的左上角 50% x 50% 区域进行识别...")
        import time

        time.sleep(3)

        # 对记事本窗口的左上角一半区域进行 OCR
        text = my_ocr_engine.ocr_window(hwnd, left=0, top=0, width=0.5, height=0.5)

        print("-" * 20)
        print(f"识别结果: {text}")
        print("-" * 20)
