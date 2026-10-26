"""
api_cost_tracker_final.py

最终可用版本 - 正确从 LLMResult 提取 token 用量

用法:
  python tests/api_cost_tracker_final.py --products Notion Figma Slack
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
    """
    正确的 Callback Handler
    on_llm_end 接收的是 LLMResult，不是 AIMessage
    """
    
    def __init__(self):
        super().__init__()
        self.records = []
        self.total_input = 0
        self.total_output = 0
        self.total_cost = 0.0
        self.current_model = None
    
    def on_llm_end(self, response, **kwargs):
        """正确提取 token 用量"""
        try:
            # response 是 LLMResult 对象
            # 方法1: 从 llm_output 提取
            if hasattr(response, 'llm_output') and response.llm_output:
                usage = response.llm_output.get('token_usage', {})
                if usage:
                    input_tokens = usage.get('prompt_tokens', 0)
                    output_tokens = usage.get('completion_tokens', 0)
                    self._record(input_tokens, output_tokens)
                    return
            
            # 方法2: 从 generations 提取
            if hasattr(response, 'generations') and response.generations:
                gen = response.generations[0][0]
                if hasattr(gen, 'generation_info') and gen.generation_info:
                    usage = gen.generation_info.get('token_usage', {})
                    if usage:
                        input_tokens = usage.get('prompt_tokens', 0)
                        output_tokens = usage.get('completion_tokens', 0)
                        self._record(input_tokens, output_tokens)
                        return
            
            # 方法3: 从 metadata (LangChain 0.3+)
            if hasattr(response, 'metadata') and response.metadata:
                usage = response.metadata.get('token_usage', {})
                if usage:
                    input_tokens = usage.get('prompt_tokens', 0) or usage.get('input_tokens', 0)
                    output_tokens = usage.get('completion_tokens', 0) or usage.get('output_tokens', 0)
                    self._record(input_tokens, output_tokens)
                    return
            
            # 方法4: 从 generations 的 message 提取 (AIMessage)
            if hasattr(response, 'generations') and response.generations:
                gen = response.generations[0][0]
                if hasattr(gen, 'message') and gen.message:
                    msg = gen.message
                    if hasattr(msg, 'usage_metadata') and msg.usage_metadata:
                        metadata = msg.usage_metadata
                        self._record(
                            metadata.get('input_tokens', 0),
                            metadata.get('output_tokens', 0)
                        )
                        return
            
        except Exception as e:
            print(f"[CostTracker] 警告: 无法提取 token 用量: {e}")
    
    def _record(self, input_tokens: int, output_tokens: int):
        """记录一次调用"""
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
    
    def get_summary(self) -> Dict:
        return {
            'model': self.current_model or os.getenv('OPENAI_MODEL', 'deepseek-chat'),
            'total_calls': len(self.records),
            'total_input_tokens': self.total_input,
            'total_output_tokens': self.total_output,
            'total_tokens': self.total_input + self.total_output,
            'total_cost_usd': round(self.total_cost, 4),
            'total_cost_rmb': round(self.total_cost * 7.2, 2),
        }


def run_analysis(products: List[str]) -> Dict:
    """运行分析并追踪成本"""
    from agents.crawler import DataCollectionAgent
    
    tracker = CostTrackerCallback()
    
    # 正确注入 callback：修改 ChatOpenAI 的默认 callbacks
    original_new = ChatOpenAI.__new__
    
    def patched_new(cls, *args, **kwargs):
        instance = original_new(cls)
        return instance
    
    # 更简单的方法：直接在每个 agent 创建时传入 callbacks
    # 修改 DataCollectionAgent 的 __init__ 来注入 callback
    
    results = []
    
    for product in products:
        print(f"\n{'='*60}")
        print(f"Analyzing: {product}")
        print(f"{'='*60}")
        
        calls_before = len(tracker.records)
        
        # 创建 crawler 并注入 callback
        crawler = DataCollectionAgent(use_playwright=True)
        crawler.llm = ChatOpenAI(
            model=os.getenv('OPENAI_MODEL', 'deepseek-chat'),
            temperature=0.0,
            api_key=os.getenv('OPENAI_API_KEY'),
            base_url=os.getenv('OPENAI_BASE_URL') or None,
            callbacks=[tracker],
        )
        
        # 执行爬取
        print(f"[1/1] Crawling {product}...")
        data = crawler.collect(product)
        
        # 统计
        calls_after = len(tracker.records)
        product_calls = tracker.records[calls_before:calls_after]
        product_input = sum(r['input_tokens'] for r in product_calls)
        product_output = sum(r['output_tokens'] for r in product_calls)
        product_cost = sum(r['cost_usd'] for r in product_calls)
        
        n_features = len(data.get('features', {}).get('core', [])) + \
                    len(data.get('features', {}).get('advanced', []))
        
        print(f"  [OK] Done | features={n_features}")
        print(f"  [OK] Tokens: {product_input:,} + {product_output:,} = {product_input + product_output:,}")
        print(f"  [OK] Cost: ${product_cost:.4f} USD")
        
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


def print_report(data: Dict):
    """打印报告"""
    tracker = data['tracker']
    results = data['results']
    summary = tracker.get_summary()
    
    print("\n" + "=" * 70)
    print("  API Cost Statistics Report")
    print("=" * 70)
    print(f"Model: {summary['model']}")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    print(f"Total calls:    {summary['total_calls']}")
    print(f"Total tokens:   {summary['total_tokens']:,}")
    print(f"  - Input:      {summary['total_input_tokens']:,}")
    print(f"  - Output:     {summary['total_output_tokens']:,}")
    print()
    print(f"Total cost: ${summary['total_cost_usd']:.4f} USD")
    print(f"            ~{summary['total_cost_rmb']:.2f} RMB")
    print()
    print("--- Per Product ---")
    for r in results:
        print(f"  {r['product']:12s} | tokens={r['total_tokens']:6,} "
              f"| calls={r['n_calls']:2d} | cost=${r['cost_usd']:.4f}")
    print("=" * 70)


def save_report(data: Dict):
    """保存报告"""
    tracker = data['tracker']
    results = data['results']
    summary = tracker.get_summary()
    
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = PROJECT_ROOT / "reports" / f"api_cost_{ts}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({
            'summary': summary,
            'products': results,
            'calls': tracker.records,
        }, f, indent=2, ensure_ascii=False)
    
    print(f"\n[OK] Report saved: {path}")
    
    # Markdown
    md_path = path.with_suffix('.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write("# API 成本统计报告\n\n")
        f.write(f"**模型**: {summary['model']}  \n")
        f.write(f"**总成本**: ${summary['total_cost_usd']:.4f} USD (¥{summary['total_cost_rmb']:.2f})  \n\n")
        f.write("| 产品 | Token 用量 | 成本(USD) |\n")
        f.write("|------|-----------|----------|\n")
        for r in results:
            f.write(f"| {r['product']} | {r['total_tokens']:,} | ${r['cost_usd']:.4f} |\n")
    
    print(f"[OK] Markdown report saved: {md_path}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--products", nargs="*", default=["Notion", "Figma"])
    args = parser.parse_args()
    
    print("=" * 70)
    print("  API Cost Tracker (Final)")
    print("=" * 70)
    print(f"Model: {os.getenv('OPENAI_MODEL', 'deepseek-chat')}")
    print(f"Products: {args.products}")
    print()
    
    data = run_analysis(args.products)
    print_report(data)
    save_report(data)


if __name__ == "__main__":
    main()
