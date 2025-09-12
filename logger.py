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
    "disable_existing_loggers": False,  # 保持为 False 以避免清除掉其他软件包添加的 logger
    "filters": {"silence_rapidocr_less_than_error": {"()": "logger.RapidOCRFilter"}},  # 让 rapidocr 闭嘴
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
            "filters": ["silence_rapidocr_less_than_error"],  # 在终端日志中添加过滤器
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


class RapidOCRFilter(logging.Filter):
    """
    一个多功能过滤器，用于处理 RapidOCR 库的日志：
    1. 将其日志记录的名称从 'root' 修改为 'RapidOCR'。
    2. 过滤掉其级别低于 ERROR 的日志。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """
        处理日志记录：先修改，再决定是否放行。

        Args:
            record (logging.LogRecord): 日志记录对象。

        Returns:
            bool: 如果返回 True，日志被处理；返回 False，日志被丢弃。
        """
        # 如果日志来自 RapidOCR，则应用过滤器
        # 通过检查日志记录的来源文件路径是否包含 'rapidocr' 来实现
        if "rapidocr" in record.pathname.lower():
            # 重命名 logger name，因为 RapidOCR 默认使用 logging.getLogger() 输出 name 为 root 的日志
            record.name = "RapidOCR"
            # 那么只有当它的级别是 ERROR 或更高级别时，我们才允许它通过
            return record.levelno >= logging.ERROR

        # 如果日志不是来自 RapidOCR，我们总是允许它通过
        return True


def setup_logging(log_level: str = None):
    """
    初始化或设置日志。

    Args:
        log_level: 日志等级: 'DEBUG','INFO','WARNING','ERROR','CRITICAL'
    """
    logging_config = DEFAULT_LOGGING_CONFIG

    # 如果启用了文件日志，则确保日志文件夹已创建
    if "handlers" in logging_config and "file" in logging_config["handlers"]:
        log_filename = logging_config["handlers"]["file"]["filename"]
        log_dir = os.path.dirname(log_filename)

        # 如果目录非空且不存在，则创建它
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir)
            logging.getLogger(__name__).error(f"日志目录 {log_dir} 已创建。")

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
