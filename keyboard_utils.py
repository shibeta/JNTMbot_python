import threading
import time
from typing import Any, List, Optional, Set, Tuple, Union, Callable, Dict
from pynput.keyboard import Controller, KeyCode, Key, GlobalHotKeys

from app_lifecycle import sleep_stoppable as sleep, is_exiting
from logger import get_logger

logger = get_logger(__name__)


class KeyboardSimulator:
    """
    用于模拟键盘按键操作的类。

    该类封装了 pynput.keyboard.Controller，并维护了一个线程安全的、
    当前已按下按键的集合。在程序退出时，会自动释放所有已按下的按键，
    防止按键卡住。
    """

    # 定义一个类型别名，方便注解
    KeyType = Union[KeyCode, Key, str]

    def __init__(self):
        """
        初始化 KeyboardSimulator 实例。
        """
        # 键盘控制器实例
        self._controller: Controller = Controller()

        # 记录当前通过此实例按下的按键集合
        self._pressed_keys: Set[KeyboardSimulator.KeyType] = set()

        # 用于保护 _pressed_keys 集合的线程锁
        self._lock: threading.Lock = threading.Lock()

    def press(self, key: KeyType) -> None:
        """
        模拟按下指定的按键。

        :param key: 要按下的键 (pynput.Key, pynput.KeyCode 或 str)。
        """
        with self._lock:
            self._controller.press(key)
            if key not in self._pressed_keys:
                self._pressed_keys.add(key)

    def release(self, key: KeyType) -> None:
        """
        模拟释放指定的按键。

        :param key: 要释放的键。
        """
        with self._lock:
            try:
                # 即使释放失败或按键未被按下，也尝试执行清理
                self._controller.release(key)
            finally:
                if key in self._pressed_keys:
                    self._pressed_keys.remove(key)

    def click(self, keys: Union[KeyType, List[KeyType], Tuple[KeyType, ...]], milliseconds: int = 90) -> None:
        """
        模拟单击指定的单个或多个按键（按下后释放）。

        - 如果 keys 是单个按键，则模拟单击该键。
        - 如果 keys 是一个列表或元组，则依次按下所有键，然后以相反的顺序释放它们。

        :param keys: 要单击的单个键或多个键的列表/元组。
        :param milliseconds: 按下和释放之间的延迟毫秒数。
        """
        # 判断是单个按键还是按键列表
        is_single_key = not isinstance(keys, (list, tuple))

        keys_to_process = [keys] if is_single_key else keys

        if not keys_to_process:
            return  # 如果列表为空，则不执行任何操作

        # 依次按下所有按键
        for key in keys_to_process:
            self.press(key)

        sleep(milliseconds / 1000.0)

        # 以相反的顺序释放所有按键 (这对于组合键非常重要)
        for key in reversed(keys_to_process):
            self.release(key)

    def hotkey(self, *keys: KeyType, milliseconds: int = 90) -> None:
        """
        一个更方便的语法糖，用于模拟组合键单击。

        它会按下所有传入的按键，等待片刻，然后以相反的顺序释放它们。
        示例: hotkey(Key.ctrl, 'c')

        :param *keys: 要同时按下的多个按键。
        :param milliseconds: 按下和释放之间的延迟毫秒数。
        """
        if not keys:
            return

        # 直接调用 click 方法并传入按键元组
        self.click(keys, milliseconds=milliseconds)

    def release_all(self) -> None:
        """
        释放当前实例记录的所有已按下按键。
        """
        with self._lock:
            # 复制一份当前按下的按键列表，以安全地遍历
            keys_to_release = list(self._pressed_keys)

            for key in keys_to_release:
                try:
                    self._controller.release(key)
                except Exception as e:
                    print(f"释放按键失败: {e}")

            # 清空集合
            self._pressed_keys.clear()

    @property
    def pressed_keys(self) -> Set[KeyType]:
        """
        返回当前已按下按键集合的副本（线程安全）。

        :return: 一个包含当前按下按键的集合。
        """
        with self._lock:
            return self._pressed_keys.copy()

    def type_string(self, text: str, delay: float = 0.01) -> None:
        """
        模拟输入字符串。

        :param text: 要输入的字符串。
        :param delay: 每个字符按下和释放后的延迟（秒）。
        """
        for char in text:
            self.press(char)
            sleep(delay)
            self.release(char)
            sleep(delay)


class HotKeyManager:
    """
    一个用于管理全局热键的类，基于 pynput.keyboard.GlobalHotKeys。

    该类在一个独立的后台线程中运行监听器。
    它支持在运行时动态地添加和移除热键。
    """

    def __init__(self, enable: bool = True, debounce_interval: float = 0.1, refresh_interval: float = 3600.0):
        """
        初始化 HotKeyManager 实例。

        :param bool enable: 是否立刻启动热键监听器。默认启用
        :param float debounce_interval: 防抖时间间隔（秒），在此时间内重复触发将被忽略。默认 0.1 秒。
        :param float refresh_interval: 自动刷新底层Hook的间隔时间（秒）。默认 3600 秒。
        """
        # 是否启用
        self.enable: bool = enable
        # 防抖间隔 (秒)
        self.debounce_interval: float = debounce_interval

        # 热键字符串到回调函数的映射
        self._hotkeys: Dict[str, Callable[[], Any]] = {}
        # GlobalHotKeys 对象，支持部分 threading.Thread 的特性
        self._listener: GlobalHotKeys | None = None
        # GlobalHotKeys 对象的锁
        self._listener_lock: threading.Lock = threading.Lock()

        # 看门狗对象: 用于定时重启全局热键
        self._watchdog_thread: threading.Thread | None = None
        # 重启全局热键的间隔 (秒)
        self._watchdog_refresh_interval: float = refresh_interval
        # 看门狗停止信号
        self._watchdog_stop_event: threading.Event = threading.Event()
        # 看门狗对象的锁
        self._watchdog_lock: threading.Lock = threading.Lock()

    def __update_listener_unsafe(self) -> None:
        """
        根据热键字典和使能状态，更新监听器:
        - 如果启用且有热键，则运行监听器。
        - 如果禁用或没有热键，则停止监听器。

        这个方法是线程不安全的，请确保已经获取了 self._listener_lock 。
        """
        # 停止现有的监听器
        if self._listener is not None:
            try:
                self._listener.stop()
                # 如果当前线程不是 _listener 自身，等待线程停止
                # 不检查会导致将 `__update_listener_unsafe()` 绑定到热键时，发生死锁
                if threading.current_thread() is not self._listener:
                    self._listener.join(2.0)
            except Exception as e:
                logger.error(f"停止旧热键监听器时发生异常: {e}")

        # 如果启用且有热键，则启动新的监听器
        if self.enable and self._hotkeys:
            self._listener = GlobalHotKeys(self._hotkeys, daemon=True)
            self._listener.start()
        else:
            self._listener = None

    def _watchdog_loop(self):
        """看门狗循环：定期刷新监听器以应对远程桌面导致的 Hook 丢失"""
        logger.debug("看门狗线程已启动。")
        # 同时等待看门狗停止信号和程序停止信号
        while not self._watchdog_stop_event.is_set() and not is_exiting():
            # 休眠目标时间，避免循环漂移
            target_wakeup_time = time.monotonic() + self._watchdog_refresh_interval
            # 休眠是否被打断
            is_interrupted = False

            while time.monotonic() < target_wakeup_time:
                # 检查看门狗自身的停止信号
                if self._watchdog_stop_event.is_set():
                    is_interrupted = True
                    break

                # 每次休眠 1 秒
                remaining = target_wakeup_time - time.monotonic()
                sleep_duration = min(remaining, 1.0)

                if sleep_duration > 0:
                    # sleep 本身就会等待程序停止信号，是无延迟的
                    if not sleep(sleep_duration):
                        is_interrupted = True
                        break

            # 如果休眠被打断，说明接收到了停止信号，结束线程
            if is_interrupted:
                break

            # 如果未被打断则执行热键监听器刷新
            with self._listener_lock:
                if self.enable and self._hotkeys:
                    logger.debug("执行例行热键监听器刷新，防止 Hook 失效。")
                    self.__update_listener_unsafe()

        logger.debug("看门狗线程已退出。")

    def start(self):
        """
        启动热键管理器服务和看门狗，开始监听管理的热键。
        """
        with self._listener_lock:
            self.enable = True
            self.__update_listener_unsafe()
            logger.debug("全局热键监听器已启动。")

        with self._watchdog_lock:
            if self._watchdog_thread is None or not self._watchdog_thread.is_alive():
                self._watchdog_stop_event.clear()
                self._watchdog_thread = threading.Thread(
                    target=self._watchdog_loop, name="HotKey_Watchdog", daemon=True
                )
                self._watchdog_thread.start()

    def stop(self):
        """
        停止热键管理器服务和看门狗，并释放所有资源。
        """
        self._watchdog_stop_event.set()

        with self._listener_lock:
            self.enable = False
            self.__update_listener_unsafe()

        with self._watchdog_lock:
            if self._watchdog_thread is not None and self._watchdog_thread.is_alive():
                self._watchdog_thread.join(timeout=1.0)
                self._watchdog_thread = None

    def update_listener(self):
        """供批量操作后手动刷新监听器使用"""
        with self._listener_lock:
            if self.enable:
                self.__update_listener_unsafe()

    def add_hotkey(
        self,
        hotkey: str,
        callback: Callable[[], Any],
        debounce: Optional[float] = None,
        auto_update: bool = True,
    ):
        """
        添加或更新一个全局热键。
        需要重启热键监听器，才能使用新的热键。

        :param hotkey: 热键字符串, 比如 "<ctrl>+<alt>+h"
        :param callback: 绑定至热键的无参回调函数, 有参的调用请通过 partial 包装
        :param debounce: (可选) 防抖时间(秒)
        :param auto_update: (可选) 是否立即重启监听器。如果需要连续添加多个热键，建议设为 False，最后手动刷新。
        """
        # 如果未传入防抖时间，使用 self 中定义的全局防抖时间
        debounce_interval = debounce if debounce is not None else self.debounce_interval

        # 初始化该热键的上一次触发时间
        last_triggered = 0.0

        # 为回调函数创建包装函数，添加防抖和异常捕获
        def callback_warpper():
            # 使用 nonlocal 实现可变对象
            nonlocal last_triggered
            current_time = time.monotonic()
            # 防抖检查: 距离上次执行时间是否超过防抖阈值
            if current_time - last_triggered < debounce_interval:
                # 未超过防抖阈值直接返回
                return

            # 更新上次执行时间
            last_triggered = current_time

            try:
                callback()
            except Exception as e:
                # 防止回调报错导致监听线程崩溃
                logger.error(f"执行热键 {hotkey} 绑定的函数时发生错误: {e}", exc_info=e)

        # 添加包装函数到热键映射
        with self._listener_lock:
            self._hotkeys[hotkey] = callback_warpper
            # 如果启动了监听器，并且请求立即刷新，更新监听器
            if self.enable and auto_update:
                self.__update_listener_unsafe()

    def remove_hotkey(self, hotkey: str):
        """
        移除一个已注册的全局热键，并重启监听器。

        :param hotkey: 热键字符串, 比如 "<ctrl>+<alt>+h"
        """
        with self._listener_lock:
            if hotkey in self._hotkeys:
                self._hotkeys.pop(hotkey)
            # 如果启用，更新监听器
            if self.enable:
                self.__update_listener_unsafe()

    def clear_hotkey(self):
        """
        移除所有已注册的全局热键，并重启监听器。
        """
        with self._listener_lock:
            self._hotkeys = {}
            # 如果启用，更新监听器
            if self.enable:
                self.__update_listener_unsafe()
