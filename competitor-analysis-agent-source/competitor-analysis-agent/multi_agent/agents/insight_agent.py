"""
洞察生成 Agent - 负责基于分析结果生成 AI 洞察

特点：
- 独立的 Agent，专门负责洞察生成
- 可以基于多种分析结果生成综合洞察
- 可以与用户进行澄清对话
"""
from typing import Dict, Any, Optional, List
import logging

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from multi_agent.core import BaseAgent, Message, MessageType
from multi_agent.core.shared_state import get_shared_state
from utils.env_loader import load_env, get_env
from utils.llm_parser import safe_extract_json

load_env()
logger = logging.getLogger(__name__)


class InsightAgent(BaseAgent):
    """
    洞察生成 Agent

    职责：
    1. 基于功能、定价、Changelog 分析结果生成洞察
    2. 识别竞品间的差异和机会
    3. 生成可执行的建议
    4. 与 Verifier 协作确保洞察质量
    """

    def __init__(self, message_bus=None, shared_state=None):
        super().__init__(
            name="insight_agent",
            role="AI 洞察专家",
            message_bus=message_bus
        )
        self.shared_state = shared_state or get_shared_state()

        # 初始化 LLM
        api_key = get_env("OPENAI_API_KEY")
        base_url = get_env("OPENAI_BASE_URL")
        model = get_env("OPENAI_MODEL", "deepseek-chat")
        temperature = float(get_env("OPENAI_TEMPERATURE", "0.7"))

        self.llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=api_key,
            base_url=base_url or None,
            request_timeout=60,
            max_retries=2
        )

        # 订阅分析结果
        self.message_bus.subscribe(MessageType.DATA_READY, self._on_data_ready)

        logger.info("InsightAgent 初始化完成")

    def _on_data_ready(self, message: Message):
        """监听分析数据"""
        data_type = message.payload.get("data_type", "")
        if data_type.startswith("analysis_"):
            # 收到分析结果
            self.log(f"📊 收到 {data_type}，准备生成洞察")
            # 缓存到上下文
            self.context[data_type] = message.payload.get("data")

    def can_handle(self, message: Message) -> bool:
        return message.recipient == self.name

    def process(self, message: Message) -> Optional[Message]:
        """
        生成洞察

        输入：
            - feature_matrix, pricing_analysis, changelog_analysis
        """
        if message.msg_type != MessageType.TASK_START:
            return None

        # 收集所有分析结果
        feature_matrix = self.context.get("analysis_features") or self.shared_state.get("analysis_features")
        pricing_analysis = self.context.get("analysis_pricing") or self.shared_state.get("analysis_pricing")
        changelog_analysis = self.context.get("analysis_changelog") or self.shared_state.get("analysis_changelog")
        competitors = message.payload.get("competitors", [])

        if not any([feature_matrix is not None, pricing_analysis, changelog_analysis]):
            return message.reply(
                MessageType.TASK_FAILED,
                {"error": "没有可用的分析结果"}
            )

        self.log("💡 开始生成 AI 洞察")
        self.report_progress(78, "💡 正在生成 AI 洞察...")

        try:
            insights = self._generate_insights(
                feature_matrix, pricing_analysis, changelog_analysis, competitors
            )

            # 保存到共享状态
            self.shared_state.set("insights", insights, agent=self.name)

            self.log(f"✅ 生成 {len(insights)} 条洞察")

            # 主动通知 Reporter
            self.send_message(Message(
                sender=self.name,
                recipient="reporter_agent",
                msg_type=MessageType.DATA_READY,
                payload={
                    "data_type": "insights",
                    "data": insights
                }
            ))

            return message.reply(
                MessageType.TASK_COMPLETE,
                {"insights": insights}
            )

        except Exception as e:
            self.log(f"❌ 洞察生成失败: {e}")
            return message.reply(
                MessageType.TASK_FAILED,
                {"error": str(e)}
            )

    def _generate_insights(self, feature_matrix, pricing_analysis,
                          changelog_analysis, competitors) -> List[str]:
        """生成洞察"""
        # 准备分析数据摘要
        feature_summary = self._summarize_features(feature_matrix) if feature_matrix is not None else "无功能对比数据"
        pricing_summary = str(pricing_analysis) if pricing_analysis else "无定价数据"
        changelog_summary = str(changelog_analysis) if changelog_analysis else "无Changelog数据"

        competitors_str = "、".join(competitors) if competitors else "竞品"

        prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一位资深的产品策略专家。基于以下竞品分析数据，生成 5-8 条深刻的商业洞察。

要求：
1. 每条洞察要具体、可执行
2. 指出竞品之间的差异和机会
3. 关注用户价值和市场定位
4. 使用中文输出
5. 输出严格的 JSON 数组格式：["洞察1", "洞察2", ...]

只输出 JSON 数组，不要有其他内容。"""),
            ("user", f"""竞品: {competitors_str}

功能对比:
{feature_summary}

定价分析:
{pricing_summary}

Changelog 分析:
{changelog_summary}

请生成 5-8 条洞察。""")
        ])

        chain = prompt | self.llm
        response = chain.invoke({})

        try:
            result = safe_extract_json(response.content, verbose=True)
            if isinstance(result, list):
                return result
            elif isinstance(result, dict) and "insights" in result:
                return result["insights"]
            else:
                # 尝试提取字符串列表
                return [str(result)]
        except Exception as e:
            logger.warning(f"洞察 JSON 解析失败: {e}，使用文本模式")
            # 降级：按行分割
            lines = [
                line.strip().lstrip("0123456789.、-*•")
                for line in response.content.split("\n")
                if line.strip() and len(line.strip()) > 10
            ]
            return lines[:8]

    def _summarize_features(self, feature_matrix) -> str:
        """汇总功能数据"""
        if feature_matrix is None or (hasattr(feature_matrix, 'empty') and feature_matrix.empty):
            return "无功能数据"

        # DataFrame 转字符串
        try:
            return feature_matrix.to_markdown()
        except:
            return str(feature_matrix)
