"""
意图理解 Agent - 独立负责从用户输入中提取信息

特点：
- 独立的 Agent，不是 Coordinator 的一部分
- 通过消息总线接收任务
- 自主决定如何处理
- 可以处理多种类型的输入
"""
from typing import Dict, Any, Optional
import json
import logging
import re

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

from multi_agent.core import BaseAgent, Message, MessageType
from utils.env_loader import load_env, get_env
from utils.llm_parser import safe_extract_json

load_env()
logger = logging.getLogger(__name__)


class IntentAgent(BaseAgent):
    """
    意图理解 Agent

    职责：
    1. 从用户自然语言输入中提取竞品名称
    2. 识别分析维度（功能、定价、Changelog）
    3. 确定输出格式（markdown/html）
    4. 处理模糊输入并请求澄清
    """

    def __init__(self, message_bus=None):
        super().__init__(
            name="intent_agent",
            role="意图理解专家",
            message_bus=message_bus
        )

        # 初始化 LLM
        api_key = get_env("OPENAI_API_KEY")
        base_url = get_env("OPENAI_BASE_URL")
        model = get_env("OPENAI_MODEL", "deepseek-chat")
        temperature = float(get_env("OPENAI_TEMPERATURE", "0.7"))

        if not api_key:
            raise ValueError("未找到 OPENAI_API_KEY，请在 .env 文件中配置")

        self.llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=api_key,
            base_url=base_url or None,
            request_timeout=60,
            max_retries=2
        )

        # 订阅任务开始消息
        self.message_bus.subscribe(MessageType.TASK_START, self._on_task_start)

        logger.info("IntentAgent 初始化完成")

    def _on_task_start(self, message: Message):
        """处理任务开始消息"""
        if message.recipient != self.name and message.recipient != "*":
            return
        self.handle_message(message)

    def can_handle(self, message: Message) -> bool:
        """判断是否可以处理该消息"""
        return (
            message.recipient == self.name or
            (message.payload.get("task") == "understand_intent")
        )

    def process(self, message: Message) -> Optional[Message]:
        """
        处理意图理解任务

        输入消息 payload:
            - user_query: 用户原始输入

        输出响应 payload:
            - competitors: 竞品名称列表
            - dimensions: 分析维度
            - output_format: 输出格式
            - confidence: 理解置信度
        """
        if message.msg_type != MessageType.TASK_START:
            return None

        user_query = message.payload.get("user_query", "")
        if not user_query:
            return message.reply(
                MessageType.TASK_FAILED,
                {"error": "用户查询为空"}
            )

        self.log(f"开始理解用户意图: {user_query[:50]}...")
        self.report_progress(10, "🔍 正在理解用户意图...")

        try:
            # 使用 LLM 提取信息
            result = self._extract_with_llm(user_query)

            # 验证提取结果
            if not result.get("competitors"):
                self.log("⚠️ LLM 未提取到竞品，使用备用方法")
                result["competitors"] = self._extract_fallback(user_query)

            # 决策：是否需要向用户请求澄清？
            if len(result["competitors"]) < 2:
                self.log("⚠️ 竞品数量不足，请求澄清")
                # 注意：这里我们不阻断流程，而是给出警告
                result["_warning"] = "竞品数量不足，分析可能不全面"

            self.log(
                f"✅ 提取完成: 竞品={result['competitors']}, "
                f"维度={result.get('dimensions', [])}"
            )

            self.report_progress(
                15,
                f"✅ 识别到 {len(result['competitors'])} 个竞品"
            )

            return message.reply(
                MessageType.TASK_COMPLETE,
                result
            )

        except Exception as e:
            self.log(f"❌ 意图理解失败: {e}", )
            # 失败时使用备用方法
            competitors = self._extract_fallback(user_query)
            return message.reply(
                MessageType.TASK_COMPLETE,
                {
                    "competitors": competitors,
                    "dimensions": ["features", "pricing"],
                    "output_format": "markdown",
                    "confidence": "low",
                    "_warning": f"LLM 提取失败，使用备用方法: {str(e)}"
                }
            )

    def _extract_with_llm(self, user_query: str) -> Dict:
        """使用 LLM 提取信息"""
        prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一位竞品分析专家。请从用户的输入中提取以下信息：

1. 竞品名称列表（必须是产品名，如 Notion、Obsidian、飞书等）
2. 分析维度 (features/pricing/changelog)
3. 输出格式 (markdown/html)

输出严格的 JSON 格式（不要有 markdown 代码块）：
{{
    "competitors": ["竞品1", "竞品2"],
    "dimensions": ["features", "pricing"],
    "output_format": "markdown",
    "confidence": "high/medium/low"
}}

要求：
- 只输出 JSON，不要有其他内容
- 竞品名称必须是真实的产品名
- 如果无法识别，competitors 为空数组
- confidence 表示对结果的信心程度"""),
            ("user", "{user_query}")
        ])

        chain = prompt | self.llm
        response = chain.invoke({"user_query": user_query})

        result = safe_extract_json(response.content, verbose=True)
        return result

    def _extract_fallback(self, user_query: str) -> list:
        """备用方法：基于规则提取竞品名称"""
        # 简单的关键词提取
        words = re.split(r'[和、，,\s]+', user_query)

        # 过滤停用词和短词
        stopwords = {
            "分析", "对比", "比较", "竞品", "产品", "一下", "看看",
            "什么", "怎么", "如何", "vs", "VS", "比较一下",
            "帮我", "请", "想要", "需要", "想要", "和", "及"
        }

        candidates = []
        for word in words:
            word = word.strip()
            if word and word not in stopwords and len(word) >= 2:
                # 进一步过滤：只保留可能是产品名的词
                if re.match(r'^[A-Za-z0-9\u4e00-\u9fff]+$', word):
                    candidates.append(word)

        return candidates[:5]  # 最多5个
