import time
from pynput.keyboard import Controller, KeyCode, Key

# 创建一个全局的键盘控制器实例，以提高效率
keyboard_controller = Controller()

# 封装 KeyCode 以便于调用
KEY_ENTER = Key.enter
KEY_ESCAPE = Key.esc
KEY_LCONTROL = 0xA2


def press_keyboard(key: KeyCode | Key | str):
    """模拟按下指定的虚拟按键。"""
    keyboard_controller.press(key)


def release_keyboard(key: KeyCode | Key | str):
    """模拟释放指定的虚拟按键。"""
    keyboard_controller.release(key)


def click_keyboard(key: KeyCode | Key | str, milliseconds: int = 90):
    """模拟单击指定的虚拟按键（按下然后释放）。"""
    press_keyboard(key)
    time.sleep(milliseconds / 1000.0)
    release_keyboard(key)
