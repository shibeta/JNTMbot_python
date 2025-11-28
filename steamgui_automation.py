import uiautomation as auto
import time

from logger import get_logger

logger = get_logger(__name__)


class SteamAutomation:
    """使用 UIautomation，自动化控制 Steam 客户端"""

    def __init__(self, window_title_substring: str):
        self.window_title_substring = window_title_substring
        self.last_send_monotonic_time = time.monotonic()  # 上次向 Steam 发送消息的相对时间
        self.last_send_system_time = time.time()  # 上次向 Steam 发送消息的系统时间，仅作参考

        logger.info("正在检查 Steam 聊天窗口是否打开...")
        try:
            chat_window = self.find_steam_chat_window()
            logger.info(f"已找到 Steam 聊天窗口: {chat_window.Name} 。")
        except Exception as e:
            logger.error(f"未找到 Steam 聊天窗口: {e}。")
            logger.warning(
                "Steam Automation 需要手动打开 Steam 群组聊天窗口，请确保 Steam 群组聊天窗口已经打开。"
            )
            raise

        logger.info("Steam Automation 初始化完成。")

    def find_steam_chat_window(self):
        """查找 Steam 聊天窗口"""
        chat_window = auto.WindowControl(searchDepth=1, RegexName=self.window_title_substring)

        if not chat_window.Exists():
            raise Exception(f"未找到标题包含 '{self.window_title_substring}' 的窗口")

        return chat_window

    def send_group_message(self, message: str):
        """
        查找 Steam 聊天窗口，并发送消息。

        :param str window_title_substring: 窗口标题的一部分，支持正则。比如: 群组名
        :param str message: 发送的文本消息内容
        :raises Exception: 查找窗口或发送消息失败
        """
        try:
            # 记录发送消息前激活的控件，发送消息后切换回该控件
            original_focused_control = auto.GetFocusedControl()
            # 记录剪贴板
        except:
            original_focused_control = None
        try:
            # 寻找 Steam 聊天窗口
            chat_window = self.find_steam_chat_window()

            chat_window.SwitchToThisWindow()  # 从最小化恢复
            chat_window.SetFocus()  # 将窗口放置在前台，否则查找元素会出错
            time.sleep(0.5)  # 等待窗口绘制

            # 文本输入框没有特征，基于发送按钮辅助定位文本输入框
            input_field = chat_window.ButtonControl(Name="发送").GetPreviousSiblingControl()

            if input_field is None or not input_field.Exists():
                raise Exception("未找到文本输入框")

            # 由于文本输入框不是 EditControl，只能手动输入内容
            input_field.SetFocus()
            input_field.SendKeys(message)
            time.sleep(0.1)

            # 按下回车以发送消息
            input_field.SetFocus()
            input_field.SendKeys("{Enter}")

            logger.info(f"成功发送消息: '{message}'")
            self.last_send_monotonic_time = time.monotonic()
            self.last_send_system_time = time.time()

        except Exception as e:
            raise Exception(f"使用 Steam GUI 向群组发送消息时出错: {e}") from e

        finally:
            # 切换回发送消息前激活的控件
            if original_focused_control is not None and original_focused_control.Exists():
                try:
                    original_focused_control.SetFocus()
                except:
                    # 某些控件（如桌面）可能无法被SetFocus
                    pass

    def reset_send_timer(self):
        """重置上次发送消息的时间戳为当前时间。"""
        self.last_send_monotonic_time = time.monotonic()
        self.last_send_system_time = time.time()

    def get_login_status(self):
        """未实现的方法。总是返回``{"loggedIn": False, "name": ""}``"""
        return {"loggedIn": False, "name": ""}


if __name__ == "__main__":
    GROUP_NAME = "蠢人帮"
    MESSAGE_TO_SEND = "这是一条 UIautomation 发送的测试消息！"
    my_steamautomation = SteamAutomation(GROUP_NAME)
    print("1秒钟后将向Steam聊天窗口发送测试消息。")
    time.sleep(1)
    my_steamautomation.send_group_message(MESSAGE_TO_SEND)
