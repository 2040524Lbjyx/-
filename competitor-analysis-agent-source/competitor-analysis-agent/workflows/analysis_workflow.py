"""
LangGraph工作流定义
定义多Agent协作的状态机

⚠️ 弃用警告：此文件已被弃用，不再使用。
   工作流逻辑已移至 agents/coordinator.py 中的 CoordinatorAgent 类。

   此文件保留仅作为参考，将在未来版本中删除。

Date: 2026-07-02
Reason: 修复逻辑错误 - 问题4：死代码
"""

import warnings
warnings.warn(
    "workflows/analysis_workflow.py 已弃用，请使用 agents/coordinator.py 中的 CoordinatorAgent",
    DeprecationWarning,
    stacklevel=2
)

# 以下代码已弃用，不再维护
# 请参考 agents/coordinator.py 中的实现

raise ImportError(
    "此模块已弃用。请导入 agents.coordinator 中的 CoordinatorAgent 类。"
)

