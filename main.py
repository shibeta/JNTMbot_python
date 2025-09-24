import time
import threading
import keyboard
import os
import traceback
from functools import wraps
import requests
from atexit import _run_exitfuncs as trigger_atexit

from logger import setup_logging, get_logger
from config import Config
from ocr_utils import get_ocr_engine
from steambot_utils import SteamBotClient
from push_utils import wechat_push
from gta5_utils import GameAutomator
from health_check import HealthMonitor
from gameautomator_exception import *

logger = get_logger(name="main")


# 用于处理退出的装饰器
def interrupt_decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except KeyboardInterrupt:
            logger.warning("程序被用户中断，正在退出。")
            return

    return wrapper


# 安全退出程序而不需要调用 return 或 sys.exit
# 因为有人抱怨这不安全，所以改名为 unsafe_exit()
def unsafe_exit():
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

    # 初始化热键
    pause_event = threading.Event()
    pause_event.set()  # 初始状态为“已恢复”

    # 暂停/恢复热键
    def toggle_pause():
        if pause_event.is_set():
            pause_event.clear()  # 清除标志，进入暂停状态
            logger.warning("暂停/恢复热键被按下，Bot 将在本循环结束后暂停。按 F10 恢复。")
        else:
            pause_event.set()  # 设置标志，恢复运行
            try:
                steam_bot.reset_send_timer()
            except:
                pass  # 没有什么需要做的
            logger.warning("暂停/恢复热键被按下，Bot 已恢复。")

    keyboard.add_hotkey("ctrl+f9", toggle_pause)

    # 退出热键
    def toggle_exit():
        logger.warning("退出热键被按下，退出程序。。。")
        unsafe_exit()

    keyboard.add_hotkey("ctrl+f10", toggle_exit)
    logger.warning("热键初始化成功，使用 CTRL+F9 暂停和恢复 Bot，使用 CTRL+F10 退出程序。")

    # 初始化 Steam Bot
    try:
        steam_bot = None
        logger.info("正在初始化 Steam Bot 客户端...")
        steam_bot = SteamBotClient(config)
    except Exception as e:
        logger.error(f"初始化 Steam Bot 客户端失败: {e}")
        if steam_bot:
            steam_bot.shutdown()
        return
    # 等待至多 steamBotLoginTimeout 秒来让 Steam Bot 完成初始化
    if not steam_bot.wait_for_ready(timeout=config.steamBotLoginTimeout):
        logger.error(f"Steam Bot 后端未能在 {config.steamBotLoginTimeout} 秒内准备就绪。")
    # 等待 Steam Bot 完成首次登录
    while steam_bot.get_login_status()["loggedIn"] != True:
        time.sleep(5)
    logger.info("Steam Bot 客户端初始化完成。")

    # 验证配置中的群组ID
    bot_userinfo = steam_bot.get_userinfo()
    if bot_userinfo.get("error"):
        logger.warning(f"获取群组列表失败。错误: {bot_userinfo.get('error', '未知原因')}")
    else:
        for group in bot_userinfo["groups"]:
            if config.steamGroupId == group["id"]:
                logger.info(f"Bot发车信息将发送到{group['name']} ({group['id']})群组。")
                break
        else:
            logger.error(f"配置中的 Steam 群组 ID ({config.steamGroupId})无效，或者 Bot 不在该群组中。")
            logger.error("================Bot 所在的群组列表=================")
            for group in bot_userinfo["groups"]:
                logger.error(f"  - {group['name']} (ID: {group['id']})")
            logger.error("=================================================")
            logger.error(f"请将正确的群组ID填入 {config_file_path} 。")
            return

    # 初始化 OCR
    try:
        GOCREngine = get_ocr_engine()
    except Exception as e:
        logger.error(f"初始化 OCR 引擎失败: {e}")
        return

    # 初始化游戏控制器
    automator = GameAutomator(config, GOCREngine, steam_bot)

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
            time.sleep(1)

            logger.info("动作: 正在开始新一轮循环...")
            # 确保游戏启动
            try:
                automator.setup_gta()
            except UnexpectedGameState as e:
                # 启动 GTA V 多次失败
                logger.error(f"初始化 GTA V 窗口时，启动游戏失败次数过多。")
                raise Exception(f"初始化 GTA V 窗口时，发生异常: {e}") from e

            # 开始新战局
            try:
                automator.start_new_match()
            except UnexpectedGameState as e:
                if e.actual_state == GameState.UNKNOWN:
                    # 开始新战局多次失败
                    logger.error("开始新战局失败次数过多。杀死 GTA V 进程。")
                    automator.kill_gta()
                elif e.actual_state == GameState.OFF:
                    # 游戏被意外关闭
                    logger.error("开始新战局时游戏被意外关闭。")
                else:
                    logger.error(f"开始新战局时发生预期外的异常: {e}")

                raise Exception(f"开始新战局时，发生异常: {e}") from e

            # 等待复活
            logger.info("等待在事务所床上复活...")
            start_time = time.monotonic()
            while time.monotonic() - start_time < 60:
                if automator.is_respawned_in_agency():
                    break
                time.sleep(0.3)
            else:
                logger.error("等待复活超时。")
                raise OperationTimeout(OperationTimeoutContext.RESPAWN_IN_AGENCY)
            logger.info("在事务所床上复活成功。")

            # 导航并寻找差事
            automator.go_job_point_from_bed()
            try:
                automator.find_job_point()
            except UIElementNotFound as e:
                # 没找到差事黄圈
                logger.error(f"未能找到任务触发点。")
                raise Exception(f"寻找差事触发点时，发生异常: {e}") from e

            # 进入差事
            automator.enter_job_setup()

            # 等待差事面板
            logger.info("等待差事面板打开...")
            start_time = time.monotonic()
            while time.monotonic() - start_time < 60:
                if automator.is_on_job_panel():
                    break
                time.sleep(1)
            else:
                logger.error("等待差事面板打开超时。")
                logger.info("正在确保离开面板回到自由模式。")
                automator.exit_job_panel()
                raise OperationTimeout(OperationTimeoutContext.JOB_SETUP_PANEL_OPEN)

            # 等待队伍并开始差事
            try:
                automator.setup_wait_start_job()
            except UIElementNotFound as e:
                # 不知为何离开了面板
                logger.error(f"等待队伍并开始差事时，意外离开了任务准备面板。")
                raise Exception(f"等待队伍并开始差事时，发生异常: {e}") from e
            except OperationTimeout as e:
                # 超时是因为其他玩家造成的，无须 Bot 处理，直接开始下一轮
                logger.warning(f"等待队伍并开始差事时，{e}")
                logger.info("正在确保离开面板回到自由模式。")
                automator.exit_job_panel()
                continue
            except UnexpectedGameState as e:
                # 有玩家待命，可以直接重开差事，但还是选择开启下一轮比较稳妥
                logger.warning(f"等待队伍并开始差事时，{e}")
                logger.info("正在确保离开面板回到自由模式。")
                automator.exit_job_panel()
                continue

            # 等待面板消失
            match_start_time = time.monotonic()
            logger.info("差事启动成功！等待面板消失。")
            while time.monotonic() - match_start_time < config.exitMatchTimeout:
                if not automator.is_on_job_panel():
                    break
                time.sleep(1)
            else:
                # 差事加载超时不影响 Bot 工作，直接开始下一轮
                logger.warning("等待差事加载超时。卡单并重启循环。")
                time.sleep(config.delaySuspendTime)
                automator.glitch_single_player_session()
                continue

            # 面板消失后卡单，否则会卡在启动战局
            logger.info(f"面板已消失。{config.delaySuspendTime} 秒后将卡单。")
            time.sleep(config.delaySuspendTime)
            automator.glitch_single_player_session()

            # 差事落地后卡单，避免加恶意值
            landing_start_time = time.monotonic()
            logger.info("差事加载完成！等待人物落地。")
            while time.monotonic() - landing_start_time < config.exitMatchTimeout:
                if automator.is_job_started():
                    break
                time.sleep(1)
            else:
                logger.warning("等待人物落地超时。卡单并重启循环。")
                time.sleep(config.delaySuspendTime)
                automator.glitch_single_player_session()
                continue

            logger.info(f"人物已落地。{config.delaySuspendTime} 秒后将卡单。")
            time.sleep(config.delaySuspendTime)
            automator.glitch_single_player_session()

            # 如果战局中有其他 CEO，卡单后任务会失败并进入计分板
            # 检查当前任务状态来处理卡单后可能遇到的各种情况
            logger.info("动作: 正在检查当前差事状态...")
            # 等待5秒以响应玩家离开
            time.sleep(5)
            mission_status_check_start_time = time.monotonic()
            while time.monotonic() - mission_status_check_start_time < 5:
                if automator.is_job_started():
                    # 如果战局里只有自己一人，则无事发生
                    logger.info("当前在差事中。")
                    break
                time.sleep(1)
            else:
                # 如果战局中有其他 CEO，任务会失败并进入计分板
                possible_mission_fail_time = time.monotonic()
                while time.monotonic() - possible_mission_fail_time < 15:
                    if automator.is_on_scoreboard():
                        # 由于 CEO 退出的计分板只能通过等待来退出
                        logger.info("当前在任务失败计分板。")
                        logger.info("有神人不卡单导致任务失败，等待20秒以离开计分板。")
                        try:
                            steam_bot.send_group_message(config.msgDetectedSB)
                        except requests.RequestException as e:
                            # 发送信息失败，小事罢了，不影响自动化运行
                            pass
                        time.sleep(20)  # 需要多等一会，确保返回自由模式后落地
                        break
                    time.sleep(1)
                else:
                    # 既检测不到在任务中，也检测不到任务失败
                    # 反正已经卡过单了，就这样吧
                    logger.warning("无法确定当前差事状态，但还是尝试继续执行。")

            logger.info("本轮循环完成。")
            # 清空连续出错次数
            main_loop_consecutive_error_count = 0

        except Exception as e:
            # 捕获到异常则累加连续出错次数
            # 只有捕获到异常才认为是出错，找不到差事和各种超时等不认为是出错
            main_loop_consecutive_error_count = main_loop_consecutive_error_count + 1
            # 最大可以等 120 秒
            wait_before_restart_loop = min(main_loop_consecutive_error_count * 10, 120)
            logger.error(f"主循环中发生错误: {e}")
            logger.error(traceback.format_exc())

            # 重启循环还是退出?
            logger.info(
                f"当前连续失败次数 {main_loop_consecutive_error_count}，最大失败次数阈值 {config.mainLoopConsecutiveErrorThreshold}。"
            )
            if main_loop_consecutive_error_count <= config.mainLoopConsecutiveErrorThreshold:
                # 未超过报错退出的阈值，重启
                logger.info(f"未超过连续失败阈值，将在{wait_before_restart_loop}秒后重启循环...")
                time.sleep(wait_before_restart_loop)
            else:
                # 超过报错退出的阈值，退出
                logger.error(f"超过连续失败阈值，程序将退出...")
                if config.wechatPush:
                    # 启用了微信推送并且运行超过 wechatPushActivationDelay 分钟则推送消息
                    if time.monotonic() - global_start_time > config.wechatPushActivationDelay * 60:
                        wechat_push(config.pushplusToken, f"主循环中发生错误: {e}", traceback.format_exc())
                return


if __name__ == "__main__":
    main()
