import argparse
from argparse import ArgumentError

class ArgumentParser:
    """
    管理和解析命令行参数的封装类。
    """

    def __init__(self):
        self.parser = argparse.ArgumentParser(description="德瑞BOT自动化脚本")
        self._add_arguments()

    def _add_arguments(self):
        self.parser.add_argument(
            "--config-file",
            dest="config_file_path",  # 解析后参数字典中的键名
            default="config.yaml",  # 默认值
            help='指定配置文件的路径。\n默认值: "config.yaml"',
        )
        # 示例：添加更多参数
        # self.parser.add_argument('--verbose', action='store_true', help='启用详细输出模式')

    def parse(self) -> dict:
        args = self.parser.parse_args()
        return vars(args)