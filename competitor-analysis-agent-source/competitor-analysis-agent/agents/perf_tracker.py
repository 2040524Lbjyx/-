"""
Global Performance Tracker
记录所有 LLM 调用的时间和 token 用量
"""
import time
from typing import List, Dict, Any

class PerformanceTracker:
    """全局性能统计器"""
    
    def __init__(self):
        self.records: List[Dict[str, Any]] = []
        self.start_time = time.time()
    
    def log_call(self, agent: str, method: str, input_tokens: int, output_tokens: int, elapsed: float):
        """记录一次 LLM 调用"""
        self.records.append({
            'agent': agent,
            'method': method,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
            'total_tokens': input_tokens + output_tokens,
            'elapsed': elapsed,
            'timestamp': time.time() - self.start_time,
        })
    
    def get_summary(self) -> Dict[str, Any]:
        """获取统计摘要"""
        if not self.records:
            return {}
        
        total_calls = len(self.records)
        total_input = sum(r['input_tokens'] for r in self.records)
        total_output = sum(r['output_tokens'] for r in self.records)
        total_time = sum(r['elapsed'] for r in self.records)
        
        return {
            'total_calls': total_calls,
            'total_input_tokens': total_input,
            'total_output_tokens': total_output,
            'total_tokens': total_input + total_output,
            'total_time': total_time,
            'avg_time_per_call': total_time / total_calls if total_calls > 0 else 0,
            'records': self.records,
        }
    
    def format_report(self) -> str:
        """生成格式化的统计报告"""
        summary = self.get_summary()
        if not summary:
            return "No LLM calls recorded."
        
        lines = [
            "## 📊 Performance Statistics",
            "",
            f"- **Total LLM Calls**: {summary['total_calls']}",
            f"- **Total Tokens**: {summary['total_tokens']:,} (Input: {summary['total_input_tokens']:,}, Output: {summary['total_output_tokens']:,})",
            f"- **Total Time**: {summary['total_time']:.2f}s",
            f"- **Avg Time per Call**: {summary['avg_time_per_call']:.2f}s",
            "",
            "### Detailed Breakdown",
            "",
            "| Agent | Method | Input | Output | Time (s) |",
            "|-------|--------|-------|--------|----------|",
        ]
        
        for r in summary['records']:
            lines.append(f"| {r['agent']} | {r['method']} | {r['input_tokens']} | {r['output_tokens']} | {r['elapsed']:.2f} |")
        
        return "\n".join(lines)


# 全局实例
_global_tracker: PerformanceTracker = None

def get_tracker() -> PerformanceTracker:
    """获取全局统计器"""
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = PerformanceTracker()
    return _global_tracker

def reset_tracker():
    """重置统计器"""
    global _global_tracker
    _global_tracker = PerformanceTracker()
