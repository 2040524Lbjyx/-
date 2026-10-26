"""
api_cost_tracker.py

API 成本统计脚本 - 追踪所有 LLM 调用的 token 用量和成本

用法:
  python tests/api_cost_tracker.py                    # 跑 3 个产品并统计成本
  python tests/api_cost_tracker.py --products Notion Figma Slack Linear  # 指定产品
"""

import sys
import os
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any
from collections import defaultdict

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from langchain_openai import ChatOpenAI
from langchain_core.callbacks import BaseCallbackHandler


# ── DeepSeek 定价（官方）────────────────────────────────────────────────────
PRICING = {
    "deepseek-chat": {        # DeepSeek-V3
        "input_price_per_1m": 0.14,   # USD
        "output_price_per_1m": 0.28,  # USD
    },
    "deepseek-reasoner": {    # DeepSeek-R1
        "input_price_per_1m": 0.55,
        "output_price_per_1m": 2.19,
    },
    # 兜底（未知模型）
    "default": {
        "input_price_per_1m": 0.14,
        "output_price_per_1m": 0.28,
    },
}


class APICostTrackerCallback(BaseCallbackHandler):
    """
    自定义 LangChain Callback：拦截所有 LLM 调用，记录 token 用量和成本
    """
    
    def __init__(self):
        self.calls = []
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd = 0.0
        self.model_name = None
        
    def on_llm_start(self, serialized, prompts, **kwargs):
        """LLM 开始调用时记录"""
        pass
    
    def on_llm_end(self, response, **kwargs):
        """LLM 调用结束时提取 token 用量"""
        try:
            # LangChain 的 response 对象包含 usage_metadata
            if hasattr(response, 'llm_output') and response.llm_output:
                usage = response.llm_output.get('token_usage', {})
            elif hasattr(response, 'generations'):
                # 从 generations 中提取 usage
                gen = response.generations[0][0] if response.generations else None
                if gen and hasattr(gen, 'generation_info'):
                    usage = gen.generation_info.get('token_usage', {})
                else:
                    usage = {}
            else:
                usage = {}
            
            # 尝试从 response.metadata (LangChain 0.3+) 获取
            if not usage and hasattr(response, 'metadata'):
                usage = response.metadata.get('token_usage', {})
            
            # DeepSeek 通过 OpenAI 兼容接口返回，usage 在 response.usage
            if not usage and hasattr(response, 'usage'):
                usage = {
                    'prompt_tokens': response.usage.prompt_tokens,
                    'completion_tokens': response.usage.completion_tokens,
                    'total_tokens': response.usage.total_tokens,
                }
            
            # 如果还是没有，尝试从 raw response 提取
            if not usage and hasattr(response, 'response_metadata'):
                metadata = response.response_metadata
                if 'token_usage' in metadata:
                    usage = metadata['token_usage']
            
            input_tokens = usage.get('prompt_tokens', 0) or usage.get('input_tokens', 0)
            output_tokens = usage.get('completion_tokens', 0) or usage.get('output_tokens', 0)
            
            # 获取模型名称
            model = self.model_name or os.getenv('OPENAI_MODEL', 'deepseek-chat')
            price = PRICING.get(model, PRICING['default'])
            
            # 计算成本
            cost_usd = (input_tokens / 1_000_000 * price['input_price_per_1m'] +
                       output_tokens / 1_000_000 * price['output_price_per_1m'])
            
            call_record = {
                'timestamp': datetime.now().isoformat(),
                'model': model,
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'total_tokens': input_tokens + output_tokens,
                'cost_usd': round(cost_usd, 6),
            }
            
            self.calls.append(call_record)
            self.total_input_tokens += input_tokens
            self.total_output_tokens += output_tokens
            self.total_cost_usd += cost_usd
            
            if self.model_name is None:
                self.model_name = model
            
        except Exception as e:
            print(f"[CostTracker] 警告: 无法提取 token 用量: {e}")
    
    def get_summary(self) -> Dict:
        """返回统计摘要"""
        return {
            'model': self.model_name or os.getenv('OPENAI_MODEL', 'deepseek-chat'),
            'total_calls': len(self.calls),
            'total_input_tokens': self.total_input_tokens,
            'total_output_tokens': self.total_output_tokens,
            'total_tokens': self.total_input_tokens + self.total_output_tokens,
            'total_cost_usd': round(self.total_cost_usd, 4),
            'total_cost_rmb': round(self.total_cost_usd * 7.2, 4),  # 按 1 USD = 7.2 RMB
            'avg_tokens_per_call': round((self.total_input_tokens + self.total_output_tokens) / len(self.calls)) if self.calls else 0,
            'avg_cost_per_call_usd': round(self.total_cost_usd / len(self.calls), 4) if self.calls else 0,
        }
    
    def save_details(self, path: str):
        """保存每次调用的详细记录"""
        data = {
            'summary': self.get_summary(),
            'calls': self.calls,
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


# ── 主测试流程 ────────────────────────────────────────────────────────────────

DEFAULT_PRODUCTS = [
    {"name": "Notion",     "hint_url": "https://www.notion.so"},
    {"name": "Figma",      "hint_url": "https://www.figma.com"},
    {"name": "Slack",      "hint_url": "https://slack.com"},
    {"name": "Linear",     "hint_url": "https://linear.app"},
]


def run_with_cost_tracking(products: List[Dict]) -> Dict:
    """
    运行完整的竞品分析流程，并追踪 API 成本
    """
    from agents.crawler import DataCollectionAgent
    from agents.analyzer import AnalysisAgent
    from agents.reporter import ReportAgent
    
    # 创建成本追踪器
    tracker = APICostTrackerCallback()
    
    # 修改 agents 的 LLM 初始化，注入 callback
    # 方法：临时 monkey patch ChatOpenAI
    original_init = ChatOpenAI.__init__
    
    def patched_init(self, *args, **kwargs):
        kwargs['callbacks'] = [tracker]
        original_init(self, *args, **kwargs)
    
    ChatOpenAI.__init__ = patched_init
    
    try:
        results = []
        
        for prod in products:
            name = prod['name']
            print(f"\n{'='*60}")
            print(f"开始分析: {name}")
            print(f"{'='*60}")
            
            # 记录开始时的 token 计数
            calls_before = len(tracker.calls)
            
            # Step 1: 爬取
            print(f"[1/3] 爬取 {name}...")
            crawler = DataCollectionAgent(use_playwright=True)
            crawl_data = crawler.collect(name)
            
            # Step 2: 分析（简化版，只做功能提取）
            print(f"[2/3] 分析 {name}...")
            # 这里我们只统计 crawler 的 API 调用
            # 完整流程需要跑 analyzer
            
            # Step 3: 记录本次产品的 API 用量
            calls_after = len(tracker.calls)
            product_calls = tracker.calls[calls_before:calls_after]
            product_input = sum(c['input_tokens'] for c in product_calls)
            product_output = sum(c['output_tokens'] for c in product_calls)
            product_cost = sum(c['cost_usd'] for c in product_calls)
            
            print(f"  ✓ 完成 | tokens={product_input}+{product_output} | cost=${product_cost:.4f}")
            
            results.append({
                'product': name,
                'input_tokens': product_input,
                'output_tokens': product_output,
                'total_tokens': product_input + product_output,
                'cost_usd': product_cost,
                'n_calls': len(product_calls),
            })
        
        # 恢复原始 ChatOpenAI
        ChatOpenAI.__init__ = original_init
        
        return {
            'products': results,
            'tracker_summary': tracker.get_summary(),
            'tracker': tracker,
        }
        
    except Exception as e:
        # 确保恢复原始 ChatOpenAI
        ChatOpenAI.__init__ = original_init
        raise e


def print_cost_report(result: Dict):
    """打印成本报告"""
    summary = result['tracker_summary']
    products = result['products']
    
    print("\n" + "=" * 70)
    print("  API 成本统计报告")
    print("=" * 70)
    print(f"模型: {summary['model']}")
    print(f"测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    print(f"总调用次数:   {summary['total_calls']}")
    print(f"总 Token 用量: {summary['total_tokens']:,} "
          f"(input={summary['total_input_tokens']:,}, output={summary['total_output_tokens']:,})")
    print()
    print(f"总成本: ${summary['total_cost_usd']:.4f} USD")
    print(f"      ≈ ¥{summary['total_cost_rmb']:.4f} RMB")
    print()
    print(f"平均每次调用: {summary['avg_tokens_per_call']:,} tokens")
    print(f"平均每次成本: ${summary['avg_cost_per_call_usd']:.4f} USD")
    print()
    print("── 逐产品成本 ──────────────────────────────────────────")
    for p in products:
        print(f"  {p['product']:12s} | tokens={p['total_tokens']:6,} "
              f"| calls={p['n_calls']:2d} | cost=${p['cost_usd']:.4f}")
    print("=" * 70)


def save_cost_report(result: Dict, path: str = None):
    """保存成本报告"""
    if path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = PROJECT_ROOT / "reports" / f"api_cost_{ts}.json"
    
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    data = {
        'generated_at': datetime.now().isoformat(),
        'summary': result['tracker_summary'],
        'products': result['products'],
    }
    
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"\n报告已保存: {path}")
    
    # 同时保存 Markdown 版本
    md_path = path.with_suffix('.md')
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write("# API 成本统计报告\n\n")
        f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n")
        f.write(f"**模型**: {result['tracker_summary']['model']}  \n\n")
        f.write("---\n\n")
        f.write("## 总体统计\n\n")
        f.write(f"- 总调用次数: **{result['tracker_summary']['total_calls']}**  \n")
        f.write(f"- 总 Token 用量: **{result['tracker_summary']['total_tokens']:,}**  \n")
        f.write(f"  - Input: {result['tracker_summary']['total_input_tokens']:,}  \n")
        f.write(f"  - Output: {result['tracker_summary']['total_output_tokens']:,}  \n")
        f.write(f"- 总成本: **${result['tracker_summary']['total_cost_usd']:.4f} USD**  \n")
        f.write(f"  - ≈ ¥{result['tracker_summary']['total_cost_rmb']:.2f} RMB  \n")
        f.write(f"- 平均每次调用: {result['tracker_summary']['avg_tokens_per_call']:,} tokens  \n")
        f.write(f"- 平均每次成本: ${result['tracker_summary']['avg_cost_per_call_usd']:.4f} USD  \n\n")
        f.write("---\n\n")
        f.write("## 逐产品成本\n\n")
        f.write("| 产品 | Token 用量 | 调用次数 | 成本(USD) |\n")
        f.write("|------|-----------|----------|----------|\n")
        for p in result['products']:
            f.write(f"| {p['product']} | {p['total_tokens']:,} | {p['n_calls']} | ${p['cost_usd']:.4f} |\n")
    
    print(f"Markdown 报告已保存: {md_path}")
    
    return path


# ── 入口 ─────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="API 成本统计")
    parser.add_argument("--products", nargs="*", default=None,
                        help="指定测试产品（默认使用内置列表）")
    args = parser.parse_args()
    
    if args.products:
        products = [{"name": p, "hint_url": None} for p in args.products]
    else:
        products = DEFAULT_PRODUCTS
    
    print(f"开始 API 成本统计，共 {len(products)} 个产品...")
    print(f"模型: {os.getenv('OPENAI_MODEL', 'deepseek-chat')}")
    print(f"定价: Input=${PRICING.get(os.getenv('OPENAI_MODEL', 'deepseek-chat'), PRICING['default'])['input_price_per_1m']}/1M tokens, "
          f"Output=${PRICING.get(os.getenv('OPENAI_MODEL', 'deepseek-chat'), PRICING['default'])['output_price_per_1m']}/1M tokens")
    
    result = run_with_cost_tracking(products)
    print_cost_report(result)
    save_cost_report(result)
    
    # 保存详细调用记录
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    detail_path = PROJECT_ROOT / "reports" / f"api_cost_details_{ts}.json"
    result['tracker'].save_details(detail_path)
    print(f"详细调用记录已保存: {detail_path}")


if __name__ == "__main__":
    main()
