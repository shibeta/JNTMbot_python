import sys
from pathlib import Path


def get_base_dir() -> Path:
    """
    获取程序资源根目录。
    对于源码运行即是本文件所在目录, 对于打包运行则是可执行文件所在目录。

    :return: 资源根目录的绝对路径
    """
    if getattr(sys, "frozen", False):
        # 打包运行时，可执行文件在上级目录
        return Path(sys.executable).resolve().parent
    else:
        # 源码运行时，直接返回本文件所在目录
        return Path(__file__).resolve().parent


# 根目录
BASE_DIR = get_base_dir()

# 日志目录
LOG_DIR = BASE_DIR / "logs"
# 日志文件名
LOG_FILE_PATH = LOG_DIR / "app.log"

# OCR 引擎路径
OCR_EXECUTABLE_PATH = BASE_DIR / "RapidOCR-json.exe"

# 打包后的 Steam Bot 可执行文件路径，用于发行版
STEAM_BOT_EXECUTABLE_PATH = BASE_DIR / "steam_bot.exe"
# Steam Bot 后端脚本路径，用于源码运行
STEAM_BOT_SCRIPT_PATH = BASE_DIR / "steam_bot" / "server.js"

# 默认配置文件路径
DEFAULT_CONFIG_PATH = BASE_DIR / "config.yaml"

# ViGEmBus 驱动安装程序路径候选列表
VIGEMBUS_DRIVER_PATH_CANDIDATES = (
    # 发行版放在根目录
    BASE_DIR / "虚拟手柄驱动ViGEmBusSetup_x64.msi",
    # 源码运行时放在 assets 目录
    BASE_DIR / "assets" / "虚拟手柄驱动ViGEmBusSetup_x64.msi",
)
