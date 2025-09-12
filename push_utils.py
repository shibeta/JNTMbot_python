import requests

from logger import get_logger

GLogger = get_logger("push_utils")


def push_wechat(token: str, title: str, msg: str):
    """
    调用 pushplus 的 API 向用户的微信推送消息

    Args:
        token: pushplus API token。
            可以从 https://www.pushplus.plus 注册账号来获取
        title: 标题，在聊天窗口就能直接看到
        msg: 内容，需要点开消息才能看到
    """
    try:
        url = f"https://www.pushplus.plus/send?token={token}&title={title}&content={msg}&template=txt"
        GLogger.info(f"使用pushplus向微信发送通知 {title}: {msg}")
        r = requests.get(url=url)
        r.raise_for_status()
        GLogger.info(f"pushplus: {r.json()['msg']}")
    except requests.HTTPError:
        GLogger.error(f"pushplus: {r.json()['msg']} ({r.json()['data']})")
    except requests.RequestException as e:
        GLogger.error(f"调用 pushplus API 时发生致命错误: {e}")
