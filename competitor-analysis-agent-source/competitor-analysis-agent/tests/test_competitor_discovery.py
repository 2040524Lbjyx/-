"""Discovery must retain search evidence and reject invented candidates (no network)."""
import importlib.util
import json
import unittest


RESULTS = [
    {"title": "Notion alternatives: Obsidian and Anytype", "link": "https://review.example.com/notes", "snippet": "Obsidian supports local notes. Anytype offers team knowledge management."},
    {"title": "Obsidian", "link": "https://obsidian.md/", "snippet": "Obsidian: local knowledge management."},
]


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec("services.competitor_discovery"), "Missing competitor discovery service")
        from services.competitor_discovery import CompetitorDiscovery
        self.cls = CompetitorDiscovery

    def service(self, candidates, results=None):
        return self.cls(search=lambda query, num_results: RESULTS if results is None else results,
                        summarize=lambda prompt: json.dumps({"candidates": candidates}))

    def test_returns_only_named_candidates_with_actual_search_evidence(self):
        service = self.service([
            {"name": "Obsidian", "reason": "本地知识管理与笔记需求相近", "source_ids": [1, 2]},
            {"name": "Invented", "reason": "模型臆造", "source_ids": [1]},
            {"name": "Anytype", "reason": "伪造来源", "source_ids": [99]},
            {"name": "Notion", "reason": "自身产品", "source_ids": [1]},
            {"name": "obsidian", "reason": "重复", "source_ids": [2]},
        ])
        result = service.discover("notion.so", "团队知识管理", product_name="Notion")
        self.assertEqual([c["name"] for c in result], ["Obsidian"])
        self.assertEqual(result[0]["sources"][0]["url"], "https://review.example.com/notes")
        self.assertIn("Obsidian supports", result[0]["sources"][0]["snippet"])

    def test_url_only_and_description_only_are_supported(self):
        for url, description in [("notion.so", ""), ("", "团队知识管理")]:
            with self.subTest(url=url):
                service = self.service([{"name": "Anytype", "reason": "知识管理", "source_ids": [1]}])
                self.assertEqual(service.discover(url, description)[0]["name"], "Anytype")

    def test_invalid_input_never_starts_external_calls(self):
        def unexpected(*args, **kwargs):
            self.fail("Invalid input triggered an external request")
        service = self.cls(search=unexpected, summarize=unexpected)
        for url, description in [("", " "), ("javascript:alert(1)", "notes"), ("http://localhost", "notes")]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                service.discover(url, description)

    def test_search_failure_does_not_fall_back_to_model_memory(self):
        def unexpected(prompt):
            self.fail("No evidence must not trigger model synthesis")
        service = self.cls(search=lambda *a, **k: [], summarize=unexpected)
        with self.assertRaisesRegex(ValueError, "搜索"):
            service.discover("", "团队知识管理")

    def test_malformed_model_output_is_actionable_error(self):
        service = self.cls(search=lambda *a, **k: RESULTS, summarize=lambda p: "not json")
        with self.assertRaisesRegex(ValueError, "候选"):
            service.discover("", "团队知识管理")

    def test_search_handles_product_descriptions_with_slashes(self):
        from unittest.mock import patch, Mock
        from services.search_service import SearchService
        response = Mock()
        response.text = '<div class="vrwrap"><h3><a href="https://obsidian.md">Obsidian</a></h3><p>本地笔记</p></div>'
        # A description is search text, not a filesystem path.
        with patch("services.search_service.requests.get", return_value=response):
            results = SearchService().search("团队文档/知识管理 alternatives")
        self.assertEqual([r["link"] for r in results], ["https://obsidian.md"])

    def test_backup_search_provides_evidence_when_primary_has_no_results(self):
        from unittest.mock import patch, Mock
        primary = Mock()
        primary.search.return_value = []
        response = Mock()
        response.content = b'<rss><channel><item><title>Obsidian alternatives</title><link>https://review.example.com/notes</link><description>Obsidian supports local notes</description></item></channel></rss>'
        service = self.cls(summarize=lambda p: '{"candidates":[{"name":"Obsidian","reason":"local notes","source_ids":[1]}]}')
        with patch("services.search_service.get_search_service", return_value=primary), patch("requests.get", return_value=response):
            result = service.discover("notion.so", "")
        self.assertEqual(result[0]["sources"][0]["url"], "https://review.example.com/notes")

    def test_configured_exa_returns_sources_without_scraping_search_pages(self):
        import inspect
        from unittest.mock import patch, Mock
        self.assertIn("exa_api_key", inspect.signature(self.cls).parameters, "Missing structured search provider")
        response = Mock()
        response.json.return_value = {"results": [{"title": "Obsidian alternatives", "url": "https://review.example.com/notes", "text": "Obsidian supports local notes"}]}
        service = self.cls(exa_api_key="test-key", summarize=lambda p: '{"candidates":[{"name":"Obsidian","reason":"local notes","source_ids":[1]}]}')
        with patch("requests.post", return_value=response), patch("requests.get", side_effect=AssertionError("Unexpected public search")):
            result = service.discover("notion.so", "")
        self.assertEqual(result[0]["name"], "Obsidian")
        self.assertEqual(result[0]["sources"][0]["snippet"], "Obsidian supports local notes")


if __name__ == "__main__":
    unittest.main()
