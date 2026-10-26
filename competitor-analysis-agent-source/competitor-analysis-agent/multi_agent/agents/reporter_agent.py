"""
报告生成 Agent - 独立负责生成最终分析报告

特点：
- 监听所有数据消息
- 等所有数据就绪后自动生成报告
- 支持多种输出格式
"""
from typing import Dict, Any, Optional
import logging
import time

from multi_agent.core import BaseAgent, Message, MessageType
from multi_agent.core.shared_state import get_shared_state


logger = logging.getLogger(__name__)


class ReporterAgent(BaseAgent):
    """
    报告生成 Agent

    职责：
    1. 汇总所有分析结果
    2. 生成可视化图表
    3. 渲染最终报告
    4. 支持多种格式（markdown/html）

    协作方式：
    - 监听所有 DATA_READY 消息
    - 数据齐全后自动开始生成
    - 也可以接收显式的生成任务
    """

    def __init__(self, message_bus=None, shared_state=None):
        super().__init__(
            name="reporter_agent",
            role="报告生成专家",
            message_bus=message_bus
        )
        self.shared_state = shared_state or get_shared_state()

        # 复用原有 ReportAgent
        try:
            from agents.reporter import ReportAgent
            self._reporter = ReportAgent()
            logger.info("ReporterAgent 使用原有 ReportAgent")
        except ImportError as e:
            logger.warning(f"无法导入 ReportAgent: {e}")
            self._reporter = None

        # 订阅所有数据消息
        self.message_bus.subscribe(MessageType.DATA_READY, self._on_data_ready)

        # 数据就绪标记
        self._data_ready = {
            "feature_matrix": False,
            "pricing_analysis": False,
            "insights": False
        }

        logger.info("ReporterAgent 初始化完成")

    def _on_data_ready(self, message: Message):
        """接收数据消息"""
        data_type = message.payload.get("data_type", "")
        self.log(f"📊 收到 {data_type} 数据")

        # 缓存数据
        self.context[data_type] = message.payload.get("data")

        # 标记数据就绪
        if data_type in self._data_ready:
            self._data_ready[data_type] = True
        elif data_type == "analysis_features":
            self.context["feature_matrix"] = message.payload.get("data")
        elif data_type == "analysis_pricing":
            self.context["pricing_analysis"] = message.payload.get("data")
        elif data_type == "analysis_changelog":
            self.context["changelog_analysis"] = message.payload.get("data")

    def can_handle(self, message: Message) -> bool:
        return message.recipient == self.name

    def process(self, message: Message) -> Optional[Message]:
        """处理报告生成任务"""
        if message.msg_type != MessageType.TASK_START:
            return None

        self.log("📝 开始生成报告")
        self.report_progress(85, "📝 正在生成报告...")

        # 收集所有分析结果
        analysis_results = {
            "feature_matrix": self.context.get("feature_matrix") or self.shared_state.get("analysis_features"),
            "pricing_analysis": self.context.get("pricing_analysis") or self.shared_state.get("analysis_pricing"),
            "changelog_analysis": self.context.get("changelog_analysis") or self.shared_state.get("analysis_changelog"),
            "insights": self.context.get("insights") or self.shared_state.get("insights", [])
        }

        competitors = message.payload.get("competitors") or self.shared_state.get("competitors", [])
        output_format = message.payload.get("output_format") or self.shared_state.get("output_format", "markdown")

        if not competitors:
            return message.reply(
                MessageType.TASK_FAILED,
                {"error": "没有竞品信息"}
            )

        # 处理 DataFrame 序列化问题
        safe_results = self._make_serializable(analysis_results)

        try:
            if self._reporter is None:
                # 降级方案：生成简单报告
                report_path = self._generate_simple_report(safe_results, competitors, output_format)
            else:
                report_path = self._reporter.generate(
                    analysis_results=safe_results,
                    competitors=competitors,
                    output_format=output_format
                )

            self.shared_state.set("report_path", report_path, agent=self.name)
            self.log(f"✅ 报告生成完成: {report_path}")
            self.report_progress(95, f"📄 报告已生成")

            # 主动通知 Orchestrator
            self.send_message(Message(
                sender=self.name,
                recipient="orchestrator",
                msg_type=MessageType.TASK_COMPLETE,
                payload={
                    "task": "report_generated",
                    "report_path": report_path
                }
            ))

            return message.reply(
                MessageType.TASK_COMPLETE,
                {"report_path": report_path}
            )

        except Exception as e:
            self.log(f"❌ 报告生成失败: {e}")
            return message.reply(
                MessageType.TASK_FAILED,
                {"error": str(e)}
            )

    def _make_serializable(self, results: Dict) -> Dict:
        """将结果转换为可序列化格式"""
        import pandas as pd
        import numpy as np

        serializable = {}
        for key, value in results.items():
            if isinstance(value, pd.DataFrame):
                serializable[key] = value.to_dict('records')
            elif isinstance(value, np.ndarray):
                serializable[key] = value.tolist()
            elif isinstance(value, dict):
                serializable[key] = {
                    k: v.to_dict('records') if isinstance(v, pd.DataFrame)
                    else v.tolist() if isinstance(v, np.ndarray)
                    else v
                    for k, v in value.items()
                }
            else:
                serializable[key] = value
        return serializable

    def _generate_simple_report(self, results: Dict, competitors: list, output_format: str) -> str:
        """生成简单报告（降级方案）"""
        import os
        os.makedirs("./reports", exist_ok=True)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_simple_report.md"
        filepath = os.path.join("./reports", filename)

        content = f"# 竞品分析报告\n\n**竞品**: {', '.join(competitors)}\n\n"
        content += "## 洞察\n\n"
        insights = results.get("insights", [])
        if isinstance(insights, list):
            for i, insight in enumerate(insights, 1):
                content += f"{i}. {insight}\n"
        else:
            content += str(insights)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)

        return filepath
