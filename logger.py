import logging
import logging.config
from logging.handlers import RotatingFileHandler
from pathlib import Path

try:
    # 尝试导入 colorlog 库
    import colorlog
except ImportError:
    # 导入失败保留为 None, 稍后回退到不带颜色的日志
    colorlog = None


class UIautomationFilter(logging.Filter):
    """
    过滤 comtypes 的低于 WARNING 等级的日志。
    """

    def filter(self, record: logging.LogRecord) -> bool | logging.LogRecord:
        if "comtypes" in record.name:
            return record.levelno >= logging.WARNING
        return True


# 默认日志配置字典
# 格式化日志输出到文件和终端, 日志等级为 debug
# 过滤器 UIautomationFilter
DEFAULT_LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,  # 保持为 False 以避免清除掉其他软件包添加的 logger
    "filters": {"silence_uiautomation_less_than_info": {"()": f"{__name__}.UIautomationFilter"}},
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

if "handlers" in DEFAULT_LOGGING_CONFIG and "file" in DEFAULT_LOGGING_CONFIG["handlers"]:
    # 如果启用了文件日志，则确保日志文件夹已创建
    log_filename = Path(DEFAULT_LOGGING_CONFIG["handlers"]["file"]["filename"]).absolute()
    log_dir = log_filename.parent
    log_dir.mkdir(parents=True, exist_ok=True)
else:
    log_filename = None

# 应用日志设置
logging.config.dictConfig(DEFAULT_LOGGING_CONFIG)

if log_filename:
    logging.getLogger(__name__).info(f"程序日志将被记录到文件: {log_filename}")


def set_loglevel(log_level: str):
    """
    设置日志等级。

    :param log_level: 日志等级: 'DEBUG','INFO','WARNING','ERROR','CRITICAL'
    """

    # 输入验证
    if log_level.upper() not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        raise ValueError(
            f"输入的日志等级无效: {log_level} 。日志等级应当为'DEBUG','INFO','WARNING','ERROR','CRITICAL'中的一个"
        )

    logging_config = DEFAULT_LOGGING_CONFIG.copy()
    logging_config["handlers"]["console"]["level"] = log_level.upper()

    # 添加增量标记
    logging_config["incremental"] = True

    # 应用日志设置
    logging.config.dictConfig(DEFAULT_LOGGING_CONFIG)


def get_logger(name: str) -> logging.Logger:
    """
    获取一个 logger 实例。

    :param name: logger 的名称
    :return: logging.Logger
    """
    return logging.getLogger(name)


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
