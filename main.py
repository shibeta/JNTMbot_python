import time
import threading
import os
import traceback
from functools import wraps
from atexit import _run_exitfuncs as trigger_atexit

from keyboard_utils import HotKeyManager
from logger import setup_logging, get_logger
from config import Config

from ocr_utils import OCREngine
from steambot_utils import SteamBot
from push_utils import wechat_push
from gta_automator import GTAAutomator
from health_check import HealthMonitor
from gta_automator.exception import *

logger = get_logger("main")


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
        finally:
            trigger_atexit()

    return wrapper


def unsafe_exit():
    """
    退出程序而不需要调用 return 或 sys.exit
    因为有人抱怨这不安全，所以改名为 unsafe_exit()
    """
    try:
        # os._exit() 不会触发 atexit，因此需要手动触发
        trigger_atexit()
    finally:
        os._exit(0)


# --- 主程序执行 ---
@interrupt_decorator
def main():
    os.system(f"title 鸡你太美")
    global_start_time = time.monotonic()

    # 加载配置
    try:
        config_file_path = "config.yaml"
        config = Config(config_file_path)
        logger.info("配置加载成功。")
    except Exception as e:
        logger.error(f"加载配置失败: {e}")
        return

    # 初始化日志
    logger.info("根据配置重新加载日志模块。")
    # 设置日志等级
    if config.debug:
        logger.warning("启用了 DEBUG 模式，将输出更详细的日志。")
        setup_logging(log_level="DEBUG")
    else:
        setup_logging(log_level="INFO")

    # 初始化 OCR
    try:
        ocrArgs = config.ocrArgs
        GOCREngine = OCREngine(ocrArgs)
    except Exception as e:
        logger.error(f"初始化 OCR 引擎失败: {e}")
        return

    # 初始化 Steam Bot
    steam_bot = None
    try:
        logger.info("正在初始化 Steam Bot ...")
        steam_bot = SteamBot(config)
    except Exception as e:
        logger.error(f"初始化 Steam Bot 失败: {e}")
        return

    # 验证 Steam Bot 能否访问配置中的群组ID
    try:
        bot_userinfo = steam_bot.get_userinfo()
    except Exception as e:
        logger.error(f"获取 Steam 群组信息失败: {e}", exc_info=e)
        return

    logger.info(f"登录的 Steam 用户名: {bot_userinfo['name']}")
    for group in bot_userinfo["groups"]:
        if config.steamGroupId == group["id"]:
            logger.info(f"Bot发车信息将发送到 {group['name']} ({group['id']}) 群组。")
            break
    else:
        logger.error(f"配置中的 Steam 群组 ID ({config.steamGroupId})无效，或者 Bot 不在该群组中。")
        logger.error("================Bot 所在的群组列表=================")
        for group in bot_userinfo["groups"]:
            logger.error(f"  - {group['name']} (ID: {group['id']})")
        logger.error("=================================================")
        logger.error(f"请将正确的群组ID填入 {config_file_path} 。")
        return

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
                    if steam_bot:
                        steam_bot.reset_send_timer()
                except:
                    pass  # 没有什么需要做的
                logger.warning("暂停/恢复热键被按下，Bot 已恢复。")

    hotkey.add_hotkey("<ctrl>+<f9>", toggle_pause)

    # 退出热键
    exit_lock = threading.Lock()

    def toggle_exit():
        with exit_lock:
            logger.warning("退出热键被按下，退出程序...")
            unsafe_exit()

    hotkey.add_hotkey("<ctrl>+<f10>", toggle_exit)
    logger.warning("热键初始化成功，使用 CTRL+F9 暂停和恢复 Bot，使用 CTRL+F10 退出程序。")

    # 初始化游戏控制器
    automator = GTAAutomator(config, GOCREngine, steam_bot)

    # 初始化健康检查
    if config.enableHealthCheck:
        logger.warning(f"已启用健康检查。正在初始化监控模块...")
        monitor = HealthMonitor(steam_bot, pause_event, unsafe_exit, config)
        monitor.start()

    else:
        logger.warning("未启用健康检查。")

    # 初始化微信推送
    if config.enableWechatPush:
        if config.pushplusToken:
            logger.warning("已启用微信推送。")
            if config.enableHealthCheck:
                logger.info("当健康检查发现 Bot 状态发生变化时，将通过微信通知。")
            logger.info(
                f"当程序运行超过 {config.wechatPushActivationDelay} 分钟后，因发生异常而退出时，将通过微信通知。"
            )

        else:
            logger.warning("已启用微信推送，但没有提供 pushplus token。")
            logger.info(f"请访问 https://www.pushplus.plus/ 获取 token，并填入 {config_file_path}")
            return
    else:
        logger.warning("未启用微信推送。")

    # --- 主循环 ---
    # 记录主循环连续出错的次数
    main_loop_consecutive_error_count = 0
    while True:
        try:
            # 响应暂停信号
            pause_event.wait()

            # 执行一轮完整的业务逻辑
            automator.run_dre_bot()

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

            # 为保证账号安全，恶意状态玩家报错直接退出程序
            if isinstance(e, UnexpectedGameState) and e.actual_state == GameState.BAD_SPORT_LEVEL:
                logger.info(f"检测到恶意等级过高，程序将退出以保护账号安全。")
                if config.enableWechatPush:
                    bot_name = steam_bot.get_login_status().get("name", "")
                    if not bot_name:
                        bot_name = "N/A"
                    wechat_push(
                        config.pushplusToken,
                        f"Bot: {bot_name} 恶意等级过高，程序将退出以保护账号安全。",
                        traceback.format_exc(),
                    )
                return  # 退出程序

            # 其他异常则根据配置文件决定是重试还是退出
            logger.info(
                f"当前连续失败次数 {main_loop_consecutive_error_count}，阈值 {config.mainLoopConsecutiveErrorThreshold}。"
            )
            if main_loop_consecutive_error_count > config.mainLoopConsecutiveErrorThreshold:
                logger.error("超过连续失败阈值，程序将退出...")
                # 启用了微信推送并且运行超过 wechatPushActivationDelay 分钟则推送消息
                if config.enableWechatPush:
                    if time.monotonic() - global_start_time > config.wechatPushActivationDelay * 60:
                        wechat_push(config.pushplusToken, f"主循环中发生错误: {e}", traceback.format_exc())
                return  # 退出程序

            logger.info(f"未超过连续失败阈值，将在 {wait_before_restart_loop} 秒后重启循环...")
            time.sleep(wait_before_restart_loop)


if __name__ == "__main__":
    main()
