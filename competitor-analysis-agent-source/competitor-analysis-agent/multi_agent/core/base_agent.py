"""
基础 Agent 类 - 所有 Agent 的父类

这是多 Agent 系统的核心抽象：
- 每个 Agent 是独立的实体
- 通过消息总线与其他 Agent 通信
- 有自己的状态和决策能力
- 可以订阅消息、发送消息
"""
from typing import Dict, Any, Optional, List
from abc import ABC, abstractmethod
from datetime import datetime
import logging
import json

from multi_agent.core.message_bus import MessageBus, Message, MessageType, get_message_bus


class AgentStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING = "waiting"


class BaseAgent(ABC):
    """
    基础 Agent 类

    真正的 Agent 特性：
    1. 自主决策：可以决定如何处理消息
    2. 主动通信：可以主动发送消息给其他 Agent
    3. 状态管理：有自己的运行状态
    4. 可观测：可以报告进度和状态
    """

    def __init__(
        self,
        name: str,
        role: str,
        message_bus: Optional[MessageBus] = None
    ):
        """
        初始化 Agent

        Args:
            name: Agent 名称（唯一标识）
            role: Agent 角色描述
            message_bus: 消息总线实例
        """
        self.name = name
        self.role = role
        self.message_bus = message_bus or get_message_bus()
        self.status = AgentStatus.PENDING
        self.context: Dict[str, Any] = {}  # Agent 私有上下文
        self.inbox: List[Message] = []    # 收件箱
        self.outbox: List[Message] = []   # 发件箱

        # 进度回调（可选）
        self._progress_callback = None
        self._log_callback = None

        # 注册到消息总线
        self.message_bus.register(self.name, self.handle_message)

        # 订阅感兴趣的消息类型
        self._subscribe_messages()

        self.logger = logging.getLogger(f"agent.{self.name}")
        self.logger.info(f"Agent '{self.name}' ({self.role}) 已初始化")

    def _subscribe_messages(self):
        """订阅 Agent 感兴趣的消息类型（子类可重写）"""
        # 默认订阅所有定向消息
        pass

    def handle_message(self, message: Message):
        """
        处理接收到的消息（消息总线回调）

        这是 Agent 的"大脑入口"：
        1. 接收消息
        2. 决策如何处理
        3. 执行动作
        4. 发送响应

        子类必须实现 process 方法
        """
        self.inbox.append(message)
        self.logger.info(
            f"[{self.name}] 收到消息: {message.msg_type.value} 来自 {message.sender}"
        )

        try:
            self.status = AgentStatus.RUNNING
            response = self.process(message)
            self.status = (
                AgentStatus.FAILED
                if response and response.msg_type == MessageType.TASK_FAILED
                else AgentStatus.COMPLETED
            )

            # 如果有响应，发送回给发送者
            if response:
                self.send_message(response)
        except Exception as e:
            self.status = AgentStatus.FAILED
            self.logger.error(f"[{self.name}] 处理消息失败: {e}", exc_info=True)
            # 发送失败消息
            self.send_message(message.reply(
                MessageType.TASK_FAILED,
                {"error": str(e), "agent": self.name}
            ))

    @abstractmethod
    def process(self, message: Message) -> Optional[Message]:
        """
        处理消息的核心逻辑（子类必须实现）

        Args:
            message: 接收到的消息

        Returns:
            可选的响应消息（如果有的话）
        """
        pass

    def send_message(self, message: Message):
        """
        发送消息给其他 Agent

        这是 Agent 主动通信的方式：
        - 不再是被动等待 Coordinator 调用
        - Agent 可以主动发送反馈、请求、通知
        """
        self.outbox.append(message)
        self.message_bus.send(message)
        self.logger.info(
            f"[{self.name}] 发送消息: {message.msg_type.value} 给 {message.recipient}"
        )

    def send_broadcast(self, msg_type: MessageType, payload: Dict):
        """广播消息给所有 Agent"""
        msg = Message(
            sender=self.name,
            recipient="*",
            msg_type=msg_type,
            payload=payload
        )
        self.send_message(msg)

    def report_progress(self, progress: int, message: str):
        """报告进度（如果设置了回调）"""
        if self._progress_callback:
            try:
                self._progress_callback(progress, message)
            except Exception as e:
                self.logger.warning(f"进度回调失败: {e}")

    def log(self, message: str):
        """记录日志（同时输出到 logger 和 log_callback）"""
        self.logger.info(message)
        if self._log_callback:
            try:
                self._log_callback(f"[{self.name}] {message}")
            except Exception as e:
                self.logger.warning(f"日志回调失败: {e}")

    def set_callbacks(self, progress_callback=None, log_callback=None):
        """设置进度和日志回调"""
        self._progress_callback = progress_callback
        self._log_callback = log_callback

    def can_handle(self, message: Message) -> bool:
        """
        判断是否可以处理该消息（子类可重写）

        用于编排器决定消息应该路由到哪个 Agent
        """
        # 默认所有 Agent 都能处理所有消息（但只有一个会处理）
        # 实际路由由编排器根据消息的 recipient 决定
        return True

    def get_state(self) -> Dict[str, Any]:
        """获取 Agent 状态（用于监控和调试）"""
        return {
            "name": self.name,
            "role": self.role,
            "status": self.status,
            "inbox_count": len(self.inbox),
            "outbox_count": len(self.outbox),
            "context": self.context
        }

    def __repr__(self):
        return f"<Agent {self.name} ({self.role}) status={self.status}>"
