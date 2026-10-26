"""
计划制定 Agent - 独立负责制定分析计划

特点：
- 根据意图理解结果制定执行计划
- 可以并行执行的任务会标记为可并行
- 计划是动态的，可以根据执行情况调整
"""
from typing import Dict, Any, Optional, List
import logging
import uuid
from datetime import datetime

from multi_agent.core import BaseAgent, Message, MessageType
from multi_agent.core.shared_state import get_shared_state


logger = logging.getLogger(__name__)


class Task:
    """任务结构"""
    def __init__(self, task_id: str, agent_name: str, action: str,
                 target: Any, params: Dict = None, parallel: bool = False):
        self.task_id = task_id
        self.agent_name = agent_name
        self.action = action
        self.target = target
        self.params = params or {}
        self.parallel = parallel
        self.status = "pending"  # pending / running / completed / failed
        self.result = None
        self.error = None
        self.created_at = datetime.now().isoformat()
        self.completed_at = None

    def to_dict(self) -> Dict:
        return {
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "action": self.action,
            "target": self.target,
            "params": self.params,
            "parallel": self.parallel,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "completed_at": self.completed_at
        }

    def mark_running(self):
        self.status = "running"

    def mark_completed(self, result: Any):
        self.status = "completed"
        self.result = result
        self.completed_at = datetime.now().isoformat()

    def mark_failed(self, error: str):
        self.status = "failed"
        self.error = error
        self.completed_at = datetime.now().isoformat()


class PlannerAgent(BaseAgent):
    """
    计划制定 Agent

    职责：
    1. 根据意图理解结果制定执行计划
    2. 识别可以并行执行的任务
    3. 动态调整计划（根据执行情况）
    """

    def __init__(self, message_bus=None, shared_state=None):
        super().__init__(
            name="planner_agent",
            role="计划制定专家",
            message_bus=message_bus
        )
        self.shared_state = shared_state or get_shared_state()
        self.tasks: Dict[str, Task] = {}  # task_id -> Task
        logger.info("PlannerAgent 初始化完成")

    def can_handle(self, message: Message) -> bool:
        return message.recipient == self.name

    def process(self, message: Message) -> Optional[Message]:
        """
        制定分析计划

        输入消息 payload:
            - competitors: 竞品列表
            - dimensions: 分析维度
            - output_format: 输出格式

        输出响应 payload:
            - tasks: 任务列表（按执行顺序）
        """
        if message.msg_type != MessageType.TASK_START:
            return None

        competitors = message.payload.get("competitors", [])
        dimensions = message.payload.get("dimensions", ["features", "pricing"])
        output_format = message.payload.get("output_format", "markdown")

        if not competitors:
            return message.reply(
                MessageType.TASK_FAILED,
                {"error": "没有竞品，无法制定计划"}
            )

        self.log(f"开始制定计划: {len(competitors)} 个竞品, {len(dimensions)} 个维度")
        self.report_progress(20, "📋 制定分析计划...")

        # 清空旧任务
        self.tasks.clear()

        # ========== 阶段 1: 数据采集（并行） ==========
        for i, competitor in enumerate(competitors):
            task = Task(
                task_id=f"crawl_{i}_{uuid.uuid4().hex[:8]}",
                agent_name="crawler_agent",
                action="collect",
                target=competitor,
                params={"competitor": competitor},
                parallel=True  # 多个竞品并行爬取
            )
            self.tasks[task.task_id] = task

        # ========== 阶段 2: 数据验证（并行） ==========
        verify_task = Task(
            task_id=f"verify_{uuid.uuid4().hex[:8]}",
            agent_name="verifier_agent",
            action="verify",
            target="all",
            params={"stage": "crawling"},
            parallel=False  # 验证是单点
        )
        self.tasks[verify_task.task_id] = verify_task

        # ========== 阶段 3: 数据分析（按维度并行） ==========
        for dimension in dimensions:
            task = Task(
                task_id=f"analyze_{dimension}_{uuid.uuid4().hex[:8]}",
                agent_name="analyzer_agent",
                action=f"analyze_{dimension}",
                target="all",
                params={"dimension": dimension, "competitors": competitors},
                parallel=True  # 不同维度并行分析
            )
            self.tasks[task.task_id] = task

        # ========== 阶段 4: 洞察生成 ==========
        insight_task = Task(
            task_id=f"insight_{uuid.uuid4().hex[:8]}",
            agent_name="insight_agent",
            action="generate",
            target="all",
            params={"competitors": competitors},
            parallel=False
        )
        self.tasks[insight_task.task_id] = insight_task

        # ========== 阶段 5: 报告生成 ==========
        report_task = Task(
            task_id=f"report_{uuid.uuid4().hex[:8]}",
            agent_name="reporter_agent",
            action="generate",
            target="all",
            params={"output_format": output_format},
            parallel=False
        )
        self.tasks[report_task.task_id] = report_task

        # 组织任务列表（按阶段）
        task_list = list(self.tasks.values())
        task_dicts = [t.to_dict() for t in task_list]

        # 保存到共享状态
        self.shared_state.set("plan", task_dicts, agent=self.name)
        self.shared_state.set("competitors", competitors, agent=self.name)
        self.shared_state.set("output_format", output_format, agent=self.name)

        # 统计
        parallel_count = sum(1 for t in task_list if t.parallel)
        self.log(
            f"✅ 计划制定完成: {len(task_list)} 个任务, "
            f"其中 {parallel_count} 个可并行"
        )
        self.report_progress(
            25,
            f"📋 计划已制定：{len(task_list)} 个任务"
        )

        return message.reply(
            MessageType.TASK_COMPLETE,
            {
                "tasks": task_dicts,
                "total_tasks": len(task_list),
                "parallel_tasks": parallel_count
            }
        )

    def update_task_status(self, task_id: str, status: str, result: Any = None, error: str = None):
        """更新任务状态"""
        if task_id in self.tasks:
            task = self.tasks[task_id]
            if status == "running":
                task.mark_running()
            elif status == "completed":
                task.mark_completed(result)
                self.log(f"✅ 任务完成: {task_id}")
            elif status == "failed":
                task.mark_failed(error)
                self.log(f"❌ 任务失败: {task_id} - {error}")
