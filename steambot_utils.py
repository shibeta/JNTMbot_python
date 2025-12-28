import os
import subprocess
import threading
import signal
import time
import atexit
from typing import Callable, Optional
import requests
from requests.exceptions import JSONDecodeError

from config import Config
from logger import get_logger
from windows_utils import get_system_proxy

logger = get_logger(__name__)


class SteamBotApiError(Exception):
    """
    SteamBotApiClient 异常类。
    用于封装后端返回的错误，并隐藏 requests 内部冗长的堆栈信息。
    """

    def __init__(self, message: str, response: Optional[requests.Response] = None):
        self.response = response
        self.status_code = response.status_code if response is not None else None
        super().__init__(message)


class ProcessManager:
    """负责管理一个进程的生命周期。"""

    def __init__(self, command: list[str]):
        self.command = command
        self.process: Optional[subprocess.Popen] = None
        self.lock = threading.Lock()

    def is_running(self) -> bool:
        """检查进程当前是否正在运行。"""
        with self.lock:
            return self.process is not None and self.process.poll() is None

    def is_running_unsafe(self) -> bool:
        """
        检查进程当前是否正在运行。
        该方法不安全，调用前应确保已持有 `self.lock`
        """
        return self.process is not None and self.process.poll() is None

    def start(self):
        """启动进程。"""
        with self.lock:
            if self.is_running_unsafe():
                logger.warning("进程已在运行，无需重复启动。")
                return

            logger.info(f"正在启动进程: {' '.join(self.command)}")
            try:
                # CREATE_NEW_PROCESS_GROUP 可以避免主进程的 Ctrl+C 信号传递给子进程
                self.process = subprocess.Popen(
                    self.command, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                )
                logger.debug(f"进程已启动，PID: {self.process.pid}")
            except FileNotFoundError:
                logger.error(f"启动失败: 未找到可执行文件: {self.command[0]}")
                self.process = None
            except Exception as e:
                logger.error(f"启动进程时发生未知错误: {e}")
                self.process = None

    def stop(self):
        """停止进程。"""
        with self.lock:
            if not self.process or not self.is_running_unsafe():
                return

            proc_to_kill = self.process
            logger.info(f"正在终止进程 (PID: {proc_to_kill.pid})...")
            try:
                proc_to_kill.send_signal(signal.SIGTERM)
                return_code = proc_to_kill.wait(timeout=2)
                if isinstance(return_code, int):
                    logger.debug(f"进程 {proc_to_kill.pid} 已成功终止。")
                else:
                    raise TimeoutError(f"等待进程 {proc_to_kill.pid} 终止超时")
            except Exception:
                logger.warning(f"终止进程 {proc_to_kill.pid} 失败，将执行强制终止。")
                proc_to_kill.kill()
            finally:
                self.process = None

    def restart(self):
        """重启子进程。"""
        self.stop()
        self.start()


class SteamBotApiClient:
    """负责与 Steam Bot 后端进行 HTTP API 通信。"""

    def __init__(self, base_url: str, headers: dict):
        self.base_url = base_url
        self.headers = headers

    def _make_authenticated_request(
        self, request_func: Callable[..., requests.Response], *args, **kwargs
    ) -> requests.Response:
        """
        一个包装器，用于执行需要认证的 API 请求。
        如果请求因 401 Unauthorized 失败，它会自动尝试重新登录并重试一次。

        :raises SteamBotApiError: 请求出错
        """
        try:
            return self._make_request(request_func, *args, **kwargs)
        except SteamBotApiError as e:
            # 401 Unauthorized 错误，尝试重新登录，然后重新请求
            if e.status_code == 401:
                logger.warning("请求失败（401 Unauthorized），检测到后端未登录。正在尝试重新登录...")
                try:
                    self.login()
                except SteamBotApiError as login_e:
                    logger.error(f"重新登录失败: {login_e}", exc_info=login_e)
                    # 抛出原始的未登录异常
                    raise e from None

                # 重试请求
                logger.info("重新登录成功，正在重试请求...")
                try:
                    return self._make_request(request_func, *args, **kwargs)
                except SteamBotApiError as retry_e:
                    # 已知的 401 错误无须包含在错误堆栈中，丢弃上一次请求的错误堆栈
                    raise retry_e from None

            else:
                # 如果是其他HTTP错误，直接抛出
                raise

    @staticmethod
    def _make_request(request_func: Callable[..., requests.Response], *args, **kwargs) -> requests.Response:
        """
        一个包装器，用于执行普通的 API 请求。
        自动将后端的错误信息抛出为 SteamBotApiError 异常

        :raises SteamBotApiError: 请求出错
        """
        try:
            response = request_func(*args, **kwargs)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            error_message = f"请求发生错误: {str(e)}"
            if hasattr(e, "response"):
                response = e.response
            else:
                response = None

            # 尝试从响应体解析更具体的错误信息
            if response is not None:
                try:
                    error_info = response.json()
                    err_code = error_info.get("error", "Unknown Error")
                    err_details = error_info.get("details", response.text)
                    error_message = f"API 错误 [{response.status_code}]: {err_code} - {err_details}"
                except (JSONDecodeError, ValueError):
                    # JSON 解析失败，回退到使用原始文本
                    # 截断消息以防日志爆炸
                    error_message = f"API 错误 [{response.status_code}] (非JSON响应{', 已截断' if len(response.text) > 200 else ''}): {response.text[:200]}"

            # 丢弃原始的 requests/urllib3 堆栈
            raise SteamBotApiError(error_message, response) from None

    def is_healthy(self) -> bool:
        """检查后端服务的健康状况。这个方法不会抛出任何异常。"""
        try:
            response = requests.get(f"{self.base_url}/health", headers=self.headers, timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def get_login_status(self) -> dict:
        """
        调用 /status API，获取Bot的登录状态。

        :return: {"loggedIn":布尔值表示的是否登录, "name":登录的用户名，未登录时为空字符串}
        :raises SteamBotApiError: 请求出错
        """
        try:
            response = self._make_request(
                requests.get, f"{self.base_url}/status", headers=self.headers, timeout=(5, 20)
            )

            # 如果是 200 OK，表示已登录
            if response.status_code == 200:
                return {"loggedIn": True, "name": response.json().get("name", "")}
            else:
                return {"loggedIn": False, "name": ""}

        except requests.HTTPError as e:
            # 未登录时会返回401，这算哪门子 Restful ？
            if e.response is not None and e.response.status_code == 401:
                return {"loggedIn": False, "name": ""}
            else:
                raise

    def login(self):
        """
        调用 /login API，让 Bot 进行登录操作。

        :raises SteamBotApiError: 请求出错
        """
        response = self._make_request(
            requests.post, f"{self.base_url}/login", headers=self.headers, timeout=(5, 20)
        )

    def get_userinfo(self) -> dict:
        """
        调用 /userinfo API，获取Bot的用户名，SteamID，群组列表。

        :return: {"name": 用户名, "steamID": SteamID, "groups":[{"name": 群组名, "id": 群组ID},...]}
        :raises SteamBotApiError: 请求出错
        """
        response = self._make_authenticated_request(
            requests.get, f"{self.base_url}/userinfo", headers=self.headers, timeout=(5, 20)
        )
        return response.json()

    def send_group_message(self, group_id: str, channel_id: str, message: str):
        """
        调用 /send-message API，向某群组ID的某频道ID发送消息。

        :raises SteamBotApiError: 请求出错
        """
        payload = {
            "groupId": group_id,
            "channelId": channel_id,
            "message": message,
        }

        self._make_authenticated_request(
            requests.post,
            f"{self.base_url}/send-message",
            json=payload,
            headers=self.headers,
            timeout=(5, 20),
        )

    def logout(self):
        """
        调用 /logout API，让 Bot 进行登出操作。

        :raises SteamBotApiError: 请求出错
        """
        # 超时时间为 10 秒，比其他方法短，减少退出时的等待时间
        self._make_authenticated_request(
            requests.post, f"{self.base_url}/logout", headers=self.headers, timeout=(5, 10)
        )

    def get_group_channels(self, group_id: str) -> list[dict[str, str | bool]]:
        """
        调用 /group-channels API，获取指定群组的文字频道列表。

        :param group_id: 目标群组的 ID
        :return: 包含频道信息的字典列表 [{"name": "...", "id": "...", "isVoiceChannel": True/False}, ...]
        :raises SteamBotApiError: 请求出错
        """
        payload = {"groupId": group_id}

        response = self._make_authenticated_request(
            requests.get,
            f"{self.base_url}/group-channels",
            params=payload,
            headers=self.headers,
            timeout=(5, 20),
        )

        # 返回 JSON 中的 channels 列表
        return response.json().get("channels", [])


class Supervisor(threading.Thread):
    """
    一个专用的后台线程，监控和维护 Steam Bot 后端的健康。
    """

    def __init__(self, process_manager: ProcessManager, api_client: SteamBotApiClient, check_interval=30):
        super().__init__(daemon=True)
        self.process_manager = process_manager
        self.api_client = api_client
        self.check_interval = check_interval
        self.stop_event = threading.Event()
        self.initial_health_event = threading.Event()
        self.is_first_check = True

    def run(self):
        """线程的主循环。"""
        logger.debug("Supervisor 线程已启动。")
        while not self.stop_event.is_set():
            is_process_running = self.process_manager.is_running()
            is_service_healthy = self.api_client.is_healthy() if is_process_running else False

            if not is_service_healthy:
                if self.is_first_check:
                    logger.debug("首次启动，正在初始化 Steam Bot 后端...")
                else:
                    logger.warning("检测到 Steam Bot 后端已关闭或不健康。正在尝试重启...")

                self.is_first_check = False
                self.process_manager.restart()

                # 等待服务在重启后变得健康
                if self._wait_for_health(timeout=30):
                    if not self.initial_health_event.is_set():
                        logger.debug("后端首次进入健康状态。")
                        self.initial_health_event.set()
                else:
                    logger.error("后端重启后未能在30秒内进入健康状态，将稍后重试。")

            self.stop_event.wait(self.check_interval)

        logger.debug("Supervisor 线程已接收到停止信号，正在退出。")

    def _wait_for_health(self, timeout) -> bool:
        """轮询健康检查端点，直到服务就绪或超时。"""
        end_time = time.monotonic() + timeout
        while time.monotonic() < end_time:
            if self.api_client.is_healthy():
                return True
            if self.stop_event.is_set():
                return False
            time.sleep(5)
        return False

    def stop(self):
        """向线程发送停止信号并等待其结束。"""
        self.stop_event.set()
        self.join()


class SteamBot:
    """
    一个基于 JS 实现的 Steam 客户端。
    """

    def __init__(self, config: Config):
        """
        初始化 SteamBot，启动后端子进程和守护线程，并等待登录完成

        :param config: 配置对象
        :raises ``TimeoutError``: 等待客户端子进程就绪超时
        :raises ``FileNotFoundError``: 未找到后端可执行文件或脚本
        :raise ``ValueError``: 群组 ID 或频道名称无效
        :raise ``Exception``: 验证群组 ID 和频道 ID 时，后端请求出错
        """
        self.config = config
        self.last_send_monotonic_time = time.monotonic()  # 上次向 Steam 发送消息的相对时间
        self.last_send_system_time = time.time()  # 上次向 Steam 发送消息的系统时间，仅作参考

        # 确保程序退出时 steam_bot 进程一并被关闭
        atexit.register(self.shutdown)

        # ProcessManager 管理 Steam Bot 进程启停
        command = self._build_command()
        self.process_manager = ProcessManager(command)

        # ApiClient 封装 HTTP 操作
        base_url = f"http://{config.steamBotHost}:{config.steamBotPort}"
        headers = {"Authorization": f"Bearer {config.steamBotToken}"}
        self.api_client = SteamBotApiClient(base_url, headers)

        # Supervisor 监控并自动重启 Steam Bot
        self.supervisor = Supervisor(self.process_manager, self.api_client)
        self.supervisor.start()

        # 等待 Steam Bot 启动
        if not self.supervisor.initial_health_event.wait(timeout=30):
            raise TimeoutError("启动超时，未能在 30 秒内准备就绪。")

        # 等待 Steam Bot 完成登录，无限期等待
        while self.get_login_status()["loggedIn"] != True:
            time.sleep(5)
        logger.info("Steam Bot 后端登录成功。")

        # 验证群组 ID 和频道 ID 是否有效
        logger.info("检查配置的群组 ID 和频道 ID 是否有效。。。")
        self.verify_group_config()

        logger.info("Steam Bot 后端初始化完成。")

    def _build_command(self) -> list[str]:
        """
        基于配置，构造 Steam Bot 后端启动指令。

        :raises ``FileNotFoundError``: 未找到后端可执行文件或脚本
        """
        node_executable = "node"
        script_path = "./steam_bot/server.js"
        executable_path = "./steam_bot.exe"

        if os.path.exists(executable_path):
            # 优先用打包好的 exe
            command = [executable_path]
        elif os.path.exists(script_path):
            command = [node_executable, script_path]
        else:
            raise FileNotFoundError(f'未找到 "{executable_path}" 或 "{script_path}"')

        command.extend(
            [
                f"--host={self.config.steamBotHost}",
                f"--port={self.config.steamBotPort}",
                f"--auth_token={self.config.steamBotToken}",
            ]
        )

        # 代理参数
        if self.config.steamBotProxy:
            if self.config.steamBotProxy == "system":
                system_proxy = get_system_proxy()
                if system_proxy:
                    command.append(f"--proxy={system_proxy}")
                else:
                    logger.warning(
                        "配置了使用系统代理，但未获取到系统代理。请注意程序不支持 PAC 模式的代理。"
                    )
            else:
                command.append(f"--proxy={self.config.steamBotProxy}")

        return command

    def verify_group_config(self, config: Optional[Config] = None):
        """
        验证配置中的 Steam 群组 ID 和频道名称是否有效。无效将抛出异常

        :param config: 可选的配置对象，不提供时将使用 self 的配置
        :raise ``ValueError``: 群组 ID 或频道名称无效
        :raise ``Exception``: 请求出错
        """
        if config is None:
            config = self.config

        # 获取 Steam 用户信息和群组列表
        try:
            bot_userinfo = self.get_userinfo()
        except Exception as e:
            raise Exception("获取 Steam 用户信息失败") from e

        logger.info(f"登录的 Steam 用户名: {bot_userinfo['name']}")

        # 验证 Steam Bot 能否访问配置中的群组ID
        for group in bot_userinfo["groups"]:
            if config.steamGroupId == group["id"]:
                # 获取频道列表
                try:
                    channel_list = self.get_group_channels(config.steamGroupId)
                except Exception as e:
                    raise Exception("获取群组频道列表失败") from e
                # 验证 Steam 群组中含有配置中的聊天频道
                for channel in channel_list:
                    if config.steamChannelId == channel["id"]:
                        logger.info(
                            f"Bot发车信息将发送到 {group['name']} ({group['id']}) 群组中的 {channel['name']} ({channel['id']}) 频道。"
                        )
                        # 在这里返回
                        return
                else:
                    logger.error(
                        f"配置中的 Steam 群组频道 ID ({config.steamChannelId}) 无效，群组 {group['name']} 中找不到该频道。"
                    )
                    logger.error("================ 当前群组可用频道 =================")
                    if not channel_list:
                        logger.error("  (没有找到任何频道，可能是权限不足或这是一个纯语音群组)")
                    # 输出时非语音频道在前，语音频道在后
                    for channel in sorted(channel_list, key=lambda x: x["isVoiceChannel"]):
                        logger.error(
                            f"  - {channel['name'] if channel['name'] else '主频道'} (ID: {channel['id']}){' (语音频道)' if channel['isVoiceChannel'] else ''}"
                        )
                    logger.error("=================================================")
                    logger.error(
                        f"请将正确的频道 ID 填入 {self.config.config_filepath} 中的 steamChannelId 。"
                    )

                    raise ValueError(f"配置中的 Steam 群组频道 ID ({config.steamChannelId}) 无效")
        else:
            logger.error(f"配置中的 Steam 群组 ID ({config.steamGroupId}) 无效，Bot 不在该群组中。")
            logger.error("=============== Bot 所在的群组列表 ================")
            if not bot_userinfo["groups"]:
                logger.error("  (列表为空，Bot 没有加入任何群组)")
            for group in bot_userinfo["groups"]:
                logger.error(f"  - {group['name']} (ID: {group['id']})")
            logger.error("=================================================")
            logger.error(f"请将正确的群组ID填入 {self.config.config_filepath} 中的 steamGroupId 。")

            raise ValueError(f"配置中的 Steam 群组 ID ({config.steamGroupId})无效")

    def send_group_message(self, message: str):
        """
        发送消息到群组。

        :param message: 消息字符串
        :raises ``Exception``: 请求出错
        """

        logger.info(
            f"正在向 Steam 群组 ({self.config.steamGroupId}) 的频道 ({self.config.steamChannelId}) 发送消息..."
        )
        if message:
            logger.info(f'消息内容: "{message}"')
        else:
            logger.warning("消息内容为空，跳过发送。")
            self.reset_send_timer()
            return

        try:
            self.api_client.send_group_message(self.config.steamGroupId, self.config.steamChannelId, message)
            logger.info("已提交消息发送任务。")
            self.reset_send_timer()
        except Exception as e:
            logger.error(f'向 Steam 群组 "{self.config.steamGroupId}" 发送消息失败: {e}', exc_info=e)
            raise

    def get_userinfo(self) -> dict:
        """
        获取用户信息，包括用户名，SteamID，群组列表。

        :return: {"name": 用户名, "steamID": SteamID, "groups":[{"name": 群组名, "id": 群组ID},...]}
        :raises ``Exception``: 请求出错
        """
        try:
            return self.api_client.get_userinfo()
        except Exception as e:
            raise Exception(f"获取用户信息时发生异常: {e}") from e

    def get_group_channels(self, group_id: str):
        """
        获取群组中的文字频道列表。

        :param group_id: 群组ID
        :return: [{"name": 频道名称字符串, "id": 频道ID字符串, "isVoiceChannel": 语音频道为True，其他为False}, ...]
        :raises ``Exception``: 请求出错
        """
        try:
            return self.api_client.get_group_channels(group_id)
        except Exception as e:
            raise Exception(f"获取群组(ID:{group_id})中的频道列表时发生异常: {e}") from e

    def login(self):
        """
        进行登录操作。登录时需要在控制台与 Node.js 进程进行交互。
        请求出错时，将抛出异常。
        """
        logger.info("正在尝试登录 Steam...")
        self.api_client.login()
        logger.info("登录请求已成功发送。")

    def get_login_status(self) -> dict:
        """
        获取登录状态。这个方法永远不会抛出异常。

        :return: {"loggedIn":布尔值表示的是否登录, "name":登录的用户名，未登录时为空字符串}
        """
        try:
            return self.api_client.get_login_status()
        except:
            return {"loggedIn": False, "name": ""}

    def get_last_send_system_time(self):
        """
        返回上次发送消息时的本地时间

        :return float: 秒数形式的浮点时间
        """
        return self.last_send_system_time

    def get_last_send_monotonic_time(self):
        """
        返回上次发送消息时的单调时间

        :return float: 秒数形式的浮点时间
        """
        return self.last_send_monotonic_time

    def reset_send_timer(self):
        """重置上次发送消息的时间戳为当前时间。"""
        self.last_send_monotonic_time = time.monotonic()
        self.last_send_system_time = time.time()

    def shutdown(self):
        """关闭所有组件。"""
        logger.info("正在关闭 Steam Bot...")
        # 停止 Supervisor，避免再次重启进程
        if hasattr(self, "supervisor") and self.supervisor is not None:
            self.supervisor.stop()

        # 通过API请求登出
        try:
            if hasattr(self, "api_client") and self.api_client is not None:
                self.api_client.logout()
        except Exception:
            pass  # 失败也无所谓

        # 停止子进程
        if hasattr(self, "process_manager") and self.process_manager is not None:
            self.process_manager.stop()
        logger.info("Steam Bot 已成功关闭。")
