import argparse
import signal
import sys
import time
import threading
import os
import traceback
from functools import wraps, partial
from atexit import _run_exitfuncs as trigger_atexit
from typing import Callable, ParamSpec, TypeVar

from keyboard_utils import HotKeyManager
from logger import set_loglevel, get_logger
from config import Config

from ocr_utils import OCREngine
from steambot_utils import SteamBot
from steamgui_automation import SteamAutomation
from push_utils import UniPush
from gta_automator import GTAAutomator
from health_check import HealthMonitor
from gta_automator.exception import *

# 用于装饰器类型注解的泛型变量
P = ParamSpec("P")  # 捕获函数的参数列表 (args, kwargs)
R = TypeVar("R")  # 捕获函数的返回值类型

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


def interrupt_decorator(main_func: Callable[P, R]) -> Callable[P, R]:
    """
    用于处理退出的装饰器。
    """

    @wraps(main_func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return main_func(*args, **kwargs)
        except KeyboardInterrupt:
            logger.warning("程序被用户中断，正在退出。")
            sys.exit(0)
        except Exception as e:
            logger.error(f"未捕获的异常: {e}", exc_info=e)
            sys.exit(1)

    return wrapper


def exit_main_process(main_pid: int):
    """
    触发 atexit 中注册的所有方法，然后向主进程发送 SIGTERM 信号。

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
    finally:
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
        set_loglevel(log_level="DEBUG")
    else:
        set_loglevel(log_level="INFO")

    # 初始化热键
    hotkey = HotKeyManager()

    # 暂停/恢复热键
    pause_lock = threading.Lock()
    run_control_event = threading.Event()
    run_control_event.set()  # 初始状态为“正在运行”

    def toggle_pause():
        with pause_lock:
            if run_control_event.is_set():
                run_control_event.clear()  # 清除标志，进入暂停状态
                logger.warning("暂停/恢复热键被按下，Bot 将在本轮循环结束后暂停。按 CTRL+F9 恢复。")
            else:
                run_control_event.set()  # 设置标志，恢复运行
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
    def should_suppress_health_check():
        """如果处于暂停状态，或者 Bot 在恢复模式，跳过健康检查。"""
        if not run_control_event.is_set():
            return False

        try:
            if automator.is_in_recovery_mode():
                return False
        except Exception as e:
            raise Exception(f"获取 Bot 工作模式出错: {e}")

        return True

    if config.enableHealthCheck:
        logger.warning(f"已启用健康检查。正在初始化监控模块...")
        health_check_exit_func = partial(exit_main_process, os.getpid())
        monitor = HealthMonitor(
            config,
            steam_bot.get_last_send_system_time,
            steam_bot.get_last_send_monotonic_time,
            health_check_exit_func,
            push_integration.push_message,
            should_suppress_health_check,
        )
    else:
        logger.warning("未启用健康检查。")

    # --- 主循环 ---
    # 主循环连续出错的次数
    main_loop_consecutive_error_count = 0

    while True:
        try:
            # 响应暂停信号
            run_control_event.wait()

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
