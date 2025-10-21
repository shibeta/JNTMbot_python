import time

from config import Config
from gamepad_utils import Button, GamepadSimulator, JoystickDirection
from logger import get_logger

logger = get_logger(name="game_action")


class GameAction:
    """封装游戏内各种动作的具体实现"""

    def __init__(self, gamepad: GamepadSimulator, config: Config):
        self.gamepad = gamepad
        self.config = config

    def walk_left(self, duration_milliseconds: int):
        """向左走"""
        self.gamepad.hold_left_joystick(JoystickDirection.HALF_LEFT, duration_milliseconds)

    def walk_right(self, duration_milliseconds: int):
        """向右走"""
        self.gamepad.hold_left_joystick(JoystickDirection.HALF_RIGHT, duration_milliseconds)

    def walk_forward(self, duration_milliseconds: int):
        """向前走"""
        self.gamepad.hold_left_joystick(JoystickDirection.HALF_UP, duration_milliseconds)

    def walk_backward(self, duration_milliseconds: int):
        """向后走"""
        self.gamepad.hold_left_joystick(JoystickDirection.HALF_DOWN, duration_milliseconds)

    def run_left(self, duration_milliseconds: int):
        """向左跑"""
        self.gamepad.hold_left_joystick(JoystickDirection.FULL_LEFT, duration_milliseconds)

    def run_right(self, duration_milliseconds: int):
        """向右跑"""
        self.gamepad.hold_left_joystick(JoystickDirection.FULL_RIGHT, duration_milliseconds)

    def run_forward(self, duration_milliseconds: int):
        """向前跑"""
        self.gamepad.hold_left_joystick(JoystickDirection.FULL_UP, duration_milliseconds)

    def run_backward(self, duration_milliseconds: int):
        """向后跑"""
        self.gamepad.hold_left_joystick(JoystickDirection.FULL_DOWN, duration_milliseconds)

    def confirm(self):
        """确认当前选择"""
        self.gamepad.click_button(Button.A)
        time.sleep(1)

    def back(self):
        """返回上一级菜单"""
        self.gamepad.click_button(Button.B)
        time.sleep(1)

    def up(self):
        """向上移动选择"""
        self.gamepad.click_button(Button.DPAD_UP)
        time.sleep(0.5)

    def down(self):
        """向下移动选择"""
        self.gamepad.click_button(Button.DPAD_DOWN)
        time.sleep(0.5)

    def left(self):
        """向左移动选择"""
        self.gamepad.click_button(Button.DPAD_LEFT)
        time.sleep(0.5)

    def right(self):
        """向右移动选择"""
        self.gamepad.click_button(Button.DPAD_RIGHT)
        time.sleep(0.5)

    def previous_page(self):
        """翻到上一页"""
        self.gamepad.click_button(Button.LEFT_SHOULDER)
        time.sleep(2)

    def next_page(self):
        """翻到下一页"""
        self.gamepad.click_button(Button.RIGHT_SHOULDER)
        time.sleep(2)

    def open_or_close_pause_menu(self):
        """打开或关闭暂停菜单"""
        self.gamepad.click_button(Button.MENU)
        time.sleep(2)

    def open_onlinemode_info_panel(self):
        """打开在线模式信息面板"""
        self.gamepad.click_button(Button.DPAD_DOWN)
        time.sleep(1)

    def navigate_to_storymode_tab_in_mainmenu(self):
        """在主菜单中，导航到'故事模式'选项卡"""
        for _ in range(3):  # 目前主菜单最多有4个选项卡，故事模式一定在最右边
            self.next_page()
            time.sleep(1)

    def navigate_to_online_tab_in_storymode(self):
        """在故事模式的暂停菜单中，导航到'进入在线模式'选项卡"""
        # 选中在线选择卡
        for _ in range(5):
            self.next_page()
        self.confirm()  # 打开在线选择卡
        self.up()  # 选中"进入在线模式"
        self.confirm()  # 进入"进入在线模式"选项卡

    def navigate_to_switch_session_tab_in_onlinemode(self):
        """在在线模式的暂停菜单中，导航到'寻找新战局'选项卡"""
        self.next_page()  # 选中在线选择卡
        self.confirm()  # 打开在线选择卡
        # 选中"寻找新战局"
        for _ in range(5):
            self.up()
        self.confirm()  # 进入"切换会话"选项卡

    def enter_invite_only_session(self):
        """在'寻找新战局'选项卡中，进入仅受邀请的战局"""
        self.down()  # 选中"仅邀请战局"
        self.confirm()  # 进入"仅邀请战局"
        time.sleep(1)  # 多等一会
        self.confirm()  # 确认进入战局

    def go_job_point_from_bed(self):
        """从事务所的床出发，下到一楼，移动到任务点附近。"""
        logger.info("动作：正在从事务所个人空间走到楼梯间...")
        # 走到柱子上卡住
        self.gamepad.hold_left_joystick(JoystickDirection.FULL_LEFTUP, 1500)
        # 走到个人空间门口
        self.gamepad.hold_left_joystick(JoystickDirection.FULL_RIGHT, 5500)
        # 走出个人空间的门
        self.gamepad.hold_left_joystick(JoystickDirection.HALF_RIGHTDOWN, 1500)
        self.gamepad.hold_left_joystick(JoystickDirection.HALF_RIGHTUP, 1000)
        # 走进楼梯门
        self.gamepad.hold_left_joystick(JoystickDirection.FULL_RIGHT, 700)
        self.gamepad.hold_left_joystick(JoystickDirection.FULL_UP, 2300)
        # 走下楼梯
        logger.info("动作：正在下楼...")
        self.gamepad.hold_left_joystick(JoystickDirection.FULL_DOWN, 4000)
        self.gamepad.hold_left_joystick(JoystickDirection.FULL_RIGHTUP, 1500)
        self.gamepad.hold_left_joystick(JoystickDirection.FULL_LEFT, 4500)
        # 走出楼梯间
        self.gamepad.hold_left_joystick(JoystickDirection.HALF_LEFTDOWN, 1000)
        # 穿过走廊
        logger.info("动作：正在穿过差事层走廊...")
        self.gamepad.hold_left_joystick(JoystickDirection.FULL_LEFTDOWN, self.config.crossAisleTime)

    def launch_job_setup_panel(self):
        """在差事点上进入差事准备面板，目前只需要按一下十字键右键。"""
        self.gamepad.click_button(Button.DPAD_RIGHT)

    def setup_job_panel(self):
        """在差事准备面板中，设置差事参数"""
        self.up()
        self.confirm()
        self.left()  # 关闭匹配功能，防止玩家通过匹配功能意外进入该差事
        self.up()  # 选中"开始差事"

    def exit_job_panel_from_first_page(self):
        """从差事准备面板的第一个面板退出"""
        self.back()
        self.confirm()
        time.sleep(4)  # 多等一会，确保退出完成

    def exit_job_panel_from_second_page(self):
        """从差事准备面板的第二个面板退出"""
        self.back()
        self.back()
        self.confirm()
        time.sleep(4)  # 多等一会，确保退出完成
