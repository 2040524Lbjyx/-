"""
多 Agent 竞品分析系统

这是真正的多 Agent 协作系统：
- Agent 之间通过消息总线通信（不是函数调用）
- 每个 Agent 有独立的决策能力
- 支持并行执行
- 支持反馈循环（Verifier -> Crawler）
- 支持共享状态（黑板）

主要模块：
- core: 核心模块（消息总线、基础 Agent、共享状态）
- agents: 各个专门的 Agent
- orchestrator: 编排器（系统入口）
"""
from multi_agent.core import (
    MessageBus,
    Message,
    MessageType,
    BaseAgent,
    SharedState,
    get_message_bus,
    get_shared_state,
)
from multi_agent.orchestrator import MultiAgentOrchestrator
from multi_agent.agents import (
    IntentAgent,
    PlannerAgent,
    CrawlerAgent,
    VerifierAgent,
    AnalyzerAgent,
    InsightAgent,
    ReporterAgent,
)

__version__ = "2.0.0"
__all__ = [
    # Core
    "MessageBus",
    "Message",
    "MessageType",
    "BaseAgent",
    "SharedState",
    "get_message_bus",
    "get_shared_state",
    # Orchestrator
    "MultiAgentOrchestrator",
    # Agents
    "IntentAgent",
    "PlannerAgent",
    "CrawlerAgent",
    "VerifierAgent",
    "AnalyzerAgent",
    "InsightAgent",
    "ReporterAgent",
]
