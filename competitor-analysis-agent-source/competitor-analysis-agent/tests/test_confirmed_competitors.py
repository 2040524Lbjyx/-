"""User-confirmed names must survive LLM parsing and network fallback."""
import unittest
from langchain_core.runnables import RunnableLambda
from langchain_core.messages import AIMessage
from agents.coordinator import CoordinatorAgent


class ConfirmedCompetitorTests(unittest.TestCase):
    def test_run_carries_confirmed_names_into_workflow_state(self):
        from types import SimpleNamespace
        agent = CoordinatorAgent.__new__(CoordinatorAgent)
        # Terminal test graph echoes state; the real run method must pass confirmation.
        def terminal(state):
            return {**state, "competitors": state.get("confirmed_competitors", []),
                    "crawled_data": {}, "analysis_results": {}, "report_path": "test.md"}
        agent.workflow = SimpleNamespace(invoke=terminal)
        result = agent.run("分析产品", confirmed_competitors=["Foo Bar", "Anytype"])
        self.assertEqual(result["competitors"], ["Foo Bar", "Anytype"])

    def test_model_cannot_replace_confirmed_products(self):
        agent = CoordinatorAgent.__new__(CoordinatorAgent)
        agent.llm = RunnableLambda(lambda _: AIMessage(content='{"competitors":["Wrong"],"dimensions":["pricing"]}'))
        result = agent._understand_intent({"user_query": "分析 Foo Bar 和 Anytype", "confirmed_competitors": ["Foo Bar", "Anytype"], "errors": []})
        self.assertEqual(result["competitors"], ["Foo Bar", "Anytype"])
        self.assertEqual(result["dimensions"], ["pricing"])

    def test_llm_failure_keeps_multiword_product_names(self):
        def fail(_):
            raise ConnectionError("offline")
        agent = CoordinatorAgent.__new__(CoordinatorAgent)
        agent.llm = RunnableLambda(fail)
        result = agent._understand_intent({"user_query": "分析 Foo Bar 和 Anytype", "confirmed_competitors": ["Foo Bar", "Anytype"], "errors": []})
        self.assertEqual(result["competitors"], ["Foo Bar", "Anytype"])


if __name__ == "__main__":
    unittest.main()
