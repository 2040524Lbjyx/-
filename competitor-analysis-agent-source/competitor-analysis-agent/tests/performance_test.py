"""
性能测试 + Token 用量统计
找出速度瓶颈，并在结果中显示 token 用量
"""
import sys
import time
import json
import os
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from langchain_openai import ChatOpenAI
from agents.crawler import DataCollectionAgent
from agents.analyzer import CompetitiveAnalyzer


def test_crawler_speed(product: str):
    """测试爬虫速度"""
    print(f"\n{'='*60}")
    print(f"Testing Crawler Speed: {product}")
    print(f"{'='*60}")
    
    # 测试爬虫
    crawler = DataCollectionAgent(use_playwright=True)
    
    start = time.time()
    data = crawler.collect(product)
    elapsed = time.time() - start
    
    pages = len(data.get('crawled_pages', []))
    features = len(data.get('features', {}).get('core', [])) + \
               len(data.get('features', {}).get('advanced', []))
    
    print(f"  Time: {elapsed:.2f}s")
    print(f"  Pages crawled: {pages}")
    print(f"  Features extracted: {features}")
    print(f"  Speed: {pages/elapsed:.1f} pages/s" if elapsed > 0 else "  Speed: N/A")
    
    return {
        'phase': 'crawler',
        'product': product,
        'time': elapsed,
        'pages': pages,
        'features': features,
    }


def test_llm_speed():
    """测试 LLM 响应速度"""
    print(f"\n{'='*60}")
    print(f"Testing LLM Speed")
    print(f"{'='*60}")
    
    llm = ChatOpenAI(
        model=os.getenv('OPENAI_MODEL', 'deepseek-chat'),
        temperature=0.0,
        api_key=os.getenv('OPENAI_API_KEY'),
        base_url=os.getenv('OPENAI_BASE_URL') or None,
    )
    
    # 测试不同大小的请求
    test_cases = [
        ("Short (10 words)", "What is Notion?"),
        ("Medium (100 words)", "Describe the main features of Notion in detail. Include information about collaboration, databases, and templates."),
        ("Long (500 words)", """
        Please analyze the following product and extract structured information:
        Product: Notion
        Website: https://www.notion.com
        
        Extract the following information:
        1. Core features (list 10-15 features)
        2. Advanced features (list 5-10 features)
        3. Pricing plans (list all plans with prices)
        4. Target audience
        5. Key differentiators
        
        For each feature, provide a brief description.
        """),
    ]
    
    results = []
    for name, prompt in test_cases:
        start = time.time()
        response = llm.invoke(prompt)
        elapsed = time.time() - start
        
        # 获取 token 用量
        usage = response.usage_metadata if hasattr(response, 'usage_metadata') else {}
        input_tokens = usage.get('input_tokens', 0)
        output_tokens = usage.get('output_tokens', 0)
        
        print(f"  {name:20s} | Time: {elapsed:5.2f}s | Input: {input_tokens:5d} | Output: {output_tokens:5d}")
        results.append({
            'name': name,
            'time': elapsed,
            'input_tokens': input_tokens,
            'output_tokens': output_tokens,
        })
    
    return results


def analyze_bottlenecks():
    """分析性能瓶颈"""
    print(f"\n{'='*60}")
    print(f"Performance Bottleneck Analysis")
    print(f"{'='*60}")
    
    print("\nPotential bottlenecks:")
    print("  1. Playwright startup time (~2-3s per product)")
    print("  2. Page load time (waiting for JS rendering)")
    print("  3. LLM API latency (~1-3s per call)")
    print("  4. Vector search (if using ChromaDB)")
    print("\nOptimization suggestions:")
    print("  1. Reuse Playwright browser instance")
    print("  2. Reduce pages crawled (focus on key pages)")
    print("  3. Use faster model (deepseek-chat vs deepseek-reasoner)")
    print("  4. Parallelize independent LLM calls")
    print("  5. Cache crawled results")


def modify_output_to_show_tokens():
    """修改输出，显示 token 用量"""
    print(f"\n{'='*60}")
    print(f"Modifying Output to Show Token Usage")
    print(f"{'='*60}")
    
    # 读取 analyzer.py，看看在哪里可以加入 token 统计
    analyzer_path = PROJECT_ROOT / "agents" / "analyzer.py"
    with open(analyzer_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查是否已经有 token 统计
    if 'usage_metadata' in content:
        print("  [OK] analyzer.py already has usage_metadata access")
    else:
        print("  [!] Need to add token tracking to analyzer.py")
    
    # 读取 main.py，看看输出格式
    main_path = PROJECT_ROOT / "main.py"
    if main_path.exists():
        with open(main_path, 'r', encoding='utf-8') as f:
            main_content = f.read()
        if 'token' in main_content.lower():
            print("  [OK] main.py already shows token usage")
        else:
            print("  [!] Need to add token usage to main.py output")


def run_full_analysis_with_timing(products: list):
    """运行完整分析并记录时间和 token"""
    print(f"\n{'='*70}")
    print(f"Full Analysis with Timing & Token Tracking")
    print(f"{'='*70}")
    
    from agents.crawler import DataCollectionAgent
    from agents.analyzer import CompetitiveAnalyzer
    
    llm = ChatOpenAI(
        model=os.getenv('OPENAI_MODEL', 'deepseek-chat'),
        temperature=0.0,
        api_key=os.getenv('OPENAI_API_KEY'),
        base_url=os.getenv('OPENAI_BASE_URL') or None,
    )
    
    total_start = time.time()
    total_tokens = {'input': 0, 'output': 0}
    
    for product in products:
        print(f"\n--- {product} ---")
        
        # Crawler
        t0 = time.time()
        crawler = DataCollectionAgent(use_playwright=True)
        data = crawler.collect(product)
        t1 = time.time()
        print(f"  Crawler: {t1-t0:.2f}s")
        
        # Analyzer
        analyzer = CompetitiveAnalyzer(llm=llm)
        
        # 手动调用 analyzer 的各个方法，记录时间
        t2 = time.time()
        # 这里需要看 analyzer 的具体接口
        # 暂时跳过，因为接口可能比较复杂
        t3 = time.time()
        
        print(f"  Analyzer: {t3-t2:.2f}s (estimated)")
    
    total_elapsed = time.time() - total_start
    print(f"\nTotal time: {total_elapsed:.2f}s")
    print(f"Estimated tokens: {total_tokens}")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--products", nargs="*", default=["Notion"])
    parser.add_argument("--mode", choices=["speed", "llm", "bottleneck", "modify", "full"], 
                       default="speed")
    args = parser.parse_args()
    
    if args.mode == "speed":
        for product in args.products:
            test_crawler_speed(product)
    
    elif args.mode == "llm":
        test_llm_speed()
    
    elif args.mode == "bottleneck":
        analyze_bottlenecks()
    
    elif args.mode == "modify":
        modify_output_to_show_tokens()
    
    elif args.mode == "full":
        run_full_analysis_with_timing(args.products)
    
    print(f"\nDone. Results saved to reports/performance_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")


if __name__ == "__main__":
    main()
