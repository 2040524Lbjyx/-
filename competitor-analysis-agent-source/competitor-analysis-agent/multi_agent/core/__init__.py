"""
多 Agent 系统核心模块

包含：
- message_bus: 消息总线（Agent 间通信）
- base_agent: 基础 Agent 类
- shared_state: 共享状态（黑板）
"""
from multi_agent.core.message_bus import (
    MessageBus,
    Message,
    MessageType,
    get_message_bus
)
from multi_agent.core.base_agent import BaseAgent, AgentStatus
from multi_agent.core.shared_state import SharedState, get_shared_state

__all__ = [
    "MessageBus",
    "Message",
    "MessageType",
    "get_message_bus",
    "BaseAgent",
    "AgentStatus",
    "SharedState",
    "get_shared_state",
]
