import subprocess
import time
import requests
import atexit
import os
from urllib.request import getproxies

from logger import setup_logger

GLogger = setup_logger("steam_utils")


class SteamBotClient:
    """
    一个用于管理和与 Node.js Steam Bot 后端交互的客户端。
    它负责启动、监控和关闭 server.js 子进程，并提供调用其API的方法。
    """

    def __init__(self, config):
        self.config = config
        self.process = None  # node.js 的 PID
        self.base_url = f"http://{config.steamBotHost}:{config.steamBotPort}"  # node.js 后端的地址
        self.headers = {"Authorization": f"Bearer {config.steamBotToken}"}  # 用于认证，防止未授权访问
        self.last_send_time = time.monotonic()  # 最后一次发送消息的时间戳
        # 启动后端进程
        self._launch_process()

        # 注册一个退出处理函数，以确保Python程序退出时子进程也能被关闭
        atexit.register(self.shutdown)

    def _launch_process(self):
        """构建启动命令并启动 server.js 子进程。"""
        node_executable = "node"  # 假设 'node' 在系统PATH中
        script_path = "./steam_bot/server.js"  # server.js 在steam_bot目录下
        executable_path = "./steam_bot.exe"  # 打包好的 steam_bot.exe 在当前目录下

        if os.path.exists(executable_path):
            # 优先使用打包好的后端
            command = [executable_path]
        elif os.path.exists(script_path):
            # 使用node执行不是最佳的方法，因为需要安装node.js
            command = [node_executable, script_path]
        else:
            GLogger.error(f"Steam Bot 启动失败: 未在当前目录找到 '{executable_path}' 或 '{script_path}'。")
            return

        command.extend(
            [
                f"--host={self.config.steamBotHost}",  # 监听地址
                f"--port={self.config.steamBotPort}",  # 监听端口
                f"--auth_token={self.config.steamBotToken}",  # 访问令牌
            ]
        )

        # 从代理配置项获取代理 URL
        proxy_url = self.get_http_proxy_string(self.config.steamBotProxy)
        if proxy_url:
            GLogger.info(f"Steam Bot 将使用 {proxy_url} 代理到 Steam 的连接。")
            command.append(f"--proxy={proxy_url}")
        else:
            GLogger.info("没有配置系统代理，Steam Bot 将不使用代理连接 Steam 。")
            GLogger.warning("请注意，不配置代理可能导致 Steam Bot 无法连接 Steam !")

        GLogger.info(f"正在启动 Steam Bot 后端: {' '.join(command)}")
        try:
            # CREATE_NEW_PROCESS_GROUP 会在一个新的独立进程组中运行子进程
            # 这样做可以使子进程不响应 SIGINT 信号，因为已经在主进程中实现了自动退出子进程的功能。
            self.process = subprocess.Popen(command, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
            GLogger.info(f"Steam Bot 后端已启动，进程ID: {self.process.pid}")
        except FileNotFoundError:
            GLogger.error("启动失败: 未找到 'node' 可执行文件。请确保 Node.js 已安装并配置在系统PATH中。")
        except Exception as e:
            GLogger.error(f"启动 Steam Bot 后端时发生未知错误: {e}")

        # 每 2 秒轮询 /status 接口，直到登录状态为True
        GLogger.info("等待 Steam Bot 后端完成登录")
        while True:
            time.sleep(5)
            login_status = self.get_status()["loggedIn"]
            if login_status:
                break

    def get_http_proxy_string(self, raw_proxy_config: str) -> str:
        """
        将代理配置字符串翻译为具体的代理字符串。
        目前将"system"翻译为具体的http代理字符串，其他时候直接返回原始值。

        Args:
            raw_proxy_config: 代理配置字符串
        """
        if raw_proxy_config == "system":
            # system 表示使用系统代理
            system_proxies = getproxies()["http"]
            # getproxies() 只支持环境变量或者注册表中配置的代理字符串
            if system_proxies == "":
                GLogger.warning("配置了使用系统代理，但未获取到系统代理。请注意程序不支持 PAC 模式的代理。")
                return ""
            else:
                GLogger.info(f"发现系统代理: {system_proxies}")
                return system_proxies
        else:
            # 其他值则直接作为代理字符串
            return raw_proxy_config

    def _ensure_running(self) -> bool:
        """检查子进程是否仍在运行。如果已退出，则尝试重启。"""
        if self.process is None or self.process.poll() is not None:
            GLogger.warning("检测到 Steam Bot 后端已关闭。正在尝试重启...")
            self._launch_process()
            time.sleep(10)  # 重启后等待一段时间让服务器初始化

        return self.process is not None and self.process.poll() is None

    def get_status(self) -> dict:
        """调用 /status API，获取Bot的登录状态。"""
        if not self._ensure_running():
            return {"loggedIn": False, "error": "后端未运行"}
        try:
            response = requests.get(f"{self.base_url}/status", headers=self.headers, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            GLogger.error(f"调用 /status API 失败: {e}")
            return {"loggedIn": False, "error": str(e)}

    def get_userinfo(self) -> dict:
        """调用 /userinfo API，获取Bot的用户名，SteamID，群组列表。"""
        if not self._ensure_running():
            return {"loggedIn": False, "error": "后端未运行"}
        try:
            response = requests.get(f"{self.base_url}/userinfo", headers=self.headers, timeout=5)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as e:
            GLogger.error(f"调用 /userinfo API 失败: {e}")
            return response.json()
        except requests.RequestException as e:
            GLogger.error(f"调用 /userinfo API 失败: {e}")
            return {"error": str(e)}

    def send_group_message(self, message: str) -> bool:
        """调用 /send-message API，向预设的群组和频道发送消息。"""
        self.last_send_time = time.monotonic()  # 更新最后一次发送消息的时间戳
        if not message:
            return True  # 如果消息为空，则认为发送成功

        if not self._ensure_running():
            return False

        payload = {
            "groupId": self.config.steamGroupId,
            "channelName": self.config.steamChannelName,
            "message": message,
        }

        try:
            GLogger.info(f"正在通过API向Steam群组 '{payload['groupId']}' 发送消息...")
            response = requests.post(
                f"{self.base_url}/send-message", json=payload, headers=self.headers, timeout=10
            )
            if response.status_code == 200:
                GLogger.info("消息发送成功。")
                return True
            else:
                GLogger.error(f"发送消息失败，状态码: {response.status_code}, 响应: {response.text}")
                return False
        except requests.RequestException as e:
            GLogger.error(f"调用 /send-message API 失败: {e}")
            return False

    def get_last_send_time(self) -> float:
        """返回上一次成功发送消息的时间戳 (monotonic time)。"""
        return self.last_send_time

    def reset_send_timer(self):
        """
        重置上次发送消息的时间戳到当前时间。
        这在机器人从暂停状态恢复时非常有用，可以防止健康检查立即触发。
        """
        # GLogger.info("重置健康检查计时器。")
        self.last_send_time = time.monotonic()

    def shutdown(self):
        """关闭 Steam Bot 后端。"""
        if self.process and self.process.poll() is None:
            GLogger.info("正在关闭 Steam Bot 后端...")
            try:
                # 首先尝试通过API让其退出
                requests.post(f"{self.base_url}/logout", headers=self.headers, timeout=5)
                time.sleep(3)  # 等待进程自行退出
            except requests.RequestException:
                GLogger.warning("通过API登出失败，将强制终止进程。")
            finally:
                # 无论API调用是否成功，都检查并终止进程
                if self.process.poll() is None:
                    self.process.terminate()
                    GLogger.info(f"已终止 Steam Bot 进程 (PID: {self.process.pid})。")
        self.process = None
