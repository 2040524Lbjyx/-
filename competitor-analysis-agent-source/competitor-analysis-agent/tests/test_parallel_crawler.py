"""
并行爬取 smoke test:
- 不发起真实网络请求，不调用真实 LLM
- 用 monkey-patch 模拟 collect() 的耗时与返回值
- 验证：
  1) collect_many() 并发跑（总时长 << 串行）
  2) 结果完整（每个输入都有输出）
  3) 失败任务被捕获，不影响其他任务
  4) progress_callback 被正确调用
"""
import os
import sys
import time
import threading
import unittest
from unittest.mock import patch, MagicMock

# 让脚本直接执行时能 import agents.* / vector_store
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# 在 import agents.crawler 之前，先 patch 重型依赖 (ChatOpenAI)
# 注意：不要用 patch.dict(os.environ, ...) —— .env 文件可能让 os.environ 超过 32k 限制
with patch("langchain_openai.ChatOpenAI") as mock_llm:
    mock_llm.return_value = MagicMock()
    from agents.crawler import DataCollectionAgent


class FakeData:
    """模拟 collect() 返回的结构化数据"""
    @staticmethod
    def make(name: str) -> dict:
        return {
            "name": name,
            "website": f"https://www.{name.lower()}.com",
            "features": {"core": [f"core-{name}-1", f"core-{name}-2"], "advanced": []},
            "pricing": {"model": "subscription", "plans": []},
            "changelog": {"latest_version": None, "latest_release_date": None,
                          "recent_updates": [], "update_frequency": None},
            "company_info": {},
            "target_users": [],
            "platforms": [],
            "crawled_pages": [],
            "_source": "crawl",
        }


def slow_collect(self, name: str) -> dict:
    """模拟一次耗时 1.0s 的爬取"""
    time.sleep(1.0)
    return FakeData.make(name)


def failing_collect(self, name: str) -> dict:
    time.sleep(0.3)
    raise RuntimeError(f"模拟失败: {name}")


class TestParallelCollect(unittest.TestCase):

    def test_concurrent_speedup(self):
        """3 个任务，并发 3，总耗时应明显 < 3 秒（串行要 3s）"""
        with patch.object(DataCollectionAgent, "collect", slow_collect):
            crawler = DataCollectionAgent.__new__(DataCollectionAgent)
            crawler.llm = MagicMock()
            crawler.use_playwright = False
            crawler.max_retries = 1
            crawler.user_agents = ["UA"]
            crawler.session = MagicMock()

            t0 = time.time()
            results = crawler.collect_many(
                ["A", "B", "C"],
                max_workers=3,
            )
            elapsed = time.time() - t0

        self.assertEqual(set(results.keys()), {"A", "B", "C"})
        for name, data in results.items():
            self.assertFalse(data.get("_error"), f"{name} 不应有错误")
            self.assertEqual(data["name"], name)
        # 并发 3 个 1s 任务，理想总耗时约 1s；容忍 1.8s（线程启动开销）
        self.assertLess(
            elapsed, 1.8,
            f"并发执行应 < 1.8s，实际 {elapsed:.2f}s（说明没在并发）",
        )
        print(f"[OK] 3 任务并发耗时 {elapsed:.2f}s（串行需 3.0s）")

    def test_partial_failure_isolated(self):
        """单个失败不应影响其他任务"""
        original = DataCollectionAgent.collect

        def dispatcher(self, name):
            if name == "BAD":
                return failing_collect(self, name)
            return slow_collect(self, name)

        with patch.object(DataCollectionAgent, "collect", dispatcher):
            crawler = DataCollectionAgent.__new__(DataCollectionAgent)
            crawler.llm = MagicMock()
            crawler.use_playwright = False
            crawler.max_retries = 1
            crawler.user_agents = ["UA"]
            crawler.session = MagicMock()

            results = crawler.collect_many(["GOOD1", "BAD", "GOOD2"], max_workers=3)

        self.assertEqual(len(results), 3)
        self.assertIn("_error", results["BAD"], "失败任务应包含 _error")
        self.assertNotIn("_error", results["GOOD1"])
        self.assertNotIn("_error", results["GOOD2"])
        print(f"[OK] 失败隔离: GOOD1/GOOD2 成功, BAD 失败被捕获")

    def test_progress_callback(self):
        """progress_callback 应收到 start/done 事件"""
        events = []
        lock = threading.Lock()

        def cb(index, total, name, status, payload):
            with lock:
                events.append((index, total, name, status))

        with patch.object(DataCollectionAgent, "collect", slow_collect):
            crawler = DataCollectionAgent.__new__(DataCollectionAgent)
            crawler.llm = MagicMock()
            crawler.use_playwright = False
            crawler.max_retries = 1
            crawler.user_agents = ["UA"]
            crawler.session = MagicMock()

            crawler.collect_many(["X", "Y"], max_workers=2, progress_callback=cb)

        statuses = [e[3] for e in events]
        # 至少 2 个 start + 2 个 done
        self.assertGreaterEqual(statuses.count("start"), 2)
        self.assertGreaterEqual(statuses.count("done"), 2)
        names = {e[2] for e in events}
        self.assertEqual(names, {"X", "Y"})
        print(f"[OK] 进度回调触发 {len(events)} 次事件: {statuses}")

    def test_empty_input(self):
        crawler = DataCollectionAgent.__new__(DataCollectionAgent)
        crawler.llm = MagicMock()
        crawler.use_playwright = False
        crawler.max_retries = 1
        crawler.user_agents = ["UA"]
        crawler.session = MagicMock()
        self.assertEqual(crawler.collect_many([]), {})
        self.assertEqual(crawler.collect_many(["", None, "  "]), {})
        print("[OK] 空输入安全返回 {}")


if __name__ == "__main__":
    print("=" * 60)
    print("并行爬取 smoke test")
    print("=" * 60)
    unittest.main(verbosity=2)
