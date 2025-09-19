import atexit
import threading
import time
from typing import List, Set, Tuple, Union
from pynput.keyboard import Controller, KeyCode, Key


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

        # 注册程序退出时的清理函数
        atexit.register(self._release_all_on_exit)

    def press(self, key: KeyType) -> None:
        """
        模拟按下指定的按键。

        Args:
            key: 要按下的键 (pynput.Key, pynput.KeyCode 或 str)。
        """
        with self._lock:
            self._controller.press(key)
            if key not in self._pressed_keys:
                self._pressed_keys.add(key)

    def release(self, key: KeyType) -> None:
        """
        模拟释放指定的按键。

        Args:
            key: 要释放的键。
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

        Args:
            keys: 要单击的单个键或多个键的列表/元组。
            milliseconds: 按下和释放之间的延迟毫秒数。
        """
        # 判断是单个按键还是按键列表
        is_single_key = not isinstance(keys, (list, tuple))

        keys_to_process = [keys] if is_single_key else keys

        if not keys_to_process:
            return  # 如果列表为空，则不执行任何操作

        # 依次按下所有按键
        for key in keys_to_process:
            self.press(key)

        time.sleep(milliseconds / 1000.0)

        # 以相反的顺序释放所有按键 (这对于组合键非常重要)
        for key in reversed(keys_to_process):
            self.release(key)

    def hotkey(self, *keys: KeyType, milliseconds: int = 90) -> None:
        """
        一个更方便的语法糖，用于模拟组合键单击。

        它会按下所有传入的按键，等待片刻，然后以相反的顺序释放它们。
        示例: hotkey(Key.ctrl, 'c')

        Args:
            *keys: 要同时按下的多个按键。
            milliseconds: 按下和释放之间的延迟毫秒数。
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
                    print(f"Releasing key failed: {e}")

            # 清空集合
            self._pressed_keys.clear()

    def _release_all_on_exit(self) -> None:
        """
        供 atexit 调用的内部方法，用于在程序退出时释放所有按键。
        """
        self.release_all()

    @property
    def pressed_keys(self) -> Set[KeyType]:
        """
        返回当前已按下按键集合的副本（线程安全）。

        Returns:
            一个包含当前按下按键的集合。
        """
        with self._lock:
            return self._pressed_keys.copy()

    def type_string(self, text: str, delay: float = 0.01) -> None:
        """
        模拟输入字符串。

        Args:
            text: 要输入的字符串。
            delay: 每个字符按下和释放后的延迟（秒）。
        """
        for char in text:
            self.press(char)
            time.sleep(delay)
            self.release(char)
            time.sleep(delay)
