import logging
import logging.config
from logging.handlers import RotatingFileHandler
import os
from typing import Optional

try:
    # 尝试导入 colorlog 库
    import colorlog
except ImportError:
    # 如果导入失败，说明库未安装，设置一个标志位
    colorlog = None


# 目前设置了控制台日志和文件日志
DEFAULT_LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,  # 保持为 False 以避免清除掉其他软件包添加的 logger
    "filters": {"silence_uiautomation_less_than_info": {"()": "logger.UIautomationFilter"}},
    "formatters": {
        "default": {
            "format": "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "color": {
            "()": "colorlog.ColoredFormatter",
            "format": "%(log_color)s[%(asctime)s] [%(levelname)s] [%(name)s]%(reset)s %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
            "log_colors": {
                "DEBUG": "white",
                "INFO": "cyan",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "bold_red",
            },
        },
        "file_formatter": {
            "format": "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "color" if colorlog else "default",
            "level": "DEBUG",
            "filters": ["silence_uiautomation_less_than_info"],
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "file_formatter",
            "filename": "logs/app.log",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
            "encoding": "utf8",
            "level": "DEBUG",
            "filters": ["silence_uiautomation_less_than_info"],
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": "DEBUG",  # 根 logger 的级别建议设为 DEBUG
    },
}

class UIautomationFilter(logging.Filter):
    """
    过滤 comtypes 的低于 WARNING 等级的日志。
    """
    def filter(self, record: logging.LogRecord) -> bool | logging.LogRecord:
        if "comtypes" in record.name:
            return record.levelno >= logging.WARNING
        return True

def setup_logging(log_level: Optional[str] = None):
    """
    初始化或设置日志。

    :param log_level: 日志等级: 'DEBUG','INFO','WARNING','ERROR','CRITICAL'
    """
    logging_config = DEFAULT_LOGGING_CONFIG

    # 如果启用了文件日志，则确保日志文件夹已创建
    if "handlers" in logging_config and "file" in logging_config["handlers"]:
        log_filename = logging_config["handlers"]["file"]["filename"]
        log_dir = os.path.dirname(log_filename)

        # 如果目录非空且不存在，则创建它
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)

    # 根据每个参数修改日志设置
    if log_level:
        if log_level.upper() in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            logging_config["handlers"]["console"]["level"] = log_level.upper()
        else:
            logging.getLogger(__name__).error(
                f"输入的日志等级无效: {log_level} 。日志等级应当为'DEBUG','INFO','WARNING','ERROR','CRITICAL'中的一个。将使用默认配置。"
            )

    # 应用日志设置
    logging.config.dictConfig(logging_config)
    logging.getLogger(__name__).info("日志模块加载完成。")


def get_logger(name: str) -> logging.Logger:
    """
    获取一个 logger 实例。
    应当在 setup_logging 后执行。

    :param name: logger 的名称
    :return: logging.Logger
    """
    return logging.getLogger(name)


setup_logging()


# --- 使用示例 ---
if __name__ == "__main__":
    # 传入不同的 name 来演示模块名的显示效果
    main_logger = get_logger(name="main")
    ocr_logger = get_logger(name="ocr_engine")
    window_logger = get_logger(name="window_utils")

    print("\n--- 诊断信息 ---")
    root_logger = logging.getLogger()
    print(f"Root logger 的有效级别是: {logging.getLevelName(root_logger.getEffectiveLevel())}")
    # 检查文件处理器的级别
    for handler in root_logger.handlers:
        if isinstance(handler, RotatingFileHandler):
            print(f"文件处理器 ({handler.baseFilename}) 的级别是: {logging.getLevelName(handler.level)}")
    print("--- 诊断结束 ---\n")

    print("\n--- 日志功能演示 ---")
    # 现在 logger 的输出会包含模块名和对齐的级别
    main_logger.debug("这是一条来自 main 模块的调试信息。")
    ocr_logger.info("正在初始化 OCR 引擎...")
    main_logger.warning("主程序检测到一个潜在问题。")
    window_logger.error("未找到 GTA V 窗口。请先启动游戏。")

    player_name = "Player123"
    score = 500
    main_logger.info(f"玩家 '{player_name}' 成功完成任务，得分: {score}")
    main_logger.critical("发生严重错误，程序即将退出！")

    print("\n--- 日志演示结束 ---")

    if not colorlog:
        print("\n提示: 'colorlog' 库未安装，日志将不带颜色。")
        print("请在命令行运行 'pip install colorlog' 来启用彩色日志。")
