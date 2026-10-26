"""
数据验证 Agent - 负责验证数据质量和完整性

这是多 Agent 系统的关键创新：
- 不是简单的"通过/失败"
- 而是评估数据质量（0-1 分数）
- 决定是否可以继续，还是需要重新采集
- 主动反馈给 Crawler 请求改进
"""
from typing import Dict, Any, Optional, List
import logging
from datetime import datetime

from multi_agent.core import BaseAgent, Message, MessageType
from multi_agent.core.shared_state import get_shared_state


logger = logging.getLogger(__name__)


class VerifierAgent(BaseAgent):
    """
    数据验证 Agent

    职责：
    1. 验证爬取数据的完整性
    2. 评估数据质量（0-1 分数）
    3. 识别缺失或错误的数据
    4. 决定是否需要重新采集
    5. 主动向 Crawler 发送改进请求（反馈循环）

    这是多 Agent 系统的重要特征：
    - 不再是简单的"通过/失败"
    - 可以请求特定字段的改进
    - 实现了 Agent 之间的反馈循环
    """

    # 质量阈值
    QUALITY_THRESHOLD = 0.6  # 低于此分数会请求重新采集
    HIGH_QUALITY = 0.8       # 高于此分数认为是高质量

    def __init__(self, message_bus=None, shared_state=None):
        super().__init__(
            name="verifier_agent",
            role="数据质量验证专家",
            message_bus=message_bus
        )
        self.shared_state = shared_state or get_shared_state()
        logger.info("VerifierAgent 初始化完成")

    def can_handle(self, message: Message) -> bool:
        return (
            message.recipient == self.name or
            message.msg_type == MessageType.DATA_READY
        )

    def process(self, message: Message) -> Optional[Message]:
        """
        处理验证任务

        输入消息：
            - DATA_READY: 数据已准备好
            - TASK_START: 显式验证任务

        输出响应：
            - quality_scores: 每个竞品的质量分数
            - issues: 发现的问题
            - recommendations: 改进建议
        """
        if message.msg_type == MessageType.DATA_READY:
            # 接收数据并验证
            data_type = message.payload.get("data_type", "")
            data = message.payload.get("data", {})

            if data_type == "crawled_data":
                return self._verify_crawled_data(message, data)
            elif data_type == "analysis_results":
                return self._verify_analysis_results(message, data)
            else:
                # 通用验证
                return self._verify_generic(message, data)

        elif message.msg_type == MessageType.TASK_START:
            # 显式验证任务
            target = message.payload.get("target", "all")
            data = self.shared_state.get("crawled_data", {})
            return self._verify_crawled_data(message, data)

        return None

    def _verify_crawled_data(self, message: Message, data: Dict) -> Message:
        """验证爬取数据"""
        self.log("🔍 开始验证爬取数据质量")
        self.report_progress(52, "🔍 正在验证数据质量...")

        quality_scores = {}
        issues = {}
        recommendations = []
        verified_data = {}

        for competitor, comp_data in data.items():
            # 跳过已经是错误的数据
            if comp_data.get("_error"):
                quality_scores[competitor] = 0.0
                issues[competitor] = [f"采集失败: {comp_data.get('_error')}"]
                continue

            # 评估数据质量
            score, comp_issues = self._assess_quality(comp_data)
            quality_scores[competitor] = score

            if comp_issues:
                issues[competitor] = comp_issues

            # 根据质量决定是否使用
            if score >= self.QUALITY_THRESHOLD:
                verified_data[competitor] = comp_data
                self.log(f"  ✅ {competitor}: 质量 {score:.2f} 通过")
            else:
                # 质量不达标，请求重新采集
                self.log(
                    f"  ⚠️ {competitor}: 质量 {score:.2f} 不达标，"
                    f"问题: {comp_issues}"
                )
                recommendations.append({
                    "competitor": competitor,
                    "current_score": score,
                    "issues": comp_issues,
                    "action": "re_crawl",
                    "priority": "high" if score < 0.3 else "medium"
                })

        # 计算总体质量
        valid_scores = [s for s in quality_scores.values() if s > 0]
        avg_quality = sum(valid_scores) / len(valid_scores) if valid_scores else 0.0

        self.log(
            f"📊 验证完成: 平均质量 {avg_quality:.2f}, "
            f"通过 {len(verified_data)}/{len(data)}"
        )

        # 保存到共享状态
        self.shared_state.set("verified_data", verified_data, agent=self.name)
        self.shared_state.set("quality_scores", quality_scores, agent=self.name)
        self.shared_state.set("data_issues", issues, agent=self.name)

        # 关键：主动反馈给 Crawler（如果需要）
        if recommendations:
            self._send_refinement_request(recommendations)

        # 主动通知 Analyzer 数据已验证
        self.send_message(Message(
            sender=self.name,
            recipient="analyzer_agent",
            msg_type=MessageType.VERIFICATION_RESULT,
            payload={
                "verified_data": verified_data,
                "quality_scores": quality_scores,
                "issues": issues,
                "avg_quality": avg_quality,
                "needs_refinement": bool(recommendations)
            }
        ))

        self.report_progress(
            55,
            f"📊 数据质量: {avg_quality:.0%}"
        )

        # DATA_READY 由 Crawler 发出，reply 只会回到 Crawler；
        # 额外通知 Orchestrator，避免验证阶段固定等到超时。
        self.send_message(Message(
            sender=self.name,
            recipient="orchestrator",
            msg_type=MessageType.TASK_COMPLETE,
            correlation_id="verifier_agent",
            payload={
                "verified_data": verified_data,
                "quality_scores": quality_scores,
                "issues": issues,
                "avg_quality": avg_quality,
                "recommendations": recommendations
            }
        ))

        return message.reply(
            MessageType.TASK_COMPLETE,
            {
                "verified_data": verified_data,
                "quality_scores": quality_scores,
                "issues": issues,
                "avg_quality": avg_quality,
                "recommendations": recommendations
            }
        )

    def _assess_quality(self, comp_data: Dict) -> tuple:
        """
        评估单个竞品数据的质量

        Returns:
            (quality_score, issues_list)
        """
        score = 1.0
        issues = []

        # 1. 检查基本字段
        if not comp_data.get("competitor"):
            score -= 0.1
            issues.append("缺少竞品名称")

        if not comp_data.get("website"):
            score -= 0.1
            issues.append("缺少官网URL")

        # 2. 检查功能数据
        features = comp_data.get("features", {})
        core_count = len(features.get("core", [])) if isinstance(features, dict) else 0
        advanced_count = len(features.get("advanced", [])) if isinstance(features, dict) else 0

        if core_count == 0 and advanced_count == 0:
            score -= 0.4
            issues.append("无功能数据")
        elif core_count + advanced_count < 3:
            score -= 0.2
            issues.append(f"功能数据较少 ({core_count + advanced_count} 项)")

        # 3. 检查定价数据
        pricing = comp_data.get("pricing", {})
        if not pricing:
            score -= 0.2
            issues.append("无定价数据")
        elif isinstance(pricing, dict) and not pricing.get("model") and not pricing.get("plans"):
            score -= 0.1
            issues.append("定价数据不完整")

        # 4. 检查数据来源
        source = comp_data.get("_source", "")
        if source == "llm_fallback":
            score -= 0.3
            issues.append("数据来自LLM兜底（未经过官网验证）")
        elif source == "crawl_partial":
            score -= 0.2
            issues.append("爬取数据不完整")

        return max(0.0, score), issues

    def _send_refinement_request(self, recommendations: List[Dict]):
        """发送改进请求给 Crawler（实现反馈循环）"""
        self.log(f"📤 向 Crawler 发送 {len(recommendations)} 个改进请求")
        self.send_message(Message(
            sender=self.name,
            recipient="crawler_agent",
            msg_type=MessageType.REFINEMENT_REQUEST,
            payload={
                "recommendations": recommendations,
                "timestamp": datetime.now().isoformat()
            }
        ))

    def _verify_analysis_results(self, message: Message, data: Dict) -> Message:
        """验证分析结果"""
        self.log("🔍 验证分析结果")

        # 检查分析结果是否完整
        required_keys = ["feature_matrix", "pricing_analysis", "insights"]
        issues = []

        for key in required_keys:
            if key not in data or not data[key]:
                issues.append(f"缺少 {key}")

        score = 1.0 - (len(issues) * 0.3)

        return message.reply(
            MessageType.VERIFICATION_RESULT,
            {
                "quality_scores": {"analysis": score},
                "issues": {"analysis": issues},
                "verified_data": data if score >= self.QUALITY_THRESHOLD else None
            }
        )

    def _verify_generic(self, message: Message, data: Dict) -> Message:
        """通用验证"""
        return message.reply(
            MessageType.VERIFICATION_RESULT,
            {
                "verified_data": data,
                "quality_scores": {"generic": 0.8},
                "issues": {}
            }
        )
