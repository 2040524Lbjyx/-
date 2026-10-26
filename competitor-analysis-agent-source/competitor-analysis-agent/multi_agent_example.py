"""
多 Agent 竞品分析系统使用示例

展示如何使用新的多 Agent 协作系统。
"""
import logging
import time
import sys

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def example_basic_usage():
    """基础使用 - 与原系统相同的接口"""
    print("\n" + "=" * 60)
    print("示例 1: 基础使用（兼容原接口）")
    print("=" * 60)

    # 使用兼容接口
    from multi_agent_compat import CoordinatorAgent

    coordinator = CoordinatorAgent()

    def on_progress(progress, message):
        print(f"  [进度 {progress:3d}%] {message}")

    result = coordinator.run(
        user_query="分析 Notion 和 Obsidian",
        output_format="markdown",
        verbose=True,
        callback=on_progress,
        max_workers=2
    )

    print(f"\n分析结果:")
    print(f"  状态: {result['status']}")
    print(f"  报告: {result['report_path']}")
    print(f"  竞品: {result['competitors']}")

    if result['data'].get('insights'):
        print(f"\n  AI 洞察:")
        for i, insight in enumerate(result['data']['insights'][:3], 1):
            print(f"    {i}. {insight}")


def example_native_usage():
    """原生使用 - 展示多 Agent 系统的真正能力"""
    print("\n" + "=" * 60)
    print("示例 2: 原生使用（展示多 Agent 协作）")
    print("=" * 60)

    from multi_agent import MultiAgentOrchestrator

    # 创建编排器
    orchestrator = MultiAgentOrchestrator(max_workers=3)

    # 设置回调
    def on_progress(progress, message):
        print(f"  [进度 {progress:3d}%] {message}")

    def on_log(message):
        print(f"    [日志] {message}")

    orchestrator.set_callbacks(on_progress, on_log)

    # 运行分析
    result = orchestrator.run(
        user_query="对比 Notion 和 Obsidian 的功能",
        output_format="markdown"
    )

    # 查看 Agent 状态
    print("\n" + "-" * 40)
    print("Agent 状态:")
    print("-" * 40)
    for state in orchestrator.get_agent_states():
        print(f"  {state['name']:20s} | {state['status']:10s} | "
              f"收:{state['inbox_count']:2d} | 发:{state['outbox_count']:2d}")

    # 查看消息历史
    print("\n" + "-" * 40)
    print("消息历史（前10条）:")
    print("-" * 40)
    history = orchestrator.get_message_history()[:10]
    for msg in history:
        print(f"  {msg['sender']:15s} -> {msg['recipient']:15s} | {msg['msg_type']}")

    orchestrator.shutdown()


def example_agent_communication():
    """展示 Agent 之间的消息通信"""
    print("\n" + "=" * 60)
    print("示例 3: Agent 之间的消息通信")
    print("=" * 60)

    from multi_agent import (
        MultiAgentOrchestrator,
        Message,
        MessageType,
        get_message_bus
    )

    orchestrator = MultiAgentOrchestrator()

    # 监听所有消息
    bus = get_message_bus()
    received_messages = []

    def monitor(msg):
        received_messages.append({
            "from": msg.sender,
            "to": msg.recipient,
            "type": msg.msg_type.value,
            "time": msg.timestamp
        })

    # 订阅所有 TASK_COMPLETE 消息
    bus.subscribe(MessageType.TASK_COMPLETE, monitor)

    # 运行分析
    result = orchestrator.run(
        user_query="分析飞书和钉钉",
        output_format="html"
    )

    # 显示通信过程
    print(f"\n共产生了 {len(received_messages)} 条任务完成消息:")
    for msg in received_messages[:15]:
        print(f"  {msg['time'][:19]} | {msg['from']} -> {msg['to']} | {msg['type']}")

    orchestrator.shutdown()


def example_parallel_execution():
    """展示并行执行能力"""
    print("\n" + "=" * 60)
    print("示例 4: 并行执行能力")
    print("=" * 60)

    from multi_agent import MultiAgentOrchestrator

    # 使用更高并发度
    orchestrator = MultiAgentOrchestrator(max_workers=4)

    start = time.time()
    result = orchestrator.run(
        user_query="分析 Notion, Obsidian, Roam Research, Logseq",
        output_format="markdown"
    )
    elapsed = time.time() - start

    print(f"\n并行执行 4 个竞品，耗时 {elapsed:.1f} 秒")
    print(f"竞品: {result['competitors']}")

    # 查看消息历史，统计并行情况
    history = orchestrator.get_message_history()
    parallel_msgs = [m for m in history if m['msg_type'] == 'task_start']
    print(f"任务启动消息: {len(parallel_msgs)} 条")

    orchestrator.shutdown()


def example_error_recovery():
    """展示错误恢复能力（反馈循环）"""
    print("\n" + "=" * 60)
    print("示例 5: 错误恢复（Verifier -> Crawler 反馈循环）")
    print("=" * 60)

    from multi_agent import MultiAgentOrchestrator

    orchestrator = MultiAgentOrchestrator()

    # 显示反馈循环
    def on_log(msg):
        if "改进" in msg or "验证" in msg or "反馈" in msg:
            print(f"  🔄 {msg}")

    orchestrator.set_callbacks(log_callback=on_log)

    result = orchestrator.run(
        user_query="分析 Notion",  # 单个竞品，可能触发改进请求
        output_format="markdown"
    )

    print(f"\n分析结果: {result['status']}")
    orchestrator.shutdown()


if __name__ == "__main__":
    print("🤖 多 Agent 竞品分析系统演示")
    print("=" * 60)

    # 选择要运行的示例
    examples = {
        "1": ("基础使用", example_basic_usage),
        "2": ("原生使用", example_native_usage),
        "3": ("消息通信", example_agent_communication),
        "4": ("并行执行", example_parallel_execution),
        "5": ("错误恢复", example_error_recovery),
    }

    print("\n可用示例:")
    for key, (name, _) in examples.items():
        print(f"  {key}. {name}")
    print("  a. 运行所有示例")

    choice = input("\n请选择 (1-5/a): ").strip().lower()

    if choice == "a":
        for _, (_, func) in examples.items():
            try:
                func()
            except Exception as e:
                print(f"  ❌ 示例失败: {e}")
                logger.error(f"示例失败: {e}", exc_info=True)
    elif choice in examples:
        try:
            examples[choice][1]()
        except Exception as e:
            print(f"❌ 运行失败: {e}")
            logger.error(f"运行失败: {e}", exc_info=True)
    else:
        print("无效选择")
