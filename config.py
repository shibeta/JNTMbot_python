import sys
from dataclasses import Field, dataclass, field
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Any, Callable, Optional, ParamSpec, TypeVar

from ruamel.yaml import YAML, YAMLError
from ruamel.yaml.comments import CommentedMap

from logger import get_logger
from paths import BASE_DIR

# 用于类型注解的泛型变量
T = TypeVar("T")  # 捕获函数的返回值类型

logger = get_logger(__name__)


class ConfigError(Exception):
    """配置文件错误基类"""


class ConfigParseError(ConfigError):
    """配置文件不存在、无法读取，或者不是合法的 YAML 键值对文档。"""


class ConfigValidationError(ConfigError):
    """配置项的类型或取值不合法。"""


_Checker = Callable[[Any], Optional[str]]
"""配置项校验函数：合法时返回 ``None``，不合法时返回给用户看的说明。"""

# 用于配置项校验的常量
_TRUE_WORDS = {"true", "yes", "on", "1"}
_FALSE_WORDS = {"false", "no", "off", "0"}
_TYPE_NAMES = {bool: "布尔值 (true/false)", int: "整数", float: "数字", str: "字符串"}


def _check_range(
    minimum: Optional[float] = None, maximum: Optional[float] = None, unit: str = ""
) -> _Checker:
    """数值范围校验函数生成器"""

    def check(value: Any) -> Optional[str]:
        if minimum is not None and value < minimum:
            return f"不能小于 {minimum}{unit}（当前为 {value}）"
        if maximum is not None and value > maximum:
            return f"不能大于 {maximum}{unit}（当前为 {value}）"
        return None

    return check


def _check_not_empty(what: str) -> _Checker:
    """空值校验函数生成器"""

    def check(value: Any) -> Optional[str]:
        if not str(value).strip():
            return f"{what}不能为空"
        return None

    return check


def _check_digits(what: str) -> _Checker:
    """纯数字格式校验函数生成器"""

    def check(value: Any) -> Optional[str]:
        if not str(value).isdigit():
            return f"{what}必须全部由数字组成（当前为 {value!r}）"
        return None

    return check


def _check_proxy(value: Any) -> Optional[str]:
    """简单的代理字符串格式校验函数生成器"""
    if value in ("", "system"):
        return None
    if "://" not in str(value):
        return '应为 "system"、留空，或者形如 "http://127.0.0.1:8080" 的代理地址'
    return None


_ms_check = _check_range(minimum=0, unit=" 毫秒")

# 程序初始化配置文件时，自动添加在配置文件开头的说明
_FILE_HEADER = (
    "本文件由 config.py 生成，请不要删除其中的配置项。\n"
    "程序启动时会自动补全缺失的配置项，并保留你已经修改过的值和注释。"
)


def _opt(default: T, comment: str, check: Optional[_Checker] = None) -> T:
    """
    声明一个会写入配置文件的配置项。

    :param default: 默认值，同时也是配置文件中缺少该项时使用的值
    :param comment: 写进配置文件时，该项上方的注释
    :param check: 可选的取值范围校验函数
    """
    return field(default=default, metadata={"yaml": True, "comment": comment, "check": check})


def _runtime_state(default: T = None) -> T:
    """声明一个**不写入配置文件**的运行期状态字段。"""
    return field(default=default, init=False, repr=False, compare=False, metadata={"yaml": False})


def _declared_kind(spec: Field) -> Optional[type]:
    """取出字段声明的类型，只关心本模块用到的几种。"""
    for kind in (bool, int, float, str):
        if spec.type is kind:
            return kind
    return None


def _matches_type(value: Any, kind: type) -> bool:
    """判断一个值是否符合字段声明的类型（允许整数用于浮点数配置项）。"""
    if kind is bool:
        return isinstance(value, bool)
    if isinstance(value, bool):
        # bool 是 int 的子类，但配置里的 true/false 不应该被当成数字
        return False
    if kind is int:
        # 浮点数（例如 13091.0）不算匹配，交给 _coerce_value 转换成整数
        return isinstance(value, int)
    if kind is float:
        return isinstance(value, (int, float))
    return isinstance(value, kind)


def _coerce_value(spec: Field, value: Any) -> tuple[Any, Optional[str]]:
    """
    把从 YAML 中读到的值转换成字段声明的类型。

    只修正几种常见的书写错误（数字没有加引号、布尔值写成了字符串等）。转换不了的值会原样
    返回，由 :meth:`Config.validate` 统一报错。

    :return: ``(转换后的值, 提示信息)``，提示信息为 ``None`` 表示没有做任何转换
    """
    kind = _declared_kind(spec)
    # 如果值的类型已经符合声明，直接返回
    if kind is None or _matches_type(value, kind):
        return value, None

    # 尝试将数字类型转换为字符串
    if kind is str and isinstance(value, (int, float)):
        return str(value), (
            f"配置项 '{spec.name}' 的值 {value!r} 会被 YAML 解析成数字，已按字符串 '{value}' 处理。"
            f"建议在 config.yaml 中为它加上引号。"
        )

    # 尝试将字符串类型转换为布尔值
    if kind is bool and isinstance(value, str):
        text = value.strip().lower()
        if text in _TRUE_WORDS or text in _FALSE_WORDS:
            boolean = text in _TRUE_WORDS
            return boolean, f"配置项 '{spec.name}' 的值 '{value}' 是字符串，已按布尔值 {boolean} 处理。"

    # 尝试将实际上是整数值的浮点类型转换为整数
    if kind is int and isinstance(value, float) and value.is_integer():
        return int(value), f"配置项 '{spec.name}' 的值 {value!r} 是浮点数，已按整数 {int(value)} 处理。"

    # 尝试将字符串类型转换为整数/浮点数
    if kind in (int, float) and isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return value, None
        if kind is float or number.is_integer():
            numeric: int | float = int(number) if kind is int else number
            return numeric, f"配置项 '{spec.name}' 的值 '{value}' 是字符串，已按数字 {numeric} 处理。"

    return value, None


@dataclass
class Config:
    """
    程序的所有配置项。

    字段的声明顺序也是写进 ``config.yaml`` 的顺序，字段的默认值就是新建配置文件时的取值。

    用法: `config = Config.load(路径)`
    """

    # ---- 通用 ----
    debug: bool = _opt(False, "开启调试模式，日志输出将非常详细")

    # ---- Steam Bot 后端 ----
    steamBotHost: str = _opt("127.0.0.1", "Steam Bot后端的监听地址", _check_not_empty("监听地址"))
    steamBotPort: int = _opt(13091, "Steam Bot后端的监听端口", _check_range(minimum=1, maximum=65535))
    steamBotToken: str = _opt(
        "0x4445414442454546", "访问Steam Bot后端的认证Token", _check_not_empty("认证 Token")
    )
    steamBotProxy: str = _opt(
        "system",
        'Steam Bot使用的代理，格式为"http://127.0.0.1:8080"或"socks5h://127.0.0.1:1080"。"system"表示使用系统代理，留空则不使用代理。建议使用HTTP代理',
        _check_proxy,
    )

    # ---- Steam 游戏 ----
    gameAppId: str = _opt(
        "3240220",
        "GTA V 增强版在 Steam 上的 App ID，用于通过 Steam 启动游戏和加入战局，一般不需要修改",
        _check_digits("App ID"),
    )

    # ---- Steam 群组消息 ----
    steamGroupId: str = _opt(
        "37660928",
        "要发送消息的Steam群组ID，程序启动时可以读取到",
        _check_not_empty("群组 ID"),
    )
    steamChannelId: str = _opt(
        "163168791",
        "要发送消息的Steam群组频道ID，程序启动时可以读取到",
        _check_not_empty("频道 ID"),
    )
    useAlterMessagingMethod: bool = _opt(
        False,
        "是否改用备用方法发送Steam群组消息，该方法通过与Steam客户端GUI交互以发送消息。该方法会频繁弹出Steam聊天窗口，推荐长期挂Bot使用",
    )
    AlterMessagingMethodWindowTitle: str = _opt(
        "蠢人帮",
        "用备用方法发送群组消息时，群聊窗口标题关键字，支持正则",
    )

    # ---- 健康检查 ----
    enableHealthCheck: bool = _opt(True, "启用健康检查，每间隔一段时间检查Bot上次向Steam发送信息的时间")
    healthCheckInterval: int = _opt(
        10,
        "健康检查的频率，即两次健康检查之间等待的时间 (分钟)",
        _check_range(minimum=1, unit=" 分钟"),
    )
    healthCheckSteamChatTimeoutThreshold: int = _opt(
        60,
        "基于Steam消息的健康检查判断阈值，如果发现Bot一段时间内未向Steam发送过信息，则认为Bot不可用 (分钟)",
        _check_range(minimum=1, unit=" 分钟"),
    )
    enableExitOnUnhealthy: bool = _opt(False, "健康检查发现Bot不可用时，是否退出程序")

    # ---- 微信推送 ----
    enableWechatPush: bool = _opt(
        False,
        "是否启用微信推送bot状态信息。启用后，当程序运行一段时间后发生报错退出，或健康状态发生变化时，会向微信推送错误信息",
    )
    pushplusToken: str = _opt("", "pushplus的API token，用于微信通知")
    pushActivationDelay: int = _opt(
        5,
        "微信推送报错退出的启用延迟。为节省API用量，只有程序运行时长超过该时间后，报错退出时才会向微信推送 (分钟)",
        _check_range(minimum=0, unit=" 分钟"),
    )

    # ---- 主循环与卡单 ----
    mainLoopConsecutiveErrorThreshold: int = _opt(
        10,
        "主循环连续报错的阈值，连续报错超过该次数将报错退出。设置为<=1则报错一次即退出",
        _check_range(minimum=0),
    )
    restartGTAConsecutiveFailThreshold: int = _opt(
        5,
        "初始化GTA时重启GTA失败的阈值，连续重启失败超过该次数将抛出异常。设置为<=1则重启失败立即抛出异常",
        _check_range(minimum=0),
    )
    suspendGTATime: int = _opt(13, "卡单持续时间 (秒)", _check_range(minimum=0, unit=" 秒"))
    delaySuspendTimePanelDisappear: int = _opt(
        5, "面板消失后，卡单延迟时间 (秒)", _check_range(minimum=0, unit=" 秒")
    )
    delaySuspendTimeJobStart: int = _opt(
        10, "任务启动玩家落地后，卡单延迟时间 (秒)", _check_range(minimum=0, unit=" 秒")
    )
    autoReduceBadSportOnDodgyPlayer: bool = _opt(
        True, "当bot变成问题玩家后是否自动挂机清除恶意值。设置为False后变成问题玩家会退出程序。"
    )
    badSportCheckInterval: int = _opt(
        3600,
        "两次恶意值检查之间的最小间隔 (秒)，用于减少检查恶意值带来的停顿",
        _check_range(minimum=1, unit=" 秒"),
    )
    recoveryTotalDuration: int = _opt(
        20 * 3600,
        "自动挂机清除恶意值时，累计挂机的目标时长 (秒)(默认 20 小时)，达到该时长后会切回德瑞 Bot",
        _check_range(minimum=1, unit=" 秒"),
    )
    recoveryChunkSize: int = _opt(
        10 * 60,
        "自动挂机清除恶意值时，单次挂机的时长 (秒)(默认 10 分钟)。每挂完一段都会重新检查恶意值，"
        "因此在挂机期间变成恶意玩家也能被及时发现",
        _check_range(minimum=1, unit=" 秒"),
    )
    manualMoveToPoint: bool = _opt(
        False,
        "禁用在事务所内起床后自动移动到任务触发点，改为要求用户手动将角色移动到任务触发点",
    )
    startOnAllJoined: bool = _opt(True, '全部玩家已加入时立即开始差事而不等待 (绕过 "startMatchDelay" 时间)')

    # ---- 生活层与楼梯间的移动时间 (毫秒) ----
    walkToPillarTime: int = _opt(1500, '生活层进行"走到床头柱子前卡住"动作的持续时间 (毫秒)', _ms_check)
    walkToBedroomEntranceTime: int = _opt(
        5500, '生活层进行"走到个人空间门口"动作的持续时间 (毫秒)', _ms_check
    )
    exitBedroomDoorBackTime: int = _opt(
        1500, '生活层进行"走出个人空间的门"动作时，向右后方移动的持续时间 (毫秒)', _ms_check
    )
    exitBedroomDoorForwardTime: int = _opt(
        1000, '生活层进行"走出个人空间的门"动作时，向右前方移动的持续时间 (毫秒)', _ms_check
    )
    walkToStairwellTime: int = _opt(700, '生活层进行"走到楼梯门口"动作的持续时间 (毫秒)', _ms_check)
    enterStairwellTime: int = _opt(2300, '生活层进行"走进楼梯门"动作的持续时间 (毫秒)', _ms_check)
    goDownFirstStairFlightTime: int = _opt(4000, '楼梯间进行"走前半截楼梯"动作的持续时间 (毫秒)', _ms_check)
    crossStairLandingTime: int = _opt(1500, '楼梯间进行"穿过楼梯中间的平台"动作的持续时间 (毫秒)', _ms_check)
    goDownSecondStairFlightTime: int = _opt(4500, '楼梯间进行"走后半截楼梯"动作的持续时间 (毫秒)', _ms_check)
    exitStairwellTime: int = _opt(1000, '差事层进行"走出楼梯间"动作的持续时间 (毫秒)', _ms_check)
    crossAisleTime: int = _opt(4250, '差事层进行"穿过走廊"动作的持续时间 (毫秒)', _ms_check)
    moveTimeFindJob: int = _opt(350, '差事层进行"寻找差事黄圈"动作时 每次移动的持续时间 (毫秒)', _ms_check)

    # ---- 差事流程超时 (秒) ----
    lobbyCheckLoopTime: int = _opt(
        1, "差事面板玩家加入状态检测间隔时间 (秒)", _check_range(minimum=1, unit=" 秒")
    )
    matchPanelTimeout: int = _opt(180, "面板无人加入时重开时间 (秒)", _check_range(minimum=1, unit=" 秒"))
    playerJoiningTimeout: int = _opt(
        60, "等待正在加入玩家超时重开时间 (秒)", _check_range(minimum=1, unit=" 秒")
    )
    startMatchDelay: int = _opt(15, "开始差事等待延迟 (秒)", _check_range(minimum=0, unit=" 秒"))
    exitMatchTimeout: int = _opt(
        120,
        "等待差事启动落地超时时间 (秒)(防止卡在启动战局中)",
        _check_range(minimum=1, unit=" 秒"),
    )
    respawnInAgencyTimeout: int = _opt(
        120,
        "等待在事务所复活超时时间 (秒)(防止切换战局时卡云)",
        _check_range(minimum=1, unit=" 秒"),
    )
    onlineModeLoadingTimeout: int = _opt(
        300,
        "等待从线下进入线上和通过Steam加入战局落地超时时间 (秒)(防止在线模式加载时卡云)",
        _check_range(minimum=1, unit=" 秒"),
    )

    # ---- OCR ----
    ocrArgs: str = _opt(
        r'--models=".\models" --det=ch_PP-OCRv4_det_infer.onnx --cls=ch_ppocr_mobile_v2.0_cls_infer.onnx --rec=rec_ch_PP-OCRv4_infer.onnx --keys=dict_chinese.txt --padding=70 --maxSideLen=1024 --boxScoreThresh=0.5 --boxThresh=0.3 --unClipRatio=1.6 --doAngle=0 --mostAngle=0 --numThread=1',
        "RapidOCR的启动参数",
        _check_not_empty("OCR 启动参数"),
    )

    # ---- 发送到 Steam 群组的消息 (设置为空字符串则不发这条消息) ----
    msgOpenJobPanel: str = _opt(
        "德瑞差事已启动，请先看教程，学会卡CEO和卡单再进。如果无法连接请再试一次，bot没加速器网不好",
        "开好面板时发的消息 (设置为空字符串则不发这条消息)",
    )
    msgMatchPanelTimeout: str = _opt(
        "一直没有玩家加入，重新启动中", "没人加入超时重开时发的消息 (设置为空字符串则不发这条消息)"
    )
    msgPlayerJoiningTimeout: str = _opt(
        "任务中含有卡B，重新启动中", "有人卡在正在加入超时重开时发的消息 (设置为空字符串则不发这条消息)"
    )
    msgTeamFull: str = _opt("满了，请等下一班车", "满人时发的消息 (设置为空字符串则不发这条消息)")
    msgJobStarting: str = _opt(
        "即将发车，请在听到“咚”的一声后卡单",
        "差事启动时发的消息 (设置为空字符串则不发这条消息)",
    )
    msgJobStartFail: str = _opt(
        "启动差事失败，请等下一班车", "差事启动失败时发的消息 (设置为空字符串则不发这条消息)"
    )
    msgDetectedSB: str = _opt(
        "有人没有卡单，请先阅读教程，了解Bot的使用方法后再使用本bot",
        "发现有人没卡单时发的消息 (设置为空字符串则不发这条消息)",
    )

    # ---- 运行期状态，不会写入配置文件 ----
    # 配置文件绝对路径
    config_filepath: Path = _runtime_state(BASE_DIR / "config.yaml")

    def __post_init__(self) -> None:
        """
        适用于 dataclass 的初始化方法
        """
        # 磁盘上的原始文档，用于在写回时保留用户的注释和自定义配置项
        self._raw_document: CommentedMap = CommentedMap()
        self._yaml = _new_yaml()
        # 是否需要把补全后的配置写回文件
        self._needs_write: bool = False
        # 需要由程序补上注释的配置项（新建文件时是全部，读取已有文件时只有文件里缺少的那些）
        # 已经存在于文件中的配置项一律保留文件里的注释，不会被程序改写
        self._keys_needing_comment: set[str] = {spec.name for spec in self._schema_fields()}
        # 写入的目标文件是否还不存在（或内容为空），此时会额外写上文件开头的说明
        self._is_new_file: bool = True

        # 检查配置项是否合法
        self.validate()

    @classmethod
    def load(cls, config_filepath: Optional[str | Path] = None) -> "Config":
        """
        读取配置文件并返回配置对象。

        文件不存在时会按默认值创建一份带注释的配置；文件缺少某些配置项时会用默认值补全，
        并把补全后的内容写回文件。

        :param config_filepath: 配置文件路径。相对路径会以**程序所在目录**为基准，而不是
            当前工作目录；为 ``None`` 时使用 ``<程序目录>/config.yaml``
        :raises ConfigParseError: 文件无法读取，或者不是合法的 YAML 键值对文档
        :raises ConfigValidationError: 存在类型或取值不合法的配置项
        """
        config = cls()
        config.config_filepath = cls._resolve_path(config_filepath)
        logger.info(f"正在从 '{config.config_filepath}' 加载配置文件...")
        config._read()
        config.validate()
        if config._needs_write:
            config.save()
        return config

    @staticmethod
    def _resolve_path(config_filepath: Optional[str | Path]) -> Path:
        """把配置文件路径解析成绝对路径，相对路径以程序所在目录为基准。"""
        if config_filepath is None:
            return BASE_DIR / "config.yaml"
        path = Path(config_filepath).expanduser()
        if not path.is_absolute():
            path = BASE_DIR / path
        return path.resolve()

    def _read(self) -> None:
        """把配置文件的内容读进本对象，并记录是否需要把补全结果写回文件。"""
        document = self._load_document()
        schema = self._schema_fields()
        known_names = {spec.name for spec in schema}

        # 文件不存在时 document 为 None，此时所有配置项都使用默认值
        self._raw_document = document if document is not None else CommentedMap()
        self._is_new_file = document is None or len(document) == 0
        self._needs_write = document is None

        missing = []
        for spec in schema:
            if document is not None and spec.name in document:
                value, note = _coerce_value(spec, document[spec.name])
                if note is not None:
                    logger.warning(note)
                    self._needs_write = True
            else:
                value = spec.default
                missing.append(spec.name)
                self._needs_write = True
            setattr(self, spec.name, value)

        if missing:
            logger.info(f"配置文件缺少以下配置项，将用默认值补全: {', '.join(missing)}")
        self._keys_needing_comment = set(missing)

        if document is not None:
            unknown = sorted(set(document) - known_names)
            if unknown:
                logger.warning(
                    "配置文件中的以下配置项不是本程序支持的配置项，将被忽略"
                    f"（但会原样保留在文件中）: {', '.join(unknown)}"
                )

    def _load_document(self) -> Optional[CommentedMap]:
        """
        读取并解析配置文件。

        :return: 解析得到的文档；文件不存在时返回 ``None``
        :raises ConfigParseError: 文件无法读取，或者不是 YAML 键值对文档
        """
        if self.config_filepath.is_dir():
            raise ConfigParseError(f"配置文件路径 '{self.config_filepath}' 是一个文件夹，不是一个文件。")

        try:
            with open(self.config_filepath, encoding="utf-8") as f:
                document = self._yaml.load(f)
        except FileNotFoundError:
            logger.info(f"未找到配置文件 '{self.config_filepath}'，将按默认值创建一个新的。")
            return None
        except OSError as e:
            raise ConfigParseError(f"无法读取配置文件 '{self.config_filepath}': {e}") from e
        except YAMLError as e:
            raise ConfigParseError(f"配置文件 '{self.config_filepath}' 不是合法的 YAML: {e}") from e

        if document is None:
            logger.warning(f"配置文件 '{self.config_filepath}' 是空的。")
            return CommentedMap()
        if not isinstance(document, CommentedMap):
            raise ConfigParseError(
                f"配置文件 '{self.config_filepath}' 的顶层必须是一组 '配置项: 值'，而不是 {type(document).__name__}。"
            )
        return document

    def validate(self) -> None:
        """
        检查全部配置项的类型和取值范围。

        :raises ConfigValidationError: 存在不合法的配置项，异常信息中会一次性列出全部问题
        """
        problems = []
        for spec in self._schema_fields():
            value = getattr(self, spec.name)

            kind = _declared_kind(spec)
            if kind is not None and not _matches_type(value, kind):
                problems.append(f"  - {spec.name}: 应为{_TYPE_NAMES[kind]}，当前为 {value!r}")
                continue

            check = spec.metadata.get("check")
            if check is not None:
                problem = check(value)
                if problem is not None:
                    problems.append(f"  - {spec.name}: {problem}")

        # 只有启用 useAlterMessagingMethod 时才检查 AlterMessagingMethodWindowTitle
        if self.useAlterMessagingMethod and not self.AlterMessagingMethodWindowTitle.strip():
            problems.append(
                "  - AlterMessagingMethodWindowTitle: 启用 useAlterMessagingMethod 时不能为空，否则会匹配到任意窗口"
            )

        if problems:
            raise ConfigValidationError(
                f"配置文件 {self.config_filepath} 中存在 {len(problems)} 处不合法配置:\n"
                + "\n".join(problems)
            )

    def save(self, config_filepath: Optional[str | Path] = None) -> bool:
        """
        把当前配置写回配置文件。

        只修改配置值，不影响用户注释和未定义的配置项。

        :param config_filepath: 写入的目标路径，默认为本对象正在使用的配置文件
        :return bool: 写入成功返回 ``True``，写入失败返回 ``False``
        """
        target = self.config_filepath if config_filepath is None else self._resolve_path(config_filepath)

        document = self._raw_document
        for spec in self._schema_fields():
            document[spec.name] = getattr(self, spec.name)
            if spec.name in self._keys_needing_comment:
                document.yaml_set_comment_before_after_key(spec.name, before=spec.metadata["comment"])

        if self._is_new_file:
            document.yaml_set_start_comment(_FILE_HEADER)

        try:
            # 使用 Windows 风格的换行符
            with open(target, "w", encoding="utf-8", newline="\n") as f:
                self._yaml.dump(document, f)
        except OSError as e:
            logger.error(f"无法写入配置文件 '{target}': {e}")
            logger.error("程序会继续使用内存中的配置，但本次的改动在退出后会丢失。")
            return False

        logger.info(f"配置已写入 '{target}'。")
        return True

    @classmethod
    def _schema_fields(cls) -> list[Field]:
        """返回所有会写入配置文件的字段，顺序与声明顺序一致。"""
        return [spec for spec in dataclass_fields(cls) if spec.metadata.get("yaml")]


def _new_yaml() -> YAML:
    """创建一个写配置文件用的 YAML 实例。"""
    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    # 保留用户自己书写的引号，避免写回时把整个文件重新格式化
    yaml.preserve_quotes = True
    return yaml


def main() -> int:
    """
    按当前 schema 生成一份带注释的配置文件。

    用法::

        python config.py [目标文件]

    不指定目标文件时写入 ``<程序目录>/config.yaml.example``。
    """
    config = Config()
    target = sys.argv[1] if len(sys.argv) > 1 else "config.yaml.example"
    if not config.save(target):
        return 1
    print(f"已生成配置文件 {config.config_filepath if Path(target).is_absolute() else BASE_DIR / target}")
    return 0


if __name__ == "__main__":
    ret_code = main()
    sys.exit(ret_code)
