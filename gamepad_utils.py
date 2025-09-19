import atexit
import time
import vgamepad as vg

from logger import get_logger

logger = get_logger(name="gamepad_utils")


class Button:
    # 手柄按键映射
    A = vg.XUSB_BUTTON.XUSB_GAMEPAD_A
    B = vg.XUSB_BUTTON.XUSB_GAMEPAD_B
    X = vg.XUSB_BUTTON.XUSB_GAMEPAD_X
    Y = vg.XUSB_BUTTON.XUSB_GAMEPAD_Y
    DPAD_UP = vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP
    DPAD_DOWN = vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN
    DPAD_LEFT = vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT
    DPAD_RIGHT = vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT
    START = vg.XUSB_BUTTON.XUSB_GAMEPAD_START
    BACK = vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK
    LEFT_STICK = vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB
    RIGHT_STICK = vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB
    LEFT_SHOULDER = vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER
    RIGHT_SHOULDER = vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER


class JoystickDirection:
    # 常用摇杆方向映射
    center = (0.0, 0.0)

    half_up = (0.0, 0.7)
    half_right = (0.7, 0.0)
    half_left = (-0.7, 0.0)
    half_down = (0.0, -0.7)

    half_upleft = (-0.6, 0.6)
    half_upright = (0.6, 0.6)
    half_downleft = (-0.6, -0.6)
    half_downright = (0.6, -0.6)

    full_up = (0.0, 1)
    full_right = (1, 0.0)
    full_left = (-1, 0.0)
    full_down = (0.0, -1)

    full_upleft = (-1, 1)
    full_upright = (1, 1)
    full_downleft = (-1, -1)
    full_downright = (1, -1)


class GamepadSimulator:

    def __init__(self):
        self.pad = None
        self.connected = False
        try:
            self.pad = vg.VX360Gamepad()
            self.connected = True
            logger.debug("虚拟手柄设备已创建。")

            # 注册清理函数
            atexit.register(self._cleanup)

            # 按一下A键以唤醒手柄
            self.click_button(Button.A)
            logger.info("初始化虚拟手柄完成。")

        except Exception as e:
            logger.error(f"初始化虚拟手柄失败: {e}。请确保已安装 ViGEmBus 驱动。")


    def _cleanup(self):
        """程序退出时调用的清理函数。"""
        if self.connected and self.pad:
            try:
                logger.info("程序退出，正在重置虚拟手柄状态...")
                self.pad.reset()
                self.pad.update()
                logger.info("虚拟手柄状态已重置。")
            except Exception as e:
                logger.error(f"重置虚拟手柄时出错: {e}")
    
    def _check_connected(self):
        if not self.connected or self.pad is None:
            logger.error("没有安装虚拟手柄驱动，或没有初始化")
            return False
        return True

    def press_button(self, button):
        """按下一个按钮"""
        if not self._check_connected():
            return
        try:
            self.pad.press_button(button)
            self.pad.update()
        except Exception as e:
            logger.error(f"按下按钮 {button} 时出错: {e}")

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
        except Exception as e:
            logger.error(f"点按按钮 {button} 时出错: {e}")
        finally:
            self.release_button(button)

    def return_left_joystick_to_center(self):
        self.move_left_joystick(JoystickDirection.center)

    def move_left_joystick(self, x_percent: float, y_percent: float):
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

    def hold_left_joystick(self, x_percent: float, y_percent: float, duration_seconds: float):
        """
        推动左摇杆到某位置，一段时间后回中。

        Args:
            x_percent: 左右方向，取值范围为 -1.0 ~ 1.0. (0代表回中)。
            y_percent: 后前方向，取值范围为 -1.0 ~ 1.0. (0代表回中)。
            duration_seconds: 持续时间，单位为秒
        """
        if not self._check_connected():
            return
        self.move_left_joystick(x_percent, y_percent)
        time.sleep(duration_seconds)
        self.move_left_joystick(JoystickDirection.center)
        self.pad.update()

    def return_right_joystick_to_center(self):
        self.move_right_joystick(JoystickDirection.center)

    def move_right_joystick(self, x_percent: float, y_percent: float):
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

    def hold_right_joystick(self, x_percent: float, y_percent: float, duration_seconds: float):
        """
        推动右摇杆到某位置，一段时间后回中。

        Args:
            x_percent: 左右方向，取值范围为 -1.0 ~ 1.0. (0代表回中)。
            y_percent: 后前方向，取值范围为 -1.0 ~ 1.0. (0代表回中)。
            duration_seconds: 持续时间，单位为秒
        """
        if not self._check_connected():
            return
        self.move_right_joystick(x_percent, y_percent)
        time.sleep(duration_seconds)
        self.move_right_joystick(JoystickDirection.center)
        self.pad.update()


# --- 使用示例 ---
if __name__ == "__main__":
    from time import sleep

    gamepad = GamepadSimulator()
    if not gamepad.connected:
        print("Gamepad not connected.  Exiting test.")
        exit()

    print("--- 手柄测试 ---")
    print("按下 A 键...")
    gamepad.click_button(Button.A)
    sleep(1)
    print("左摇杆向前50%...")
    gamepad.move_left_joystick(0, 0.5)
    sleep(1)
    gamepad.move_left_joystick(0, 0)
    sleep(1)
    print("右摇杆向后50%...")
    gamepad.hold_right_joystick(JoystickDirection.half_down, 1)
    print("测试结束.")
