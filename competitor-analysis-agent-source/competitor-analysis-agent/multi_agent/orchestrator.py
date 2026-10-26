"""
多 Agent 编排器 - 使用 LangGraph 实现 Agent 编排

这是整个多 Agent 系统的入口：
- 创建和管理所有 Agent
- 编排 Agent 之间的协作流程
- 支持并行执行
- 处理错误和反馈循环
"""
from typing import Dict, Any, Optional, List
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from multi_agent.core import (
    MessageBus,
    SharedState,
    BaseAgent,
    Message,
    MessageType
)
from multi_agent.agents import (
    IntentAgent,
    PlannerAgent,
    CrawlerAgent,
    VerifierAgent,
    AnalyzerAgent,
    InsightAgent,
    ReporterAgent
)


logger = logging.getLogger(__name__)


class MultiAgentOrchestrator:
    """
    多 Agent 编排器

    这是真正的多 Agent 系统的"导演"：
    1. 管理所有 Agent 的生命周期
    2. 启动 Agent 并协调它们的协作
    3. 等待任务完成
    4. 收集最终结果

    特点：
    - Agent 之间通过消息总线通信（不是函数调用）
    - 支持并行执行
    - 支持反馈循环
    - 集中处理进度回调
    """

    def __init__(self, max_workers: int = 3):
        """
        初始化编排器

        Args:
            max_workers: Crawler Agent 的并行工作数
        """
        # 每个编排器拥有独立总线和状态，避免并发请求串数据。
        self.message_bus = MessageBus()
        self.shared_state = SharedState()

        # 创建所有 Agent（真正的多 Agent 协作）
        self.agents: Dict[str, BaseAgent] = {
            "intent_agent": IntentAgent(self.message_bus),
            "planner_agent": PlannerAgent(self.message_bus, self.shared_state),
            "crawler_agent": CrawlerAgent(
                self.message_bus, max_workers=max_workers,
                shared_state=self.shared_state
            ),
            "verifier_agent": VerifierAgent(self.message_bus, self.shared_state),
            "analyzer_agent": AnalyzerAgent(self.message_bus, self.shared_state),
            "insight_agent": InsightAgent(self.message_bus, self.shared_state),
            "reporter_agent": ReporterAgent(self.message_bus, self.shared_state),
        }

        # 进度回调
        self._progress_callback = None
        self._log_callback = None

        # 任务状态
        self._completed_tasks = set()
        self._task_results: Dict[str, Any] = {}

        # 监听任务完成消息
        self.message_bus.subscribe(MessageType.TASK_COMPLETE, self._on_task_complete)
        self.message_bus.subscribe(MessageType.TASK_FAILED, self._on_task_failed)

        logger.info(f"MultiAgentOrchestrator 初始化完成，注册了 {len(self.agents)} 个 Agent")

    def set_callbacks(self, progress_callback=None, log_callback=None):
        """设置进度和日志回调"""
        self._progress_callback = progress_callback
        self._log_callback = log_callback
        for agent in self.agents.values():
            agent.set_callbacks(progress_callback, log_callback)

    def _on_task_complete(self, message: Message):
        """处理任务完成消息"""
        task = message.correlation_id or message.payload.get("task", message.sender)
        self._completed_tasks.add(task)
        self._task_results[task] = message.payload
        logger.info(f"任务完成: {task}")

    def _on_task_failed(self, message: Message):
        """处理任务失败消息，立即唤醒等待方。"""
        task = message.correlation_id or message.payload.get("task", message.sender)
        payload = dict(message.payload)
        payload["_failed"] = True
        self._completed_tasks.add(task)
        self._task_results[task] = payload
        logger.error(f"任务失败: {task}: {payload.get('error', '未知错误')}")

    def _wait_for_task(self, agent_name: str, timeout: float = 120) -> Optional[Dict]:
        """等待指定 Agent 完成任务"""
        start = time.time()
        while time.time() - start < timeout:
            if agent_name in self._completed_tasks:
                return self._task_results.get(agent_name)
            time.sleep(0.5)
        logger.warning(f"等待 {agent_name} 超时")
        return None

    def _send_task_and_wait(self, agent_name: str, payload: Dict,
                            task_name: str = None, timeout: float = 180) -> Optional[Dict]:
        """
        发送任务给指定 Agent 并等待完成

        这不是函数调用！是：
        1. 向消息总线发送消息
        2. Agent 自主处理
        3. Agent 完成后发送响应
        4. 我们等待响应
        """
        # 清空已完成标记
        self._completed_tasks.discard(task_name or agent_name)

        # 发送任务消息
        self.message_bus.send(Message(
            sender="orchestrator",
            recipient=agent_name,
            msg_type=MessageType.TASK_START,
            payload=payload,
            correlation_id=task_name or agent_name
        ))

        # 等待任务完成
        return self._wait_for_task(task_name or agent_name, timeout)

    def run(self, user_query: str, output_format: str = "markdown",
            verbose: bool = False) -> Dict[str, Any]:
        """
        运行多 Agent 竞品分析

        Args:
            user_query: 用户输入
            output_format: 输出格式
            verbose: 是否显示详细日志

        Returns:
            分析结果
        """
        start_time = time.time()
        self._log("=" * 60)
        self._log("🚀 启动多 Agent 竞品分析系统")
        self._log("=" * 60)

        # 清空状态
        self.shared_state.clear()
        self._completed_tasks.clear()
        self._task_results.clear()

        self._report(0, "🚀 启动多 Agent 竞品分析...")

        try:
            # ========== 阶段 1: 意图理解 ==========
            self._log("📌 阶段 1: 意图理解")
            intent_result = self._send_task_and_wait(
                "intent_agent",
                {"user_query": user_query},
                task_name="understand_intent"
            )

            if not intent_result or intent_result.get("_failed"):
                return self._error_result(
                    (intent_result or {}).get("error", "意图理解失败")
                )

            competitors = intent_result.get("competitors", [])
            if not competitors:
                return self._error_result("未识别到竞品")

            self._log(f"✅ 识别到 {len(competitors)} 个竞品: {competitors}")
            self._report(15, f"✅ 识别到 {len(competitors)} 个竞品")

            # ========== 阶段 2: 制定计划 ==========
            self._log("📌 阶段 2: 制定计划")
            plan_result = self._send_task_and_wait(
                "planner_agent",
                {
                    "competitors": competitors,
                    "dimensions": intent_result.get("dimensions", ["features", "pricing"]),
                    "output_format": output_format
                },
                task_name="create_plan"
            )

            if not plan_result or plan_result.get("_failed"):
                return self._error_result(
                    (plan_result or {}).get("error", "计划制定失败")
                )

            self._log(
                f"✅ 计划已制定: {plan_result.get('total_tasks', 0)} 个任务, "
                f"其中 {plan_result.get('parallel_tasks', 0)} 个可并行"
            )

            # ========== 阶段 3: 并行执行数据采集 ==========
            self._log("📌 阶段 3: 并行数据采集")
            crawl_result = self._send_task_and_wait(
                "crawler_agent",
                {"competitors": competitors},
                task_name="crawl_competitors"
            )

            if not crawl_result or crawl_result.get("_failed"):
                return self._error_result(
                    (crawl_result or {}).get("error", "数据采集失败")
                )

            self._log(
                f"✅ 采集完成: 成功 {crawl_result.get('success', 0)}, "
                f"失败 {crawl_result.get('failed', 0)}"
            )

            # ========== 阶段 4: 验证（自动触发，验证完成后 Verifier 会主动通知 Analyzer） ==========
            self._log("📌 阶段 4: 数据验证")
            self._report(52, "🔍 正在验证数据...")

            # 等待验证完成（Verifier 在收到 DATA_READY 后会自动处理）
            verify_result = self._wait_for_task("verifier_agent", timeout=30)
            self._log(f"✅ 验证完成: {verify_result}")

            # ========== 阶段 5: 多维度并行分析 ==========
            self._log("📌 阶段 5: 多维度并行分析")
            dimensions = intent_result.get("dimensions", ["features", "pricing"])
            if isinstance(dimensions, str):
                dimensions = [dimensions]
            dimensions = [d for d in dimensions if d in {"features", "pricing", "changelog"}]
            if not dimensions:
                dimensions = ["features", "pricing"]

            # 并行发送多个分析任务
            analysis_results = {}
            with ThreadPoolExecutor(max_workers=len(dimensions)) as executor:
                futures = {}
                for dim in dimensions:
                    self._completed_tasks.discard(f"analyze_{dim}")
                    self.message_bus.send(Message(
                        sender="orchestrator",
                        recipient="analyzer_agent",
                        msg_type=MessageType.TASK_START,
                        payload={
                            "dimension": dim,
                            "competitors": competitors
                        },
                        correlation_id=f"analyze_{dim}"
                    ))
                    futures[dim] = f"analyze_{dim}"

                # 等待所有分析完成
                for dim, task_name in futures.items():
                    result = self._wait_for_task(task_name, timeout=120)
                    if result and not result.get("_failed"):
                        analysis_results[dim] = result
                        self._log(f"✅ {dim} 分析完成")

            # ========== 阶段 6: 洞察生成 ==========
            self._log("📌 阶段 6: AI 洞察生成")
            insight_result = self._send_task_and_wait(
                "insight_agent",
                {"competitors": competitors},
                task_name="generate_insights"
            )

            if not insight_result:
                self._log("⚠️ 洞察生成失败，继续生成报告")

            # ========== 阶段 7: 报告生成 ==========
            self._log("📌 阶段 7: 报告生成")
            report_result = self._send_task_and_wait(
                "reporter_agent",
                {
                    "competitors": competitors,
                    "output_format": output_format
                },
                task_name="generate_report"
            )

            if not report_result or report_result.get("_failed"):
                return self._error_result(
                    (report_result or {}).get("error", "报告生成失败")
                )

            report_path = report_result.get("report_path")
            elapsed = time.time() - start_time
            self._log(f"🎉 全部完成！耗时 {elapsed:.1f}秒")
            self._report(100, "🎉 分析全部完成！")

            # ========== 整理结果 ==========
            return self._collect_results(competitors, analysis_results, report_path, intent_result)

        except Exception as e:
            self._log(f"❌ 系统异常: {e}", )
            return self._error_result(str(e))

    def _collect_results(self, competitors, analysis_results, report_path, intent_result) -> Dict:
        """收集并整理结果"""
        # 整理分析结果
        data = {}

        for dim, result in analysis_results.items():
            inner = result.get("result", {})
            if dim == "features":
                data["feature_matrix"] = inner
            elif dim == "pricing":
                data["pricing_analysis"] = inner
            elif dim == "changelog":
                data["changelog_analysis"] = inner

        # 获取洞察
        insights = self.shared_state.get("insights", [])
        data["insights"] = insights

        # 数据来源信息
        crawled_data = self.shared_state.get("crawled_data", {})
        competitor_sources = {}
        for name, comp_data in crawled_data.items():
            if comp_data.get("_error"):
                competitor_sources[name] = {"_source": "error"}
            else:
                competitor_sources[name] = {
                    "_source": comp_data.get("_source", "unknown"),
                    "_source_warn": comp_data.get("_source_warn", ""),
                    "_website": comp_data.get("website", ""),
                }
        data["competitor_sources"] = competitor_sources

        return {
            "status": "success",
            "report_path": report_path,
            "competitors": competitors,
            "data": data,
            "errors": []
        }

    def _error_result(self, error_msg: str) -> Dict:
        """返回错误结果"""
        return {
            "status": "failed",
            "report_path": None,
            "competitors": [],
            "data": {},
            "errors": [error_msg]
        }

    def _report(self, progress: int, message: str):
        """报告进度"""
        if self._progress_callback:
            try:
                self._progress_callback(progress, message)
            except Exception as e:
                logger.warning(f"进度回调失败: {e}")

    def _log(self, message: str):
        """记录日志"""
        logger.info(message)
        if self._log_callback:
            try:
                self._log_callback(message)
            except Exception as e:
                logger.warning(f"日志回调失败: {e}")

    def get_agent_states(self) -> List[Dict]:
        """获取所有 Agent 状态（用于调试和监控）"""
        return [agent.get_state() for agent in self.agents.values()]

    def get_message_history(self) -> List[Dict]:
        """获取消息历史"""
        return [msg.to_dict() for msg in self.message_bus.get_history()]

    def shutdown(self):
        """关闭编排器"""
        self.message_bus.shutdown()
        logger.info("MultiAgentOrchestrator 已关闭")


# 使用示例
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 创建编排器
    orchestrator = MultiAgentOrchestrator(max_workers=2)

    # 设置回调
    def on_progress(progress, message):
        print(f"[进度 {progress}%] {message}")

    def on_log(message):
        print(f"  {message}")

    orchestrator.set_callbacks(on_progress, on_log)

    # 运行分析
    result = orchestrator.run(
        user_query="分析 Notion 和 Obsidian",
        output_format="markdown"
    )

    print("\n" + "=" * 60)
    print("分析结果:")
    print(f"状态: {result['status']}")
    print(f"报告: {result['report_path']}")
    print(f"竞品: {result['competitors']}")

    # 显示 Agent 状态
    print("\nAgent 状态:")
    for state in orchestrator.get_agent_states():
        print(f"  {state['name']}: {state['status']} (收:{state['inbox_count']}, 发:{state['outbox_count']})")

    orchestrator.shutdown()
