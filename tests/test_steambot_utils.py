"""``steambot_utils`` 的单元测试。

覆盖三块内容：

- ``ProcessManager``：子进程生命周期的启动、停止与重启（``subprocess.Popen`` 全部 mock）
- ``SteamBotApiClient`` / ``Supervisor``：HTTP API 交互与健康检查（``requests`` 全部 mock）
- ``SteamBot``：命令构造、群组配置校验、消息发送、计时与关闭

注意：**不会**真正构造 ``SteamBot(config)``，因为其 ``__init__`` 会启动后台线程并无限
等待后端健康；这里统一用 ``SteamBot.__new__(SteamBot)`` 手动注入属性后再测试实例方法。
"""

from __future__ import annotations

import signal
import subprocess
import time
from unittest.mock import MagicMock, patch

import pytest
import requests

import steambot_utils
from steambot_utils import (
    ProcessManager,
    SteamBot,
    SteamBotApiClient,
    SteamBotApiError,
    Supervisor,
)

BASE_URL = "http://127.0.0.1:13091"
HEADERS = {"Authorization": "Bearer 0x4445414442454546"}


def make_response(status_code: int = 200, json_data=None, json_error: Exception | None = None, text: str = ""):
    """构造一个假的 ``requests.Response``。"""
    response = MagicMock(name="Response")
    response.status_code = status_code
    response.text = text
    if json_error is not None:
        response.json.side_effect = json_error
    else:
        response.json.return_value = {} if json_data is None else json_data
    return response


def make_api_error(status_code: int = 500, message: str = "error") -> SteamBotApiError:
    return SteamBotApiError(message, make_response(status_code))


# ---------------------------------------------------------------------------
# ProcessManager
# ---------------------------------------------------------------------------


class TestProcessManager:
    """子进程管理器。"""

    @pytest.fixture
    def manager(self) -> ProcessManager:
        return ProcessManager(["node", "server.js"])

    def test_is_running_false_without_process(self, manager: ProcessManager):
        assert manager.is_running() is False

    def test_is_running_true_while_poll_returns_none(self, manager: ProcessManager):
        process = MagicMock(name="Popen")
        process.poll.return_value = None
        manager.process = process

        assert manager.is_running() is True

    def test_is_running_false_after_process_exited(self, manager: ProcessManager):
        process = MagicMock(name="Popen")
        process.poll.return_value = 0
        manager.process = process

        assert manager.is_running() is False

    def test_start_skips_when_already_running(self, manager: ProcessManager):
        manager.process = MagicMock(name="Popen")
        manager.process.poll.return_value = None

        with patch("steambot_utils.subprocess.Popen") as popen:
            manager.start()

        popen.assert_not_called()

    def test_start_spawns_process(self, manager: ProcessManager):
        fake_process = MagicMock(name="Popen")
        fake_process.pid = 4321

        with patch("steambot_utils.subprocess.Popen", return_value=fake_process) as popen:
            manager.start()

        popen.assert_called_once_with(
            ["node", "server.js"],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        assert manager.process is fake_process

    def test_start_handles_missing_executable(self, manager: ProcessManager):
        with patch("steambot_utils.subprocess.Popen", side_effect=FileNotFoundError("node 不存在")):
            manager.start()  # 不应抛出异常

        assert manager.process is None

    def test_start_handles_unknown_error(self, manager: ProcessManager):
        with patch("steambot_utils.subprocess.Popen", side_effect=OSError("无法启动")):
            manager.start()

        assert manager.process is None

    def test_stop_without_process_does_nothing(self, manager: ProcessManager):
        manager.stop()

        assert manager.process is None

    def test_stop_terminates_process(self, manager: ProcessManager):
        process = MagicMock(name="Popen")
        process.poll.return_value = None
        process.wait.return_value = 0
        manager.process = process

        manager.stop()

        process.send_signal.assert_called_once_with(signal.SIGTERM)
        process.wait.assert_called_once_with(timeout=2)
        process.kill.assert_not_called()
        assert manager.process is None

    def test_stop_kills_process_when_wait_fails(self, manager: ProcessManager):
        process = MagicMock(name="Popen")
        process.poll.return_value = None
        process.wait.side_effect = TimeoutError("等待超时")
        manager.process = process

        manager.stop()

        process.kill.assert_called_once_with()
        assert manager.process is None

    def test_stop_kills_process_when_wait_returns_non_int(self, manager: ProcessManager):
        process = MagicMock(name="Popen")
        process.poll.return_value = None
        process.wait.return_value = None  # 非 int → 触发 TimeoutError 分支
        manager.process = process

        manager.stop()

        process.kill.assert_called_once_with()
        assert manager.process is None

    def test_restart_stops_then_starts(self, manager: ProcessManager):
        with (
            patch.object(manager, "stop") as stop,
            patch.object(manager, "start") as start,
        ):
            manager.restart()

        stop.assert_called_once_with()
        start.assert_called_once_with()


# ---------------------------------------------------------------------------
# SteamBotApiClient
# ---------------------------------------------------------------------------


class TestSteamBotApiClientBasics:
    """API 客户端的基础请求方法。"""

    @pytest.fixture
    def client(self) -> SteamBotApiClient:
        return SteamBotApiClient(BASE_URL, HEADERS)

    def test_is_healthy_true_on_200(self, client: SteamBotApiClient):
        response = make_response(200)

        with patch("steambot_utils.requests.get", return_value=response) as get:
            assert client.is_healthy() is True

        get.assert_called_once_with(f"{BASE_URL}/health", headers=HEADERS, timeout=5)

    def test_is_healthy_false_on_error_status(self, client: SteamBotApiClient):
        with patch("steambot_utils.requests.get", return_value=make_response(503)):
            assert client.is_healthy() is False

    def test_is_healthy_false_on_exception(self, client: SteamBotApiClient):
        with patch("steambot_utils.requests.get", side_effect=requests.ConnectionError("拒绝连接")):
            assert client.is_healthy() is False

    def test_get_login_status_logged_in(self, client: SteamBotApiClient):
        response = make_response(200, json_data={"name": "bot-user"})

        with patch.object(client, "get", return_value=response) as get:
            assert client.get_login_status() == {"loggedIn": True, "name": "bot-user"}

        get.assert_called_once_with(f"{BASE_URL}/status", headers=HEADERS, timeout=(5, 20))

    def test_get_login_status_missing_name(self, client: SteamBotApiClient):
        with patch.object(client, "get", return_value=make_response(200, json_data={})):
            assert client.get_login_status() == {"loggedIn": True, "name": ""}

    def test_get_login_status_not_logged_in_on_non_200(self, client: SteamBotApiClient):
        with patch.object(client, "get", return_value=make_response(204)):
            assert client.get_login_status() == {"loggedIn": False, "name": ""}

    def test_get_login_status_not_logged_in_on_401(self, client: SteamBotApiClient):
        with patch.object(client, "get", side_effect=make_api_error(401, "未登录")):
            assert client.get_login_status() == {"loggedIn": False, "name": ""}

    def test_get_login_status_reraises_other_errors(self, client: SteamBotApiClient):
        with (
            patch.object(client, "get", side_effect=make_api_error(500, "后端错误")),
            pytest.raises(SteamBotApiError) as excinfo,
        ):
            client.get_login_status()

        assert excinfo.value.status_code == 500

    def test_login_posts_to_login_endpoint(self, client: SteamBotApiClient):
        with patch.object(client, "post", return_value=make_response(200)) as post:
            client.login()

        post.assert_called_once_with(f"{BASE_URL}/login", headers=HEADERS, timeout=(5, 20))

    def test_get_userinfo_returns_json(self, client: SteamBotApiClient):
        payload = {"name": "bot", "steamID": "1", "groups": []}
        response = make_response(200, json_data=payload)

        with patch.object(client, "get_with_auth", return_value=response) as get:
            assert client.get_userinfo() == payload

        get.assert_called_once_with(f"{BASE_URL}/userinfo", headers=HEADERS, timeout=(5, 20))

    def test_send_group_message_payload(self, client: SteamBotApiClient):
        with patch.object(client, "post_with_auth", return_value=make_response(200)) as post:
            client.send_group_message("group-1", "channel-2", "你好")

        post.assert_called_once_with(
            f"{BASE_URL}/send-message",
            json={"groupId": "group-1", "channelId": "channel-2", "message": "你好"},
            headers=HEADERS,
            timeout=(5, 20),
        )

    def test_logout_uses_shorter_timeout(self, client: SteamBotApiClient):
        with patch.object(client, "post_with_auth", return_value=make_response(200)) as post:
            client.logout()

        post.assert_called_once_with(f"{BASE_URL}/logout", headers=HEADERS, timeout=(5, 10))

    def test_get_group_channels_returns_channel_list(self, client: SteamBotApiClient):
        channels = [{"name": "综合", "id": "c1", "isVoiceChannel": False}]
        response = make_response(200, json_data={"channels": channels})

        with patch.object(client, "get_with_auth", return_value=response) as get:
            assert client.get_group_channels("group-1") == channels

        get.assert_called_once_with(
            f"{BASE_URL}/group-channels",
            params={"groupId": "group-1"},
            headers=HEADERS,
            timeout=(5, 20),
        )

    def test_get_group_channels_defaults_to_empty_list(self, client: SteamBotApiClient):
        with patch.object(client, "get_with_auth", return_value=make_response(200, json_data={})):
            assert client.get_group_channels("group-1") == []


class TestMakeRequest:
    """``_make_request`` 的错误信息构造。"""

    def test_success_returns_response(self):
        response = make_response(200)

        result = SteamBotApiClient._make_request(MagicMock(return_value=response))

        assert result is response
        response.raise_for_status.assert_called_once_with()

    def test_http_error_with_json_body(self):
        response = make_response(500, json_data={"error": "E123", "details": "数据库炸了"})
        error = requests.HTTPError("500", response=response)

        with pytest.raises(SteamBotApiError) as excinfo:
            SteamBotApiClient._make_request(MagicMock(side_effect=error))

        assert excinfo.value.status_code == 500
        assert excinfo.value.response is response
        assert "500" in str(excinfo.value)
        assert "E123" in str(excinfo.value)
        assert "数据库炸了" in str(excinfo.value)

    def test_http_error_with_json_body_missing_fields(self):
        response = make_response(400, json_data={})
        error = requests.HTTPError("400", response=response)

        with pytest.raises(SteamBotApiError) as excinfo:
            SteamBotApiClient._make_request(MagicMock(side_effect=error))

        assert "Unknown Error" in str(excinfo.value)

    def test_http_error_with_long_non_json_body_is_truncated(self):
        response = make_response(502, json_error=ValueError("不是 JSON"), text="x" * 300)
        error = requests.HTTPError("502", response=response)

        with pytest.raises(SteamBotApiError) as excinfo:
            SteamBotApiClient._make_request(MagicMock(side_effect=error))

        assert "已截断" in str(excinfo.value)

    def test_http_error_with_short_non_json_body(self):
        response = make_response(502, json_error=ValueError("不是 JSON"), text="Bad Gateway")
        error = requests.HTTPError("502", response=response)

        with pytest.raises(SteamBotApiError) as excinfo:
            SteamBotApiClient._make_request(MagicMock(side_effect=error))

        assert "非JSON响应" in str(excinfo.value)
        assert "Bad Gateway" in str(excinfo.value)

    def test_error_without_response(self):
        error = requests.ConnectionError("连接被拒绝")
        error.response = None

        with pytest.raises(SteamBotApiError) as excinfo:
            SteamBotApiClient._make_request(MagicMock(side_effect=error))

        assert excinfo.value.status_code is None
        assert excinfo.value.response is None
        assert "请求发生错误" in str(excinfo.value)


class TestMakeAuthenticatedRequest:
    """401 时自动重新登录并重试一次。"""

    @pytest.fixture
    def client(self) -> SteamBotApiClient:
        return SteamBotApiClient(BASE_URL, HEADERS)

    def test_relogin_then_retry_succeeds(self, client: SteamBotApiClient):
        success = make_response(200)
        client.login = MagicMock()

        with patch.object(
            client,
            "_make_request",
            side_effect=[make_api_error(401, "未登录"), success],
        ) as make_request:
            result = client.get_with_auth(f"{BASE_URL}/userinfo")

        assert result is success
        client.login.assert_called_once_with()
        assert make_request.call_count == 2

    def test_relogin_failure_raises_original_error(self, client: SteamBotApiClient):
        client.login = MagicMock(side_effect=make_api_error(500, "登录失败"))

        with (
            patch.object(client, "_make_request", side_effect=make_api_error(401, "未登录")),
            pytest.raises(SteamBotApiError) as excinfo,
        ):
            client.post_with_auth(f"{BASE_URL}/send-message")

        assert excinfo.value.status_code == 401

    def test_retry_failure_raises_new_error(self, client: SteamBotApiClient):
        client.login = MagicMock()

        with (
            patch.object(
                client,
                "_make_request",
                side_effect=[make_api_error(401, "未登录"), make_api_error(503, "服务不可用")],
            ),
            pytest.raises(SteamBotApiError) as excinfo,
        ):
            client.get_with_auth(f"{BASE_URL}/userinfo")

        assert excinfo.value.status_code == 503

    def test_non_401_error_is_reraised_without_login(self, client: SteamBotApiClient):
        client.login = MagicMock()

        with (
            patch.object(client, "_make_request", side_effect=make_api_error(500, "后端错误")),
            pytest.raises(SteamBotApiError) as excinfo,
        ):
            client.get_with_auth(f"{BASE_URL}/userinfo")

        assert excinfo.value.status_code == 500
        client.login.assert_not_called()


# ---------------------------------------------------------------------------
# Supervisor
# ---------------------------------------------------------------------------


class TestSupervisor:
    """后端守护线程。"""

    @pytest.fixture
    def supervisor(self) -> Supervisor:
        return Supervisor(MagicMock(name="process_manager"), MagicMock(name="api_client"), check_interval=30)

    def _stop_after_first_wait(self, supervisor: Supervisor) -> None:
        """让 ``stop_event.wait`` 在第一次调用时立即置位，从而只跑一轮循环。"""
        supervisor.stop_event.wait = MagicMock(side_effect=lambda *args, **kwargs: supervisor.stop_event.set())

    def test_is_first_check_initially_true(self, supervisor: Supervisor):
        assert supervisor.is_first_check is True
        assert supervisor.stop_event.is_set() is False

    def test_wait_for_health_returns_true_when_healthy(self, supervisor: Supervisor):
        supervisor.api_client.is_healthy.return_value = True

        assert supervisor._wait_for_health(timeout=30) is True

    def test_wait_for_health_times_out(self, supervisor: Supervisor):
        supervisor.api_client.is_healthy.return_value = False

        assert supervisor._wait_for_health(timeout=10) is False

    def test_wait_for_health_aborts_when_stopped(self, supervisor: Supervisor):
        supervisor.api_client.is_healthy.return_value = False
        supervisor.stop_event.set()

        assert supervisor._wait_for_health(timeout=30) is False

    def test_run_restarts_unhealthy_backend(self, supervisor: Supervisor):
        supervisor.process_manager.is_running.return_value = True
        supervisor.api_client.is_healthy.return_value = False
        supervisor._wait_for_health = MagicMock(return_value=True)
        self._stop_after_first_wait(supervisor)

        supervisor.run()

        supervisor.process_manager.restart.assert_called_once_with()
        assert supervisor.initial_health_event.is_set()
        assert supervisor.is_first_check is False

    def test_run_does_not_restart_healthy_backend(self, supervisor: Supervisor):
        supervisor.process_manager.is_running.return_value = True
        supervisor.api_client.is_healthy.return_value = True
        self._stop_after_first_wait(supervisor)

        supervisor.run()

        supervisor.process_manager.restart.assert_not_called()
        assert supervisor.initial_health_event.is_set() is False

    def test_run_skips_health_check_when_process_missing(self, supervisor: Supervisor):
        supervisor.process_manager.is_running.return_value = False
        supervisor._wait_for_health = MagicMock(return_value=False)
        self._stop_after_first_wait(supervisor)

        supervisor.run()

        supervisor.api_client.is_healthy.assert_not_called()
        supervisor.process_manager.restart.assert_called_once_with()
        assert supervisor.initial_health_event.is_set() is False

    def test_stop_sets_event_and_joins(self, supervisor: Supervisor):
        with patch.object(supervisor, "join") as join:
            supervisor.stop()

        assert supervisor.stop_event.is_set() is True
        join.assert_called_once_with(2.0)


# ---------------------------------------------------------------------------
# SteamBot
# ---------------------------------------------------------------------------


@pytest.fixture
def bot(config) -> SteamBot:
    """一个未执行 ``__init__``、依赖全部注入为 mock 的 SteamBot。

    这样既能测试实例方法，又不会启动真实线程或等待后端健康检查。
    """
    instance = SteamBot.__new__(SteamBot)
    instance.config = config
    instance.api_client = MagicMock(name="api_client")
    instance.process_manager = MagicMock(name="process_manager")
    instance.supervisor = MagicMock(name="supervisor")
    instance.last_send_monotonic_time = 0.0
    instance.last_send_system_time = 0.0
    return instance


class TestSteamBotBuildCommand:
    """``_build_command`` 的可执行文件选择与代理参数。"""

    def _prepare(self, bot: SteamBot, monkeypatch, tmp_path, executable_exists: bool, script_exists: bool):
        executable = tmp_path / "steam_bot.exe"
        script = tmp_path / "server.js"
        if executable_exists:
            executable.touch()
        if script_exists:
            script.touch()
        monkeypatch.setattr(steambot_utils, "STEAM_BOT_EXECUTABLE_PATH", executable)
        monkeypatch.setattr(steambot_utils, "STEAM_BOT_SCRIPT_PATH", script)
        return executable, script

    def test_prefers_packaged_executable(self, bot: SteamBot, monkeypatch, tmp_path):
        executable, _ = self._prepare(bot, monkeypatch, tmp_path, executable_exists=True, script_exists=True)
        bot.config.steamBotProxy = ""

        command = bot._build_command()

        assert command[0] == str(executable)

    def test_falls_back_to_node_script(self, bot: SteamBot, monkeypatch, tmp_path):
        _, script = self._prepare(bot, monkeypatch, tmp_path, executable_exists=False, script_exists=True)
        bot.config.steamBotProxy = ""

        command = bot._build_command()

        assert command[:2] == ["node", str(script)]

    def test_raises_when_nothing_found(self, bot: SteamBot, monkeypatch, tmp_path):
        self._prepare(bot, monkeypatch, tmp_path, executable_exists=False, script_exists=False)

        with pytest.raises(FileNotFoundError):
            bot._build_command()

    def test_includes_connection_arguments(self, bot: SteamBot, monkeypatch, tmp_path):
        executable, _ = self._prepare(bot, monkeypatch, tmp_path, executable_exists=True, script_exists=True)
        bot.config.steamBotProxy = ""
        bot.config.steamBotHost = "0.0.0.0"
        bot.config.steamBotPort = 9999
        bot.config.steamBotToken = "secret"

        command = bot._build_command()

        assert command == [
            str(executable),
            "--host=0.0.0.0",
            "--port=9999",
            "--auth_token=secret",
        ]

    def test_system_proxy_is_resolved(self, bot: SteamBot, monkeypatch, tmp_path):
        self._prepare(bot, monkeypatch, tmp_path, executable_exists=True, script_exists=True)
        bot.config.steamBotProxy = "system"

        with patch("steambot_utils.get_system_proxy", return_value="http://127.0.0.1:8080"):
            command = bot._build_command()

        assert "--proxy=http://127.0.0.1:8080" in command

    def test_system_proxy_missing_is_ignored(self, bot: SteamBot, monkeypatch, tmp_path):
        self._prepare(bot, monkeypatch, tmp_path, executable_exists=True, script_exists=True)
        bot.config.steamBotProxy = "system"

        with patch("steambot_utils.get_system_proxy", return_value=None):
            command = bot._build_command()

        assert not any(arg.startswith("--proxy=") for arg in command)

    def test_custom_proxy_is_passed_through(self, bot: SteamBot, monkeypatch, tmp_path):
        self._prepare(bot, monkeypatch, tmp_path, executable_exists=True, script_exists=True)
        bot.config.steamBotProxy = "socks5h://127.0.0.1:1080"

        command = bot._build_command()

        assert "--proxy=socks5h://127.0.0.1:1080" in command

    def test_empty_proxy_adds_nothing(self, bot: SteamBot, monkeypatch, tmp_path):
        self._prepare(bot, monkeypatch, tmp_path, executable_exists=True, script_exists=True)
        bot.config.steamBotProxy = ""

        command = bot._build_command()

        assert not any(arg.startswith("--proxy=") for arg in command)


class TestSteamBotVerifyGroupConfig:
    """群组 / 频道配置校验。"""

    @pytest.fixture
    def userinfo(self) -> dict:
        return {
            "name": "bot",
            "steamID": "7656119",
            "groups": [{"name": "蠢人帮", "id": "g1"}],
        }

    def _set_ids(self, bot: SteamBot) -> None:
        bot.config.steamGroupId = "g1"
        bot.config.steamChannelId = "c1"

    def test_valid_group_and_channel(self, bot: SteamBot, userinfo: dict):
        self._set_ids(bot)
        bot.get_group_channels = MagicMock(return_value=[{"name": "综合", "id": "c1", "isVoiceChannel": False}])

        bot.verify_group_config(userinfo)

        bot.get_group_channels.assert_called_once_with("g1")

    def test_group_not_found_raises(self, bot: SteamBot, userinfo: dict):
        bot.config.steamGroupId = "不存在"
        bot.config.steamChannelId = "c1"

        with pytest.raises(ValueError, match="Steam 群组 ID"):
            bot.verify_group_config(userinfo)

    def test_channel_not_found_raises(self, bot: SteamBot, userinfo: dict):
        self._set_ids(bot)
        bot.get_group_channels = MagicMock(return_value=[{"name": "闲聊", "id": "c9", "isVoiceChannel": True}])

        with pytest.raises(ValueError, match="Steam 群组频道 ID"):
            bot.verify_group_config(userinfo)

    def test_invalid_userinfo_without_groups_raises(self, bot: SteamBot):
        with pytest.raises(TypeError):
            bot.verify_group_config({"name": "bot"})

    def test_fetches_userinfo_when_not_provided(self, bot: SteamBot, userinfo: dict):
        self._set_ids(bot)
        bot.get_userinfo = MagicMock(return_value=userinfo)
        bot.get_group_channels = MagicMock(return_value=[{"name": "综合", "id": "c1", "isVoiceChannel": False}])

        bot.verify_group_config()

        bot.get_userinfo.assert_called_once_with()

    def test_wraps_userinfo_fetch_failure(self, bot: SteamBot):
        bot.get_userinfo = MagicMock(side_effect=RuntimeError("网络挂了"))

        with pytest.raises(Exception, match="获取 Steam 用户信息失败"):
            bot.verify_group_config()

    def test_wraps_channel_fetch_failure(self, bot: SteamBot, userinfo: dict):
        self._set_ids(bot)
        bot.get_group_channels = MagicMock(side_effect=RuntimeError("网络挂了"))

        with pytest.raises(Exception, match="获取群组频道列表失败"):
            bot.verify_group_config(userinfo)


class TestSteamBotMessaging:
    """消息发送、用户信息与关闭流程。"""

    def test_send_empty_message_resets_timer_only(self, bot: SteamBot):
        bot.reset_send_timer = MagicMock()

        bot.send_group_message("")

        bot.reset_send_timer.assert_called_once_with()
        bot.api_client.send_group_message.assert_not_called()

    def test_send_message_success(self, bot: SteamBot):
        bot.config.steamGroupId = "g1"
        bot.config.steamChannelId = "c1"
        bot.reset_send_timer = MagicMock()

        bot.send_group_message("你好")

        bot.api_client.send_group_message.assert_called_once_with("g1", "c1", "你好")
        bot.reset_send_timer.assert_called_once_with()

    def test_send_message_failure_propagates(self, bot: SteamBot):
        bot.api_client.send_group_message.side_effect = RuntimeError("请求失败")

        with pytest.raises(RuntimeError, match="请求失败"):
            bot.send_group_message("你好")

    def test_get_userinfo_delegates(self, bot: SteamBot):
        bot.api_client.get_userinfo.return_value = {"name": "bot"}

        assert bot.get_userinfo() == {"name": "bot"}

    def test_get_userinfo_wraps_error(self, bot: SteamBot):
        bot.api_client.get_userinfo.side_effect = RuntimeError("请求失败")

        with pytest.raises(Exception, match="获取用户信息时发生异常"):
            bot.get_userinfo()

    def test_get_group_channels_delegates(self, bot: SteamBot):
        bot.api_client.get_group_channels.return_value = [{"id": "c1"}]

        assert bot.get_group_channels("g1") == [{"id": "c1"}]

    def test_get_group_channels_wraps_error(self, bot: SteamBot):
        bot.api_client.get_group_channels.side_effect = RuntimeError("请求失败")

        with pytest.raises(Exception, match="中的频道列表时发生异常"):
            bot.get_group_channels("g1")

    def test_login_delegates(self, bot: SteamBot):
        bot.login()

        bot.api_client.login.assert_called_once_with()

    def test_get_login_status_returns_api_result(self, bot: SteamBot):
        bot.api_client.get_login_status.return_value = {"loggedIn": True, "name": "bot"}

        assert bot.get_login_status() == {"loggedIn": True, "name": "bot"}

    def test_get_login_status_never_raises(self, bot: SteamBot):
        bot.api_client.get_login_status.side_effect = SteamBotApiError("后端错误", make_response(500))

        assert bot.get_login_status() == {"loggedIn": False, "name": ""}

    def test_get_last_send_times(self, bot: SteamBot):
        bot.last_send_monotonic_time = 12.5
        bot.last_send_system_time = 34.5

        assert bot.get_last_send_monotonic_time() == 12.5
        assert bot.get_last_send_system_time() == 34.5

    def test_reset_send_timer_updates_both_timestamps(self, bot: SteamBot):
        before_wall = time.time()

        bot.reset_send_timer()

        assert bot.last_send_monotonic_time > 0
        assert bot.last_send_system_time >= before_wall

    def test_shutdown_stops_all_components(self, bot: SteamBot):
        bot.shutdown()

        bot.supervisor.stop.assert_called_once_with()
        bot.api_client.logout.assert_called_once_with()
        bot.process_manager.stop.assert_called_once_with()

    def test_shutdown_swallows_logout_error(self, bot: SteamBot):
        bot.api_client.logout.side_effect = RuntimeError("登出失败")

        bot.shutdown()  # 不应抛出异常

        bot.supervisor.stop.assert_called_once_with()
        bot.process_manager.stop.assert_called_once_with()
