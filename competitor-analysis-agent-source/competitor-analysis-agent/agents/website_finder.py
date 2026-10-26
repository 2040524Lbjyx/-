"""
Website Finder - 官网查找模块

通过百度搜索自动查找产品官网，无需 API Key。
使用 Playwright 访问百度搜索结果页，解析更可靠。
"""

import logging
import re
from typing import Optional, List
from bs4 import BeautifulSoup
import requests

logger = logging.getLogger(__name__)


# 搜索结果中应排除的域名（非官方网站）
EXCLUDE_DOMAINS = [
    "baidu.com", "zhihu.com", "zhidao.baidu.com",
    "baike.baidu.com", "sogou.com", "so.com",
    "360.cn", "bing.com", "google.com",
    "youtube.com", "wikipedia.org",
    "xiaohongshu.com", "douban.com",
    "toutiao.com", "csdn.net", "juejin.cn",
    "github.com", "gitee.com", "oschina.net",
]

# Playwright 延迟导入
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


def _is_excluded_domain(url: str) -> bool:
    """检查 URL 是否来自应排除的域名"""
    for domain in EXCLUDE_DOMAINS:
        if domain in url:
            return True
    return False


def _extract_domain(url: str) -> str:
    """从 URL 中提取主域名"""
    domain = re.sub(r"^https?://(www\.)?", "", url)
    domain = domain.split("/")[0]
    return domain


def search_with_playwright(product_name: str, max_results: int = 5) -> Optional[str]:
    """
    使用 Playwright 访问百度搜索，提取第一条非排除结果的 URL。
    比纯 requests 更稳定，能处理 JS 渲染的页面。
    """
    if not PLAYWRIGHT_AVAILABLE:
        logger.warning("[Playwright] Playwright 未安装，跳过浏览器搜索")
        return None

    search_query = f"{product_name} 官网"
    search_url = f"https://www.baidu.com/s?wd={requests.utils.quote(search_query)}"

    try:
        logger.info(f"[Playwright搜索] 查询: {search_query}")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="zh-CN",
            )
            page = context.new_page()

            # 访问百度搜索结果页
            page.goto(search_url, timeout=20000, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)  # 等待 JS 渲染

            # 尝试多种选择器提取结果链接
            results = []
            selectors = [
                "h3 a",           # 通用标题链接
                ".t a",           # 旧版百度
                ".c-container h3 a",  # 新版百度
                "[data-tools] a",  # 另一种格式
            ]

            for sel in selectors:
                links = page.query_selector_all(sel)
                if links:
                    for link in links[:max_results]:
                        href = link.get_attribute("href")
                        title = link.inner_text().strip()
                        if href and not _is_excluded_domain(href):
                            # 百度重定向链接处理
                            if href.startswith("http://www.baidu.com/link?"):
                                # 尝试从 data-real-url 获取
                                real = link.get_attribute("data-real-url")
                                if real:
                                    href = real
                            results.append({"url": href, "title": title})
                    if results:
                        break

            browser.close()

            # 去重并返回
            seen = set()
            unique = []
            for r in results:
                if r["url"] not in seen:
                    seen.add(r["url"])
                    unique.append(r)

            # 优先返回域名包含产品名的结果
            name_clean = product_name.lower().replace(" ", "")
            for r in unique:
                domain = _extract_domain(r["url"])
                if name_clean in domain.lower():
                    logger.info(f"[Playwright搜索] 找到官网（域名匹配）: {r['url']}")
                    return r["url"]

            if unique:
                url = unique[0]["url"]
                logger.info(f"[Playwright搜索] 找到官网: {url}")
                return url

    except Exception as e:
        logger.warning(f"[Playwright搜索] 失败: {e}")

    return None


def search_with_requests(product_name: str, max_results: int = 5) -> Optional[str]:
    """
    使用 requests 访问百度搜索（轻量级方案，不需要 Playwright）。
    作为 Playwright 的降级方案。
    """
    try:
        logger.info(f"[Requests搜索] 查询: {product_name} 官网")
        resp = requests.get(
            "https://www.baidu.com/s",
            params={"wd": f"{product_name} 官网", "rn": max_results},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Cookie": "BAIDUID=xxx;",  # 空 Cookie 也可能有用
            },
            timeout=10
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # 提取所有结果链接
        results = []
        for h3 in soup.select("h3.t, h3, .c-container h3"):
            a = h3.find("a")
            if a and a.get("href"):
                href = a["href"]
                title = a.get_text(strip=True)
                if href and not _is_excluded_domain(href):
                    results.append({"url": href, "title": title})

        # 百度重定向链接解码
        for r in results:
            href = r["url"]
            if "baidu.com/link?" in href:
                # 尝试从响应头或页面中获取真实 URL
                try:
                    redirect_resp = requests.head(href, allow_redirects=True, timeout=5)
                    r["url"] = redirect_resp.url
                except Exception:
                    pass

        if results:
            url = results[0]["url"]
            logger.info(f"[Requests搜索] 找到官网: {url}")
            return url

    except Exception as e:
        logger.warning(f"[Requests搜索] 失败: {e}")

    return None


def _guess_and_verify_url(product_name: str) -> Optional[str]:
    """
    启发式猜测官网 URL 并验证。
    对英文产品名尝试常见域名格式，实际访问验证。
    """
    if all(ord(c) < 128 for c in product_name):
        base = product_name.lower().replace(" ", "").replace("-", "")
        candidates = [
            f"https://www.{base}.com",
            f"https://{base}.com",
            f"https://www.{base}.cn",
            f"https://{base}.cn",
            f"https://www.{base}.ai",
            f"https://{base}.ai",
            f"https://www.{base}.io",
            f"https://{base}.io",
        ]
    else:
        # 中文产品名：常见拼音映射
        pinyin_map = {
            "豆包": "doubao",
            "剪映": "capcut",
            "飞书": "feishu",
            "抖音": "douyin",
            "通义千问": "tongyi",
            "文心一言": "yiyan",
            "讯飞星火": "xinghuo",
            "今日头条": "toutiao",
            "西瓜视频": "ixigua",
        }
        base = pinyin_map.get(product_name)
        if not base:
            return None
        candidates = [
            f"https://www.{base}.com",
            f"https://{base}.com",
            f"https://www.{base}.cn",
        ]

    for url in candidates:
        try:
            resp = requests.get(url, timeout=5, allow_redirects=True, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            if resp.status_code == 200:
                final_url = resp.url.rstrip("/")
                if not _is_excluded_domain(final_url):
                    return final_url
        except Exception:
            continue

    return None


def find_official_website(
    product_name: str,
    whitelist: dict = None,
    use_playwright_search: bool = True,
) -> dict:
    """
    综合方法查找官网。

    查找策略（按顺序）：
    1. 白名单精确匹配（最快最准）
    2. Playwright + 百度搜索（可靠，无需 API Key）
    3. requests + 百度搜索（轻量级降级）
    4. URL 启发式猜测（兜底）
    5. 返回 None

    Returns:
        {"url": str, "method": str, "confidence": str}
    """
    result = {"url": None, "method": "not_found", "confidence": "none"}

    # 方法 1：白名单
    if whitelist:
        name_norm = product_name.lower().replace(" ", "").replace("-", "")
        for key, url in whitelist.items():
            key_norm = key.lower().replace(" ", "").replace("-", "")
            if name_norm == key_norm or name_norm in key_norm or key_norm in name_norm:
                result["url"] = url
                result["method"] = "whitelist"
                result["confidence"] = "high"
                logger.info(f"[WebsiteFinder] 白名单命中: {product_name} -> {url}")
                return result

    # 方法 2：Playwright + 百度搜索
    if use_playwright_search and PLAYWRIGHT_AVAILABLE:
        url = search_with_playwright(product_name)
        if url:
            result["url"] = url
            result["method"] = "baidu_playwright"
            result["confidence"] = "medium"
            logger.info(f"[WebsiteFinder] Playwright搜索找到: {product_name} -> {url}")
            return result

    # 方法 3：requests + 百度搜索（降级）
    url = search_with_requests(product_name)
    if url:
        result["url"] = url
        result["method"] = "baidu_requests"
        result["confidence"] = "medium"
        logger.info(f"[WebsiteFinder] Requests搜索找到: {product_name} -> {url}")
        return result

    # 方法 4：URL 猜测
    url = _guess_and_verify_url(product_name)
    if url:
        result["url"] = url
        result["method"] = "guess"
        result["confidence"] = "low"
        logger.info(f"[WebsiteFinder] URL猜测找到: {product_name} -> {url}")
        return result

    logger.warning(f"[WebsiteFinder] 找不到官网: {product_name}")
    return result
