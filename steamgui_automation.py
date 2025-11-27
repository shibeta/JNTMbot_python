import uiautomation as auto
import pyperclip
import time

from logger import get_logger

logger = get_logger(__name__)


class SteamAutomation:
    """使用 UIautomation，自动化控制 Steam 客户端"""

    def __init__(self, window_title_substring: str):
        self.window_title_substring = window_title_substring
        self.last_send_monotonic_time = time.monotonic()  # 上次向 Steam 发送消息的相对时间
        self.last_send_system_time = time.time()  # 上次向 Steam 发送消息的系统时间，仅作参考

        logger.warning(
            "Steam Automation 需要手动打开 Steam 群组聊天窗口，请确保 Steam 群组聊天窗口已经打开。"
        )

        logger.info("Steam Automation 初始化完成。")

    def send_group_message(self, message: str):
        """
        查找 Steam 聊天窗口，并发送消息。

        :param str window_title_substring: 窗口标题的一部分，支持正则。比如: 群组名
        :param str message: 发送的文本消息内容
        :raises Exception: 查找窗口或发送消息失败
        """
        try:
            # 寻找 Steam 聊天窗口
            chat_window = auto.WindowControl(searchDepth=1, RegexName=self.window_title_substring)

            if not chat_window.Exists():
                raise Exception(f"未找到标题包含 '{self.window_title_substring}' 的窗口")

            chat_window.Restore()  # 从最小化恢复
            chat_window.SetFocus()  # 将窗口放置在前台，否则查找元素会出错
            time.sleep(0.5)  # 等待窗口绘制

            # 文本输入框没有特征，基于发送按钮辅助定位文本输入框
            input_field = chat_window.ButtonControl(Name="发送").GetPreviousSiblingControl()

            if input_field is None or not input_field.Exists():
                raise Exception("未找到文本输入框")

            # 激活光标
            input_field.SetFocus()

            # 由于文本输入框不是 EditControl，只能手动输入内容
            # 复制粘贴对非 ASCII 字符兼容性更好
            pyperclip.copy(message)
            input_field.SendKeys("{Ctrl}v")
            time.sleep(0.1)

            # 按下回车以发送消息
            input_field.SendKeys("{Enter}")
            logger.info(f"成功发送消息: '{message}'")
            self.last_send_monotonic_time = time.monotonic()
            self.last_send_system_time = time.time()

        except Exception as e:
            raise Exception(f"使用 Steam GUI 向群组发送消息时出错: {e}") from e

    def reset_send_timer(self):
        """重置上次发送消息的时间戳为当前时间。"""
        self.last_send_monotonic_time = time.monotonic()
        self.last_send_system_time = time.time()

    def get_login_status(self):
        """未实现的方法。总是返回``{"loggedIn": False, "name": ""}``"""
        return {"loggedIn": False, "name": ""}
