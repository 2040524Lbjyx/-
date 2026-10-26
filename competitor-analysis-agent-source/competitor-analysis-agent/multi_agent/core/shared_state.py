"""
共享状态（黑板） - 多 Agent 系统的数据存储

这是多 Agent 系统的"共享记忆"：
- 所有 Agent 都可以读取和写入
- 状态变更会被记录（事件溯源）
- 支持并发访问
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
import threading
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class StateChange:
    """状态变更事件"""
    agent: str
    key: str
    old_value: Any
    new_value: Any
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class SharedState:
    """
    共享状态（黑板）

    特点：
    1. 线程安全：使用读写锁保护
    2. 事件溯源：记录所有状态变更
    3. 快照支持：可以保存和恢复状态
    4. 变更通知：状态变更时通知订阅者
    """

    def __init__(self):
        self._state: Dict[str, Any] = {}
        self._lock = threading.RLock()  # 读写锁
        self._history: List[StateChange] = []
        self._subscribers: Dict[str, List[callable]] = {}  # key -> [callbacks]
        logger.info("SharedState 初始化完成")

    def set(self, key: str, value: Any, agent: str = "unknown"):
        """
        设置状态值

        Args:
            key: 状态键
            value: 状态值
            agent: 修改状态的 Agent 名称（用于追踪）
        """
        with self._lock:
            old_value = self._state.get(key)
            self._state[key] = value

            # 记录变更
            change = StateChange(
                agent=agent,
                key=key,
                old_value=old_value,
                new_value=value
            )
            self._history.append(change)

            logger.info(f"[State] {agent} 设置 {key} = {self._truncate(value)}")

            # 通知订阅者
            self._notify(key, value, change)

    def get(self, key: str, default: Any = None) -> Any:
        """获取状态值"""
        with self._lock:
            return self._state.get(key, default)

    def update(self, updates: Dict[str, Any], agent: str = "unknown"):
        """批量更新状态"""
        with self._lock:
            for key, value in updates.items():
                self.set(key, value, agent)

    def has(self, key: str) -> bool:
        """检查状态键是否存在"""
        with self._lock:
            return key in self._state

    def delete(self, key: str, agent: str = "unknown") -> bool:
        """删除状态键"""
        with self._lock:
            if key in self._state:
                old_value = self._state.pop(key)
                change = StateChange(
                    agent=agent,
                    key=key,
                    old_value=old_value,
                    new_value=None
                )
                self._history.append(change)
                self._notify(key, None, change)
                return True
            return False

    def get_all(self) -> Dict[str, Any]:
        """获取所有状态（返回副本）"""
        with self._lock:
            return dict(self._state)

    def subscribe(self, key: str, callback: callable):
        """订阅状态变更"""
        with self._lock:
            if key not in self._subscribers:
                self._subscribers[key] = []
            self._subscribers[key].append(callback)

    def _notify(self, key: str, value: Any, change: StateChange):
        """通知状态变更订阅者"""
        if key in self._subscribers:
            for callback in self._subscribers[key]:
                try:
                    callback(change)
                except Exception as e:
                    logger.error(f"状态变更通知失败: {e}")

    def snapshot(self) -> Dict[str, Any]:
        """创建状态快照"""
        with self._lock:
            return {
                "state": dict(self._state),
                "history": [
                    {
                        "agent": c.agent,
                        "key": c.key,
                        "old_value": self._truncate(c.old_value),
                        "new_value": self._truncate(c.new_value),
                        "timestamp": c.timestamp
                    }
                    for c in self._history
                ]
            }

    def get_history(self, key: Optional[str] = None) -> List[Dict]:
        """获取状态变更历史"""
        with self._lock:
            if key:
                return [
                    {
                        "agent": c.agent,
                        "key": c.key,
                        "old_value": self._truncate(c.old_value),
                        "new_value": self._truncate(c.new_value),
                        "timestamp": c.timestamp
                    }
                    for c in self._history
                    if c.key == key
                ]
            return [
                {
                    "agent": c.agent,
                    "key": c.key,
                    "old_value": self._truncate(c.old_value),
                    "new_value": self._truncate(c.new_value),
                    "timestamp": c.timestamp
                }
                for c in self._history
            ]

    def clear(self):
        """清空状态"""
        with self._lock:
            self._state.clear()
            self._history.clear()
            logger.info("SharedState 已清空")

    @staticmethod
    def _truncate(value: Any, max_len: int = 100) -> str:
        """截断长值用于日志"""
        if value is None:
            return "None"
        s = str(value)
        if len(s) > max_len:
            return s[:max_len] + "..."
        return s


# 全局共享状态实例
_shared_state: Optional[SharedState] = None


def get_shared_state() -> SharedState:
    """获取全局共享状态实例（单例）"""
    global _shared_state
    if _shared_state is None:
        _shared_state = SharedState()
    return _shared_state


if __name__ == "__main__":
    # 测试共享状态
    logging.basicConfig(level=logging.INFO)
    state = get_shared_state()

    # 设置状态
    state.set("competitors", ["Notion", "Obsidian"], agent="intent_agent")
    state.set("crawled_data", {"Notion": {"features": [...]}}, agent="crawler_agent")

    # 获取状态
    print(f"竞品: {state.get('competitors')}")

    # 订阅状态变更
    def on_change(change):
        print(f"🔔 状态变更: {change.key} by {change.agent}")

    state.subscribe("crawled_data", on_change)
    state.set("crawled_data", {"updated": True}, agent="verifier_agent")

    # 查看历史
    print(f"\n历史: {len(state.get_history())} 条")
