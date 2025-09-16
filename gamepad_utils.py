import time
import vgamepad as vg

from logger import get_logger

logger = get_logger(name="gamepad_utils")


class Gamepad:
    # 手柄按键映射
    button_A = vg.XUSB_BUTTON.XUSB_GAMEPAD_A
    button_B = vg.XUSB_BUTTON.XUSB_GAMEPAD_B
    button_X = vg.XUSB_BUTTON.XUSB_GAMEPAD_X
    button_Y = vg.XUSB_BUTTON.XUSB_GAMEPAD_Y
    button_DPAD_UP = vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP
    button_DPAD_DOWN = vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN
    button_DPAD_LEFT = vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT
    button_DPAD_RIGHT = vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT
    button_START = vg.XUSB_BUTTON.XUSB_GAMEPAD_START
    button_BACK = vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK
    button_LEFT_STICK = vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB
    button_RIGHT_STICK = vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB
    button_LEFT_SHOULDER = vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER
    button_RIGHT_SHOULDER = vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER

    # 常用摇杆方向映射
    stick_half_up = (0.0, 0.7)
    stick_half_right = (0.7, 0.0)
    stick_half_left = (-0.7, 0.0)
    stick_half_down = (0.0, -0.7)

    stick_half_upleft = (-0.6, 0.6)
    stick_half_upright = (0.6, 0.6)
    stick_half_downleft = (-0.6, -0.6)
    stick_half_downright = (0.6, -0.6)

    stick_full_up = (0.0, 1)
    stick_full_right = (1, 0.0)
    stick_full_left = (-1, 0.0)
    stick_full_down = (0.0, -1)

    stick_full_upleft = (-1, 1)
    stick_full_upright = (1, 1)
    stick_full_downleft = (-1, -1)
    stick_full_downright = (1, -1)

    def __init__(self):
        try:
            self.pad = vg.VX360Gamepad()  # Or use vg.XBox360Gamepad() if you prefer
        except Exception as e:
            logger.error(f"初始化虚拟手柄失败: {e}")
            self.pad = None  # Mark as uninitialized
            self.connected = False
            return

        self.connected = True
        self.MAX_ANALOG = 255  # 摇杆的最大值

        # 按一下A键以唤醒手柄
        self.pad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
        self.pad.update()
        time.sleep(0.1)
        self.pad.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_A)
        self.pad.update()
        time.sleep(0.1)
        logger.info("初始化虚拟手柄完成。")

    def _check_connected(self):
        if not self.connected or self.pad is None:
            logger.error("没有安装虚拟手柄驱动，或没有初始化")
            return False
        return True

    def press_button(self, button):
        """按住一个按钮"""
        if not self._check_connected():
            return
        try:
            self.pad.press_button(button)
            self.pad.update()
        except Exception as e:
            logger.error(f"按住按钮 {button} 时出错: {e}")

    def release_button(self, button):
        """松开一个按钮"""
        if not self._check_connected():
            return
        try:
            self.pad.release_button(button)
            self.pad.update()
        except Exception as e:
            logger.error(f"松开按钮 {button} 时出错: {e}")

    def click_button(self, button, duration_seconds=0.2):
        """按住一个按钮一段时间"""
        if not self._check_connected():
            return
        try:
            self.press_button(button)
            time.sleep(duration_seconds)
            self.release_button(button)
        except Exception as e:
            logger.error(f"点按按钮 {button} 时出错: {e}")

    def move_left_stick(self, x_percent: float, y_percent: float):
        """
        推动左摇杆到某位置。

        Args:
            x_percent: 左右方向，取值范围为 -1.0 ~ 1.0. (0代表回中)。
            y_percent: 后前方向，取值范围为 -1.0 ~ 1.0. (0代表回中)。
        """
        if not self._check_connected():
            return
        try:
            self.pad.left_joystick_float(x_percent, y_percent)
            self.pad.update()
        except Exception as e:
            logger.error(f"移动左摇杆时出错: {e}")

    def hold_left_stick_percent(self, x_percent: float, y_percent: float, duration_seconds: float):
        """
        推动左摇杆到某位置，一段时间后回中。

        Args:
            x_percent: 左右方向，取值范围为 -1.0 ~ 1.0. (0代表回中)。
            y_percent: 后前方向，取值范围为 -1.0 ~ 1.0. (0代表回中)。
            duration_seconds: 持续时间，单位为秒
        """
        if not self._check_connected():
            return
        self.move_left_stick(x_percent, y_percent)
        time.sleep(duration_seconds)
        self.move_left_stick(self.MAX_ANALOG // 2, self.MAX_ANALOG // 2)  # Return to center
        self.pad.update()

    def move_right_stick(self, x_percent: float, y_percent: float):
        """
        推动右摇杆到某位置。

        Args:
            x_percent: 左右方向，取值范围为 -1.0 ~ 1.0. (0代表回中)。
            y_percent: 后前方向，取值范围为 -1.0 ~ 1.0. (0代表回中)。
        """
        if not self._check_connected():
            return
        try:
            self.pad.right_joystick_float(x_percent, y_percent)
            self.pad.update()
        except Exception as e:
            logger.error(f"Error moving right stick: {e}")

    def hold_right_stick_percent(self, x_percent: float, y_percent: float, duration_seconds: float):
        """
        推动右摇杆到某位置，一段时间后回中。

        Args:
            x_percent: 左右方向，取值范围为 -1.0 ~ 1.0. (0代表回中)。
            y_percent: 后前方向，取值范围为 -1.0 ~ 1.0. (0代表回中)。
            duration_seconds: 持续时间，单位为秒
        """
        if not self._check_connected():
            return
        self.move_right_stick(x_percent, y_percent)
        time.sleep(duration_seconds)
        self.move_right_stick(self.MAX_ANALOG // 2, self.MAX_ANALOG // 2)  # Return to center
        self.pad.update()


# --- 使用示例 ---
if __name__ == "__main__":
    from time import sleep

    gamepad = Gamepad()
    if not gamepad.connected:
        print("Gamepad not connected.  Exiting test.")
        exit()

    print("--- 手柄测试 ---")
    print("按下 A 键...")
    gamepad.click_button(gamepad.button_A)
    sleep(1)
    print("左摇杆向前50%...")
    gamepad.move_left_stick(0, 0.5)
    sleep(1)
    gamepad.move_left_stick(0, 0)
    sleep(1)
    print("右摇杆向后50%...")
    gamepad.hold_right_stick_percent(*gamepad.stick_half_down, 1)
    print("测试结束.")
