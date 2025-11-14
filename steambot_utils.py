from __future__ import annotations
import subprocess
import threading
from signal import CTRL_BREAK_EVENT
import time
from typing import Optional
import requests
import atexit
import os
from urllib.request import getproxies

from config import Config
from logger import get_logger

logger = get_logger(__name__)


class _SupervisorThread(threading.Thread):
    """
    一个专用的后台线程，负责监控和维护 Steam Bot 子进程的健康。
    """

    def __init__(self, client: SteamBot, headers, stop_event, initial_health_event, check_interval=30):
        super().__init__(daemon=True)
        self.client = client
        self.headers = headers
        self.stop_event = stop_event
        self.initial_health_event = initial_health_event
        self.check_interval = check_interval
        self.is_first_run = True

    def run(self):
        """线程的主循环。"""
        while not self.stop_event.is_set():
            is_healthy = False

            # 使用锁来安全地检查进程状态
            with self.client.process_lock:
                if self.client.process and self.client.process.poll() is None:
                    # 进程存在，现在检查它是否健康
                    try:
                        response = requests.get(
                            f"{self.client.base_url}/health", headers=self.headers, timeout=5
                        )
                        if response.status_code == 200:
                            is_healthy = True
                    except requests.RequestException:
                        logger.warning("后端进程仍在运行，但健康检查失败。")

            if not is_healthy:
                if self.is_first_run:
                    logger.info("首次启动，正在初始化 Steam Bot 后端...")
                else:
                    logger.warning("检测到 Steam Bot 后端已关闭或不健康。正在尝试重启...")

                # 标记第一次运行已结束
                self.is_first_run = False

                # 再次获取锁来执行启动操作
                with self.client.process_lock:
                    # 确保旧进程（如果不健康但仍在）被清理
                    if self.client.process and self.client.process.poll() is None:
                        self.client._terminate_process(self.client.process)

                    # 启动新进程
                    self.client._launch_process_internal_unsafe()

                    # 如果启动成功，等待它变得健康
                    if self.client.process:
                        if self._wait_for_health(timeout=30):
                            if not self.initial_health_event.is_set():
                                logger.debug("后端首次进入健康状态。")
                                self.initial_health_event.set()
                        else:
                            logger.error("后端启动后未能在30秒内进入健康状态，将稍后重试。")
                            # 启动失败，终止这个僵尸进程
                            self.client._terminate_process(self.client.process)
                            self.client.process = None

            # 等待一段时间再进行下一次检查
            # 使用 event.wait() 代替 time.sleep() 可以让线程在收到停止信号时立即响应
            self.stop_event.wait(self.check_interval)

        logger.debug("Supervisor 线程已接收到停止信号，正在退出。")

    def _wait_for_health(self, timeout) -> bool:
        """轮询 /health 端点，直到服务就绪或超时。"""
        end_time = time.monotonic() + timeout
        while time.monotonic() < end_time:
            try:
                response = requests.get(f"{self.client.base_url}/health", headers=self.headers, timeout=5)
                if response.status_code == 200:
                    logger.debug(
                        f"Steam Bot 后端已确认健康 (PID: {self.client.process.pid if self.client.process else '未知'})。"
                    )
                    return True
            except requests.ConnectionError:
                # 这是预料之中的，因为服务器可能还没开始监听
                pass
            except requests.RequestException as e:
                logger.debug(f"健康检查请求异常: {e}")

            if self.stop_event.is_set():
                return False  # 如果在等待期间收到停止信号，则中止
            time.sleep(5)
        return False


class SteamBot:
    """
    一个基于 Node.js 实现的 Steam 客户端。
    运行 Node.js 后端并通过 HTTP 与其交互。
    """

    def __init__(self, config: Config):
        """
        :raises ``TimeoutError``: 启动超时
        """
        self.config = config
        self.process = None
        self.process_lock = threading.Lock()  # 用于操作子进程的锁
        self.base_url = f"http://{config.steamBotHost}:{config.steamBotPort}"
        self.headers = {"Authorization": f"Bearer {config.steamBotToken}"}
        self.last_send_monotonic_time = time.monotonic()  # 上次向 Steam 发送消息的相对时间
        self.last_send_system_time = time.time()  # 上次向 Steam 发送消息的系统时间，仅作参考
        self.login_lock = threading.Lock()  # 为登录操作创建一个专用的锁
        self._is_login_in_progress = False  # 一个辅助标志

        # 为 Supervisor 线程创建停止事件
        self.supervisor_stop_event = threading.Event()
        self.initial_health_event = threading.Event()
        self.supervisor = _SupervisorThread(
            self, self.headers, self.supervisor_stop_event, self.initial_health_event
        )

        # 注册退出处理函数
        atexit.register(self.shutdown)

        # 启动 supervisor 线程，它将在后台处理所有事情
        self.supervisor.start()

        # 等待后端启动
        if not self._wait_for_ready(30):
            raise TimeoutError("启动超时，未能在 30 秒内准备就绪。")

        # 等待 Steam Bot 完成登录，无限期等待
        while self.get_login_status()["loggedIn"] != True:
            time.sleep(5)

        logger.warning("Steam Bot 客户端初始化完成。")

    def _launch_process_internal_unsafe(self):
        """
        启动子进程的内部实现。
        !! 重要: 这个方法假设调用者已经持有了 self.process_lock !!
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
            logger.error(f'Steam Bot 启动失败: 未找到 "{executable_path}" 或 "{script_path}"。')
            self.process = None
            return

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
                system_proxy = self._get_system_proxy()
                if system_proxy:
                    command.append(f"--proxy={system_proxy}")
                else:
                    logger.warning(
                        "配置了使用系统代理，但未获取到系统代理。请注意程序不支持 PAC 模式的代理。"
                    )
            else:
                command.append(f"--proxy={self.config.steamBotProxy}")

        logger.info(f"正在启动 Steam Bot 后端: {' '.join(command)}")
        try:
            # CREATE_NEW_PROCESS_GROUP 可以避免主进程的 Ctrl+C 信号传递给子进程
            self.process = subprocess.Popen(command, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            logger.warning(f"Steam Bot 后端已启动，进程ID: {self.process.pid}")
        except FileNotFoundError:
            logger.error('启动失败: 未找到 "node" 可执行文件。')
            self.process = None
        except Exception as e:
            logger.error(f"启动 Steam Bot 后端时发生未知错误: {e}")
            self.process = None

    def _terminate_process(self, proc_to_kill: subprocess.Popen):
        """内部方法，用于终止一个给定的进程对象。"""
        if proc_to_kill is None or proc_to_kill.poll() is not None:
            return  # 进程不存在或已退出

        logger.debug(f"正在尝试终止进程 (PID: {proc_to_kill.pid})...")
        try:
            # 发送一个可以被捕获的信号 (在Windows上对进程组更有效)
            proc_to_kill.send_signal(CTRL_BREAK_EVENT)

            # 等待一小段时间让进程响应
            # .wait() 比 time.sleep() 循环更高效
            proc_to_kill.wait(timeout=2)
            logger.debug(f"进程 {proc_to_kill.pid} 已成功终止。")

        except subprocess.TimeoutExpired:
            # 如果等待超时，则采取强制措施
            if proc_to_kill.poll() is None:
                logger.warning(f"进程 {proc_to_kill.pid} 未能退出，将执行强制终止。")
                proc_to_kill.kill()
                logger.debug(f"进程 {proc_to_kill.pid} 已被强制终止。")

        except Exception as e:
            # 捕获其他可能的错误 (例如进程在操作期间突然消失)
            logger.error(f"终止进程 {proc_to_kill.pid} 时发生意外错误: {e}")

    def _make_authenticated_request(self, request_func, *args, **kwargs):
        """
        一个包装器，用于执行需要认证的API请求。
        如果请求因401 Unauthorized失败，它会自动尝试重新登录并重试一次。

        :raises ``requests.HTTPError``: 请求出错
        """
        try:
            # 第一次尝试
            response = request_func(*args, **kwargs)
            response.raise_for_status()
            return response
        except requests.HTTPError as e:
            # 检查是否是 401 Unauthorized 错误
            if e.response.status_code == 401:
                logger.warning("请求失败（401 Unauthorized），检测到后端未登录。正在尝试自动重新登录...")
                try:
                    # 触发线程安全的登录
                    self.login()

                    logger.info("重新登录成功，正在重试原始请求...")
                    # 重试原始请求
                    return request_func(*args, **kwargs)
                except Exception as login_e:
                    logger.error(f"自动重新登录失败: {login_e}")
                    # 抛出原始的 401 错误，因为我们无法恢复
                    raise
            else:
                # 如果是其他HTTP错误，直接抛出
                raise

    def _generate_proxy_string(self, raw_proxy_config: str) -> str:
        """
        将代理配置翻译为具体的代理字符串。
        目前将"system"翻译为具体的http代理字符串，其他时候直接返回原始值。

        :param raw_proxy_config: 代理配置字符串
        :return: 代理字符串。如果传入"system"并且未找到系统代理，返回空字符串
        """
        if raw_proxy_config == "system":
            system_proxies = getproxies().get("http", "")
            if system_proxies == "":
                logger.warning("配置了使用系统代理，但未获取到系统代理。请注意程序不支持 PAC 模式的代理。")
                return ""
            else:
                logger.info(f"发现系统代理: {system_proxies}")
                return system_proxies
        else:
            return raw_proxy_config

    def _wait_for_ready(self, timeout: int) -> bool:
        """
        阻塞当前线程，直到 Supervisor 线程报告后端首次进入健康状态，或达到超时。

        :param timeout: 最长等待时间（秒）。
        :return: True 如果后端在超时前就绪，否则 False。
        """
        logger.info(f"正在等待 Steam Bot 后端在 {timeout} 秒内准备就绪...")
        # Event.wait() 是一个高效的阻塞操作，它会等待直到事件被 set() 或超时
        is_ready = self.initial_health_event.wait(timeout=timeout)
        return is_ready

    # --- 业务逻辑方法 ---
    def get_login_status(self) -> dict:
        """调用 /status API，获取Bot的登录状态。"""
        try:
            response = requests.get(f"{self.base_url}/status", headers=self.headers, timeout=5)

            # 如果是 200 OK，表示已登录
            if response.status_code == 200:
                return {"loggedIn": True, "name": response.json().get("name", "N/A")}

            # 如果是 401 Unauthorized，明确表示未登录
            elif response.status_code == 401:
                return {"loggedIn": False, "error": response.json().get("error", "Not logged in")}

            # 对于其他所有失败的状态码 (如 500 Internal Server Error)
            response.raise_for_status()

            # 兜底，理论上不会执行到这里
            return {"loggedIn": False, "error": f"Unexpected status code: {response.status_code}"}

        except requests.ConnectionError:
            # 网络连接层面的错误
            return {"loggedIn": False, "error": "后端服务不可用"}
        except requests.RequestException as e:
            # 其他所有 requests 相关的错误 (包括 HTTPError)
            logger.error(f"调用 /status API 失败: {e}")
            return {"loggedIn": False, "error": str(e)}

    def login(self):
        """
        调用 /login API，让 Bot 进行登录操作。

        :raises ``requests.RequestException``: 请求失败
        """
        if self._is_login_in_progress:
            logger.info("检测到已有登录操作正在进行，将等待其完成...")
            # 简单地等待锁被释放
            with self.login_lock:
                return  # 另一个线程已经完成了登录

        with self.login_lock:
            self._is_login_in_progress = True
            logger.info("正在尝试登录 Steam...")
            try:
                response = requests.post(
                    f"{self.base_url}/login", headers=self.headers, timeout=(5, 30)
                )  # 登录可能耗时较长
                response.raise_for_status()
                logger.info("登录请求已成功发送。")
            except requests.RequestException as e:
                logger.error(f"调用 /login API 失败: {e}")
                raise  # 将异常抛出，让调用者处理
            finally:
                self._is_login_in_progress = False

    def get_userinfo(self) -> dict:
        """
        调用 /userinfo API，获取Bot的用户名，SteamID，群组列表。

        :return: {"name": 用户名, "steamID": SteamID, "groups":[{"name": 群组名, "id": 群组ID},...]}
        """
        try:
            # 将实际的 requests 调用包裹起来
            response = self._make_authenticated_request(
                requests.get, f"{self.base_url}/userinfo", headers=self.headers, timeout=(5, 20)
            )
            response.raise_for_status()
            return response.json()
        except requests.ConnectionError:
            return {"error": "后端服务不可用"}
        except requests.RequestException as e:
            logger.error(f"调用 /userinfo API 失败: {e}")
            # 如果是 HTTPError，响应可能包含有用的信息
            if isinstance(e, requests.HTTPError) and e.response:
                return e.response.json()
            return {"error": str(e)}

    def send_group_message(self, message: str):
        """调用 /send-message API，向预设的群组和频道发送消息。"""
        if not message:
            return

        payload = {
            "groupId": self.config.steamGroupId,
            "channelName": self.config.steamChannelName,
            "message": message,
        }

        try:
            logger.info(f"正在通过API向Steam群组 \"{payload['groupId']}\" 发送消息...")
            response = self._make_authenticated_request(
                requests.post,
                f"{self.base_url}/send-message",
                json=payload,
                headers=self.headers,
                timeout=(5, 20),
            )
            response.raise_for_status()
            logger.info("已提交消息发送任务。")
            self.last_send_monotonic_time = time.monotonic()
            self.last_send_system_time = time.time()
        except requests.ConnectionError as e:
            logger.error("后端服务不可用，无法发送消息。")
            raise Exception("Steam Bot 后端未运行，无法发送消息") from e
        except requests.RequestException as e:
            logger.error(f"调用 /send-message API 失败: {e}")
            if e.response is not None:
                try:
                    error_info = e.response.json()
                    logger.error(f"错误信息: {error_info['error']}")
                    logger.error(f"错误详情: {error_info['details']}")
                except Exception:
                    logger.error(f"错误详情: {e.response.text}")
            else:
                logger.error("未收到任何服务器响应。")

            raise

    def reset_send_timer(self):
        """重置上次发送消息的时间戳为当前时间。"""
        self.last_send_monotonic_time = time.monotonic()
        self.last_send_system_time = time.time()

    def shutdown(self):
        """关闭 Supervisor 线程和 Steam Bot 子进程。"""
        logger.info("正在关闭 Steam Bot...")

        # 通知 Supervisor 线程停止
        if self.supervisor.is_alive():
            logger.debug("正在通知 Supervisor 线程停止...")
            self.supervisor_stop_event.set()
            self.supervisor.join()
            logger.debug("Supervisor 线程已成功退出。")
        else:
            logger.debug("Supervisor 线程已经停止。")

        # Supervisor 停止后，可以安全地关闭子进程，因为它不会再被重启
        with self.process_lock:
            proc_to_shutdown = self.process
            self.process = None  # 防止任何意外的重入

        if proc_to_shutdown is None or proc_to_shutdown.poll() is not None:
            logger.info("Steam Bot 后端没有在运行，无须关闭。")
            return

        # 请求后端登出Steam。如果失败也无所谓，因为稍后将直接关闭进程
        logger.debug(f"正在关闭 Steam Bot 后端 (PID: {proc_to_shutdown.pid})...")
        try:
            logger.debug("正在通过 API 请求后端从 Steam 登出...")
            requests.post(f"{self.base_url}/logout", headers=self.headers, timeout=(5, 10))
            logger.debug("已成功向后端发送登出请求。")
        except requests.RequestException as e:
            logger.debug(f"请求后端登出失败 (这可能是正常的，如果进程已无响应): {e}")

        # 终止 Steam Bot 进程
        self._terminate_process(proc_to_shutdown)

        logger.info("成功关闭 Steam Bot。")
