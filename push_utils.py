import requests

from config import Config
from logger import get_logger

logger = get_logger(__name__)


class UniPush:
    def __init__(self, config: Config, bot_name: str):
        self.config = config
        self.bot_name = bot_name

        if not self.validate_push_config(config):
            raise ValueError("推送配置内容无效，请参考日志检查配置文件")

        if config.enableWechatPush:
            logger.warning("已启用微信推送。")
            if config.enableHealthCheck:
                logger.info("当健康检查发现 Bot 状态发生变化时，将通过微信通知。")
            logger.info(
                f"当程序运行超过 {config.pushActivationDelay} 分钟后，因发生异常而退出时，将通过微信通知。"
            )

    @staticmethod
    def validate_push_config(config: Config):
        """
        验证推送配置是否合法。

        :param Config config: 配置对象
        :return bool: ``False``不合法，``True``合法
        """
        # 微信推送检查
        is_push_config_valid = True
        if config.enableWechatPush == True:
            if not config.pushplusToken:
                logger.error("已启用微信推送，但没有提供 pushplus token。")
                logger.info(
                    f"请访问 https://www.pushplus.plus/ 获取 token，并填入 {config.config_filepath} 中的 pushplusToken 。"
                )
                is_push_config_valid = False

        return is_push_config_valid

    def push_message(self, title: str, messege: str):
        """
        将消息推送到配置的消息平台的统一方法。目前只有微信推送。

        :param str title: 要发送的消息标题
        :param str messege: 要发送的消息内容
        """
        if self.config.enableWechatPush:
            self.wechat_push(
                self.config.pushplusToken,
                f"Bot: {self.bot_name} {title}",
                messege,
            )

    def wechat_push(self, token: str, title: str, msg: str):
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
        except requests.HTTPError as e:
            resp = getattr(e, "response", None)
            if resp is not None:
                try:
                    logger.error(f"pushplus: {resp.json()['msg']} ({resp.json()['data']})")
                except ValueError:
                    logger.error(f"pushplus: ({resp.status_code}) {resp.text}")
            else:
                logger.error(f"pushplus 请求失败且无响应")
        except requests.RequestException as e:
            logger.error(f"调用 pushplus API 时发生致命错误: {e}")
