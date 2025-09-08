import logging

try:
    # 尝试导入 colorlog 库
    import colorlog
except ImportError:
    # 如果导入失败，说明库未安装，设置一个标志位
    colorlog = None


def setup_logger(name: str, level=logging.DEBUG):
    """
    配置并返回一个支持控制台颜色输出的 logger。

    Args:
        name (str): logger 的名称。
        level (int): logger 的最低输出级别

    Returns:
        logging.Logger: 配置好的 logger 实例。
    """

    # 获取 logger 实例
    logger = logging.getLogger(name)

    # 设置最低日志级别
    logger.setLevel(level)

    # 防止日志消息向上传递给根 logger，避免重复输出
    logger.propagate = False

    # 如果 logger 已有 handlers，先清空，防止重复添加
    if logger.hasHandlers():
        logger.handlers.clear()

    # 定义日志格式为 [YYYY-MM-DD hh:mm:ss] [level] [source] message
    log_format = "%(log_color)s[%(asctime)s] [%(levelname)s] [%(name)s]%(reset)s %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # 创建 formatter 并应用颜色
    if colorlog:
        # 如果 colorlog 安装成功，则使用 ColoredFormatter
        formatter = colorlog.ColoredFormatter(
            log_format,
            datefmt=date_format,
            reset=True,
            log_colors={
                "DEBUG": "white",
                "INFO": "cyan",
                "WARNING": "yellow",
                "ERROR": "red",
                "CRITICAL": "bold_red",
            },
        )
    else:
        # 如果 colorlog 未安装，则使用标准 formatter，移除颜色相关的占位符
        plain_format = "[%(asctime)s] [%(levelname)-5s] %(message)s"
        formatter = logging.Formatter(plain_format, datefmt=date_format)

    # 将 handler 添加到 logger
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # 输出构造完成提示
    logger.debug(f"Logger {name} started up")

    return logger


# --- 使用示例 ---
if __name__ == "__main__":
    # 传入不同的 name 来演示模块名的显示效果
    main_logger = setup_logger(name="main")
    ocr_logger = setup_logger(name="ocr_engine")
    window_logger = setup_logger(name="window_utils")

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

    if not colorlog:
        print("\n提示: 'colorlog' 库未安装，日志将不带颜色。")
        print("请在命令行运行 'pip install colorlog' 来启用彩色日志。")
