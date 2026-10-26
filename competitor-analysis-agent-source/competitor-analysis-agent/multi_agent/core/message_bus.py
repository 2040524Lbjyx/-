"""
消息总线 - Agent 间通信的基础设施

这是真正的多 Agent 系统的核心：
- Agent 之间通过消息通信（而非函数调用）
- 消息总线是 Agent 间通信的"共享黑板"
- 支持同步/异步消息处理
- 支持消息订阅和广播
"""
from typing import Dict, List, Callable, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
import logging
import asyncio
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    """消息类型"""
    # 任务消息
    TASK_START = "task_start"           # 启动任务
    TASK_COMPLETE = "task_complete"     # 任务完成
    TASK_FAILED = "task_failed"         # 任务失败

    # 数据消息
    DATA_READY = "data_ready"           # 数据已准备好
    DATA_REQUEST = "data_request"       # 请求数据

    # 反馈消息
    FEEDBACK = "feedback"               # 反馈
    VERIFICATION_RESULT = "verification_result"  # 验证结果
    REFINEMENT_REQUEST = "refinement_request"    # 改进请求

    # 控制消息
    HEARTBEAT = "heartbeat"             # 心跳
    SHUTDOWN = "shutdown"               # 关闭


@dataclass
class Message:
    """消息结构"""
    sender: str                          # 发送者 Agent 名称
    recipient: str                       # 接收者 Agent 名称（"*" 表示广播）
    msg_type: MessageType                # 消息类型
    payload: Dict[str, Any] = field(default_factory=dict)  # 消息内容
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    correlation_id: Optional[str] = None  # 关联 ID（用于追踪请求/响应）
    reply_to: Optional[str] = None       # 回复某个消息

    def to_dict(self) -> Dict:
        return {
            "sender": self.sender,
            "recipient": self.recipient,
            "msg_type": self.msg_type.value,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "reply_to": self.reply_to
        }

    def reply(self, msg_type: MessageType, payload: Dict) -> "Message":
        """创建对此消息的回复"""
        return Message(
            sender=self.recipient,        # 收件人变发件人
            recipient=self.sender,        # 发件人变收件人
            msg_type=msg_type,
            payload=payload,
            correlation_id=self.correlation_id,
            reply_to=self.timestamp
        )


class MessageBus:
    """
    消息总线 - Agent 间通信的核心

    特点：
    1. 发布/订阅模式：Agent 订阅感兴趣的消息类型
    2. 点对点通信：Agent 可以发送消息给特定 Agent
    3. 广播：Agent 可以发送消息给所有订阅者
    4. 异步处理：消息处理在独立线程中执行
    5. 消息历史：记录所有消息（可追踪和调试）
    """

    def __init__(self, max_workers: int = 4):
        self._subscribers: Dict[str, Callable] = {}  # agent_name -> callback
        self._msg_type_subscribers: Dict[MessageType, List[Callable]] = {}  # msg_type -> [callbacks]
        self._message_history: List[Message] = []
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._loop = asyncio.new_event_loop()
        logger.info("MessageBus 初始化完成")

    def register(self, agent_name: str, callback: Callable):
        """
        注册 Agent 到消息总线

        Args:
            agent_name: Agent 名称
            callback: 消息处理回调函数 callback(message: Message) -> Optional[Message]
        """
        self._subscribers[agent_name] = callback
        logger.info(f"Agent '{agent_name}' 已注册到消息总线")

    def subscribe(self, msg_type: MessageType, callback: Callable):
        """
        订阅特定类型的消息

        Args:
            msg_type: 消息类型
            callback: 回调函数
        """
        if msg_type not in self._msg_type_subscribers:
            self._msg_type_subscribers[msg_type] = []
        self._msg_type_subscribers[msg_type].append(callback)

    def send(self, message: Message):
        """
        发送消息（异步处理）

        Args:
            message: 要发送的消息
        """
        self._message_history.append(message)
        logger.info(
            f"[MSG] {message.sender} -> {message.recipient} | "
            f"type={message.msg_type.value}"
        )

        # 提交到线程池异步处理
        self._executor.submit(self._dispatch, message)

    def send_and_wait(self, message: Message, timeout: float = 30.0) -> Optional[Message]:
        """
        发送消息并等待响应（同步）

        Args:
            message: 要发送的消息
            timeout: 超时时间（秒）

        Returns:
            响应消息或 None（超时）
        """
        import time
        self._message_history.append(message)
        self._dispatch(message)

        # 简单的同步等待（实际项目中可以使用 Future）
        start = time.time()
        while time.time() - start < timeout:
            # 检查历史中是否有相关响应
            for msg in reversed(self._message_history):
                if msg.reply_to == message.timestamp and msg.recipient == message.sender:
                    return msg
            time.sleep(0.1)
        return None

    def _dispatch(self, message: Message):
        """分发消息到目标 Agent"""
        try:
            # 1. 点对点发送
            if message.recipient in self._subscribers:
                callback = self._subscribers[message.recipient]
                callback(message)
                return

            # 2. 广播（recipient = "*"）
            if message.recipient == "*":
                for agent_name, callback in self._subscribers.items():
                    if agent_name != message.sender:  # 不发给自己
                        try:
                            callback(message)
                        except Exception as e:
                            logger.error(f"Broadcast to {agent_name} failed: {e}")
                return

            # 3. 按消息类型订阅
            if message.msg_type in self._msg_type_subscribers:
                for callback in self._msg_type_subscribers[message.msg_type]:
                    try:
                        callback(message)
                    except Exception as e:
                        logger.error(f"Subscription callback failed: {e}")
                return

            logger.warning(
                f"No handler for message: "
                f"{message.sender} -> {message.recipient} ({message.msg_type.value})"
            )
        except Exception as e:
            logger.error(f"Message dispatch failed: {e}", exc_info=True)

    def get_history(self, agent_name: Optional[str] = None) -> List[Message]:
        """获取消息历史"""
        if agent_name:
            return [
                msg for msg in self._message_history
                if msg.sender == agent_name or msg.recipient == agent_name
            ]
        return self._message_history

    def clear_history(self):
        """清空消息历史"""
        self._message_history.clear()

    def shutdown(self):
        """关闭消息总线"""
        self._executor.shutdown(wait=True)
        logger.info("MessageBus 已关闭")


# 全局消息总线实例
_message_bus: Optional[MessageBus] = None


def get_message_bus() -> MessageBus:
    """获取全局消息总线实例（单例）"""
    global _message_bus
    if _message_bus is None:
        _message_bus = MessageBus()
    return _message_bus


if __name__ == "__main__":
    # 测试消息总线
    logging.basicConfig(level=logging.INFO)

    bus = get_message_bus()

    # 注册测试 Agent
    def agent_a(msg: Message):
        print(f"[A] 收到来自 {msg.sender} 的消息: {msg.payload}")
        if msg.msg_type == MessageType.TASK_START:
            # 发送响应
            bus.send(msg.reply(MessageType.TASK_COMPLETE, {"result": "A done"}))

    def agent_b(msg: Message):
        print(f"[B] 收到来自 {msg.sender} 的消息: {msg.payload}")

    bus.register("agent_a", agent_a)
    bus.register("agent_b", agent_b)

    # 发送测试消息
    bus.send(Message(
        sender="orchestrator",
        recipient="agent_a",
        msg_type=MessageType.TASK_START,
        payload={"task": "test"}
    ))

    import time
    time.sleep(1)
    print(f"\n消息历史: {len(bus.get_history())} 条")
    bus.shutdown()
