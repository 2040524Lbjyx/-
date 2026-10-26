"""
数据采集 Agent - 独立负责竞品数据采集

特点：
- 自主决策：可以选择使用 Playwright 还是 requests
- 支持并行采集多个竞品
- 失败时自主决定是否使用 LLM 兜底
- 完成后主动发送消息给 Verifier
"""
from typing import Dict, Any, Optional, List
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from multi_agent.core import BaseAgent, Message, MessageType
from multi_agent.core.shared_state import get_shared_state


logger = logging.getLogger(__name__)


class CrawlerAgent(BaseAgent):
    """
    数据采集 Agent

    职责：
    1. 查找竞品官网（白名单/启发式/LLM）
    2. 爬取多个页面
    3. 提取结构化数据
    4. 并行采集多个竞品

    自主决策：
    - 选择爬取策略（Playwright vs requests）
    - 选择爬取哪些页面
    - 失败时是否使用 LLM 兜底
    """

    def __init__(self, message_bus=None, max_workers: int = 3, shared_state=None):
        super().__init__(
            name="crawler_agent",
            role="数据采集专家",
            message_bus=message_bus
        )
        self.shared_state = shared_state or get_shared_state()
        self.max_workers = max_workers

        # 导入原有 DataCollectionAgent（复用爬取逻辑）
        try:
            from agents.crawler import DataCollectionAgent
            self._crawler = DataCollectionAgent()
            logger.info("CrawlerAgent 使用原有 DataCollectionAgent")
        except ImportError as e:
            logger.warning(f"无法导入 DataCollectionAgent: {e}")
            self._crawler = None

        logger.info("CrawlerAgent 初始化完成")

    def can_handle(self, message: Message) -> bool:
        return (
            message.recipient == self.name or
            message.payload.get("agent") == "crawler_agent"
        )

    def process(self, message: Message) -> Optional[Message]:
        """
        处理数据采集任务

        输入消息 payload:
            - competitors: 竞品列表（批量）
            - 或 single_competitor: 单个竞品
        """
        if message.msg_type != MessageType.TASK_START:
            return None

        # 支持单竞品或批量竞品
        competitors = message.payload.get("competitors", [])
        if not competitors:
            single = message.payload.get("single_competitor") or message.payload.get("target")
            if single:
                competitors = [single] if isinstance(single, str) else single

        if not competitors:
            return message.reply(
                MessageType.TASK_FAILED,
                {"error": "没有指定竞品"}
            )

        self.log(f"开始采集 {len(competitors)} 个竞品的数据")
        self.report_progress(30, f"🕷️ 开始采集 {len(competitors)} 个竞品...")

        # 自主决策：是否使用并行采集
        use_parallel = len(competitors) > 1 and self.max_workers > 1

        if use_parallel:
            results = self._crawl_parallel(competitors)
        else:
            results = self._crawl_sequential(competitors)

        # 保存到共享状态
        self.shared_state.set("crawled_data", results, agent=self.name)

        # 统计
        success = sum(1 for v in results.values() if not v.get("_error"))
        failed = len(competitors) - success
        self.log(
            f"✅ 采集完成: 成功 {success}/{len(competitors)}, "
            f"失败 {failed}"
        )
        self.report_progress(
            50,
            f"✅ 采集完成：成功 {success}，失败 {failed}"
        )

        # 主动发送消息给 Verifier（消息驱动，非函数调用）
        self.send_message(Message(
            sender=self.name,
            recipient="verifier_agent",
            msg_type=MessageType.DATA_READY,
            payload={
                "data_type": "crawled_data",
                "data": results,
                "competitors": competitors,
                "success_count": success,
                "failed_count": failed
            }
        ))

        return message.reply(
            MessageType.TASK_COMPLETE,
            {
                "crawled_data": results,
                "success": success,
                "failed": failed,
                "total": len(competitors)
            }
        )

    def _crawl_parallel(self, competitors: List[str]) -> Dict[str, Dict]:
        """并行采集"""
        results = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_competitor = {
                executor.submit(self._crawl_single, comp): comp
                for comp in competitors
            }

            for future in as_completed(future_to_competitor):
                competitor = future_to_competitor[future]
                try:
                    data = future.result()
                    results[competitor] = data
                    self.log(f"  ✅ {competitor} 采集完成")
                except Exception as e:
                    self.log(f"  ❌ {competitor} 采集失败: {e}")
                    results[competitor] = {
                        "_error": str(e),
                        "competitor": competitor
                    }

        return results

    def _crawl_sequential(self, competitors: List[str]) -> Dict[str, Dict]:
        """顺序采集"""
        results = {}
        for i, competitor in enumerate(competitors, 1):
            self.log(f"  [{i}/{len(competitors)}] 正在采集: {competitor}")
            try:
                data = self._crawl_single(competitor)
                results[competitor] = data
            except Exception as e:
                self.log(f"  ❌ {competitor} 采集失败: {e}")
                results[competitor] = {
                    "_error": str(e),
                    "competitor": competitor
                }
        return results

    def _crawl_single(self, competitor: str) -> Dict:
        """采集单个竞品"""
        if self._crawler is None:
            # 降级方案：返回空数据
            return {
                "competitor": competitor,
                "features": {"core": [], "advanced": []},
                "pricing": {},
                "_source": "no_crawler"
            }

        # 调用原有爬虫
        return self._crawler.collect(competitor)
