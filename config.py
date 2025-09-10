import os
from typing import Any, Dict
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from logger import setup_logger

GLogger = setup_logger(name="config")


class Config:
    """
    一个用于加载和管理YAML配置文件的类，并支持注释的读写。

    此类在初始化时会读取一个YAML文件。如果文件不存在，或者文件缺少某些配置项，
    它会使用内部定义的默认值来补充，然后将一个带有注释的完整配置文件写回磁盘。
    """

    # _defaults 字典定义了所有配置项的默认值和注释。
    # 结构: { "配置项名称": {"value": 默认值, "comment": "注释"} }
    _defaults: Dict[str, Dict[str, Any]] = {
        "debug": {"value": True, "comment": "开启调试模式"},
        "steamBotHost": {"value": "127.0.0.1", "comment": "Steam Bot后端的监听地址"},
        "steamBotPort": {"value": 13091, "comment": "Steam Bot后端的监听端口"},
        "steamBotToken": {"value": "0x4445414442454546", "comment": "访问Steam Bot后端的认证Token"},
        "steamBotProxy": {
            "value": "system",
            "comment": 'Steam Bot使用的HTTP代理，格式为"http://127.0.0.1:8080"，"system"表示使用系统代理，留空则不使用代理',
        },
        "steamGroupId": {"value": "37660928", "comment": "要发送消息的Steam群组ID，程序启动时可以读取到"},
        "steamChannelName": {"value": "BOT候车室", "comment": "要发送消息的Steam群组频道名称"},
        "wechatPush": {"value": False, "comment": "是否启用微信推送bot状态信息"},
        "pushplusToken": {"value": "", "comment": "pushplus的token，用于微信通知"},
        "suspendGTATime": {"value": 15, "comment": "卡单持续时间 (秒)"},
        "delaySuspendTime": {
            "value": 3,
            "comment": "卡单延迟时间 (秒)",
        },
        "checkLoopTime": {"value": 1, "comment": "检测间隔时间 (秒)"},
        "matchPanelTimeout": {"value": 300, "comment": "面板无人加入时重开时间 (秒)"},
        "joiningPlayerKick": {"value": 120, "comment": "等待正在加入玩家超时重开时间 (秒)"},
        "startMatchDelay": {"value": 15, "comment": "开始差事等待延迟 (秒)"},
        "startOnAllJoined": {
            "value": True,
            "comment": '全部玩家已加入时立即开始差事而不等待 (绕过 "startMatchDelay" 时间)',
        },
        "exitMatchTimeout": {"value": 120, "comment": "等待差事启动落地超时时间 (秒)(防止卡在启动战局中)"},
        "pressSTimeStairs": {
            "value": 400,
            "comment": '差事层楼梯口进行"走出门"动作时 每轮按S的持续时间 (毫秒)',
        },
        "pressATimeStairs": {
            "value": 400,
            "comment": '差事层楼梯口进行"走出门"动作时 每轮按A的持续时间 (毫秒)',
        },
        "goOutStairsTime": {"value": 1000, "comment": '差事层楼梯口进行"走出门"动作持续时间 (毫秒)'},
        "pressSTimeAisle": {"value": 360, "comment": '差事层进行"穿过走道"动作时 每轮按S的持续时间 (毫秒)'},
        "pressATimeAisle": {"value": 500, "comment": '差事层进行"穿过走道"动作时 每轮按A的持续时间 (毫秒)'},
        "crossAisleTime": {"value": 3000, "comment": '差事层进行"穿过走道"动作持续时间 (毫秒)'},
        "pressSTimeGoJob": {
            "value": 340,
            "comment": '差事层进行"寻找差事黄圈"动作时 每轮按S的持续时间 (毫秒)',
        },
        "pressATimeGoJob": {
            "value": 480,
            "comment": '差事层进行"寻找差事黄圈"动作时 每轮按A的持续时间 (毫秒)',
        },
        "waitFindJobTimeout": {"value": 15000, "comment": '差事层进行"寻找差事黄圈"动作超时时间 (毫秒)'},
        "msgOpenJobPanel": {
            "value": "德瑞差事已启动，请先看教程，学会卡CEO和卡单再进",
            "comment": "开好面板时发的消息 (设置为空字符串则不发这条消息)",
        },
        "msgWaitPlayerTimeout": {
            "value": "启动任务超时，重新启动中",
            "comment": "没人加入超时重开时发的消息 (设置为空字符串则不发这条消息)",
        },
        "msgJoiningPlayerKick": {
            "value": "任务中含有卡B，重新启动中",
            "comment": "有人卡在正在加入超时重开时发的消息 (设置为空字符串则不发这条消息)",
        },
        "msgTeamFull": {
            "value": "满了，请等下一班车",
            "comment": "满人时发的消息 (设置为空字符串则不发这条消息)",
        },
        "msgJobStarted": {
            "value": "即将发车，请在听到“咚”的一声后卡单",
            "comment": "差事开始时发的消息 (设置为空字符串则不发这条消息)",
        },
        "jobTpBotIndex": {
            "value": -1,
            "comment": "差传bot的序号，-1: 不指定, 按顺序加入直到成功, 0: 第一个差传(一般为辅助瞄准), 1: 第二个差传(一般为自由瞄准); ",
        },
    }

    def __init__(self, config_filename: str = "config.yaml"):
        """
        初始化Config对象。

        Args:
            config_filename (str): 配置文件的路径，默认为'config.yaml'。
        """
        self.config_filename = config_filename
        self.yaml = YAML()
        self.yaml.indent(mapping=2, sequence=4, offset=2)
        self._load_or_create()

    def _load_or_create(self):
        """
        加载 YAML 配置文件，如果文件不存在将创建，如果配置项不完整将更新。
        最终将加载完成的配置写回 YAML 文件。
        """
        # 加载配置文件，如果文件为空或者格式错误将返回空字典
        existing_config = {}
        try:
            with open(self.config_filename, "r", encoding="utf-8") as f:
                existing_config = self.yaml.load(f)
                if existing_config is None:
                    existing_config = {}
        except FileNotFoundError:
            GLogger.info(f"未找到配置文件 '{self.config_filename}'，将创建一个新的。")
        except Exception as e:
            GLogger.error(f"加载配置文件时出错: {e}")
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
            with open(self.config_filename, "w", encoding="utf-8") as f:
                self.yaml.dump(config_to_save, f)
        except IOError as e:
            GLogger.error(f"无法写入配置文件 {self.config_filename}: {e}")


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
