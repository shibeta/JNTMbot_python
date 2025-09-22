import requests

from logger import get_logger

logger = get_logger("push_utils")


def wechat_push(token: str, title: str, msg: str):
    """
    调用 pushplus 的 API 向用户的微信推送消息

    :param token: pushplus API token。可以从 https://www.pushplus.plus 注册账号来获取
    :param title: 标题，在聊天窗口就能直接看到
    :param msg: 内容，需要点开消息才能看到
    """
    try:
        url = f"https://www.pushplus.plus/send"
        data = {"token": token, "title": title, "content": msg, "template": "txt"}
        logger.info(f"使用pushplus向微信发送通知 {title}: {msg}")
        r = requests.post(url=url, json=data)
        r.raise_for_status()
        logger.info(f"pushplus: {r.json()['msg']}")
    except requests.HTTPError:
        logger.error(f"pushplus: {r.json()['msg']} ({r.json()['data']})")
    except requests.RequestException as e:
        logger.error(f"调用 pushplus API 时发生致命错误: {e}")
