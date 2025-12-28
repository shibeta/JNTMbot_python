import argparse
import signal
import time
import threading
import os
import traceback
from functools import wraps, partial
from atexit import _run_exitfuncs as trigger_atexit

from keyboard_utils import HotKeyManager
from logger import setup_logging, get_logger
from config import Config

from ocr_utils import OCREngine
from steambot_utils import SteamBot
from steamgui_automation import SteamAutomation
from push_utils import UniPush
from gta_automator import GTAAutomator
from health_check import HealthMonitor
from gta_automator.exception import *

logger = get_logger("main")


class ArgumentParser:
    """
    管理和解析命令行参数的封装类。
    """

    def __init__(self):
        self.parser = argparse.ArgumentParser(description="德瑞BOT自动化脚本")
        self._add_arguments()

    def _add_arguments(self):
        self.parser.add_argument(
            "--config-file",
            dest="config_file_path",  # 解析后参数字典中的键名
            default="config.yaml",  # 默认值
            help='指定配置文件的路径。\n默认值: "config.yaml"',
        )
        # 示例：添加更多参数
        # self.parser.add_argument('--verbose', action='store_true', help='启用详细输出模式')

    def parse(self) -> dict:
        args = self.parser.parse_args()
        return vars(args)


# 用于处理退出的装饰器
def interrupt_decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except KeyboardInterrupt:
            logger.warning("程序被用户中断，正在退出。")
        except Exception as e:
            logger.error(f"未捕获的异常: {e}", exc_info=e)

    return wrapper


def exit_main_process(main_pid: int):
    """
    触发 atexit 中注册的所有方法，然后向主进程发送 CTRL_BREAK_EVENT 信号。

    :param int main_pid: 主进程的 PID。可以通过在主进程中执行`os.getpid()`获取。
    """
    logger.debug("正在执行 atexit 退出回调...")
    try:
        trigger_atexit()
    except Exception as e:
        logger.error(f"执行 atexit 退出回调时发生异常: {e}")

    logger.debug(f"正在向主进程 {main_pid} 发送退出信号...")
    try:
        os.kill(main_pid, signal.SIGTERM)
    except (ProcessLookupError, OSError) as e:
        logger.error(f"发送退出信号失败，主进程可能已退出。错误: {e}")
    except Exception as e:
        logger.error(f"发送退出信号时发生异常: {e}")

    # 以防终端窗口不关闭，提示用户程序已退出
    logger.info("程序已经退出，现在可以安全关闭终端窗口。")


# --- 主程序执行 ---
@interrupt_decorator
def main():
    os.system(f"title 鸡你太美")
    global_start_time = time.monotonic()

    # 初始化命令行参数
    try:
        arg_manager = ArgumentParser()
        command_line_args = arg_manager.parse()
    except argparse.ArgumentError as e:
        logger.error(f"解析命令行参数时出错: {e}", exc_info=e)
        input("\n按 Enter 键退出...")
        return

    # 加载配置
    try:
        config = Config(command_line_args["config_file_path"])
        logger.info("配置加载成功。")
    except Exception as e:
        logger.error(f"加载配置失败: {e}", exc_info=e)
        input("\n按 Enter 键退出...")
        return

    # 初始化日志
    logger.info("根据配置重新加载日志模块。")
    # 设置日志等级
    if config.debug:
        logger.warning("启用了 DEBUG 模式，将输出更详细的日志。")
        setup_logging(log_level="DEBUG")
    else:
        setup_logging(log_level="INFO")

    # 初始化热键
    hotkey = HotKeyManager()

    # 暂停/恢复热键
    pause_lock = threading.Lock()
    pause_event = threading.Event()
    pause_event.set()  # 初始状态为“已恢复”

    def toggle_pause():
        with pause_lock:
            if pause_event.is_set():
                pause_event.clear()  # 清除标志，进入暂停状态
                logger.warning("暂停/恢复热键被按下，Bot 将在本轮循环结束后暂停。按 CTRL+F9 恢复。")
            else:
                pause_event.set()  # 设置标志，恢复运行
                try:
                    steam_bot.reset_send_timer()
                except NameError:
                    pass  # steam_bot 可能未被定义
                logger.warning("暂停/恢复热键被按下，Bot 已恢复。")

    hotkey.add_hotkey("<ctrl>+<f9>", toggle_pause)

    # 退出热键
    exit_lock = threading.Lock()

    def toggle_exit():
        with exit_lock:
            logger.warning("退出热键被按下，退出程序...")
            exit_main_process(os.getpid())

    hotkey.add_hotkey("<ctrl>+<f10>", toggle_exit)
    logger.warning("热键初始化成功，使用 CTRL+F9 暂停和恢复 Bot，使用 CTRL+F10 退出程序。")

    # 初始化 OCR
    try:
        ocrArgs = config.ocrArgs
        ocr_engine = OCREngine(ocrArgs)
    except Exception as e:
        logger.error(f"初始化 OCR 引擎失败: {e}", exc_info=e)
        input("\n按 Enter 键退出...")
        return

    # 初始化 Steam Bot
    if not config.useAlterMessagingMethod:
        try:
            logger.info("正在初始化 Steam Bot ...")
            steam_bot = SteamBot(config)
        except ValueError as e:
            # 配置文件中的值错误，无须打印错误堆栈。
            logger.error(f"初始化 Steam Bot 失败: {e}")
            input("\n按 Enter 键退出...")
            return
        except Exception as e:
            logger.error(f"初始化 Steam Bot 失败: {e}", exc_info=e)
            input("\n按 Enter 键退出...")
            return
    else:
        logger.info("正在初始化 Steam Automation ...")
        try:
            steam_bot = SteamAutomation(config.AlterMessagingMethodWindowTitle)
        except Exception as e:
            logger.error(f"初始化 Steam Automation 失败: {e}", exc_info=e)
            input("\n按 Enter 键退出...")
            return

    # 初始化消息推送
    try:
        push_integration = UniPush(config, steam_bot.get_login_status().get("name", "N/A"))
    except Exception as e:
        logger.error(f"初始化消息推送失败: {e}", exc_info=e)
        input("\n按 Enter 键退出...")
        return

    # 初始化游戏控制器
    automator = GTAAutomator(
        config, ocr_engine.ocr_window, steam_bot.send_group_message, push_integration.push_message
    )

    # 初始化健康检查
    if config.enableHealthCheck:
        logger.warning(f"已启用健康检查。正在初始化监控模块...")
        health_check_exit_func = partial(exit_main_process, os.getpid())
        monitor = HealthMonitor(
            config,
            steam_bot.get_last_send_system_time,
            steam_bot.get_last_send_monotonic_time,
            pause_event,
            health_check_exit_func,
            push_integration.push_message,
            automator.is_in_recovery_mode,
        )
    else:
        logger.warning("未启用健康检查。")

    # --- 主循环 ---
    # 主循环连续出错的次数
    main_loop_consecutive_error_count = 0

    while True:
        try:
            # 响应暂停信号
            pause_event.wait()

            # 执行一轮循环
            automator.run_one_cycle()

            # 如果成功完成，重置连续错误计数器
            if main_loop_consecutive_error_count != 0:
                logger.info("本轮循环成功，重置连续错误计数。")
                main_loop_consecutive_error_count = 0

        except Exception as e:
            # 捕获到异常则累加连续出错次数
            main_loop_consecutive_error_count += 1
            # 出错后等待的时间, 随连续出错次数增大而指数增长, 最多等待 120 秒
            wait_before_restart_loop = min(2**main_loop_consecutive_error_count * 5, 120)

            logger.error(f"主循环中发生错误: {e}", exc_info=e)

            # 恶意/问题玩家，退出程序
            if isinstance(e, UnexpectedGameState) and e.actual_state in (
                GameState.BAD_SPORT_LEVEL,
                GameState.DODGY_PLAYER_LEVEL,
            ):
                logger.info(f"检测到恶意等级过高: {e.actual_state.value}。程序将退出以保护账号安全。")
                logger.warning("提示: 如果启用了自动降低恶意值，程序会在问题玩家时自动挂机降低恶意值。")
                push_integration.push_message(
                    f"恶意值过高({e.actual_state.value})",
                    "程序将退出以保护账号安全。\n提示: 如果启用了自动降低恶意值，程序会在问题玩家时自动挂机降低恶意值。",
                )
                return  # 退出程序

            # 其他异常则根据配置文件决定是重试还是退出
            else:
                logger.info(
                    f"当前连续失败次数 {main_loop_consecutive_error_count}，阈值 {config.mainLoopConsecutiveErrorThreshold}。"
                )
                if main_loop_consecutive_error_count > config.mainLoopConsecutiveErrorThreshold:
                    logger.error("超过连续失败阈值，程序退出...")
                    # 运行超过 pushActivationDelay 分钟则推送消息
                    if time.monotonic() - global_start_time > config.pushActivationDelay * 60:
                        push_integration.push_message(
                            "超过连续失败阈值，程序退出", f"最后一次错误: {e} \n{traceback.format_exc()}"
                        )
                    return  # 退出程序

                logger.info(f"未超过连续失败阈值，将在 {wait_before_restart_loop} 秒后重启循环...")
                time.sleep(wait_before_restart_loop)


if __name__ == "__main__":
    main()
