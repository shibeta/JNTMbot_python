"""``gta_automator.game_screen`` 的单元测试。

被测类通过依赖注入接收 OCR 函数（``OcrFuncProtocol``），因此这里不需要 mock
RapidOCR 本身：所有用例都传入一个 ``MagicMock`` 作为 OCR 桩，并断言它以正确的
截图区域参数被调用。
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest

from gta_automator.constant import PlayerLevel
from gta_automator.exception import GameState, UnexpectedGameState
from gta_automator.game_screen import GameScreen, GameScreenTextPatterns


@pytest.fixture
def process() -> MagicMock:
    process = MagicMock(name="GameProcess")
    process.hwnd = 12345
    process.pid = 678
    return process


@pytest.fixture
def screen(ocr_mock: MagicMock, process: MagicMock) -> GameScreen:
    return GameScreen(ocr_mock, process)


class TestOcrFuncProtocol:
    """OCR 注入接口的契约测试。"""

    def test_magicmock_is_callable_ocr_func(self, ocr_mock: MagicMock):
        """OCR 桩函数的签名应与协议一致，保证依赖注入可用。"""
        assert callable(ocr_mock)
        ocr_mock(
            hwnd=1,
            left=0.0,
            top=0.0,
            width=1.0,
            height=1.0,
            include_title_bar=False,
        )
        ocr_mock.assert_called_once_with(hwnd=1, left=0.0, top=0.0, width=1.0, height=1.0, include_title_bar=False)


class TestGameScreenTextPatterns:
    """文本模式编译辅助方法的边界条件。"""

    def test_compile_single_string_escapes_special_characters(self):
        pattern = GameScreenTextPatterns._compile_to_pattern("a.b")
        assert pattern.pattern == re.escape("a.b")
        assert pattern.search("a.b") is not None
        assert pattern.search("axb") is None

    def test_compile_string_without_escaping(self):
        pattern = GameScreenTextPatterns._compile_to_pattern("a.b", escape_spicial_character=False)
        assert pattern.search("axb") is not None

    def test_compile_list_joins_with_alternation(self):
        pattern = GameScreenTextPatterns._compile_to_pattern(["foo", "bar"])
        assert pattern.search("bar") is not None
        assert pattern.search("baz") is None

    def test_compile_empty_keywords_raises_value_error(self):
        with pytest.raises(ValueError):
            GameScreenTextPatterns._compile_to_pattern("")

    def test_compile_empty_list_raises_value_error(self):
        with pytest.raises(ValueError):
            GameScreenTextPatterns._compile_to_pattern([])

    def test_compile_list_with_non_string_raises_value_error(self):
        with pytest.raises(ValueError):
            GameScreenTextPatterns._compile_to_pattern(["ok", 1])


class TestOcrGameWindow:
    """``ocr_game_window`` 的参数透传与异常转换。"""

    def test_passes_region_to_ocr_func(self, screen: GameScreen, ocr_mock: MagicMock):
        ocr_mock.return_value = "识别结果"

        result = screen.ocr_game_window(0.1, 0.2, 0.3, 0.4)

        assert result == "识别结果"
        ocr_mock.assert_called_once_with(
            hwnd=12345,
            left=0.1,
            top=0.2,
            width=0.3,
            height=0.4,
            include_title_bar=False,
        )

    def test_raises_unexpected_game_state_when_hwnd_missing(self, screen: GameScreen, ocr_mock: MagicMock, process):
        process.hwnd = None

        with pytest.raises(UnexpectedGameState) as excinfo:
            screen.ocr_game_window(0, 0, 1, 1)

        assert excinfo.value.expected == GameState.ON
        assert excinfo.value.actual_state == GameState.OFF
        ocr_mock.assert_not_called()

    def test_raises_unexpected_game_state_when_hwnd_is_zero(self, screen: GameScreen, process):
        process.hwnd = 0

        with pytest.raises(UnexpectedGameState):
            screen.ocr_game_window(0, 0, 1, 1)

    def test_converts_value_error_to_unexpected_game_state(self, screen: GameScreen, ocr_mock: MagicMock):
        ocr_mock.side_effect = ValueError("坐标非法")

        with pytest.raises(UnexpectedGameState) as excinfo:
            screen.ocr_game_window(0, 0, 1, 1)

        assert excinfo.value.actual_state == GameState.OFF
        assert isinstance(excinfo.value.__cause__, ValueError)

    def test_propagates_other_exceptions(self, screen: GameScreen, ocr_mock: MagicMock):
        from ocr_utils import OcrError

        ocr_mock.side_effect = OcrError("引擎挂了")

        with pytest.raises(OcrError):
            screen.ocr_game_window(0, 0, 1, 1)


class TestSearchTextInText:
    """``_search_text_in_text`` 支持字符串、列表和正则。"""

    @pytest.mark.parametrize(
        ("query", "text", "expected"),
        [
            ("abc", "xxabcxx", True),
            ("abc", "xxxx", False),
            (["a", "b"], "只有b", True),
            (["x", "y"], "只有b", False),
            (("x", "y"), "只有y", True),
            (re.compile("a.c"), "a1c", True),
            (re.compile("a.c"), "axxc", False),
        ],
    )
    def test_search(self, screen: GameScreen, query, text: str, expected: bool):
        assert screen._search_text_in_text(text, query) is expected


class TestSearchText:
    """``search_text`` 的参数校验与 OCR 触发逻辑。"""

    def test_uses_provided_ocr_text_without_calling_ocr(self, screen: GameScreen, ocr_mock: MagicMock):
        assert screen.search_text("目标", "屏幕上有目标", 0, 0, 1, 1) is True
        ocr_mock.assert_not_called()

    def test_calls_ocr_when_text_is_none(self, screen: GameScreen, ocr_mock: MagicMock):
        ocr_mock.return_value = "目标出现了"

        assert screen.search_text("目标", None, 0.1, 0.2, 0.3, 0.4) is True
        ocr_mock.assert_called_once_with(
            hwnd=12345,
            left=0.1,
            top=0.2,
            width=0.3,
            height=0.4,
            include_title_bar=False,
        )

    @pytest.mark.parametrize("query", ["", [], (), re.compile("")])
    def test_empty_query_returns_false_without_ocr(self, screen: GameScreen, ocr_mock: MagicMock, query):
        assert screen.search_text(query, None, 0, 0, 1, 1) is False
        ocr_mock.assert_not_called()


class TestGetJobSetupStatus:
    """差事面板人数识别。"""

    def test_not_on_panel_returns_sentinels(self, screen: GameScreen):
        assert screen.get_job_setup_status("没有任何关键字的画面") == (False, -1, -1, -1)

    def test_on_panel_counts_players(self, screen: GameScreen):
        ocr_text = "浑球 办事 角色 正在加 正在加 离开 已加 已加 待命"

        assert screen.get_job_setup_status(ocr_text) == (True, 3, 2, 1)

    def test_on_panel_without_players(self, screen: GameScreen):
        assert screen.get_job_setup_status("浑球办事角色") == (True, 0, 0, 0)

    def test_ocr_region_when_text_not_provided(self, screen: GameScreen, ocr_mock: MagicMock):
        ocr_mock.return_value = "浑球"

        assert screen.get_job_setup_status() == (True, 0, 0, 0)
        ocr_mock.assert_called_once_with(hwnd=12345, left=0.5, top=0, width=0.5, height=1, include_title_bar=False)


class TestGetBadSportLevel:
    """恶意等级识别。"""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("清白玩家", PlayerLevel.CLEAN),
            ("问题玩家", PlayerLevel.DODGY),
            ("恶意玩家", PlayerLevel.BAD_SPORT),
            ("看不懂的东西", PlayerLevel.UNKNOWN),
        ],
    )
    def test_levels(self, screen: GameScreen, text: str, expected: PlayerLevel):
        assert screen.get_bad_sport_level_of_first_player_in_list(text) is expected

    def test_clean_takes_priority_over_others(self, screen: GameScreen):
        """同时出现多个关键字时，清白优先级最高（对应游戏内的判断顺序）。"""
        assert screen.get_bad_sport_level_of_first_player_in_list("清白 问题 恶意") is PlayerLevel.CLEAN

    def test_ocr_region_when_text_not_provided(self, screen: GameScreen, ocr_mock: MagicMock):
        ocr_mock.return_value = "问题玩家"

        assert screen.get_bad_sport_level_of_first_player_in_list() is PlayerLevel.DODGY
        ocr_mock.assert_called_once_with(hwnd=12345, left=0.5, top=0, width=0.5, height=0.5, include_title_bar=False)


class TestStatusChecksWithExplicitText:
    """各状态判断方法在直接传入 OCR 文本时的行为（不需要 OCR）。"""

    @pytest.mark.parametrize(
        ("method_name", "matching_text", "non_matching_text"),
        [
            ("is_on_mainmenu_brightness_or_warning_page", "请调整亮度", "别的东西"),
            ("is_on_mainmenu_gtaplus_advertisement_page", "查看导览", "别的东西"),
            ("is_on_mainmenu_logout", "您已登出", "别的东西"),
            ("is_on_mainmenu", "移动标签", "别的东西"),
            ("is_on_mainmenu_storymode_page", "故事模式", "别的东西"),
            ("is_on_onlinemode_info_panel", "在线模式", "别的东西"),
            ("is_respawned_in_agency", "从床上起来", "别的东西"),
            ("is_on_job_panel", "别惹德瑞", "别的东西"),
            ("is_on_first_job_setup_page", "设置 镜头 武器", "别的东西"),
            ("is_on_second_job_setup_page", "匹配 邀请 帮会", "别的东西"),
            ("is_on_scoreboard", "别惹 德瑞", "别的东西"),
            ("is_job_marker_found", "猎杀 约翰尼", "别的东西"),
            ("is_job_started", "前往 汇报 进度", "别的东西"),
            ("is_job_starting", "正在 启动 战局", "别的东西"),
            ("is_on_warning_page", "警告", "别的东西"),
            ("is_on_exit_confirm_page", "确认退出", "别的东西"),
            ("is_confirm_option_available", "是", "别的东西"),
            ("is_on_bad_pcsetting_warning_page", "目前无法载入数据", "别的东西"),
            ("is_on_online_service_policy_page", "在线服务政策", "别的东西"),
            ("is_on_privacy_policy_page", "隐私政策", "别的东西"),
            ("is_on_term_of_service_page", "服务条款", "别的东西"),
            ("is_on_pause_menu", "地图 职业 简讯", "别的东西"),
            ("is_on_story_pause_menu", "简讯 统计 设置", "别的东西"),
            ("is_on_online_pause_menu", "职业 好友 商店", "别的东西"),
            ("is_on_go_online_menu", "公开战局", "别的东西"),
        ],
    )
    def test_status_checks(self, screen: GameScreen, method_name: str, matching_text: str, non_matching_text: str):
        method = getattr(screen, method_name)

        assert method(matching_text) is True
        assert method(non_matching_text) is False

    def test_confirm_option_requires_keyword(self, screen: GameScreen):
        """ "是" / "否" 都不出现时不算确认选项。"""
        assert screen.is_confirm_option_available("普通文本内容") is False


class TestStatusChecksWithOcr:
    """状态判断方法未传入 OCR 文本时，应以正确区域调用 OCR。"""

    @pytest.mark.parametrize(
        ("method_name", "ocr_return", "expected_region"),
        [
            ("is_on_pause_menu", "地图", (0, 0.1, 0.5, 0.4)),
            ("is_on_job_panel", "搭档", (0, 0, 0.5, 0.5)),
            ("is_job_started", "团队", (0, 0.8, 1, 0.2)),
            ("is_on_warning_page", "注意", (0.25, 0, 0.5, 0.6)),
            ("is_on_first_job_setup_page", "武器", (0, 0, 1, 1)),
            ("is_on_online_pause_menu", "商店", (0, 0.1, 0.8, 0.4)),
        ],
    )
    def test_ocr_region(
        self,
        screen: GameScreen,
        ocr_mock: MagicMock,
        method_name: str,
        ocr_return: str,
        expected_region: tuple,
    ):
        ocr_mock.return_value = ocr_return

        assert getattr(screen, method_name)() is True
        ocr_mock.assert_called_once_with(
            hwnd=12345,
            left=expected_region[0],
            top=expected_region[1],
            width=expected_region[2],
            height=expected_region[3],
            include_title_bar=False,
        )


class TestIsOnlineServicePolicyLoaded:
    """在线服务政策页面的「已加载」判断需要同时命中两个关键字。"""

    def test_not_on_policy_page_returns_false(self, screen: GameScreen):
        assert screen.is_online_service_policy_loaded("完全无关的文本") is False

    def test_on_policy_page_but_not_loaded(self, screen: GameScreen):
        assert screen.is_online_service_policy_loaded("在线服务政策 请稍候") is False

    def test_loaded(self, screen: GameScreen):
        assert screen.is_online_service_policy_loaded("在线服务政策 想要阅读") is True

    def test_fetches_ocr_when_text_empty(self, screen: GameScreen, ocr_mock: MagicMock):
        ocr_mock.return_value = "在线服务政策 想要阅读"

        assert screen.is_online_service_policy_loaded() is True
        ocr_mock.assert_called_once_with(hwnd=12345, left=0, top=0, width=0.7, height=0.5, include_title_bar=False)

    def test_empty_ocr_result_returns_false(self, screen: GameScreen, ocr_mock: MagicMock):
        ocr_mock.return_value = ""

        assert screen.is_online_service_policy_loaded() is False
