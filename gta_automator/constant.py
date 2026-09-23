from enum import Enum, auto


class BotMode(Enum):
    """定义 Bot 的工作状态"""

    DRE = auto()  # 德瑞 Bot
    RECOVERY = auto()  # 恢复模式 (挂机降低恶意值)


class PlayerLevel(Enum):
    """定义玩家恶意等级"""

    CLEAN = "清白玩家"
    DODGY = "问题玩家"
    BAD_SPORT = "恶意玩家"
    UNKNOWN = "未知等级"


# 与 GTA V 增强版相关的进程名称列表
GTA_ASSOCIATED_PROCESS_NAMES = [
    "GTA5.exe",
    "GTA5_Enhanced.exe",
    "GTA5_Enhanced_BE.exe",
    "PlayGTAV.exe",
    "RockstarErrorHandler.exe",
    "RockstarService.exe",
    "SocialClubHelper.exe",
    "Launcher.exe",
]

# GTA V 增强版进程名
GTA_PROCESS_NAME = "GTA5_Enhanced.exe"

# GTA V 增强版窗口标题
GTA_WINDOW_TITLE = "Grand Theft Auto V"

# GTA V 增强版窗口类名
GTA_WINDOW_CLASS_NAME = "sgaWindow"
