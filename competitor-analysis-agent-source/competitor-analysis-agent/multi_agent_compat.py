"""
多 Agent 系统入口 - 兼容原有 Coordinator Agent 接口

这个文件让原有的调用代码（如 main.py、app.py）可以无缝切换到多 Agent 系统。

使用方式：
    # 原代码
    from agents.coordinator import CoordinatorAgent
    coordinator = CoordinatorAgent()
    result = coordinator.run("分析Notion和Obsidian")

    # 新代码（只需要修改导入）
    from multi_agent_compat import CoordinatorAgent
    coordinator = CoordinatorAgent()
    result = coordinator.run("分析Notion和Obsidian")
"""
from typing import Dict, Any, Optional
import logging

from multi_agent import MultiAgentOrchestrator


logger = logging.getLogger(__name__)


class CoordinatorAgent:
    """
    兼容原有接口的 Coordinator Agent

    内部使用多 Agent 系统，但对外保持原有 API 不变。
    """

    def __init__(self, model: str = None, temperature: float = None):
        """初始化（保持与原接口一致）"""
        self.model = model
        self.temperature = temperature
        self.orchestrator: Optional[MultiAgentOrchestrator] = None
        self._callback = None
        self._log_callback = None
        self._max_workers = 3
        logger.info("CoordinatorAgent (多 Agent 版本) 初始化")

    def run(self, user_query: str, output_format: str = "markdown",
            verbose: bool = False, callback: Any = None,
            log_callback: Any = None, max_workers: int = 3) -> Dict[str, Any]:
        """
        运行竞品分析（兼容原接口）

        Args:
            user_query: 用户输入
            output_format: 输出格式 (markdown/html)
            verbose: 是否显示详细日志
            callback: 进度回调函数
            log_callback: 日志回调函数
            max_workers: 并行爬取的最大并发数

        Returns:
            包含分析结果的字典
        """
        # 创建编排器
        self.orchestrator = MultiAgentOrchestrator(max_workers=max_workers)
        self.orchestrator.set_callbacks(
            progress_callback=callback,
            log_callback=log_callback if verbose else None
        )

        try:
            return self.orchestrator.run(
                user_query=user_query,
                output_format=output_format,
                verbose=verbose
            )
        finally:
            self.orchestrator.shutdown()
