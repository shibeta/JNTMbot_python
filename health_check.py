from datetime import datetime, timedelta
import threading
import time
from typing import Any, Callable, Optional

from config import Config
from logger import get_logger
from push_utils import wechat_push
from steambot_utils import SteamBot
from steamgui_automation import SteamAutomation

logger = get_logger(__name__)


class HealthMonitor(threading.Thread):
    """
    一个封装了所有健康检查逻辑的类。
    它作为一个独立的线程运行，监控 Bot 状态，并在状态变化时触发相应动作。
    """

    def __init__(
        self,
        steam_bot: SteamBot | SteamAutomation,
        pause_event: threading.Event,
        exit_func: Callable[[], Any],
        push_func: Callable[[str, str], Any],
        config: Config,
    ):
        # 将线程设置为守护线程，并为其命名以方便调试
        super().__init__(daemon=True, name="HealthMonitorThread")

        # 依赖注入
        self.steam_bot = steam_bot
        self.pause_event = pause_event
        # 用于退出主进程的无参方法
        self.exit_func = exit_func
        # 用于推送的方法，第一个参数接受一个字符串作为标题，第二个参数接受一个字符串作为正文
        self.push_func = push_func

        # 从config对象中解构配置
        self.check_interval = config.healthCheckInterval  # 分钟
        self.steam_chat_timeout_threshold = config.healthCheckSteamChatTimeoutThreshold  # 分钟
        self.enable_exit_on_unhealthy = config.enableExitOnUnhealthy

        # 内部状态
        self._is_healthy_on_last_check = True  # 初始假定为健康
        self._stop_event = threading.Event()  # 用于停止线程

        logger.info(f"健康检查已配置：每 {self.check_interval} 分钟检查一次。")
        logger.info(f"不健康阈值：连续 {self.steam_chat_timeout_threshold} 分钟未发送消息。")
        if self.enable_exit_on_unhealthy:
            logger.warning("不健康时自动退出程序功能：已启用。")
        else:
            logger.info("不健康时自动退出程序功能：已禁用。")

    def run(self):
        """线程的主执行逻辑。"""
        logger.info(f"健康检查监控已启动，每 {self.check_interval} 分钟检查一次。")

        while not self._stop_event.is_set():
            # 使用 Event.wait() 代替 time.sleep()，这样可以被 stop_event 立即中断
            is_stopped = self._stop_event.wait(timeout=self.check_interval * 60)
            if is_stopped:
                break  # 如果是 stop_event 触发了 wait 的返回，则退出循环

            self.pause_event.wait()  # 响应暂停事件

            self._perform_check()

    def stop(self):
        """外部调用的方法，用于请求线程停止。"""
        self._stop_event.set()

    def __send_notification(self, title: str, message: str):
        """
        推送消息到配置的推送方法。

        :param str title: 消息标题
        :param str message: 消息正文
        """
        logger.warning(f"正在发送通知: {title}: {message}")
        self.push_func(title, message)

    def _perform_check(self):
        """执行单次健康检查的核心逻辑。"""
        last_send_monotonic_time = self.steam_bot.last_send_monotonic_time
        elapsed_time = time.monotonic() - last_send_monotonic_time
        # 转换为整数以输出更好看的时间
        logger.debug(f"健康检查：距离上次发送消息已过去 {timedelta(seconds=int(elapsed_time))}。")

        unhealthy_reason = None
        if elapsed_time > self.steam_chat_timeout_threshold * 60:
            is_healthy_now = False
            unhealthy_reason = "SteamChatTimeout"
        else:
            is_healthy_now = True

        # --- 状态转换逻辑 ---
        if self._is_healthy_on_last_check and not is_healthy_now:
            logger.warning(
                f"Bot 状态变为不健康。原因: 超过 {self.steam_chat_timeout_threshold} 分钟未通过 Steam 发送消息。"
            )
            self._on_become_unhealthy(unhealthy_reason)

        elif not self._is_healthy_on_last_check and is_healthy_now:
            logger.info("Bot 状态已恢复健康。")
            self._on_become_healthy()

        if not is_healthy_now:
            self._on_unhealthy()

        # 更新状态以备下次检查
        self._is_healthy_on_last_check = is_healthy_now

    def _on_become_unhealthy(self, reason: Optional[str] = None):
        """从健康变为不健康时触发。"""
        if reason == "SteamChatTimeout":
            last_send_system_time = datetime.fromtimestamp(self.steam_bot.last_send_system_time)
            formatted_time = last_send_system_time.strftime("%Y-%m-%d %H:%M:%S")
            msg = f"Bot 超过 {self.steam_chat_timeout_threshold} 分钟未向 Steam 发送消息。上一次发送时间为 {formatted_time}。"
        else:
            msg = f"未知原因: {reason}"

        self.__send_notification("状态变为不健康", msg)

    def _on_become_healthy(self):
        """从不健康恢复为健康时触发。"""
        self.__send_notification("状态恢复健康", "现在一切正常。")

    def _on_unhealthy(self):
        """检查结果为不健康时触发。"""
        if self.enable_exit_on_unhealthy:
            logger.error("检测到 Bot 不健康且已配置为自动退出，程序将关闭。")
            self.exit_func()
