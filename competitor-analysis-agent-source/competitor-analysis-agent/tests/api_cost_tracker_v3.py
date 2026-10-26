"""
api_cost_tracker_v3.py

正确使用 LangChain Callback 系统追踪 API 成本

用法:
  python tests/api_cost_tracker_v3.py
  python tests/api_cost_tracker_v3.py --products Notion Figma Slack
"""

import sys
import os
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from langchain_openai import ChatOpenAI
from langchain_core.callbacks import BaseCallbackHandler


# ── 定价 ──────────────────────────────────────────────────────────────────────

PRICING = {
    "deepseek-chat": {"input": 0.14, "output": 0.28},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    "default": {"input": 0.14, "output": 0.28},
}


class CostTrackerCallback(BaseCallbackHandler):
    """自定义 Callback Handler - 追踪 token 用量和成本"""
    
    def __init__(self):
        super().__init__()
        self.records = []
        self.total_input = 0
        self.total_output = 0
        self.total_cost = 0.0
        self.current_model = None
    
    def on_llm_end(self, response, **kwargs):
        """LLM 调用结束时触发 - 提取 token 用量"""
        try:
            # 从 response 中提取 usage_metadata
            if hasattr(response, 'usage_metadata'):
                metadata = response.usage_metadata
                input_tokens = metadata.get('input_tokens', 0)
                output_tokens = metadata.get('output_tokens', 0)
                
                # 获取模型名称
                if hasattr(response, 'response_metadata'):
                    self.current_model = response.response_metadata.get('model_name', self.current_model)
                
                # 计算成本
                model = self.current_model or os.getenv('OPENAI_MODEL', 'deepseek-chat')
                price = PRICING.get(model, PRICING['default'])
                cost = (input_tokens / 1_000_000 * price['input'] +
                        output_tokens / 1_000_000 * price['output'])
                
                self.records.append({
                    'timestamp': datetime.now().isoformat(),
                    'model': model,
                    'input_tokens': input_tokens,
                    'output_tokens': output_tokens,
                    'total_tokens': input_tokens + output_tokens,
                    'cost_usd': round(cost, 6),
                })
                
                self.total_input += input_tokens
                self.total_output += output_tokens
                self.total_cost += cost
                
        except Exception as e:
            print(f"[CostTracker] 警告: 无法提取 token 用量: {e}")
    
    def get_summary(self) -> Dict:
        return {
            'model': self.current_model or os.getenv('OPENAI_MODEL', 'deepseek-chat'),
            'total_calls': len(self.records),
            'total_input_tokens': self.total_input,
            'total_output_tokens': self.total_output,
            'total_tokens': self.total_input + self.total_output,
            'total_cost_usd': round(self.total_cost, 4),
            'total_cost_rmb': round(self.total_cost * 7.2, 2),
            'avg_tokens_per_call': round((self.total_input + self.total_output) / len(self.records)) if self.records else 0,
            'avg_cost_per_call_usd': round(self.total_cost / len(self.records), 4) if self.records else 0,
        }


def run_analysis_with_tracking(products: List[str]) -> Dict:
    """运行分析并记录 API 成本"""
    from agents.crawler import DataCollectionAgent
    
    # 创建 tracker
    tracker = CostTrackerCallback()
    
    # 保存原始的 ChatOpenAI.__init__ 方法
    original_init = ChatOpenAI.__init__
    
    # 包装 __init__ 来注入 callback
    def patched_init(self, *args, **kwargs):
        if 'callbacks' not in kwargs:
            kwargs['callbacks'] = [tracker]
        else:
            kwargs['callbacks'].append(tracker)
        original_init(self, *args, **kwargs)
    
    # 应用 patch
    ChatOpenAI.__init__ = patched_init
    
    try:
        results = []
        
        for product in products:
            print(f"\n{'='*60}")
            print(f"分析产品: {product}")
            print(f"{'='*60}")
            
            calls_before = len(tracker.records)
            
            # 爬取
            print(f"[1/1] 爬取 {product}...")
            crawler = DataCollectionAgent(use_playwright=True)
            data = crawler.collect(product)
            
            # 统计本次产品的用量
            calls_after = len(tracker.records)
            product_calls = tracker.records[calls_before:calls_after]
            product_input = sum(r['input_tokens'] for r in product_calls)
            product_output = sum(r['output_tokens'] for r in product_calls)
            product_cost = sum(r['cost_usd'] for r in product_calls)
            
            n_features = len(data.get('features', {}).get('core', [])) + \
                        len(data.get('features', {}).get('advanced', []))
            
            print(f"  ✓ 完成 | features={n_features}")
            print(f"  ✓ Token 用量: {product_input:,} (input) + {product_output:,} (output) = {product_input + product_output:,} total")
            print(f"  ✓ 成本: ${product_cost:.4f} USD (≈ ¥{product_cost * 7.2:.2f})")
            
            results.append({
                'product': product,
                'input_tokens': product_input,
                'output_tokens': product_output,
                'total_tokens': product_input + product_output,
                'cost_usd': product_cost,
                'n_calls': len(product_calls),
                'n_features': n_features,
            })
        
        return {'results': results, 'tracker': tracker}
        
    finally:
        # 恢复原始 __init__
        ChatOpenAI.__init__ = original_init


def print_report(data: Dict):
    """打印统计报告"""
    tracker = data['tracker']
    results = data['results']
    summary = tracker.get_summary()
    
    print("\n" + "=" * 70)
    print("  API 成本统计报告")
    print("=" * 70)
    print(f"模型: {summary['model']}")
    print(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    print(f"总调用次数:   {summary['total_calls']}")
    print(f"总 Token 用量: {summary['total_tokens']:,}")
    print(f"  - Input:  {summary['total_input_tokens']:,}")
    print(f"  - Output: {summary['total_output_tokens']:,}")
    print()
    print(f"总成本: ${summary['total_cost_usd']:.4f} USD")
    print(f"      ≈ ¥{summary['total_cost_rmb']:.2f} RMB")
    print()
    if summary['total_calls'] > 0:
        print(f"平均每次调用: {summary['avg_tokens_per_call']:,} tokens")
        print(f"平均每次成本: ${summary['avg_cost_per_call_usd']:.4f} USD")
    print()
    print("── 逐产品详情 ──────────────────────────────────────────")
    for r in results:
        print(f"  {r['product']:12s} | tokens={r['total_tokens']:6,} "
              f"| calls={r['n_calls']:2d} | cost=${r['cost_usd']:.4f} "
              f"| features={r['n_features']}")
    print("=" * 70)


def save_report(data: Dict, path: str = None):
    """保存报告"""
    tracker = data['tracker']
    results = data['results']
    summary = tracker.get_summary()
    
    if path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = PROJECT_ROOT / "reports" / f"api_cost_{ts}.json"
    
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    report = {
        'generated_at': datetime.now().isoformat(),
        'summary': summary,
        'products': results,
        'calls': tracker.records,
    }
    
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"\n✓ JSON 报告已保存: {path}")
    
    # Markdown 版本
    md_path = path.with_suffix('.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write("# API 成本统计报告\n\n")
        f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
        f.write(f"**模型**: {summary['model']}  \n\n")
        f.write("---\n\n")
        f.write("## 总体统计\n\n")
        f.write(f"- 总调用次数: **{summary['total_calls']}**  \n")
        f.write(f"- 总 Token 用量: **{summary['total_tokens']:,}**  \n")
        f.write(f"  - Input: {summary['total_input_tokens']:,}  \n")
        f.write(f"  - Output: {summary['total_output_tokens']:,}  \n")
        f.write(f"- 总成本: **${summary['total_cost_usd']:.4f} USD**  \n")
        f.write(f"  - ≈ ¥{summary['total_cost_rmb']:.2f} RMB  \n\n")
        f.write("---\n\n")
        f.write("## 逐产品成本\n\n")
        f.write("| 产品 | Token 用量 | 调用次数 | 成本(USD) | 提取功能数 |\n")
        f.write("|------|-----------|----------|----------|------------|\n")
        for r in results:
            f.write(f"| {r['product']} | {r['total_tokens']:,} | {r['n_calls']} | ${r['cost_usd']:.4f} | {r['n_features']} |\n")
    
    print(f"✓ Markdown 报告已保存: {md_path}")
    
    return path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="API 成本统计 (v3)")
    parser.add_argument("--products", nargs="*", default=["Notion", "Figma", "Slack"])
    args = parser.parse_args()
    
    print("=" * 70)
    print("  API 成本统计工具 (v3 - 使用 LangChain Callback)")
    print("=" * 70)
    print(f"模型: {os.getenv('OPENAI_MODEL', 'deepseek-chat')}")
    print(f"测试产品: {args.products}")
    print()
    
    data = run_analysis_with_tracking(args.products)
    print_report(data)
    save_report(data)


if __name__ == "__main__":
    main()
