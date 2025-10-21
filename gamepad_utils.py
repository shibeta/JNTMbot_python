from __future__ import annotations
import enum
import sys
import atexit
import copy
import time
from typing import Callable, Optional, Union
from collections import defaultdict
from functools import total_ordering
import bisect

from logger import get_logger

logger = get_logger(name="gamepad_utils")

try:
    import vgamepad as vg
except Exception as e:
    if "VIGEM_ERROR_BUS_NOT_FOUND" in str(e):
        logger.error("没有安装 ViGEmBus 驱动，或驱动未正确运行。")
        logger.info('请运行程序目录下的 "install_vigembus.bat" 来安装驱动。')
        input("按 Enter 键退出...")
        sys.exit(1)
    else:
        raise e


class Button(enum.IntFlag):
    """手柄按键映射"""

    A = vg.XUSB_BUTTON.XUSB_GAMEPAD_A
    B = vg.XUSB_BUTTON.XUSB_GAMEPAD_B
    X = vg.XUSB_BUTTON.XUSB_GAMEPAD_X
    Y = vg.XUSB_BUTTON.XUSB_GAMEPAD_Y
    DPAD_UP = vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP
    DPAD_DOWN = vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN
    DPAD_LEFT = vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT
    DPAD_RIGHT = vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT
    CROSS_KEY_UP = vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_UP
    CROSS_KEY_DOWN = vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_DOWN
    CROSS_KEY_LEFT = vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_LEFT
    CROSS_KEY_RIGHT = vg.XUSB_BUTTON.XUSB_GAMEPAD_DPAD_RIGHT
    START = vg.XUSB_BUTTON.XUSB_GAMEPAD_START  # 靠右的小按钮
    MENU = vg.XUSB_BUTTON.XUSB_GAMEPAD_START  # START 的别名
    BACK = vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK  # 靠左的小按钮
    SELECT = vg.XUSB_BUTTON.XUSB_GAMEPAD_BACK  # BACK 的别名
    LEFT_STICK = vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB
    RIGHT_STICK = vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_THUMB
    LEFT_SHOULDER = vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_SHOULDER
    RIGHT_SHOULDER = vg.XUSB_BUTTON.XUSB_GAMEPAD_RIGHT_SHOULDER

AnyButton = Union[vg.XUSB_BUTTON, Button]

class JoystickDirection(tuple[float, float]):
    """常用摇杆方向映射"""

    CENTER = (0.0, 0.0)

    HALF_UP = (0.0, 0.7)
    HALF_DOWN = (0.0, -0.7)
    HALF_LEFT = (-0.7, 0.0)
    HALF_RIGHT = (0.7, 0.0)

    HALF_LEFTUP = (-0.6, 0.6)
    HALF_RIGHTUP = (0.6, 0.6)
    HALF_LEFTDOWN = (-0.6, -0.6)
    HALF_RIGHTDOWN = (0.6, -0.6)

    FULL_UP = (0.0, 1.0)
    FULL_DOWN = (0.0, -1.0)
    FULL_LEFT = (-1.0, 0.0)
    FULL_RIGHT = (1.0, 0.0)

    FULL_LEFTUP = (-1.0, 1.0)
    FULL_RIGHTUP = (1.0, 1.0)
    FULL_LEFTDOWN = (-1.0, -1.0)
    FULL_RIGHTDOWN = (1.0, -1.0)

AnyJoystickDirection = tuple[float, float]


class TriggerPressure:
    """常用扳机压力值映射"""

    released = 0.0  # 完全松开
    light = 0.4  # 轻压 (适用于需要精确控制的场景，如半按加速)
    full = 1.0  # 完全按下 (适用于射击等场景)

AnyTriggerPressure = float


@total_ordering
class MacroEvent:
    """宏中的一个独立事件，即在特定时间点执行的特定动作。"""

    def __init__(self, time_ms: int, action_name: str, params: list):
        self.time_ms = time_ms  # 动作的时间戳
        self.action_name = action_name  # 动作的名称
        self.params = params  # 动作的参数，如按键名，按键时间等

    def __repr__(self):
        """提供一个清晰的、可读的字符串表示形式，方便调试。"""
        return f"TimelineEvent(time={self.time_ms}ms, action='{self.action_name}', params={self.params})"

    def __eq__(self, other):
        """判断两个事件是否相等（主要用于排序）。"""
        if not isinstance(other, MacroEvent):
            return NotImplemented
        return self.time_ms == other.time_ms

    def __lt__(self, other):
        """定义小于关系，即如何判断一个事件是否在另一个之前发生。"""
        if not isinstance(other, MacroEvent):
            return NotImplemented
        return self.time_ms < other.time_ms


class Macro:
    """
    一个自构建的宏对象。
    它既是宏事件的容器，也是用于定义这些事件的构建器。
    事件在添加时会自动排序，使其始终保持可播放状态。
    """

    def __init__(self, events: Optional[list[MacroEvent]] = None):
        self._events: list[MacroEvent] = []
        if events:
            # 允许从一个已有的、排序好的事件列表初始化
            self._events = events

    def __repr__(self):
        return f"<Macro with {len(self._events)} events, duration: {self.get_duration_ms()}ms>"

    # --- 使 Macro 对象表现得像一个容器 (使其可迭代、可获取长度) ---
    def __iter__(self):
        return iter(self._events)

    def __len__(self):
        return len(self._events)

    def get_duration_ms(self) -> int:
        """返回宏的总时长（最后一个事件发生的时间点）。"""
        if not self._events:
            return 0
        return self._events[-1].time_ms

    def add_action(self, time_ms: int, action_type: str, params: list):
        """
        核心方法：创建一个新事件并将其有序地插入到宏中。
        使用 bisect.insort 来保持列表排序。
        """
        event = MacroEvent(time_ms=time_ms, action_name=action_type, params=params)
        bisect.insort(self._events, event)
        return self  # 返回 self 以支持链式调用

    def copy(self):
        """返回当前宏的一个精确副本。"""
        # 使用 copy.deepcopy 确保事件对象也是新的，虽然在这里不是必须，但是个好习惯
        return Macro(copy.deepcopy(self._events))

    def time_shift(self, offset_ms: Optional[int] = None):
        """
        返回一个所有事件时间戳都平移了指定毫秒数的新宏。

        未提供毫秒数时，平移以清除第一个动作前的空余时间。

        :param offset_ms: 平移的毫秒数，可以是正数（延迟）或负数（提前）。默认为第一个动作的时间戳。
        """
        new_events = []
        if not offset_ms:
            offset_ms = - self._events[0].time_ms
        for event in self._events:
            new_time = event.time_ms + offset_ms
            if new_time >= 0:
                new_events.append(MacroEvent(new_time, event.action_name, event.params))
        return Macro(new_events)


    def append(self, other_macro: Macro, delay_ms: int = 0):
        """
        将另一个宏追加到当前宏的末尾，返回合并后的新宏。

        :param other_macro: 要追加的 Macro 对象。
        :param delay_ms: 在两个宏之间的延迟时间。
        """
        if not isinstance(other_macro, Macro):
            raise TypeError("Can only append another Macro object.")

        new_macro = self.copy()

        # 计算偏移量 = 当前宏时长 + 额外延迟
        offset = self.get_duration_ms() + delay_ms

        shifted_other = other_macro.time_shift(offset)

        new_macro._events.extend(shifted_other._events)
        # 因为两个列表本身都是有序的，所以合并后只需排序一次（或使用更高效的合并）
        new_macro._events.sort()
        return new_macro

    def filter(self, condition_func: Callable):
        """
        根据给定的条件函数过滤事件，返回一个新宏，以实现“删除”逻辑。

        :param condition_func: 一个接收 MacroEvent 对象并返回 True (保留) 或 False (移除) 的函数。
        """
        new_events = [event for event in self._events if condition_func(event)]
        return Macro(new_events)

    # --- 基础动作 (Primitive Actions) ---
    # 这些方法提供最精细的控制，只在时间轴上创建一个事件。

    def press_button(self, time_ms: int, button: AnyButton):
        """在指定时间点按下一个按钮。"""
        return self.add_action(time_ms, "press_button", [button])

    def release_button(self, time_ms: int, button: AnyButton):
        """在指定时间点释放一个按钮。"""
        return self.add_action(time_ms, "release_button", [button])

    def move_left_joystick(self, time_ms: int, direction: tuple[float, float]):
        """在指定时间点将左摇杆移动到特定位置。"""
        return self.add_action(time_ms, "left_joystick_float", list(direction))

    def move_right_joystick(self, time_ms: int, direction: tuple[float, float]):
        """在指定时间点将右摇杆移动到特定位置。"""
        return self.add_action(time_ms, "right_joystick_float", list(direction))

    def press_left_trigger(self, time_ms: int, pressure: float):
        """在指定时间点将左扳机按压到特定压力值。"""
        return self.add_action(time_ms, "left_trigger_float", [pressure])

    def press_right_trigger(self, time_ms: int, pressure: float):
        """在指定时间点将右扳机按压到特定压力值。"""
        return self.add_action(time_ms, "right_trigger_float", [pressure])

    # --- 方便使用的复合动作 (Compound/Convenience Actions) ---
    # 这些方法会自动创建开始和结束事件。

    def click_button(self, start_time_ms: int, button: AnyButton, duration_ms: int):
        """在指定时间点开始，按住并释放一个按钮。"""
        self.press_button(start_time_ms, button)
        self.release_button(start_time_ms + duration_ms, button)
        return self

    def hold_left_joystick(self, start_time_ms: int, direction: tuple[float, float], duration_ms: int):
        """在指定时间点开始，推动并回中左摇杆。"""
        self.move_left_joystick(start_time_ms, direction)
        self.move_left_joystick(start_time_ms + duration_ms, JoystickDirection.CENTER)
        return self

    def hold_right_joystick(self, start_time_ms: int, direction: tuple[float, float], duration_ms: int):
        """在指定时间点开始，推动并回中右摇杆。"""
        self.move_right_joystick(start_time_ms, direction)
        self.move_right_joystick(start_time_ms + duration_ms, JoystickDirection.CENTER)
        return self

    def hold_left_trigger(self, start_time_ms: int, pressure: float, duration_ms: int):
        """在指定时间点开始，按压并松开左扳机。"""
        self.press_left_trigger(start_time_ms, pressure)
        self.press_left_trigger(start_time_ms + duration_ms, TriggerPressure.released)
        return self

    def hold_right_trigger(self, start_time_ms: int, pressure: float, duration_ms: int):
        """在指定时间点开始，按压并松开右扳机。"""
        self.press_right_trigger(start_time_ms, pressure)
        self.press_right_trigger(start_time_ms + duration_ms, TriggerPressure.released)
        return self


class GamepadSimulator:
    """
    用于模拟手柄操作的类。
    在程序退出时，会自动释放所有手柄按键、扳机和摇杆，防止卡住。
    """

    def __init__(self):
        try:
            self.pad = vg.VX360Gamepad()
            logger.debug("虚拟手柄设备已创建。")

            # 注册清理函数
            atexit.register(self._cleanup)

            # 按一下A键以唤醒手柄
            self.click_button(Button.A)
            logger.debug("初始化虚拟手柄完成。")

        except Exception as e:
            logger.error(
                f"初始化虚拟手柄失败: {e}。请确保已安装 ViGEmBus 驱动，并且没有其他程序正在使用 ViGEmBus 模拟手柄。"
            )
            logger.info('请运行程序目录下的 "install_vigembus.bat" 来安装驱动。')
            raise e

    def _cleanup(self):
        """程序退出时调用的清理函数。"""
        if self.pad:
            try:
                logger.info("程序退出，正在重置虚拟手柄状态...")
                self.pad.reset()
                self.pad.update()
                logger.info("虚拟手柄状态已重置。")
            except Exception as e:
                logger.error(f"重置虚拟手柄时出错: {e}")

    def _check_connected(self) -> bool:
        if self.pad is None:
            logger.error("没有安装虚拟手柄驱动，或没有初始化")
            return False
        return True

    def press_button(self, button: AnyButton):
        """
        按下一个按钮。

        :param button: 要按下的按钮
        """
        if not self._check_connected():
            return
        try:
            self.pad.press_button(button)
            self.pad.update()
        except Exception as e:
            logger.error(f"按下按钮 {button} 时出错: {e}")

    def release_button(self, button: AnyButton):
        """
        松开一个按钮。

        :param button: 要松开的按钮
        """
        if not self._check_connected():
            return
        try:
            self.pad.release_button(button)
            self.pad.update()
        except Exception as e:
            logger.error(f"松开按钮 {button} 时出错: {e}")

    def click_button(self, button: AnyButton, duration_milliseconds: int = 100):
        """
        按住一个按钮，一段时间后松开。

        :param button: 要按住的按钮
        :param duration_milliseconds: 持续时间，单位为毫秒
        """
        if not self._check_connected():
            return
        try:
            self.press_button(button)
            time.sleep(duration_milliseconds / 1000.0)
        except Exception as e:
            logger.error(f"点按按钮 {button} 时出错: {e}")
        finally:
            self.release_button(button)

    def return_left_joystick_to_center(self):
        self.move_left_joystick(JoystickDirection.CENTER)

    def move_left_joystick(self, direction: tuple[float, float]):
        """
        推动左摇杆到某位置。

        :param direction: 左右方向和后前方向，取值范围为 -1.0 ~ 1.0. (0代表回中)
        """
        if not self._check_connected():
            return
        try:
            self.pad.left_joystick_float(*direction)
            self.pad.update()
        except Exception as e:
            logger.error(f"移动左摇杆时出错: {e}")

    def hold_left_joystick(self, direction: tuple[float, float], duration_milliseconds: int = 100):
        """
        推动左摇杆到某位置，一段时间后回中。

        :param direction: 左右方向和后前方向，取值范围为 -1.0 ~ 1.0. (0代表回中)
        :param duration_milliseconds: 持续时间，单位为毫秒
        """
        if not self._check_connected():
            return
        self.move_left_joystick(direction)
        time.sleep(duration_milliseconds / 1000.0)
        self.return_left_joystick_to_center()
        self.pad.update()

    def return_right_joystick_to_center(self):
        self.move_right_joystick(JoystickDirection.CENTER)

    def move_right_joystick(self, direction: tuple[float, float]):
        """
        推动右摇杆到某位置。

        :param direction: 左右方向和后前方向，取值范围为 -1.0 ~ 1.0. (0代表回中)
        """
        if not self._check_connected():
            return
        try:
            self.pad.right_joystick_float(*direction)
            self.pad.update()
        except Exception as e:
            logger.error(f"Error moving right stick: {e}")

    def hold_right_joystick(self, direction: tuple[float, float], duration_milliseconds: int = 100):
        """
        推动右摇杆到某位置，一段时间后回中。

        :param direction: 左右方向和后前方向，取值范围为 -1.0 ~ 1.0. (0代表回中)
        :param duration_milliseconds: 持续时间，单位为毫秒
        """
        if not self._check_connected():
            return
        self.move_right_joystick(direction)
        time.sleep(duration_milliseconds / 1000.0)
        self.return_right_joystick_to_center()
        self.pad.update()

    def press_left_trigger(self, pressure_float: float):
        """
        按压左扳机到指定压力值。

        :param pressure_float: 压力值，取值范围为 0.0 (松开) ~ 1.0 (完全按下)。
        """
        if not self._check_connected():
            return
        try:
            self.pad.left_trigger_float(value_float=pressure_float)
            self.pad.update()
        except Exception as e:
            logger.error(f"按压左扳机时出错: {e}")

    def release_left_trigger(self):
        """完全松开左扳机。"""
        self.press_left_trigger(TriggerPressure.released)

    def hold_left_trigger(self, pressure_float: float, duration_milliseconds: int = 100):
        """
        按住左扳机一段时间后松开。

        :param pressure_float: 压力值，取值范围为 0.0 (松开) ~ 1.0 (完全按下)。
        :param duration_milliseconds: 持续时间，单位为毫秒。
        """
        if not self._check_connected():
            return
        self.press_left_trigger(pressure_float)
        time.sleep(duration_milliseconds / 1000.0)
        self.release_left_trigger()

    def press_right_trigger(self, pressure_float: float):
        """
        按压右扳机到指定压力值。

        :param pressure_float: 压力值，取值范围为 0.0 (松开) ~ 1.0 (完全按下)。
        """
        if not self._check_connected():
            return
        try:
            self.pad.right_trigger_float(value_float=pressure_float)
            self.pad.update()
        except Exception as e:
            logger.error(f"按压右扳机时出错: {e}")

    def release_right_trigger(self):
        """完全松开右扳机。"""
        self.press_right_trigger(TriggerPressure.released)

    def hold_right_trigger(self, pressure_float: float, duration_milliseconds: int = 100):
        """
        按住右扳机一段时间后松开。

        :param pressure_float: 压力值，取值范围为 0.0 (松开) ~ 1.0 (完全按下)。
        :param duration_milliseconds: 持续时间，单位为毫秒。
        """
        if not self._check_connected():
            return
        self.press_right_trigger(pressure_float)
        time.sleep(duration_milliseconds / 1000.0)
        self.release_right_trigger()

    def play_macro(self, micro: Macro, reset_at_end: bool = True):
        """
        根据给定的 MacroEvent 列表，执行一段宏。

        :param micro: 一个宏对象。
        :param reset_at_end: 宏播放完毕后是否松开所有键。默认松开
        """
        if not self._check_connected():
            return
        if not micro:
            logger.warning("宏为空，不执行任何操作。")
            return

        # 将事件按时间戳分组
        event_groups = defaultdict(list)
        for event in micro:
            event_groups[event.time_ms].append(event)

        # 获取所有事件发生的时间点，并排序
        sorted_timestamps = sorted(event_groups.keys())

        logger.debug(
            f"开始播放宏，总时长: {sorted_timestamps[-1] / 1000.0:.2f} 秒，共 {len(sorted_timestamps)} 个动作。"
        )

        start_time_monotonic = time.monotonic()

        try:
            for timestamp_ms in sorted_timestamps:
                # 计算并执行休眠
                target_elapsed_sec = timestamp_ms / 1000.0
                current_elapsed_sec = time.monotonic() - start_time_monotonic
                sleep_duration_sec = target_elapsed_sec - current_elapsed_sec

                if sleep_duration_sec > 0:
                    time.sleep(sleep_duration_sec)

                # 执行当前时间戳下的所有事件
                events_to_run = event_groups[timestamp_ms]
                log_actions = []
                for event in events_to_run:
                    method_to_call = getattr(self.pad, event.action_name, None)
                    if callable(method_to_call):
                        method_to_call(*event.params)
                        log_actions.append(f"{event.action_name}({event.params})")
                    else:
                        logger.warning(f"未知的手柄动作: {event.action_name}")

                # 5. 更新手柄状态
                self.pad.update()

                actual_time_ms = round((time.monotonic() - start_time_monotonic) * 1000)
                logger.debug(f"[{actual_time_ms}ms / 目标 {timestamp_ms}ms] 执行: {', '.join(log_actions)}")

        finally:
            # 重置手柄
            if reset_at_end:
                logger.debug("宏播放完毕，重置手柄状态。")
                self.pad.reset()
                self.pad.update()
            else:
                logger.debug("宏播放完毕，不重置手柄状态。")


# --- 使用示例 ---
if __name__ == "__main__":
    from time import sleep, monotonic
    from pprint import pprint
    from random import random, uniform
    from vgamepad import XUSB_BUTTON

    gamepad = GamepadSimulator()
    if not gamepad.pad:
        print("Gamepad not connected.  Exiting test.")
        exit()

    print("--- 手柄测试 ---")
    print("按下 A 键...")
    gamepad.click_button(XUSB_BUTTON.XUSB_GAMEPAD_A, 500)
    sleep(1)
    print("按下 START 键...")
    gamepad.click_button(Button.START, 500)
    sleep(1)
    print("按下 BACK 键...")
    gamepad.click_button(Button.BACK, 500)
    sleep(1)
    print("左摇杆向前50%...")
    gamepad.move_left_joystick((0, 0.5))
    sleep(1)
    print("左摇杆复位...")
    gamepad.move_left_joystick(JoystickDirection.CENTER)
    sleep(1)
    print("右摇杆向后50%...")
    gamepad.hold_right_joystick(JoystickDirection.HALF_DOWN, 1000)
    print("左扳机下压60%...")
    gamepad.hold_left_trigger(0.6, 1000)
    print("测试完成.")

    print("\n--- 宏测试 ---")
    print("正在创建宏: 波动拳")  # ↓ ↘ → A

    hadouken_combo = Macro()
    # 顺序是任意的，会自动排序
    hadouken_combo.move_left_joystick(80, JoystickDirection.FULL_RIGHTDOWN)
    hadouken_combo.move_left_joystick(0, JoystickDirection.FULL_DOWN)
    # 支持链式调用
    hadouken_combo.move_left_joystick(160, JoystickDirection.FULL_RIGHT).click_button(160, Button.A, 100)

    print("生成的 '波动拳' 宏:")
    for event in hadouken_combo:
        pprint(event)

    # 播放宏对象
    print("Hadouken!")
    gamepad.play_macro(hadouken_combo)

    print("\n宏播放完成。")

    print("正在创建宏: 舒婷")
    shooting_macro = (
        Macro()
        .move_left_joystick(0, JoystickDirection.FULL_LEFT)
        .move_left_joystick(10, JoystickDirection.FULL_RIGHT)
        .click_button(12, Button.X, 10)
        .move_left_joystick(20, JoystickDirection.FULL_LEFTDOWN)
    )

    print("生成的 '舒婷' 宏:")
    for event in shooting_macro:
        pprint(event)

    print("通过fitter创建一个小舒婷")
    # 将按X键后移20ms，来打出小舒婷
    fist_and_back_macro = (
        shooting_macro.filter(lambda event: event.time_ms > 10)
    )
    bad_shooting_macro = (
        shooting_macro.filter(lambda event: event.time_ms <= 10)
        .append(fist_and_back_macro, 20)
    )

    print("生成的 '小舒婷' 宏:")
    for event in bad_shooting_macro:
        pprint(event)

    print("开始拉后并随机舒婷，快去用股裂吓死你的街霸好友吧! (按 Ctrl+C 退出)")
    # 蹲后
    gamepad.move_left_joystick(JoystickDirection.FULL_LEFTDOWN)
    sleep(5)
    # 随机舒婷
    end_time = monotonic() + 20
    while monotonic() < end_time:
        if random() < 0.5:
            # 不回中来实现无限蹲
            print("舒婷!!!")
            gamepad.play_macro(shooting_macro, False)
        else:
            print("舒婷。")
            gamepad.play_macro(bad_shooting_macro, False)
        sleep(uniform(0.5, 5))
    else:
        print("相信对面已经被无敌龟男打爆了。")
