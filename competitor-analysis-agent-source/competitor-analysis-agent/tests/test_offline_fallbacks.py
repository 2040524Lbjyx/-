"""无网络/LLM 故障时的竞品识别与品类降级测试。"""

from langchain_core.runnables import RunnableLambda

from agents.analyzer import AnalysisAgent, _infer_category_from_product_name
from agents.coordinator import CoordinatorAgent
from agents.crawler import _infer_category_from_product_name as crawler_category


def _connection_error(_):
    raise ConnectionError("simulated connection error")


def test_known_short_video_products_keep_short_video_dimensions_when_llm_fails():
    analyzer = AnalysisAgent.__new__(AnalysisAgent)
    analyzer.llm_extract = RunnableLambda(_connection_error)

    matrix = analyzer._llm_fallback_compare(
        ["抖音", "快手"],
        competitors_data={"抖音": {}, "快手": {}},
    )

    assert "短视频拍摄" in matrix["功能"].tolist()
    assert "文档编辑" not in matrix["功能"].tolist()
    assert set(matrix["抖音"].tolist()) == {"⚠️"}
    assert matrix.attrs["source"] == "llm_fallback"


def test_intent_connection_failure_uses_local_rule_without_marking_task_failed():
    coordinator = CoordinatorAgent.__new__(CoordinatorAgent)
    coordinator.llm = RunnableLambda(_connection_error)
    coordinator._log = lambda _message: None
    coordinator._report = lambda _progress, _message: None
    state = {"user_query": "分析抖音和快手", "errors": []}

    result = coordinator._understand_intent(state)

    assert result["competitors"] == ["抖音", "快手"]
    assert result["dimensions"] == ["features", "pricing"]
    assert result["errors"] == []


def test_known_product_category_hints_are_consistent_across_agents():
    assert _infer_category_from_product_name("抖音") == "短视频"
    assert crawler_category("快手") == "短视频"
