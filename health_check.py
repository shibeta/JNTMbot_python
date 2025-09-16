from datetime import datetime, timedelta
import threading
import time
from typing import Callable

from logger import get_logger
from push_utils import push_wechat
from steambot_utils import SteamBotClient

logger = get_logger(name="health_check")

is_bot_healthy_on_last_check = True


def on_become_unhealthy(
    unhealthy_reason: str,
    steam_bot: SteamBotClient,
    last_send_timestamp: int,
    steam_chat_timeout_threshold: int,
    enable_wechat_push: bool,
    wechat_push_token: str,
):
    """
    在从 healthy 状态变为 unhealthy 状态后，需要执行的作业:
    根据config设置，发送微信通知
    """
    logger.info("Bot 状态变化: healthy -> unhealthy。")
    # 发送微信通知
    if enable_wechat_push:
        logger.info("启用了微信推送，将通过微信通知 Bot 变为 unhealthy。。")
        title = f"Bot: {steam_bot.get_login_status().get('name', '获取Bot名称失败')} 状态变为 unhealthy"
        # 具体原因
        if unhealthy_reason == "SteamChatTimeout":
            # 由于上次向 Steam 发送消息的时间超时
            last_send_system_time = datetime.fromtimestamp(last_send_timestamp)
            formatted_time = last_send_system_time.strftime("%Y-%m-%d %H:%M:%S")
            msg = f"Bot 超过 {steam_chat_timeout_threshold} 分钟未向 Steam 发送消息。上一次向Steam发送信息时间为 {formatted_time}"
        else:
            # 未定义的原因
            msg = f"未知原因: {unhealthy_reason}"

        logger.warning(f"正在发送微信通知: {title}: {msg}")
        push_wechat(wechat_push_token, title, msg)


def on_become_healthy(steam_bot: SteamBotClient, enable_wechat_push: bool, wechat_push_token: str):
    """
    在从 unhealthy 状态变为 healthy 状态后，需要执行的作业:
    根据config设置，发送微信通知
    """
    logger.info("Bot 状态变化: unhealthy -> healthy。")
    # 发送微信通知
    if enable_wechat_push:
        logger.info("启用了微信推送，将通过微信通知 Bot 变为 healthy。")
        title = f"Bot: {steam_bot.get_login_status().get('name', '获取Bot名称失败')} 状态变为 healthy"
        msg = "现在一切正常"

        logger.warning(f"正在发送微信通知: {title}: {msg}")
        push_wechat(wechat_push_token, title, msg)


def on_is_unhealthy(enable_exit_on_unhealthy: bool, exit_func: Callable):
    """
    在本次检查状态为 unhealthy 时，需要执行的作业:
    根据config设置，退出程序
    """
    if enable_exit_on_unhealthy:
        exit_func()


def health_check_monitor(
    steam_bot: SteamBotClient,
    pause_event: threading.Event,
    exit_func: Callable,
    check_interval: int,
    enable_wechat_push: bool,
    wechat_push_token: str,
    enable_exit_on_unhealthy: bool,
    steam_chat_timeout_threshold: int,
):
    """
    一个在后台运行的守护线程函数，用于监控 Bot 可用性。
    """
    global is_bot_healthy_on_last_check
    logger.info(f"Bot 可用性监控线程已启动，每 {check_interval} 分钟检查一次。")

    while True:
        # 可用性监控也会响应暂停
        pause_event.wait()
        time.sleep(check_interval * 60)
        pause_event.wait()

        # 基于上次向 Steam 发送消息的时间判断 Bot 健康状态
        last_send_timestamp = steam_bot.get_last_send_time()
        elapsed_time = time.monotonic() - last_send_timestamp
        logger.debug(f"健康检查：距离上次发送消息已过去 {timedelta(seconds=elapsed_time)} 。")

        # 基于所有检查项，判断 Bot 状态
        if elapsed_time > steam_chat_timeout_threshold * 60:
            # 当前状态为 unhealthy
            logger.warning(
                f"Bot 状态为 unhealthy。原因: 连续 {steam_chat_timeout_threshold} 分钟未向 Steam 发送消息。"
            )
            is_bot_healthy_on_this_check = False
            unhealthy_reason = "SteamChatTimeout"
        else:
            # 当前状态为 healthy
            logger.info(f"Bot 状态为 healthy。")
            is_bot_healthy_on_this_check = True

        # 根据本次检查状态和上次检查状态，执行行为:
        # healthy -> unhealthy
        if is_bot_healthy_on_last_check == True and is_bot_healthy_on_this_check == False:
            on_become_unhealthy(
                unhealthy_reason,
                steam_bot,
                last_send_timestamp,
                steam_chat_timeout_threshold,
                enable_wechat_push,
                wechat_push_token,
            )

        # unhealthy -> healthy
        if is_bot_healthy_on_last_check == False and is_bot_healthy_on_this_check == True:
            on_become_healthy(steam_bot, enable_wechat_push, wechat_push_token)

        # any -> unhealthy
        if is_bot_healthy_on_this_check == False:
            if enable_exit_on_unhealthy:
                exit_func()

        is_bot_healthy_on_last_check = is_bot_healthy_on_this_check
