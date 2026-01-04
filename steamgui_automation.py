from functools import wraps
from typing import Callable, TypeVar, ParamSpec
import uiautomation as auto
from windows_utils import ClipboardScope
import time

from logger import get_logger

# 用于装饰器类型注解的泛型变量
P = ParamSpec("P")  # 捕获函数的参数列表 (args, kwargs)
R = TypeVar("R")  # 捕获函数的返回值类型

logger = get_logger(__name__)


class SteamAutomation:
    """使用 UIautomation，自动化控制 Steam 客户端"""

    def __init__(self, window_title_substring: str):
        self.window_title_substring = window_title_substring
        self.last_send_monotonic_time = time.monotonic()  # 上次向 Steam 发送消息的相对时间
        self.last_send_system_time = time.time()  # 上次向 Steam 发送消息的系统时间，仅作参考

        logger.info("正在检查 Steam 聊天窗口...")
        # 聊天窗口是否打开
        try:
            chat_window = self.find_steam_chat_window()
            logger.info(f"已找到 Steam 聊天窗口: {chat_window.Name} 。")
        except Exception as e:
            logger.error(f"未找到 Steam 聊天窗口: {e}。")
            logger.warning(
                "Steam Automation 需要手动打开 Steam 群组聊天窗口，请确保 Steam 群组聊天窗口已经打开。"
            )
            raise

        # 窗口中能否找到文本输入框
        try:
            self.find_input_field(chat_window)
        except Exception as e:
            logger.error(f"找到了 Steam 聊天窗口，但{e}。")
            logger.warning("未找到聊天窗口输入框，请关闭 Steam 聊天窗口再重新打开。")
            raise

        logger.info("Steam Automation 初始化完成。")

    @staticmethod
    def _preserve_focus_decorator(func: Callable[P, R]) -> Callable[P, R]:
        """
        用于自动还原之前的键盘焦点的装饰器
        """

        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                # 记录发送消息前的窗口句柄和键盘焦点，发送消息后切换回该控件
                original_window_handle = auto.GetForegroundWindow()
                if original_window_handle == 0:
                    # 句柄无效，跳过获取键盘焦点
                    raise ValueError(f"窗口句柄 {original_window_handle} 无效")
                original_focused_control = auto.GetFocusedControl()
            except:
                original_window_handle = None
                original_focused_control = None

            try:
                return func(*args, **kwargs)

            finally:
                if original_window_handle:
                    # 检查当前的前台窗口和发送消息前是否是同一个窗口
                    try:
                        current_window_handle = auto.GetForegroundWindow()
                    except Exception as e:
                        # logger.error(f"获取前台窗口句柄失败: {e}")
                        current_window_handle = None

                    foreground_window_changed = original_window_handle != current_window_handle

                    # 切换回发送消息前激活的控件
                    if (
                        foreground_window_changed
                        and original_focused_control is not None
                        and original_focused_control.Exists()
                    ):
                        try:
                            original_focused_control.SetFocus()
                        except:
                            # 某些控件（如桌面）可能无法被SetFocus
                            pass

        return wrapper

    @staticmethod
    def _set_keyboard_focus(control: auto.Control):
        """
        设置一个控件为键盘焦点元素。

        先使用`SetFocus()`，如果未能使其`HasKeyboardFocus`，则使用`Click()`模拟点击它。

        :param control: 要设置为键盘焦点的控件
        :return: 最终控件是否成为键盘焦点
        """
        if not control.HasKeyboardFocus:
            control.SetFocus()

            if not control.HasKeyboardFocus:
                logger.info("设置键盘焦点失败，将模拟点击以激活控件。")
                SteamAutomation._click_control_seamlessly(control)

            return control.HasKeyboardFocus
        else:
            return True

    @staticmethod
    def _click_control_seamlessly(control: auto.Control):
        """
        点击一个元素，然后立刻将鼠标移回点击前的位置。

        :param control: 要点击的元素
        """
        original_cursor_pos = auto.GetCursorPos()
        control.Click(simulateMove=False)
        auto.SetCursorPos(*original_cursor_pos)

    def find_steam_chat_window(self):
        """查找 Steam 聊天窗口"""
        chat_window = auto.WindowControl(searchDepth=1, SubName=self.window_title_substring)

        if not chat_window.Exists():
            raise Exception(f"未找到标题包含 '{self.window_title_substring}' 的窗口")

        return chat_window

    @staticmethod
    @_preserve_focus_decorator
    def find_input_field(steam_chat_window: auto.WindowControl):
        """
        查找 Steam 聊天窗口中的文本输入框
        """
        # 处理窗口以准备查找元素
        steam_chat_window.SwitchToThisWindow()  # 从最小化恢复，否则查找元素会出错
        time.sleep(0.5)  # 等待窗口绘制

        # 文本输入框没有特征，基于发送按钮辅助定位文本输入框
        # 文本输入框 <- 发送包按钮
        send_button = steam_chat_window.ButtonControl(Name="发送")
        if send_button is None or not send_button.Exists():
            raise Exception("未找到辅助定位文本输入框用的表情包按钮")

        input_field = send_button.GetPreviousSiblingControl()
        if input_field is None or not input_field.Exists():
            raise Exception("未找到文本输入框")

        return input_field

    @ClipboardScope._preserve_clipboard_decorator
    @_preserve_focus_decorator
    def send_message_to_steam_chat_window(self, message: str):
        """
        查找 Steam 聊天窗口，并发送消息。发送消息会占用剪贴板。

        :param str message: 发送的文本消息内容
        :raises Exception: 查找窗口或发送消息失败
        """
        if not message:
            return

        # 寻找 Steam 聊天窗口
        chat_window = self.find_steam_chat_window()

        # 寻找文本输入框
        input_field = self.find_input_field(chat_window)

        # 激活文本输入框
        self._set_keyboard_focus(input_field)

        try:
            # 将消息写入剪贴板
            auto.SetClipboardText(message)
            # 粘贴内容
            input_field.SendKeys("{Ctrl}v")
        except Exception as e:
            logger.error(f"使用剪贴板粘贴消息失败: {e}。回退到模拟输入。")
            input_field.SendKeys(text=message, charMode=True)

        # 等待窗口响应剪贴板粘贴
        time.sleep(0.05)

        # 按下回车以发送消息
        self._set_keyboard_focus(input_field)
        input_field.SendKeys("{Enter}")
        # 多按一次
        input_field.SendKeys("{Enter}")

    def send_group_message(self, message: str):
        """
        查找 Steam 聊天窗口，并发送消息。

        :param str message: 发送的文本消息内容
        :raises Exception: 查找窗口或发送消息失败
        """
        logger.info(f'正在向 Steam 聊天窗口 "{self.window_title_substring}" 发送消息...')
        if message:
            logger.info(f'消息内容: "{message}"')
        else:
            logger.warning("消息内容为空，跳过发送。")
            self.reset_send_timer()
            return

        try:
            self.send_message_to_steam_chat_window(message)
            logger.info(f"消息发送成功。")
            self.reset_send_timer()

        except Exception as e:
            raise Exception(f"使用 Steam GUI 向群组发送消息时出错: {e}") from e

    def get_last_send_system_time(self):
        """
        返回上次发送消息时的本地时间

        :return float: 秒数形式的浮点时间
        """
        return self.last_send_system_time

    def get_last_send_monotonic_time(self):
        """
        返回上次发送消息时的单调时间

        :return float: 秒数形式的浮点时间
        """
        return self.last_send_monotonic_time

    def reset_send_timer(self):
        """重置上次发送消息的时间戳为当前时间。"""
        self.last_send_monotonic_time = time.monotonic()
        self.last_send_system_time = time.time()

    def get_login_status(self):
        """未实现的方法。总是返回``{"loggedIn": False, "name": ""}``"""
        return {"loggedIn": False, "name": ""}


if __name__ == "__main__":
    GROUP_NAME = "德瑞"
    MESSAGE_TO_SEND = "测试: 通过 UIautomation 发送 Steam 聊天消息。"
    my_steamautomation = SteamAutomation(GROUP_NAME)
    print("1秒钟后将向Steam聊天窗口发送测试消息。")
    time.sleep(1)
    my_steamautomation.send_group_message(MESSAGE_TO_SEND)
