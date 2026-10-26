"""
benchmark_crawl_accuracy.py

补测脚本：爬取成功率 + 功能对比准确率

用法:
  python tests/benchmark_crawl_accuracy.py
  python tests/benchmark_crawl_accuracy.py --products notion obsidian figma linear
"""

import sys
import os
import json
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

# 与线上代码保持一致：使用安全 JSON 解析，避免 LLM 返回代码块时解析失败
from utils.llm_parser import safe_extract_json

# ── 日志 ──────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("benchmark")

# ── 待测产品列表 ──────────────────────────────────────────────────────────────
DEFAULT_PRODUCTS = [
    {"name": "Notion",     "hint_url": "https://www.notion.so"},
    {"name": "Obsidian",   "hint_url": "https://obsidian.md"},
    {"name": "Figma",      "hint_url": "https://www.figma.com"},
    {"name": "Linear",     "hint_url": "https://linear.app"},
    {"name": "Slack",      "hint_url": "https://slack.com"},
    {"name": "Asana",      "hint_url": "https://asana.com"},
    {"name": "Trello",     "hint_url": "https://trello.com"},
    {"name": "Monday",     "hint_url": "https://monday.com"},
]

# ── LLM（用于准确率验证）────────────────────────────────────────────────────
def get_llm():
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    model = os.getenv("OPENAI_MODEL", "deepseek-chat")
    return ChatOpenAI(
        model=model,
        temperature=0.0,
        api_key=api_key,
        base_url=base_url or None,
    )


# ── 爬取成功率测试 ────────────────────────────────────────────────────────────
def test_crawl_success(products: List[Dict]) -> Dict[str, Any]:
    """
    对每个产品跑 DataCollectionAgent.collect()，
    记录 website 是否找到、页面是否爬到、功能是否提取到。
    """
    from agents.crawler import DataCollectionAgent

    crawler = DataCollectionAgent(use_playwright=True)
    results = []

    for prod in products:
        name = prod["name"]
        logger.info(f"[爬取] 开始: {name}")
        t0 = time.time()

        try:
            data = crawler.collect(name)
            elapsed = round(time.time() - t0, 2)

            website      = data.get("website")
            crawled_pages = data.get("crawled_pages", [])
            features_core = data.get("features", {}).get("core", [])
            features_adv  = data.get("features", {}).get("advanced", [])
            total_features = len(features_core) + len(features_adv)
            source        = data.get("_source", "crawl")   # "crawl" or "llm_fallback"
            merged        = data.get("_merged", False)

            # 判定"爬取成功"：至少爬到 1 个页面 且 提取到至少 1 个功能
            crawl_success = len(crawled_pages) > 0 and total_features > 0
            # 判定"完全成功"：爬取成功 且 不是纯 LLM 兜底
            full_success  = crawl_success and source != "llm_fallback"

            results.append({
                "product": name,
                "website_found": bool(website),
                "website_url": website,
                "pages_crawled": len(crawled_pages),
                "crawled_page_urls": crawled_pages,
                "features_extracted": total_features,
                "features_core_count": len(features_core),
                "features_advanced_count": len(features_adv),
                "source": source,
                "merged": merged,
                "crawl_success": crawl_success,
                "full_success": full_success,
                "elapsed_sec": elapsed,
                "raw_data": data,   # 保留原始数据供准确率测试使用
            })

            logger.info(
                f"[爬取] {name} → website={website} "
                f"pages={len(crawled_pages)} features={total_features} "
                f"source={source} time={elapsed}s"
            )

        except Exception as e:
            elapsed = round(time.time() - t0, 2)
            logger.error(f"[爬取] {name} 异常: {e}")
            results.append({
                "product": name,
                "website_found": False,
                "website_url": None,
                "pages_crawled": 0,
                "crawled_page_urls": [],
                "features_extracted": 0,
                "features_core_count": 0,
                "features_advanced_count": 0,
                "source": "error",
                "merged": False,
                "crawl_success": False,
                "full_success": False,
                "elapsed_sec": elapsed,
                "error": str(e),
                "raw_data": None,
            })

    return results


# ── 功能对比准确率验证 ────────────────────────────────────────────────────────
def verify_feature_accuracy(crawl_results: List[Dict]) -> List[Dict]:
    """
    对每个爬取成功的产品：
    用 LLM 对照爬到的原始网页文本，批量验证提取的功能是否真实存在。
    每个产品只调一次 LLM（批量验证），算出准确率。
    """
    llm = get_llm()
    verified_results = []

    for item in crawl_results:
        if not item.get("raw_data"):
            verified_results.append({**item, "feature_verifications": [], "accuracy": None})
            continue

        raw_data  = item["raw_data"]
        name      = item["product"]
        website   = item.get("website_url", "")
        source    = item.get("source", "crawl")

        # 收集所有提取的功能
        features_core = raw_data.get("features", {}).get("core", [])
        features_adv  = raw_data.get("features", {}).get("advanced", [])
        all_features  = [{"name": f, "type": "core"} for f in features_core] \
                      + [{"name": f, "type": "advanced"} for f in features_adv]

        if not all_features:
            verified_results.append({
                **item,
                "feature_verifications": [],
                "accuracy": None,
                "accuracy_note": "no_features_extracted",
            })
            continue

        # 如果数据是 LLM 兜底生成的（没有爬取页面），跳过准确率验证
        crawled_pages = raw_data.get("crawled_pages", [])
        if not crawled_pages:
            verified_results.append({
                **item,
                "feature_verifications": [],
                "accuracy": None,
                "accuracy_note": "llm_fallback_no_html_to_verify",
            })
            continue

        # 拼接爬到的网页文本（用于验证）
        page_text = _fetch_page_texts(crawled_pages)

        # 批量验证：一次 LLM 调用验证所有功能
        verifications = _verify_features_batch(llm, name, website, page_text, all_features)

        n_total    = len(verifications)
        n_correct   = sum(1 for v in verifications if v["present"] is True)
        n_uncertain = sum(1 for v in verifications if v["present"] is None)
        accuracy    = round(n_correct / n_total, 4) if n_total > 0 else None

        logger.info(
            f"[准确率] {name} → {n_correct}/{n_total} 正确 "
            f"(不确定 {n_uncertain}) accuracy={accuracy}"
        )

        verified_results.append({
            **item,
            "feature_verifications": verifications,
            "accuracy": accuracy,
            "n_features": n_total,
            "n_correct": n_correct,
            "n_uncertain": n_uncertain,
            "accuracy_note": None,
        })

    return verified_results


def _fetch_page_texts(crawled_page_urls: List[str], max_per_page: int = 5000) -> str:
    """
    根据爬取到的 URL 列表，用 Playwright 获取网页文本（支持 JS 渲染）。
    返回拼接后的文本（截断到合理长度）。
    """
    from playwright.sync_api import sync_playwright
    
    html_texts = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale='en-US'
        )
        page = context.new_page()
        
        for url in crawled_page_urls:
            try:
                page.goto(url, timeout=20000, wait_until='domcontentloaded')
                try:
                    page.wait_for_load_state('networkidle', timeout=3000)
                except Exception:
                    pass
                page.wait_for_timeout(2000)
                
                html = page.content()
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, "html.parser")
                for tag in soup(["script", "style", "noscript", "iframe"]):
                    tag.decompose()
                text = soup.get_text(separator="\n", strip=True)[:max_per_page]
                html_texts.append(f"## {url}\n{text}")
            except Exception as e:
                logger.debug(f"Playwright 获取网页文本失败 {url}: {e}")
                pass
        
        browser.close()
    
    return "\n\n".join(html_texts)


def _verify_features_batch(llm: ChatOpenAI, product_name: str,
                           website: str, page_text: str,
                           features: List[Dict]) -> List[Dict]:
    """
    批量验证：一次 LLM 调用，验证所有功能。
    返回的 verifications 列表与 features 顺序一致。
    """
    features_json = json.dumps(
        [{"index": i, "name": f["name"], "type": f["type"]} for i, f in enumerate(features)],
        ensure_ascii=False
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "你是一位严谨的产品功能审核员。请根据网页文本内容，判断每个功能是否真实存在。"
         "\n\n对每项功能，输出一个 JSON 对象："
         '\n{{"index": 功能序号, "present": true/false/null, "confidence": "high/medium/low", "reason": "简要理由"}}'
         "\n\n- present=true  表示该功能在文本中有明确提及"
         "\n- present=false 表示文本中没有任何相关信息"
         "\n- present=null  表示无法判断"
         "\n\n请输出一个 JSON 数组，包含所有功能的验证结果，顺序与输入一致。"
         "\n只输出 JSON 数组，不要其他内容。"),
        ("user",
         "产品名称：{product_name}\n官网：{website}\n\n"
         "待验证功能列表：\n{features_json}\n\n"
         "网页文本内容（截取）：\n{page_text}\n\n"
         "请逐条验证上述功能是否真实存在，输出 JSON 数组。")
    ])

    try:
        chain = prompt | llm
        resp = chain.invoke({
            "product_name": product_name,
            "website": website,
            "features_json": features_json,
            "page_text": page_text[:10000],   # 控制总 token 用量
        })
        results = safe_extract_json(resp.content)
        # 转成统一格式
        verifications = []
        for r in results:
            idx = r.get("index", 0)
            feat = features[idx] if idx < len(features) else {"name": "?", "type": "?"}
            verifications.append({
                "feature": feat["name"],
                "type": feat["type"],
                "present": r.get("present"),
                "confidence": r.get("confidence", "low"),
                "reason": r.get("reason", ""),
            })
        return verifications

    except Exception as e:
        logger.warning(f"批量验证失败 [{product_name}]: {e}")
        # 降级：逐条验证
        logger.info(f"降级为逐条验证 [{product_name}]")
        verifications = []
        for feat in features:
            v = _verify_single_feature(llm, feat["name"], product_name, website, page_text)
            verifications.append({
                "feature": feat["name"],
                "type": feat["type"],
                "present": v["present"],
                "confidence": v["confidence"],
                "reason": v["reason"],
            })
        return verifications


def _verify_single_feature(llm: ChatOpenAI, feature_name: str,
                           product_name: str, website: str,
                           page_text: str) -> Dict:
    """
    逐条验证单个功能（降级方案）。
    """
    prompt = ChatPromptTemplate.from_messages([
        ("system",
         "你是一位严谨的产品功能审核员。请根据网页文本内容，判断某个功能是否真实存在。"
         "\n输出严格 JSON："
         '\n{{"present": true/false/null, "confidence": "high/medium/low", "reason": "简要理由"}}'
         "\n- present=true  表示该功能在文本中有明确提及或描述"
         "\n- present=false 表示文本中没有任何相关信息"
         "\n- present=null  表示无法判断（文本不完整或功能名称模糊）"
         "\n只输出 JSON，不要其他内容。"),
        ("user",
         "产品名称：{product_name}\n官网：{website}\n\n"
         "待验证功能：{feature_name}\n\n"
         "网页文本内容（截取）：\n{page_text}\n\n"
         "这个功能是否真实存在？")
    ])

    try:
        chain = prompt | llm
        resp = chain.invoke({
            "product_name": product_name,
            "website": website,
            "feature_name": feature_name,
            "page_text": page_text[:6000],
        })
        result = safe_extract_json(resp.content)
        return {
            "present": result.get("present"),
            "confidence": result.get("confidence", "low"),
            "reason": result.get("reason", ""),
        }
    except Exception as e:
        logger.warning(f"验证功能失败 [{product_name}/{feature_name}]: {e}")
        return {"present": None, "confidence": "low", "reason": f"验证失败: {e}"}


# ── 汇总报告 ──────────────────────────────────────────────────────────────────
def generate_report(verified_results: List[Dict]) -> Dict[str, Any]:
    n_total     = len(verified_results)
    n_crawl_ok  = sum(1 for r in verified_results if r.get("crawl_success"))
    n_full_ok   = sum(1 for r in verified_results if r.get("full_success"))
    n_llm_only  = sum(1 for r in verified_results if r.get("source") == "llm_fallback" and r.get("raw_data"))
    n_error     = sum(1 for r in verified_results if r.get("source") == "error")

    # 准确率（只看有验证数据的）
    acc_results = [r for r in verified_results if r.get("accuracy") is not None]
    avg_accuracy = (
        round(sum(r["accuracy"] for r in acc_results) / len(acc_results), 4)
        if acc_results else None
    )

    total_features_all = sum(r.get("n_features", 0) for r in acc_results)
    total_correct_all  = sum(r.get("n_correct", 0) for r in acc_results)

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "products_tested": n_total,
        "crawl_success_rate": round(n_crawl_ok / n_total, 4) if n_total else 0,
        "full_success_rate":  round(n_full_ok  / n_total, 4) if n_total else 0,
        "n_crawl_success": n_crawl_ok,
        "n_full_success":  n_full_ok,
        "n_llm_fallback_only": n_llm_only,
        "n_error": n_error,
        "avg_features_per_product": (
            round(sum(r.get("features_extracted", 0) for r in verified_results) / n_total, 2)
            if n_total else 0
        ),
        "avg_accuracy": avg_accuracy,
        "total_features_verified": total_features_all,
        "total_features_correct":  total_correct_all,
        "overall_accuracy": (
            round(total_correct_all / total_features_all, 4) if total_features_all else None
        ),
        "details": verified_results,
    }
    return report


def print_report(report: Dict[str, Any]):
    print("\n" + "=" * 60)
    print("  补测报告")
    print("=" * 60)
    print(f"生成时间:     {report['generated_at']}")
    print(f"测试产品数:   {report['products_tested']}")
    print()
    print(f"爬取成功率:   {report['n_crawl_success']}/{report['products_tested']} "
          f"({report['crawl_success_rate']*100:.1f}%)")
    print(f"完整成功(非纯LLM兜底): {report['n_full_success']}/{report['products_tested']} "
          f"({report['full_success_rate']*100:.1f}%)")
    print(f"LLM纯兜底:    {report['n_llm_fallback_only']}")
    print(f"爬取异常:     {report['n_error']}")
    print()
    print(f"平均每产品提取功能数: {report['avg_features_per_product']}")
    print()
    if report['overall_accuracy'] is not None:
        print(f"功能提取准确率(整体): {report['overall_accuracy']*100:.1f}% "
              f"({report['total_features_correct']}/{report['total_features_verified']})")
        print(f"功能提取准确率(平均): {report['avg_accuracy']*100:.1f}%")
    else:
        print("功能提取准确率: 暂无有效数据（爬取均为 LLM 兜底，无 HTML 可验证）")
    print()
    print("── 逐产品详情 ──────────────────────────────────────────")
    for r in report["details"]:
        acc_str = f"accuracy={r['accuracy']*100:.1f}%" if r.get("accuracy") is not None else "N/A"
        website_str = (r.get("website_url") or "无")[:30]
        print(f"  {r['product']:12s} | website={website_str:30s} "
              f"| pages={r.get('pages_crawled',0)} "
              f"| features={r.get('features_extracted',0)} "
              f"| source={r.get('source','?'):15s} "
              f"| {acc_str}")
    print("=" * 60)


def save_report(report: Dict[str, Any], path: str = None):
    if path is None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = PROJECT_ROOT / "reports" / f"benchmark_{ts}.json"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    logger.info(f"报告已保存: {path}")
    return path


# ── 入口 ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="竞品分析 Agent 补测脚本")
    parser.add_argument("--products", nargs="*", default=None,
                        help="指定测试产品名（默认使用内置列表）")
    args = parser.parse_args()

    if args.products:
        products = [{"name": p, "hint_url": None} for p in args.products]
    else:
        products = DEFAULT_PRODUCTS

    logger.info(f"开始补测，共 {len(products)} 个产品: {[p['name'] for p in products]}")

    # Step 1: 爬取成功率
    crawl_results = test_crawl_success(products)

    # Step 2: 功能准确率验证
    verified = verify_feature_accuracy(crawl_results)

    # Step 3: 生成报告
    report = generate_report(verified)
    print_report(report)

    # Step 4: 保存
    save_report(report)

    # 同时保存人类可读版本
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = PROJECT_ROOT / "reports" / f"benchmark_{ts}.md"
    _save_markdown_report(report, md_path)
    logger.info(f"Markdown 报告已保存: {md_path}")


def _save_markdown_report(report: Dict[str, Any], path: Path):
    lines = []
    lines.append("# 竞品分析 Agent — 补测报告")
    lines.append("")
    lines.append(f"**生成时间**: {report['generated_at']}  ")
    lines.append(f"**测试产品数**: {report['products_tested']}  ")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 一、爬取成功率")
    lines.append("")
    lines.append(f"- 爬取成功（找到官网且提取到功能）: **{report['n_crawl_success']}/{report['products_tested']}** "
                 f"({report['crawl_success_rate']*100:.1f}%)  ")
    lines.append(f"- 完整成功（非纯 LLM 兜底）: **{report['n_full_success']}/{report['products_tested']}** "
                 f"({report['full_success_rate']*100:.1f}%)  ")
    lines.append(f"- LLM 纯兜底（未爬到页面，完全依赖 LLM 知识库）: {report['n_llm_fallback_only']}  ")
    lines.append(f"- 爬取异常: {report['n_error']}  ")
    lines.append("")

    if report['overall_accuracy'] is not None:
        lines.append("## 二、功能提取准确率")
        lines.append("")
        lines.append(f"- **整体准确率**: **{report['overall_accuracy']*100:.1f}%** "
                     f"({report['total_features_correct']}/{report['total_features_verified']})  ")
        lines.append(f"- 平均准确率（各产品均值）: {report['avg_accuracy']*100:.1f}%  ")
        lines.append(f"- 平均每产品提取功能数: {report['avg_features_per_product']}  ")
        lines.append("")

    lines.append("## 三、逐产品详情")
    lines.append("")
    lines.append("| 产品 | 官网 | 爬取页面数 | 提取功能数 | 数据来源 | 准确率 |")
    lines.append("|------|------|------------|------------|----------|--------|")
    for r in report["details"]:
        acc_str = f"{r['accuracy']*100:.1f}%" if r.get("accuracy") is not None else "N/A（LLM兜底）"
        website = (r.get("website_url") or "无")[:30]
        source_map = {
            "crawl": "爬取",
            "llm_fallback": "LLM兜底",
            "error": "异常",
        }
        source = source_map.get(r.get("source", ""), r.get("source", ""))
        lines.append(
            f"| {r['product']} | {website} | {r.get('pages_crawled', 0)} "
            f"| {r.get('features_extracted', 0)} | {source} | {acc_str} |"
        )
    lines.append("")

    # 附录：逐条功能验证结果
    lines.append("## 附录：功能验证明细")
    lines.append("")
    for r in report["details"]:
        if not r.get("feature_verifications"):
            continue
        lines.append(f"### {r['product']}")
        lines.append("")
        lines.append("| 功能 | 类型 | 是否真实 | 置信度 | 理由 |")
        lines.append("|------|------|----------|--------|------|")
        for v in r["feature_verifications"]:
            present_str = {True: "✅", False: "❌", None: "⚠️"}.get(v["present"], "?")
            lines.append(
                f"| {v['feature']} | {v['type']} | {present_str} "
                f"| {v['confidence']} | {v['reason'][:50]} |"
            )
        lines.append("")

    lines.append("---")
    lines.append("*本报告由 benchmark_crawl_accuracy.py 自动生成*")

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
