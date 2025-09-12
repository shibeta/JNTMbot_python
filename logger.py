import logging
import logging.config
import os

try:
    # 尝试导入 colorlog 库
    import colorlog
except ImportError:
    # 如果导入失败，说明库未安装，设置一个标志位
    colorlog = None


# 目前设置了控制台日志和文件日志
DEFAULT_LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,  # 保持为 False 以避免清除掉之前添加的 logger
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
        },
        "file": {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "file_formatter",
            "filename": "logs/app.log",
            "maxBytes": 10485760,  # 10MB
            "backupCount": 5,
            "encoding": "utf8",
            "level": "DEBUG",
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": "DEBUG",  # 根 logger 的级别建议设为 DEBUG
    },
}


def setup_logging(log_level: str = None):
    """
    初始化或设置日志。

    Args:
        log_level: 日志等级: 'DEBUG','INFO','WARNING','ERROR','CRITICAL'
    """
    logging_config = DEFAULT_LOGGING_CONFIG

    # 如果启用了文件日志，则确保日志文件夹已创建
    if 'handlers' in logging_config and 'file' in logging_config['handlers']:
        log_filename = logging_config['handlers']['file']['filename']
        log_dir = os.path.dirname(log_filename)

        # 如果目录非空且不存在，则创建它
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
            logging.getLogger(__name__).error(
                f"日志目录 {log_dir} 已创建。"
            )

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

    Args:
        name: logger 的名称

    Returns:
        logging.Logger
    """
    return logging.getLogger(name)


setup_logging()

# def get_logger(name: str, level=logging.DEBUG):
#     """
#     配置并返回一个支持控制台颜色输出的 logger。

#     Args:
#         name (str): logger 的名称。
#         level (int): logger 的最低输出级别

#     Returns:
#         logging.Logger: 配置好的 logger 实例。
#     """

#     # 获取 logger 实例
#     logger = logging.getLogger(name)

#     # 设置最低日志级别
#     logger.setLevel(level)

#     # 防止日志消息向上传递给根 logger，避免重复输出
#     logger.propagate = False

#     # 如果 logger 已有 handlers，先清空，防止重复添加
#     if logger.hasHandlers():
#         logger.handlers.clear()

#     # 定义日志格式为 [YYYY-MM-DD hh:mm:ss] [level] [source] message
#     log_format = "%(log_color)s[%(asctime)s] [%(levelname)s] [%(name)s]%(reset)s %(message)s"
#     date_format = "%Y-%m-%d %H:%M:%S"

#     # 创建 formatter 并应用颜色
#     if colorlog:
#         # 如果 colorlog 安装成功，则使用 ColoredFormatter
#         formatter = colorlog.ColoredFormatter(
#             log_format,
#             datefmt=date_format,
#             reset=True,
#             log_colors={
#                 "DEBUG": "white",
#                 "INFO": "cyan",
#                 "WARNING": "yellow",
#                 "ERROR": "red",
#                 "CRITICAL": "bold_red",
#             },
#         )
#     else:
#         # 如果 colorlog 未安装，则使用标准 formatter，移除颜色相关的占位符
#         plain_format = "[%(asctime)s] [%(levelname)-5s] %(message)s"
#         formatter = logging.Formatter(plain_format, datefmt=date_format)

#     # 将 handler 添加到 logger
#     handler = logging.StreamHandler()
#     handler.setFormatter(formatter)
#     logger.addHandler(handler)

#     # 输出构造完成提示
#     logger.debug(f"Logger {name} started up")

#     return logger


# --- 使用示例 ---
if __name__ == "__main__":
    # 传入不同的 name 来演示模块名的显示效果
    main_logger = get_logger(name="main")
    ocr_logger = get_logger(name="ocr_engine")
    window_logger = get_logger(name="window_utils")

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
