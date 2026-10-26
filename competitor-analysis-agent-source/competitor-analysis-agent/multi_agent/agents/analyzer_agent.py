"""
数据分析 Agent - 负责对竞品数据进行多维度分析

特点：
- 支持多维度分析（功能、定价、Changelog）
- 可以并行处理不同维度
- 复用原有 AnalysisAgent 的核心逻辑
"""
from typing import Dict, Any, Optional
import logging
import pandas as pd

from multi_agent.core import BaseAgent, Message, MessageType
from multi_agent.core.shared_state import get_shared_state


logger = logging.getLogger(__name__)


class AnalyzerAgent(BaseAgent):
    """
    数据分析 Agent

    职责：
    1. 功能对比分析
    2. 定价策略分析
    3. Changelog 分析
    4. 按维度并行分析
    """

    def __init__(self, message_bus=None, shared_state=None):
        super().__init__(
            name="analyzer_agent",
            role="数据分析专家",
            message_bus=message_bus
        )
        self.shared_state = shared_state or get_shared_state()

        # 复用原有 AnalysisAgent
        try:
            from agents.analyzer import AnalysisAgent
            self._analyzer = AnalysisAgent()
            logger.info("AnalyzerAgent 使用原有 AnalysisAgent")
        except ImportError as e:
            logger.warning(f"无法导入 AnalysisAgent: {e}")
            self._analyzer = None

        # 订阅验证结果（自动开始分析）
        self.message_bus.subscribe(MessageType.VERIFICATION_RESULT, self._on_verification_result)

        logger.info("AnalyzerAgent 初始化完成")

    def _on_verification_result(self, message: Message):
        """处理验证结果消息"""
        if message.payload.get("verified_data"):
            # 自主决策：开始分析已验证的数据
            self.log("📊 收到已验证数据，开始分析")
            # 触发分析流程
            self.handle_message(Message(
                sender=self.name,
                recipient=self.name,
                msg_type=MessageType.TASK_START,
                payload={
                    "task": "analyze",
                    "verified_data": message.payload.get("verified_data")
                }
            ))

    def can_handle(self, message: Message) -> bool:
        return message.recipient == self.name

    def process(self, message: Message) -> Optional[Message]:
        """处理分析任务"""
        if message.msg_type != MessageType.TASK_START:
            return None

        # 获取数据（从消息或共享状态）
        data = message.payload.get("verified_data") or self.shared_state.get("verified_data")
        if not data:
            data = self.shared_state.get("crawled_data", {})

        if not data:
            return message.reply(
                MessageType.TASK_FAILED,
                {"error": "没有可分析的数据"}
            )

        # 过滤掉失败的数据
        valid_data = {
            name: d for name, d in data.items()
            if not d.get("_error")
        }

        if not valid_data:
            return message.reply(
                MessageType.TASK_FAILED,
                {"error": "所有数据都无效，无法分析"}
            )

        # 获取分析维度
        dimension = message.payload.get("dimension", "features")
        competitors = message.payload.get("competitors") or list(valid_data.keys())

        self.log(f"开始分析: 维度={dimension}, 竞品数={len(valid_data)}")
        self.report_progress(60, f"🧠 正在分析 {dimension}...")

        # 自主决策：调用对应的分析方法
        try:
            if dimension == "features":
                result = self._analyze_features(valid_data)
            elif dimension == "pricing":
                result = self._analyze_pricing(valid_data)
            elif dimension == "changelog":
                result = self._analyze_changelog(valid_data)
            else:
                result = self._analyze_features(valid_data)

            # 保存到共享状态
            analysis_key = f"analysis_{dimension}"
            self.shared_state.set(analysis_key, result, agent=self.name)

            # 主动通知 Insight Agent
            self.send_message(Message(
                sender=self.name,
                recipient="insight_agent",
                msg_type=MessageType.DATA_READY,
                payload={
                    "data_type": f"analysis_{dimension}",
                    "data": result,
                    "dimension": dimension
                }
            ))

            self.log(f"✅ {dimension} 分析完成")

            return message.reply(
                MessageType.TASK_COMPLETE,
                {
                    "dimension": dimension,
                    "result": result
                }
            )

        except Exception as e:
            self.log(f"❌ {dimension} 分析失败: {e}")
            return message.reply(
                MessageType.TASK_FAILED,
                {"error": str(e), "dimension": dimension}
            )

    def _analyze_features(self, data: Dict) -> pd.DataFrame:
        """功能对比分析"""
        if self._analyzer is None:
            return pd.DataFrame()
        return self._analyzer.compare_features(data)

    def _analyze_pricing(self, data: Dict) -> Dict:
        """定价分析"""
        if self._analyzer is None:
            return {}
        return self._analyzer.analyze_pricing(data)

    def _analyze_changelog(self, data: Dict) -> Dict:
        """Changelog 分析"""
        if self._analyzer is None:
            return {}
        return self._analyzer.analyze_changelog(data)
