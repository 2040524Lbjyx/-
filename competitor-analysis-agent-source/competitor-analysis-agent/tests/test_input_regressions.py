"""用户输入、示例切换与演示结果的回归测试，不调用外部 LLM。"""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest
from agents.coordinator import CoordinatorAgent


@pytest.mark.parametrize("query,expected", [
    ("分析Notion和Obsidian的功能和定价", ["Notion", "Obsidian"]),
    ("Notion vs Obsidian", ["Notion", "Obsidian"]),
    ("比较 Notion VS. Obsidian", ["Notion", "Obsidian"]),
    ("分析抖音和快手。分析目的：版本规划；市场范围：中国大陆", ["抖音", "快手"]),
    ("分析飞书和企业微信", ["飞书", "企业微信"]),
    ("对比Figma、Sketch和Penpot", ["Figma", "Sketch", "Penpot"]),
])
def test_fallback_extracts_only_product_names(query, expected):
    assert CoordinatorAgent.__new__(CoordinatorAgent)._extract_competitors_fallback(query) == expected


@pytest.fixture
def app(monkeypatch):
    # 页面会主动初始化持久向量库；输入测试用空库隔离磁盘和模型下载。
    class EmptyStore:
        def __init__(self, **kwargs):
            pass
        def get_collection_stats(self):
            return {"total_competitors": 0}
    monkeypatch.setitem(sys.modules, "vector_store", SimpleNamespace(CompetitorVectorStore=EmptyStore))
    at = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60).run()
    assert not at.exception
    return at


def button(app, label):
    return next(b for b in app.button if b.label == label)


def test_example_replaces_existing_query(app):
    app.text_input(key="__user_query_input__").set_value("分析抖音和快手").run()
    button(app, "📝 Notion vs Obsidian").click().run()
    assert not app.exception
    assert app.text_input(key="__user_query_input__").value == "分析Notion和Obsidian"


def test_clearing_query_disables_analysis(app):
    button(app, "📝 Notion vs Obsidian").click().run()
    app.text_input(key="__user_query_input__").set_value("").run()
    assert not app.exception
    assert button(app, "🚀 开始分析").disabled
    assert not any("系统将分析" in item.value for item in app.info)


def test_demo_report_uses_only_requested_competitors(app):
    app.text_input(key="__user_query_input__").set_value("分析Notion和Obsidian的功能和定价").run()
    button(app, "🚀 开始分析").click().run()
    assert not app.exception
    result = app.session_state["last_result"]
    report = Path(result["report_path"])
    try:
        assert result["status"] == "success"
        assert result["competitors"] == ["Notion", "Obsidian"]
        assert "**竞品数量**: 2" in report.read_text(encoding="utf-8")
    finally:
        report.unlink()
