"""
api_cost_tracker_v2.py

简化版 API 成本统计 - 直接读取 response.usage_metadata

用法:
  python tests/api_cost_tracker_v2.py
  python tests/api_cost_tracker_v2.py --products Notion Figma
"""

import sys
import os
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage


# ── 定价 ──────────────────────────────────────────────────────────────────────

PRICING = {
    "deepseek-chat": {"input": 0.14, "output": 0.28},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    "default": {"input": 0.14, "output": 0.28},
}


class APICostTracker:
    """简单的 API 成本追踪器"""
    
    def __init__(self):
        self.records = []
        self.total_input = 0
        self.total_output = 0
        self.total_cost = 0.0
    
    def add_call(self, input_tokens: int, output_tokens: int, model: str = None):
        """记录一次 API 调用"""
        model = model or os.getenv("OPENAI_MODEL", "deepseek-chat")
        price = PRICING.get(model, PRICING["default"])
        
        cost = (input_tokens / 1_000_000 * price["input"] +
                output_tokens / 1_000_000 * price["output"])
        
        self.records.append({
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_usd": round(cost, 6),
        })
        
        self.total_input += input_tokens
        self.total_output += output_tokens
        self.total_cost += cost
    
    def get_summary(self) -> Dict:
        return {
            "model": os.getenv("OPENAI_MODEL", "deepseek-chat"),
            "total_calls": len(self.records),
            "total_input_tokens": self.total_input,
            "total_output_tokens": self.total_output,
            "total_tokens": self.total_input + self.total_output,
            "total_cost_usd": round(self.total_cost, 4),
            "total_cost_rmb": round(self.total_cost * 7.2, 2),
        }


def track_llm_response(response, tracker: APICostTracker):
    """从 LLM response 中提取 token 用量并记录"""
    if hasattr(response, "usage_metadata"):
        metadata = response.usage_metadata
        input_tokens = metadata.get("input_tokens", 0)
        output_tokens = metadata.get("output_tokens", 0)
        tracker.add_call(input_tokens, output_tokens)
        return input_tokens, output_tokens
    return 0, 0


def analyze_product(product_name: str, tracker: APICostTracker) -> Dict:
    """分析单个产品并记录 API 用量"""
    from agents.crawler import DataCollectionAgent
    
    print(f"\n{'='*60}")
    print(f"分析产品: {product_name}")
    print(f"{'='*60}")
    
    # 爬取
    print(f"[1/2] 爬取 {product_name}...")
    crawler = DataCollectionAgent(use_playwright=True)
    
    # 拦截 crawler 的 LLM 调用
    original_llm = crawler.llm
    
    # 包装 LLM 的 invoke 方法来追踪
    original_invoke = original_llm.invoke
    def tracked_invoke(*args, **kwargs):
        response = original_invoke(*args, **kwargs)
        track_llm_response(response, tracker)
        return response
    
    crawler.llm.invoke = tracked_invoke
    
    # 同样处理 batch
    if hasattr(original_llm, 'batch'):
        original_batch = original_llm.batch
        def tracked_batch(*args, **kwargs):
            responses = original_batch(*args, **kwargs)
            for resp in responses:
                track_llm_response(resp, tracker)
            return responses
        crawler.llm.batch = tracked_batch
    
    # 执行爬取
    data = crawler.collect(product_name)
    
    # 恢复原始 LLM
    crawler.llm.invoke = original_invoke
    
    print(f"  ✓ 爬取完成 | features={len(data.get('features', {}).get('core', [])) + len(data.get('features', {}).get('advanced', []))}")
    print(f"  ✓ 当前累计: tokens={tracker.total_input + tracker.total_output:,} | cost=${tracker.total_cost:.4f}")
    
    return data


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--products", nargs="*", default=["Notion", "Figma"])
    args = parser.parse_args()
    
    print("=" * 70)
    print("  API 成本统计工具 (v2)")
    print("=" * 70)
    print(f"模型: {os.getenv('OPENAI_MODEL', 'deepseek-chat')}")
    print(f"测试产品: {args.products}")
    print()
    
    tracker = APICostTracker()
    
    for product in args.products:
        analyze_product(product, tracker)
    
    # 打印报告
    summary = tracker.get_summary()
    
    print("\n" + "=" * 70)
    print("  统计结果")
    print("=" * 70)
    print(f"总调用次数:   {summary['total_calls']}")
    print(f"总 Token 用量: {summary['total_tokens']:,}")
    print(f"  - Input:  {summary['total_input_tokens']:,}")
    print(f"  - Output: {summary['total_output_tokens']:,}")
    print()
    print(f"总成本: ${summary['total_cost_usd']:.4f} USD")
    print(f"      ≈ ¥{summary['total_cost_rmb']:.2f} RMB")
    print("=" * 70)
    
    # 保存
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = PROJECT_ROOT / "reports" / f"api_cost_{ts}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump({"summary": summary, "records": tracker.records}, f, indent=2, ensure_ascii=False)
    
    print(f"\n报告已保存: {report_path}")


if __name__ == "__main__":
    main()
