import os
from pathlib import Path
from typing import Any, Dict, TYPE_CHECKING
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from logger import get_logger

logger = get_logger(__name__)


class Config:
    """
    一个用于加载和管理YAML配置文件的类，并支持注释的读写。

    此类在初始化时会读取一个YAML文件。如果文件不存在，或者文件缺少某些配置项，
    它会使用内部定义的默认值来补充，然后将一个带有注释的完整配置文件写回磁盘。
    """

    # _defaults 字典定义了所有配置项的默认值和注释。
    # 结构: { "配置项名称": {"value": 默认值, "comment": "注释"} }
    _defaults: Dict[str, Dict[str, Any]] = {
        "debug": {"value": False, "comment": "开启调试模式，日志输出将非常详细"},
        "steamBotHost": {"value": "127.0.0.1", "comment": "Steam Bot后端的监听地址"},
        "steamBotPort": {"value": 13091, "comment": "Steam Bot后端的监听端口"},
        "steamBotToken": {"value": "0x4445414442454546", "comment": "访问Steam Bot后端的认证Token"},
        "steamBotProxy": {
            "value": "system",
            "comment": 'Steam Bot使用的代理，格式为"http://127.0.0.1:8080"或"socks5://127.0.0.1:1080"。"system"表示使用系统代理，留空则不使用代理',
        },
        "steamGroupId": {"value": "37660928", "comment": "要发送消息的Steam群组ID，程序启动时可以读取到"},
        "steamChannelName": {"value": "BOT候车室", "comment": "要发送消息的Steam群组频道名称"},
        "useAlterMessagingMethod": {
            "value": False,
            "comment": "是否改用备用方法发送Steam群组消息，该方法通过与Steam客户端GUI交互以发送消息",
        },
        "AlterMessagingMethodWindowTitle": {
            "value": "蠢人帮",
            "comment": "用备用方法发送群组消息时，群聊窗口标题关键字，支持正则",
        },
        "enableHealthCheck": {
            "value": True,
            "comment": "启用健康检查，每间隔一段时间检查Bot上次向Steam发送信息的时间",
        },
        "healthCheckInterval": {
            "value": 10,
            "comment": "健康检查的频率，即两次健康检查之间等待的时间 (分钟)",
        },
        "healthCheckSteamChatTimeoutThreshold": {
            "value": 60,
            "comment": "基于Steam消息的健康检查判断阈值，如果发现Bot一段时间内未向Steam发送过信息，则认为Bot不可用 (分钟)",
        },
        "enableExitOnUnhealthy": {"value": False, "comment": "健康检查发现Bot不可用时，是否退出程序"},
        "enableWechatPush": {
            "value": False,
            "comment": "是否启用微信推送bot状态信息。启用后，当程序运行一段时间后发生报错退出，或健康状态发生变化时，会向微信推送错误信息",
        },
        "pushplusToken": {"value": "", "comment": "pushplus的API token，用于微信通知"},
        "pushActivationDelay": {
            "value": 5,
            "comment": "推送报错退出的启用延迟。为节省API用量，只有程序运行时长超过该时间后，报错退出时才会发起推送 (分钟)",
        },
        "mainLoopConsecutiveErrorThreshold": {
            "value": 10,
            "comment": "主循环连续报错的阈值，连续报错超过该次数将报错退出。设置为<=1则报错一次即退出",
        },
        "restartGTAConsecutiveFailThreshold": {
            "value": 5,
            "comment": "初始化GTA时重启GTA失败的阈值，连续重启失败超过该次数将抛出异常。设置为<=1则重启失败立即抛出异常",
        },
        "suspendGTATime": {"value": 13, "comment": "卡单持续时间 (秒)"},
        "delaySuspendTime": {
            "value": 5,
            "comment": "卡单延迟时间 (秒)",
        },
        "autoReduceBadSportOnDodgyPlayer": {"value": True, "comment": "当bot变成问题玩家后是否自动挂机清除恶意值。设置为False后变成问题玩家会退出程序。"},
        "manualMoveToPoint": {
            "value": False,
            "comment": "禁用在事务所内起床后自动移动到任务触发点，改为要求用户手动将角色移动到任务触发点",
        },
        "startOnAllJoined": {
            "value": True,
            "comment": '全部玩家已加入时立即开始差事而不等待 (绕过 "startMatchDelay" 时间)',
        },
        "walkToPillarTime": {"value": 1500, "comment": '生活层进行"走到床头柱子前卡住"动作的持续时间 (毫秒)'},
        "walkToBedroomEntranceTime": {
            "value": 5500,
            "comment": '生活层进行"走到个人空间门口"动作的持续时间 (毫秒)',
        },
        "exitBedroomDoorBackTime": {
            "value": 1500,
            "comment": '生活层进行"走出个人空间的门"动作时，向右后方移动的持续时间 (毫秒)',
        },
        "exitBedroomDoorForwardTime": {
            "value": 1000,
            "comment": '生活层进行"走出个人空间的门"动作时，向右前方移动的持续时间 (毫秒)',
        },
        "walkToStairwellTime": {
            "value": 700,
            "comment": '生活层进行"走到楼梯门口"动作的持续时间 (毫秒)',
        },
        "enterStairwellTime": {
            "value": 2300,
            "comment": '生活层进行"走进楼梯门"动作的持续时间 (毫秒)',
        },
        "goDownFirstStairFlightTime": {
            "value": 4000,
            "comment": '楼梯间进行"走前半截楼梯"动作的持续时间 (毫秒)',
        },
        "crossStairLandingTime": {
            "value": 1500,
            "comment": '楼梯间进行"穿过楼梯中间的平台"动作的持续时间 (毫秒)',
        },
        "goDownSecondStairFlightTime": {
            "value": 4500,
            "comment": '楼梯间进行"走后半截楼梯"动作的持续时间 (毫秒)',
        },
        "exitStairwellTime": {
            "value": 1000,
            "comment": '差事层进行"走出楼梯间"动作的持续时间 (毫秒)',
        },
        "crossAisleTime": {"value": 4200, "comment": '差事层进行"穿过走廊"动作的持续时间 (毫秒)'},
        "moveTimeFindJob": {
            "value": 350,
            "comment": '差事层进行"寻找差事黄圈"动作时 每次移动的持续时间 (毫秒)',
        },
        "lobbyCheckLoopTime": {"value": 1, "comment": "差事面板玩家加入状态检测间隔时间 (秒)"},
        "matchPanelTimeout": {"value": 180, "comment": "面板无人加入时重开时间 (秒)"},
        "playerJoiningTimeout": {"value": 120, "comment": "等待正在加入玩家超时重开时间 (秒)"},
        "startMatchDelay": {"value": 15, "comment": "开始差事等待延迟 (秒)"},
        "exitMatchTimeout": {"value": 120, "comment": "等待差事启动落地超时时间 (秒)(防止卡在启动战局中)"},
        "ocrArgs": {
            "value": r'--models=".\models" --det=ch_PP-OCRv4_det_infer.onnx --cls=ch_ppocr_mobile_v2.0_cls_infer.onnx --rec=rec_ch_PP-OCRv4_infer.onnx --keys=dict_chinese.txt --padding=70 --maxSideLen=1024 --boxScoreThresh=0.5 --boxThresh=0.3 --unClipRatio=1.6 --doAngle=0 --mostAngle=0 --numThread=1',
            "comment": "RapidOCR的启动参数",
        },
        "msgOpenJobPanel": {
            "value": "德瑞差事已启动，请先看教程，学会卡CEO和卡单再进。如果无法连接请再试一次，bot没加速器网不好",
            "comment": "开好面板时发的消息 (设置为空字符串则不发这条消息)",
        },
        "msgMatchPanelTimeout": {
            "value": "一直没有玩家加入，重新启动中",
            "comment": "没人加入超时重开时发的消息 (设置为空字符串则不发这条消息)",
        },
        "msgPlayerJoiningTimeout": {
            "value": "任务中含有卡B，重新启动中",
            "comment": "有人卡在正在加入超时重开时发的消息 (设置为空字符串则不发这条消息)",
        },
        "msgTeamFull": {
            "value": "满了，请等下一班车",
            "comment": "满人时发的消息 (设置为空字符串则不发这条消息)",
        },
        "msgJobStarting": {
            "value": "即将发车，请在听到“咚”的一声后卡单",
            "comment": "差事启动时发的消息 (设置为空字符串则不发这条消息)",
        },
        "msgJobStartFail": {
            "value": "启动差事失败，请等下一班车",
            "comment": "差事启动失败时发的消息 (设置为空字符串则不发这条消息)",
        },
        "msgDetectedSB": {
            "value": "有人没有卡单，请先阅读教程，了解Bot的使用方法后再使用本bot",
            "comment": "发现有人没卡单时发的消息 (设置为空字符串则不发这条消息)",
        },
    }

    if TYPE_CHECKING:
        # 这个块里的代码只对静态类型检查器可见，在运行时会被忽略
        # 在这里声明所有的配置项和它们的类型
        # 类型检查器现在知道了Config实例会有这些属性
        debug: bool
        steamBotHost: str
        steamBotPort: int
        steamBotToken: str
        steamBotProxy: str
        steamGroupId: str
        steamChannelName: str
        useAlterMessagingMethod: bool
        AlterMessagingMethodWindowTitle: str
        enableHealthCheck: bool
        healthCheckInterval: int
        healthCheckSteamChatTimeoutThreshold: int
        enableExitOnUnhealthy: bool
        enableWechatPush: bool
        pushplusToken: str
        pushActivationDelay: int
        mainLoopConsecutiveErrorThreshold: int
        restartGTAConsecutiveFailThreshold: int
        suspendGTATime: int
        delaySuspendTime: int
        autoReduceBadSportOnDodgyPlayer: bool
        manualMoveToPoint: bool
        startOnAllJoined: bool
        walkToPillarTime: int
        walkToBedroomEntranceTime: int
        exitBedroomDoorBackTime: int
        exitBedroomDoorForwardTime: int
        walkToStairwellTime: int
        enterStairwellTime: int
        goDownFirstStairFlightTime: int
        crossStairLandingTime: int
        goDownSecondStairFlightTime: int
        exitStairwellTime: int
        crossAisleTime: int
        moveTimeFindJob: int
        lobbyCheckLoopTime: int
        matchPanelTimeout: int
        playerJoiningTimeout: int
        startMatchDelay: int
        exitMatchTimeout: int
        ocrArgs: str
        msgOpenJobPanel: str
        msgMatchPanelTimeout: str
        msgPlayerJoiningTimeout: str
        msgTeamFull: str
        msgJobStarting: str
        msgJobStartFail: str
        msgDetectedSB: str

    def __init__(self, config_filename: str = "config.yaml"):
        """
        初始化Config对象。

        :param config_filename (str): 配置文件的路径，默认为'config.yaml'。
        """
        # 配置文件路径
        self.config_filepath = Path(config_filename).absolute()
        if self.config_filepath.is_dir():
            logger.error(f"路径 '{self.config_filepath}' 是一个文件夹，不是一个文件。")
            raise FileNotFoundError(f"配置文件路径 '{self.config_filepath}' 是一个文件夹，不是一个文件。")

        # YAML 解析器
        self.yaml = YAML()
        self.yaml.indent(mapping=2, sequence=4, offset=2)

        # 将配置写入自身的属性
        self._load_or_create()

    def _load_or_create(self):
        """
        加载 YAML 配置文件，如果文件不存在将创建，如果配置项不完整将更新。
        最终将加载完成的配置写回 YAML 文件。
        """
        # 加载配置文件，如果文件为空或者格式错误将返回空字典
        logger.info(f"正在从 '{self.config_filepath}' 加载配置文件...")
        existing_config = {}
        try:
            with open(self.config_filepath, "r", encoding="utf-8") as f:
                existing_config = self.yaml.load(f)
                if existing_config is None:
                    existing_config = {}
        except FileNotFoundError:
            logger.info(f"未找到配置文件 '{self.config_filepath}'，将创建一个新的。")
        except Exception as e:
            logger.error(f"加载配置文件时出错，将使用默认配置替换该配置文件: {e}")
            # 清除已经读取的配置
            existing_config = {}

        # 用默认值填写空的配置项
        for key, details in self._defaults.items():
            default_value = details["value"]
            value = existing_config.get(key, default_value)
            setattr(self, key, value)

        # 将加载完成的配置写回 YAML 文件
        self.save()

    def save(self):
        """
        将当前所有配置项及注释保存到 YAML 文件。
        """
        config_to_save = CommentedMap()

        # 遍历当前配置项
        for key, details in self._defaults.items():
            value = getattr(self, key)
            # 从默认配置项字典中获取注释
            comment = details["comment"]

            config_to_save[key] = value
            config_to_save.yaml_set_comment_before_after_key(key, before=comment)

        try:
            with open(self.config_filepath, "w", encoding="utf-8") as f:
                self.yaml.dump(config_to_save, f)
        except IOError as e:
            logger.error(f"无法写入配置文件 {self.config_filepath}: {e}")


# --- 使用示例 ---
if __name__ == "__main__":
    if not os.path.exists("config.yaml"):
        print("未找到 'config.yaml'。将根据默认值创建一个新的。")

    GConfig = Config("config.yaml")
    print(f"调试模式: {GConfig.debug}")
    print(f"卡单持续时间: {GConfig.suspendGTATime} 秒")

    GConfig.suspendGTATime = 25
    GConfig.save()
    print("\n配置已修改并保存:")
    print(f"卡单持续时间: {GConfig.suspendGTATime} 秒")
    print(f"\n请查看 'config.yaml' 文件。")
