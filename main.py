import time
import threading
from datetime import datetime, timedelta
import keyboard
import os
import win32gui
from win32con import SW_RESTORE
from functools import wraps

from logger import setup_logging, get_logger

GLogger = get_logger(name="main")

from config import Config
from ocr_engine import get_ocr_engine
from steam_utils import SteamBotClient
from process_utils import get_window_info
from push_utils import push_wechat
from gta5_utils import GameAutomator


def health_check_monitor(steam_bot: SteamBotClient, token: str, pause_event: threading.Event):
    """
    一个在后台运行的守护线程函数，用于监控 send_group_message 的调用情况。
    """
    GLogger.info("Bot 可用性监控线程已启动，每5分钟检查一次。")
    CHECK_INTERVAL = 300  # 检查间隔 (5分钟)
    TIMEOUT_THRESHOLD = 1800  # 超时阈值 (30分钟)

    while True:
        # 可用性监控也会响应暂停
        pause_event.wait()
        time.sleep(CHECK_INTERVAL)
        pause_event.wait()

        last_send_timestamp = steam_bot.get_last_send_time()
        elapsed_time = time.monotonic() - last_send_timestamp

        GLogger.debug(f"健康检查：距离上次发送消息已过去 {timedelta(seconds=elapsed_time)} 。")

        if elapsed_time > TIMEOUT_THRESHOLD:
            # 格式化上次发送的时间，使其更具可读性
            # time.time() - elapsed_time 近似于上次发送的系统时间
            last_send_system_time = datetime.fromtimestamp(time.time() - elapsed_time)
            formatted_time = last_send_system_time.strftime("%Y-%m-%d %H:%M:%S")

            title = "Bot不可用"
            msg = f"Bot: {steam_bot.get_status().get('name', '获取Bot名称失败')} 已经超过30分钟未向Steam发送信息，请检查Bot。上一次向Steam发送信息时间为 {formatted_time}"

            GLogger.warning(f"检测到 Bot 连续30分钟未向 Steam 发送消息！正在发送微信通知: {msg}")
            push_wechat(token, title, msg)
            steam_bot.shutdown()
            os._exit(0)


# 用于处理退出的装饰器
def interrupt_decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except KeyboardInterrupt:
            GLogger.warning("程序被用户中断，正在退出。")
            return

    return wrapper


# --- 主程序执行 ---
@interrupt_decorator
def main():
    os.system(f"title 鸡你太美")

    # 加载配置
    try:
        config_file_path = "config.yaml"
        GConfig = Config(config_file_path)
        GLogger.info("配置加载成功。")
    except Exception as e:
        GLogger.error(f"加载配置失败: {e}")
        return

    # 设置日志等级
    if GConfig.debug:
        GLogger.warning("启用了 DEBUG 模式，将输出更详细的日志。")
        setup_logging(log_level="DEBUG")
    else:
        setup_logging(log_level="INFO")

    # 初始化 Steam Bot
    try:
        steam_bot = SteamBotClient(GConfig)
    except Exception as e:
        GLogger.error(f"初始化 Steam Bot 客户端失败: {e}")
        return
    # 检查初始登录状态
    status = steam_bot.get_status()
    if status.get("loggedIn"):
        GLogger.info(f"Steam Bot 后端已连接并登录为: {status.get('name')}")
    else:
        GLogger.error(
            f"Steam Bot 后端未登录。错误: {status.get('error', '后端无法完成登录，请查看后端日志')}"
        )
        return
    # 验证配置中的群组ID
    bot_userinfo = steam_bot.get_userinfo()
    if bot_userinfo.get("error"):
        GLogger.warning(f"获取群组列表失败。错误: {bot_userinfo.get('error', '未知原因')}")
    else:
        for group in bot_userinfo["groups"]:
            if GConfig.steamGroupId == group["id"]:
                GLogger.info(f"Bot发车信息将发送到{group['name']} ({group['id']})群组。")
                break
        else:
            GLogger.error(f"配置中的 Steam 群组 ID ({GConfig.steamGroupId})无效，或者 Bot 不在该群组中。")
            GLogger.info("================Bot 所在的群组列表=================")
            for group in bot_userinfo["groups"]:
                GLogger.info(f"  - {group['name']} (ID: {group['id']})")
            GLogger.info("=================================================")
            GLogger.info(f"请将正确的群组ID填入 {config_file_path} 。")
            return

    # 初始化 OCR
    try:
        GOCREngine = get_ocr_engine()
    except Exception as e:
        GLogger.error(f"初始化 OCR 引擎失败: {e}")
        return

    # 热键设置
    pause_event = threading.Event()
    pause_event.set()  # 初始状态为“已恢复”

    # 暂停/恢复热键
    def toggle_pause():
        if pause_event.is_set():
            pause_event.clear()  # 清除标志，进入暂停状态
            GLogger.warning("暂停/恢复热键被按下，Bot 将在本循环结束后暂停。按 F10 恢复。")
        else:
            pause_event.set()  # 设置标志，恢复运行
            steam_bot.reset_send_timer()  # 恢复时重置发送信息计时器
            GLogger.warning("暂停/恢复热键被按下，Bot 已恢复。")

    keyboard.add_hotkey("ctrl+f9", toggle_pause)

    # 退出热键
    def toggle_exit(steam_bot: SteamBotClient):
        GLogger.warning("退出热键被按下，退出程序。。。")
        steam_bot.shutdown()
        os._exit(0)

    keyboard.add_hotkey("ctrl+f10", toggle_exit, args=(steam_bot,))
    GLogger.info("热键初始化成功，使用 CTRL+F9 暂停和恢复 Bot，使用 CTRL+F10 退出程序。")

    # 初始化健康检查和微信推送
    if GConfig.wechatPush:
        if GConfig.pushplusToken:
            GLogger.info("已启用微信推送，当 Bot 连续30分钟未向 Steam 发送消息时，将发送微信消息并退出程序。")
            monitor_thread = threading.Thread(
                target=health_check_monitor,
                args=(steam_bot, GConfig.pushplusToken, pause_event),
                daemon=True,  # 设置为守护线程，这样主程序退出时该线程会自动结束
            )
            monitor_thread.start()
        else:
            GLogger.warning("已启用微信推送，但没有提供 pushplus token。")
            GLogger.info(f"请访问 https://www.pushplus.plus/ 获取 token，并填入 {config_file_path}")
            return
    else:
        GLogger.info("未启用微信推送。")

    # 初始化游戏控制器
    window_info = get_window_info("Grand Theft Auto V")
    if window_info:
        hwnd, pid = window_info
        GLogger.info(f"找到 GTA V 窗口。窗口句柄: {hwnd}, 进程ID: {pid}")
        automator = GameAutomator(GConfig, GOCREngine, steam_bot, hwnd, pid)
    else:
        GLogger.error("GTA V 未启动。正在重启游戏...")
        automator = GameAutomator(GConfig, GOCREngine, steam_bot, None, None)
        automator.restart_gta()

    # --- 主循环 ---
    # 记录主循环连续出错的次数
    main_loop_consecutive_error_count = 0
    while True:
        try:
            # 响应暂停信号
            pause_event.wait()
            time.sleep(1)

            gta_hwnd = automator.get_gta_hwnd()
            if not gta_hwnd:
                GLogger.warning("GTA V 未启动。正在重启游戏...")
                automator.restart_gta()
                continue
            if gta_hwnd != win32gui.GetForegroundWindow():
                GLogger.warning("GTA V 未置于前台。尝试切换到 GTA V 窗口...")
                win32gui.SetForegroundWindow(gta_hwnd)
                win32gui.ShowWindow(gta_hwnd, SW_RESTORE)
                continue

            # 开始新战局
            if not automator.start_new_match():
                GLogger.error("开始新战局失败次数过多。正在重启游戏。")
                automator.restart_gta()
                continue

            GLogger.info("成功初始化新战局。")

            # 等待复活
            start_time = time.monotonic()
            while time.monotonic() - start_time < 60:
                if automator.is_respawned():
                    break
                time.sleep(0.3)
            else:
                GLogger.warning("等待复活超时。重启循环。")
                continue

            # 导航并寻找差事
            automator.go_downstairs()
            if not automator.find_job():
                GLogger.warning("未能找到差事标记。重启循环。")
                continue

            # 进入差事
            automator.enter_job()

            # 等待差事面板
            start_time = time.monotonic()
            while time.monotonic() - start_time < 60:
                if automator.is_on_job_panel():
                    break
                time.sleep(1)
            else:
                GLogger.warning("等待差事面板打开超时。重启循环。")
                GLogger.info("正在确保离开面板回到自由模式。")
                automator.exit_job_panel()
                continue

            # 等待队伍并开始差事
            if not automator.wait_team():
                GLogger.warning("等待队伍时出错。重启循环。")
                GLogger.info("正在确保离开面板回到自由模式。")
                automator.exit_job_panel()
                continue

            # 面板消失后卡单
            # TODO 面板消失后卡单真的是必要的吗
            match_start_time = time.monotonic()
            GLogger.info("差事启动成功！等待面板消失。")
            while time.monotonic() - match_start_time < GConfig.exitMatchTimeout:
                if not automator.is_on_job_panel():
                    break
                time.sleep(1)
            else:
                GLogger.warning("等待差事加载超时。卡单并重启循环。")
                time.sleep(GConfig.delaySuspendTime)
                automator.enter_single_player_session()
                continue

            GLogger.info(f"面板已消失。{GConfig.delaySuspendTime} 秒后将卡单。")
            time.sleep(GConfig.delaySuspendTime)
            automator.enter_single_player_session()

            # 差事落地后卡单，避免加恶意值
            landing_start_time = time.monotonic()
            GLogger.info("差事加载完成！等待人物落地。")
            while time.monotonic() - landing_start_time < GConfig.exitMatchTimeout:
                if automator.is_job_started():
                    break
                time.sleep(1)
            else:
                GLogger.warning("等待人物落地超时。卡单并重启循环。")
                time.sleep(GConfig.delaySuspendTime)
                automator.enter_single_player_session()
                continue

            GLogger.info(f"人物已落地。{GConfig.delaySuspendTime} 秒后将卡单。")
            time.sleep(GConfig.delaySuspendTime)
            automator.enter_single_player_session()

            # 如果战局中有其他 CEO，卡单后任务会失败并进入计分板
            # 检查当前任务状态来处理卡单后可能遇到的各种情况
            GLogger.info("正在检查当前差事状态。")
            # 等待5秒以响应玩家离开
            time.sleep(5)
            mission_status_check_start_time = time.monotonic()
            while time.monotonic() - mission_status_check_start_time < 5:
                if automator.is_job_started():
                    # 如果战局里只有自己一人，则无事发生
                    GLogger.info("当前在差事中。")
                    break
                time.sleep(1)
            else:
                # 如果战局中有其他 CEO，任务会失败并进入计分板
                possible_mission_fail_time = time.monotonic()
                while time.monotonic() - possible_mission_fail_time < 15:
                    if automator.is_on_scoreboard():
                        # 由于 CEO 退出的计分板只能通过等待来退出
                        GLogger.info("有神人不卡单导致任务失败，等待20秒以离开计分板。")
                        steam_bot.send_group_message(GConfig.msgDetectedSB)
                        time.sleep(20)  # 需要多等一会，确保返回自由模式后落地
                        break
                    time.sleep(1)
                else:
                    # 既检测不到在任务中，也检测不到任务失败
                    # 反正已经卡过单了，就这样吧
                    GLogger.warning("任务状态异常，但还是尝试继续执行。")

            GLogger.info("本轮循环完成。开始新一轮。")
            # 清空连续出错次数
            main_loop_consecutive_error_count = 0

        except Exception as e:
            # 捕获到异常则累加连续出错次数
            # 只有捕获到异常才认为是出错，找不到差事和各种超时等不认为是出错
            main_loop_consecutive_error_count = main_loop_consecutive_error_count + 1
            # 最大可以等 120 秒
            wait_before_restart_loop = max(main_loop_consecutive_error_count * 10, 120)
            GLogger.error(f"主循环中发生错误: {e}")
            GLogger.error(f"将在{wait_before_restart_loop}秒后重启循环...")
            time.sleep(wait_before_restart_loop)


if __name__ == "__main__":
    main()
