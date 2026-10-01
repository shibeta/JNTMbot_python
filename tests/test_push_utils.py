"""``push_utils`` 的单元测试。

``UniPush`` 会把消息推送到 pushplus 的 HTTP API，因此所有网络调用都必须被 mock。
这里统一用 ``MagicMock`` 构造假响应，既不联网，也不依赖 ``responses`` 之类的第三方库。
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
import requests

from push_utils import UniPush

PUSHPLUS_URL = "https://www.pushplus.plus/send"


def make_response(status_code: int = 200, json_data=None, json_error: Exception | None = None, text: str = ""):
    """构造一个假的 ``requests.Response``。

    :param json_error: 传入异常时，``response.json()`` 会抛出该异常（模拟非 JSON 响应）
    """
    response = MagicMock(name="Response")
    response.status_code = status_code
    response.text = text
    if json_error is not None:
        response.json.side_effect = json_error
    else:
        response.json.return_value = {"msg": "ok", "data": None} if json_data is None else json_data
    return response


def make_http_error(status_code: int = 500, response=None) -> requests.HTTPError:
    return requests.HTTPError(f"HTTP {status_code}", response=response)


@pytest.fixture
def wechat_config(config):
    config.enableWechatPush = True
    config.pushplusToken = "test-token"
    return config


class TestUniPushInit:
    """构造与配置校验。"""

    def test_disabled_push_is_valid(self, config):
        config.enableWechatPush = False
        config.pushplusToken = ""

        push = UniPush(config, "德瑞Bot")

        assert push.bot_name == "德瑞Bot"
        assert push.config is config

    def test_enabled_push_without_token_raises(self, config):
        config.enableWechatPush = True
        config.pushplusToken = ""

        with pytest.raises(ValueError, match="推送配置内容无效"):
            UniPush(config, "德瑞Bot")

    def test_enabled_push_with_token_is_valid(self, wechat_config):
        push = UniPush(wechat_config, "德瑞Bot")

        assert push.config is wechat_config

    def test_validate_push_config_disabled_ignores_missing_token(self, config):
        config.enableWechatPush = False
        config.pushplusToken = ""

        assert UniPush.validate_push_config(config) is True

    def test_validate_push_config_enabled_without_token(self, config):
        config.enableWechatPush = True
        config.pushplusToken = ""

        assert UniPush.validate_push_config(config) is False

    def test_validate_push_config_enabled_with_token(self, wechat_config):
        assert UniPush.validate_push_config(wechat_config) is True


class TestPushMessage:
    """``push_message`` 的路由逻辑。"""

    def test_disabled_does_not_send_anything(self, config):
        config.enableWechatPush = False
        push = UniPush(config, "德瑞Bot")

        with patch.object(UniPush, "wechat_push") as wechat_push:
            push.push_message("标题", "正文")

        wechat_push.assert_not_called()

    def test_enabled_forwards_to_wechat_push_with_prefixed_title(self, wechat_config):
        push = UniPush(wechat_config, "德瑞Bot")

        with patch.object(UniPush, "wechat_push") as wechat_push:
            push.push_message("恶意值过高", "程序将退出")

        wechat_push.assert_called_once_with("test-token", "Bot: 德瑞Bot 恶意值过高", "程序将退出")


class TestWechatPush:
    """``wechat_push`` 的请求内容与异常降级。"""

    def test_successful_push(self, wechat_config):
        push = UniPush(wechat_config, "德瑞Bot")
        response = make_response(200)

        with patch("push_utils.requests.post", return_value=response) as post:
            push.wechat_push("test-token", "标题", "正文")

        post.assert_called_once_with(
            url=PUSHPLUS_URL,
            json={"token": "test-token", "title": "标题", "content": "正文", "template": "txt"},
            timeout=(5, 20),
        )
        response.raise_for_status.assert_called_once_with()

    def test_http_error_with_json_body_is_swallowed(self, wechat_config, caplog):
        push = UniPush(wechat_config, "德瑞Bot")
        response = make_response(500, json_data={"msg": "内部错误", "data": "trace-id"})

        with (
            patch("push_utils.requests.post", side_effect=make_http_error(500, response)),
            caplog.at_level(logging.ERROR, logger="push_utils"),
        ):
            push.wechat_push("test-token", "标题", "正文")  # 不应抛出异常

        assert response.json.call_count >= 1
        assert any("内部错误" in record.getMessage() for record in caplog.records)

    def test_http_error_without_response(self, wechat_config, caplog):
        push = UniPush(wechat_config, "德瑞Bot")
        error = requests.HTTPError("HTTP 500")
        error.response = None

        with (
            patch("push_utils.requests.post", side_effect=error),
            caplog.at_level(logging.ERROR, logger="push_utils"),
        ):
            push.wechat_push("test-token", "标题", "正文")

        assert any("无响应" in record.getMessage() for record in caplog.records)

    def test_http_error_with_non_json_body_uses_text(self, wechat_config, caplog):
        push = UniPush(wechat_config, "德瑞Bot")
        response = make_response(status_code=502, json_error=ValueError("不是 JSON"), text="Bad Gateway")

        with (
            patch("push_utils.requests.post", side_effect=make_http_error(502, response)),
            caplog.at_level(logging.ERROR, logger="push_utils"),
        ):
            push.wechat_push("test-token", "标题", "正文")

        messages = [record.getMessage() for record in caplog.records]
        assert any("502" in message and "Bad Gateway" in message for message in messages)

    def test_request_exception_is_swallowed(self, wechat_config, caplog):
        push = UniPush(wechat_config, "德瑞Bot")

        with (
            patch("push_utils.requests.post", side_effect=requests.Timeout("连接超时")),
            caplog.at_level(logging.ERROR, logger="push_utils"),
        ):
            push.wechat_push("test-token", "标题", "正文")  # 不应抛出异常

        assert any("致命错误" in record.getMessage() for record in caplog.records)
