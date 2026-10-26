"""
Data Collection Agent - 数据采集Agent
负责爬取竞品官网、提取结构化数据

优化版本：
- 复用Playwright浏览器实例（方案1）
- 减少延迟和等待时间（方案2）
- 支持并发爬取（方案4）
"""

import json
import os
import logging
import random
import time
import re
import hashlib
import difflib
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any
from urllib.parse import quote
from bs4 import BeautifulSoup
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

# 使用统一的环境变量加载器
from utils.env_loader import load_env, get_env
from utils.llm_parser import safe_extract_json
from utils.runtime_health import classify_connection_error

# 搜索服务（DuckDuckGo Instant Answer API）
from services.search_service import get_search_service

# 加载 .env 环境变量
load_env()

# Playwright导入（可选，如果未安装则降级到requests）
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logging.warning("Playwright未安装，将使用requests作为降级方案")

logger = logging.getLogger(__name__)


def _launch_playwright_chromium(playwright):
    """启动 Chromium；优先复用本机 Chrome/Edge，避免依赖 CDN 下载内核。"""
    options = {"headless": True}
    candidates = [
        os.environ.get("CRAWL_BROWSER_EXECUTABLE"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for executable in candidates:
        if executable and os.path.exists(executable):
            options["executable_path"] = executable
            logger.info(f"[Browser] 复用本机浏览器: {executable}")
            break
    return playwright.chromium.launch(**options)


def _infer_category_from_product_name(product_name: str) -> str:
    """LLM 不可用时用产品名选择分析维度，不把结果当作事实数据。"""
    normalized = (product_name or "").lower().strip()
    hints = {
        "短视频": ["抖音", "快手", "tiktok", "youtube", "bilibili", "哔哩哔哩"],
        "笔记知识管理": ["notion", "obsidian", "logseq", "evernote", "onenote"],
        "项目管理": ["jira", "linear", "asana", "trello"],
        "设计工具": ["figma", "sketch", "adobe xd"],
        "即时通讯": ["微信", "wechat", "slack", "discord", "钉钉", "飞书"],
        "电商": ["淘宝", "京东", "拼多多", "amazon", "shopify"],
    }
    for category, aliases in hints.items():
        if any(alias in normalized for alias in aliases):
            return category
    return ""


class DataCollectionAgent:
    """数据采集Agent"""
    
    def __init__(self, model: str = None, temperature: float = None, 
                 use_playwright: bool = True, max_retries: int = 3):
        """
        初始化Data Collection Agent
        
        Args:
            model: LLM模型名称（默认从 OPENAI_MODEL 环境变量读取）
            temperature: 温度参数（默认从 OPENAI_TEMPERATURE 环境变量读取）
            use_playwright: 是否使用Playwright进行动态爬取
            max_retries: 最大重试次数
        """
        api_key = get_env("OPENAI_API_KEY")
        base_url = get_env("OPENAI_BASE_URL")
        model = model or get_env("OPENAI_MODEL", "deepseek-chat")  # DeepSeek 默认模型
        temperature = temperature if temperature is not None else float(get_env("OPENAI_TEMPERATURE", "0.7"))

        self.llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=api_key,
            base_url=base_url or None,
            request_timeout=60,  # 🔧 修复问题7：添加超时配置（60秒）
            max_retries=2  # 🔧 修复问题7：添加重试配置
        )

        # 🔧 抽取类低温实例：网页结构化抽取用低温(0.1)，降低幻觉与格式漂移
        self.llm_extract = ChatOpenAI(
            model=model,
            temperature=0.1,
            api_key=api_key,
            base_url=base_url or None,
            request_timeout=60,
            max_retries=2
        )
        self.use_playwright = use_playwright and PLAYWRIGHT_AVAILABLE
        self.max_retries = max_retries

        # User-Agent列表（用于轮换，必须在 _get_random_user_agent 之前定义）
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:121.0) Gecko/20100101 Firefox/121.0",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ]

        # 传统的requests session（作为备用）
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self._get_random_user_agent()
        })
        # requests.Session 不是线程安全的。页面并发抓取时为每个线程懒创建
        # 独立 Session，避免不同 URL 互相覆盖 User-Agent/连接状态。
        self._request_tls = threading.local()
        self._cache_events = {}

    def _get_request_session(self) -> requests.Session:
        """返回当前线程专用的 requests Session。"""
        # 兼容旧缓存/测试中通过 __new__ 构造的轻量实例。
        request_tls = getattr(self, "_request_tls", None)
        if request_tls is None:
            request_tls = threading.local()
            self._request_tls = request_tls
        session = getattr(request_tls, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({"User-Agent": self._get_random_user_agent()})
            request_tls.session = session
        return session
    
    def collect(self, competitor_name: str) -> Dict[str, Any]:
        """
        采集竞品数据

        Args:
            competitor_name: 竞品名称

        Returns:
            包含竞品数据的字典
        """

        logger.info(f"Crawler: 开始采集 {competitor_name}")
        self._cache_events = {}

        # 步骤1: 查找竞品官网（白名单优先，启发式次之，LLM 兜底）
        website, find_method = self._find_website(competitor_name)
        logger.info(f"[DIAGNOSTIC] collect('{competitor_name}'): website={website}, method={find_method}")
        logger.info(f"Crawler: 官网={website}, 查找方式={find_method}")

        # 步骤2: 爬取多个页面
        raw_data = {}
        structured_data = {}

        if website:
            best_effort = bool(find_method and find_method.endswith("_best_effort"))
            logger.info(f"Crawler: 找到官网 {website}（{find_method}），开始爬取")
            raw_data = self._crawl_website(
                website, competitor_name=competitor_name, best_effort=best_effort
            )
            structured_data = self._extract_structured_data(
                competitor_name,
                website,
                raw_data
            )
            structured_data["_find_method"] = find_method or "guess"
            structured_data["_best_effort"] = best_effort
            structured_data["website"] = website
            # 识别产品类别，供 Analyzer 按类型选择标准功能维度
            known_category = _infer_category_from_product_name(competitor_name)
            try:
                product_understanding = self._understand_product_with_llm(competitor_name, website)
                # 白名单/产品名识别比 LLM 的泛化类别稳定。例如抖音常被 LLM
                # 返回为“视频”，应优先保留“短视频”这个可用于维度选择的类别。
                llm_category = product_understanding.get("category", "")
                category = known_category or llm_category
                if category:
                    structured_data["_category"] = category
            except Exception as e:
                logger.warning(f"Crawler: 产品类别理解失败 {competitor_name}: {e}")
                if known_category:
                    structured_data["_category"] = known_category
            # 官网文案快照（首页/功能页 diff，自动，无需用户输入）
            snapshot = self._build_copy_snapshot(competitor_name, raw_data)
            if snapshot:
                structured_data["copy_snapshots"] = snapshot
        else:
            logger.warning(f"Crawler: 未找到 {competitor_name} 的官网，使用LLM知识库兜底")

        # 步骤3: 检查爬取结果，字段级来源标记
        # 原则：能爬到就用爬的，爬不到宁可留空，除非万不得已才用 AI 兜底
        # AI 兜底仅在以下情况触发：连官网都找不到
        if not website:
            logger.warning(f"Crawler: 未找到 {competitor_name} 的官网，启用LLM知识库兜底")
            llm_data = self._llm_fallback_collect(competitor_name, website)
            llm_data["_source"] = "llm_fallback"
            llm_data["_source_warn"] = "⚠️ 此数据完全来自 AI 知识库，未经过官网爬取，仅供参考"
            llm_data = self._enrich_with_app_stores(competitor_name, llm_data)
            return self._attach_evidence_manifest(llm_data)

        # 有官网但爬取数据不完整：按字段调用 AI 补全。
        # 之前只有“至少抓到一个核心字段”才会进入这里，导致功能和定价
        # 同时为空时直接返回 crawl_partial，完全不会使用 AI 兜底。
        features = structured_data.get("features", {})
        pricing = structured_data.get("pricing", {})
        changelog = structured_data.get("changelog", {})
        has_features = bool(features.get("core") or features.get("advanced"))
        has_pricing = bool(pricing.get("model") or pricing.get("plans"))
        has_changelog = bool(
            changelog.get("latest_version")
            or changelog.get("latest_release_date")
            or changelog.get("recent_updates")
            or changelog.get("update_frequency")
        )

        missing_fields = []
        if not has_features:
            missing_fields.append("features")
        if not has_pricing:
            missing_fields.append("pricing")
        if not has_changelog:
            missing_fields.append("changelog")

        if missing_fields:
            # 有官网也允许 AI 补全，但 _llm_filled_fields 会逐字段记录来源，
            # 报告不会把 AI 推测当作官网事实。
            logger.info(f"Crawler: {competitor_name} 缺少 {missing_fields}，调用 LLM 补充")
            filled_by_llm = self._fill_blank_fields_with_llm(structured_data, competitor_name, website)
            structured_data = filled_by_llm
            filled = structured_data.get("_llm_filled_fields", []) or []
            if filled:
                structured_data["_source"] = "crawl" if raw_data else "llm_fallback"
                structured_data["_source_warn"] = (
                    "⚠️ 部分字段由 AI 知识库补全，未被计为已验证官网事实。"
                )
            else:
                structured_data["_source"] = "crawl_partial"
                structured_data["_source_warn"] = (
                    "⚠️ 官网页面可访问但未提取到有效字段，且 AI 补全失败；核心字段已留空。"
                )
        else:
            structured_data["_source"] = "crawl"

        structured_data["crawled_pages"] = list(raw_data.keys()) if raw_data else []
        if getattr(self, "_cache_events", None):
            structured_data["_cache_events"] = dict(self._cache_events)
        structured_data = self._enrich_with_app_stores(competitor_name, structured_data)
        structured_data = self._attach_evidence_manifest(structured_data)
        logger.info(f"Crawler: {competitor_name} 采集完成，来源: {structured_data.get('_source')}")
        return structured_data

    # ------------------------------------------------------------------
    # 多源自动采集：App Store / GitHub Releases / 官网文案快照
    # （均在 collect() 内自动触发，用户只需输入自然语言竞品名）
    # ------------------------------------------------------------------
    def _enrich_with_app_stores(self, competitor_name: str, data: Dict) -> Dict:
        """自动补充 App Store 评分/评论/版本、GitHub Releases、官网文案快照、派生热度指标。"""
        # 1) App Store（官方公开 API，自动推断 app_id）
        try:
            app_block = self._collect_app_store(competitor_name)
            if app_block:
                data["app_store"] = app_block
        except Exception as e:
            logger.warning(f"Crawler: App Store 采集失败 {competitor_name}: {e}")
        # 2) GitHub Releases（公开 API，自动推断 repo，尽力而为）
        try:
            gh_block = self._collect_github_releases(competitor_name)
            if gh_block:
                data["github_releases"] = gh_block
        except Exception as e:
            logger.warning(f"Crawler: GitHub Releases 采集失败 {competitor_name}: {e}")
        # 4) 下载量/排名：付费封闭，改由 App Store 评分人数派生相对热度（非真实下载量）
        try:
            metrics = self._derive_app_metrics(data.get("app_store"))
            if metrics:
                data["app_metrics"] = metrics
        except Exception as e:
            logger.warning(f"Crawler: 派生指标失败 {competitor_name}: {e}")
        return data

    def _attach_evidence_manifest(self, data: Dict) -> Dict:
        """汇总本次真实访问过的来源，供 Analyzer 质量闸门和报告追溯。"""
        evidence = []
        captured_at = datetime.now().astimezone().isoformat(timespec="seconds")
        seen = set()

        def add(source: str, url: str, fields: List[str]):
            if not url or url in seen:
                return
            seen.add(url)
            cache_event = (getattr(self, "_cache_events", {}) or {}).get(url, {})
            evidence.append({
                "source": source,
                "url": url,
                "fields": fields,
                "captured_at": cache_event.get("captured_at") or captured_at,
                "cache_status": cache_event.get("status", "live"),
            })

        field_evidence = data.get("_field_evidence", {}) or {}
        for url in data.get("crawled_pages", []) or []:
            # 访问成功不等于页面中的每个字段都提取成功；同时附上
            # 实际由该页面支撑的字段，供质量闸门做字段级判断。
            fields = ["page_access"]
            for field, urls in field_evidence.items():
                if url in (urls or []):
                    fields.append(field)
            add("official_web", url, fields)

        app_store = data.get("app_store", {}) or {}
        add("app_store", app_store.get("_url"), ["rating", "version", "release_notes"])
        add("app_store_reviews", app_store.get("_reviews_url"), ["reviews"])

        github = data.get("github_releases", {}) or {}
        add("github_releases", github.get("_url"), ["changelog", "releases"])

        data["_evidence"] = evidence
        return data

    # ---- App Store ----
    def _discover_app_store_id(self, name: str) -> Optional[str]:
        """用 iTunes search API 自动推断 App ID（中/美区各试一次）。"""
        for country in ("cn", "us"):
            try:
                url = f"https://itunes.apple.com/search?term={quote(name)}&entity=software&country={country}&limit=1"
                r = requests.get(url, timeout=10, headers={"User-Agent": self._get_random_user_agent()})
                if r.status_code == 200:
                    j = r.json()
                    if j.get("results"):
                        return j["results"][0].get("trackId")
            except Exception:
                continue
        return None

    def _collect_app_store(self, name: str) -> Optional[Dict]:
        app_id = self._discover_app_store_id(name)
        if not app_id:
            return None
        info: Dict[str, Any] = {
            "app_id": app_id,
            "_source": "api",
            "_url": f"https://apps.apple.com/cn/app/id{app_id}",
            "_reviews_url": f"https://itunes.apple.com/cn/rss/customerreviews/page=1/id={app_id}/sortBy=mostRecent/json",
        }
        try:
            r = requests.get(
                f"https://itunes.apple.com/lookup?id={app_id}&country=cn",
                timeout=10, headers={"User-Agent": self._get_random_user_agent()},
            )
            if r.status_code == 200:
                j = r.json().get("results", [])
                if j:
                    res = j[0]
                    info["rating"] = res.get("averageUserRating")
                    info["rating_count"] = res.get("userRatingCount")
                    info["version"] = res.get("version")
                    info["release_date"] = res.get("currentVersionReleaseDate")
                    info["release_notes"] = res.get("releaseNotes")
        except Exception as e:
            logger.debug(f"App Store lookup 失败: {e}")
        # 评论 RSS（中/美区各试）
        reviews = []
        for country in ("cn", "us"):
            try:
                url = f"https://itunes.apple.com/{country}/rss/customerreviews/page=1/id={app_id}/sortBy=mostRecent/json"
                r = requests.get(url, timeout=10, headers={"User-Agent": self._get_random_user_agent()})
                if r.status_code == 200:
                    feed = r.json().get("feed", {})
                    for entry in feed.get("entry", []):
                        if isinstance(entry, dict):
                            summary = entry.get("summary", {})
                            txt = summary.get("label", "") if isinstance(summary, dict) else ""
                            if txt:
                                reviews.append(txt)
                    if reviews:
                        break
            except Exception:
                continue
        info["reviews"] = reviews[:20]
        # 没有任何有效数据则不附加，避免污染结果
        if info.get("rating") is None and not reviews and not info.get("version"):
            return None
        return info

    # ---- GitHub Releases ----
    def _discover_github_repo(self, name: str) -> Optional[str]:
        try:
            q = quote(f"{name} in:name")
            r = requests.get(
                f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page=5",
                timeout=10, headers={"User-Agent": self._get_random_user_agent()},
            )
            if r.status_code == 200:
                for it in r.json().get("items", []):
                    repo = it.get("full_name")
                    if repo:
                        return repo
        except Exception:
            pass
        return None

    def _collect_github_releases(self, name: str) -> Optional[Dict]:
        repo = self._discover_github_repo(name)
        if not repo:
            return None
        try:
            r = requests.get(
                f"https://api.github.com/repos/{repo}/releases?per_page=10",
                timeout=10, headers={"User-Agent": self._get_random_user_agent()},
            )
            if r.status_code == 200:
                rels = r.json()
                if isinstance(rels, list) and rels:
                    out = []
                    for rel in rels[:10]:
                        out.append({
                            "tag": rel.get("tag_name"),
                            "name": rel.get("name"),
                            "published_at": rel.get("published_at"),
                            "body": (rel.get("body") or "")[:500],
                            "url": rel.get("html_url"),
                        })
                    return {
                        "repo": repo,
                        "releases": out,
                        "_source": "api",
                        "_url": f"https://github.com/{repo}/releases",
                    }
        except Exception as e:
            logger.debug(f"GitHub releases 失败 {repo}: {e}")
        return None

    # ---- 官网文案快照对比 ----
    def _snapshot_path(self, name: str) -> str:
        cd = self._crawl_cache_dir()
        return os.path.join(cd, f"snapshot_{hashlib.md5(name.encode('utf-8')).hexdigest()[:16]}.txt")

    def _build_copy_snapshot(self, name: str, raw_data: Dict[str, str]) -> Optional[Dict]:
        """合并首页/功能页文本存为快照，并与上一次快照做 diff（自动，无需用户输入）。"""
        texts = []
        for url, html in (raw_data or {}).items():
            if not html:
                continue
            try:
                soup = BeautifulSoup(html, "html.parser")
                for x in soup(["script", "style", "noscript", "iframe"]):
                    x.decompose()
                txt = soup.get_text(separator="\n", strip=True)
                if txt:
                    texts.append(txt[:15000])
            except Exception:
                continue
        current = "\n\n=====PAGE=====\n\n".join(texts)
        if not current:
            return None
        path = self._snapshot_path(name)
        prev = None
        if os.path.exists(path):
            try:
                prev = open(path, encoding="utf-8", errors="ignore").read()
            except Exception:
                prev = None
        diff_text = ""
        has_prev = bool(prev)
        if prev and prev != current:
            dl = list(difflib.unified_diff(prev.splitlines(), current.splitlines(), lineterm="", n=1))
            diff_text = "\n".join(dl[:300])
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(current)
        except Exception:
            pass
        return {"has_previous": has_prev, "diff": diff_text, "pages": len(texts)}

    # ---- 下载量/排名：派生相对热度 ----
    def _derive_app_metrics(self, app_store: Optional[Dict]) -> Optional[Dict]:
        if not app_store:
            return None
        rc = app_store.get("rating_count")
        if rc is None:
            return None
        return {
            "user_rating_count_derived": rc,
            "note": "相对热度由 App Store 评分人数派生，非真实下载量/排名（App Annie/Sensor Tower/七麦为付费封闭数据源）",
        }

    # ------------------------------------------------------------------
    # 并行爬取：方案4 升级版
    # ------------------------------------------------------------------
    def _clone_for_worker(self) -> "DataCollectionAgent":
        """
        为线程池 worker 复制一个轻量级实例。

        requests.Session 也是独立对象，避免 User-Agent/连接池互相覆盖。
        Playwright 由 collect_many 的调用线程串行启动，不在 worker 中创建。
        LLM 客户端 (ChatOpenAI) 底层是 httpx.Client，原生线程安全，多个 worker 可共享。
        """
        worker = DataCollectionAgent.__new__(DataCollectionAgent)
        worker.llm = getattr(self, "llm", None)  # ChatOpenAI 线程安全，共享即可
        worker.llm_extract = getattr(self, "llm_extract", worker.llm)
        # Playwright 的 sync API 在 Windows 线程池中会触发
        # asyncio.create_subprocess_exec -> NotImplementedError。collect_many
        # 在启用 Playwright 时会走主线程串行路径；requests 并发 worker 保持关闭
        # 浏览器，避免把动态浏览器误放进线程池。
        worker.use_playwright = self.use_playwright
        worker.max_retries = self.max_retries
        worker.user_agents = list(self.user_agents)
        # 独立 requests session，避免被其他 worker 改 UA / 复用连接
        worker.session = requests.Session()
        worker.session.headers.update({
            "User-Agent": worker._get_random_user_agent()
        })
        worker._request_tls = threading.local()
        return worker

    def collect_many(self, competitor_names: List[str],
                     max_workers: int = 3,
                     progress_callback: Optional[Any] = None
                     ) -> Dict[str, Dict[str, Any]]:
        """
        并行采集多个竞品数据；启用同步 Playwright 时自动切换为调用线程串行，
        以兼容 Windows 子进程限制。

        Args:
            competitor_names: 竞品名称列表
            max_workers: 最大并发线程数（默认 3，建议 2-4）
            progress_callback: 可选回调，签名 (index, total, name, status, data_or_error)
                - status: "start" / "done" / "failed"
                - 当 status="done" 时 data_or_error 是结构化数据
                - 当 status="failed" 时 data_or_error 是异常对象

        Returns:
            {competitor_name: structured_data} 字典（失败的竞品值仍保留，包含 _error 字段）
        """
        if not competitor_names:
            return {}

        # 去掉空字符串、保持顺序去重
        seen = set()
        tasks: List[str] = []
        for name in competitor_names:
            if not name:
                continue
            key = name.strip()
            if key and key not in seen:
                seen.add(key)
                tasks.append(key)

        total = len(tasks)
        results: Dict[str, Dict[str, Any]] = {}
        max_workers = max(1, min(max_workers, total))

        logger.info(
            f"Crawler: 开始并行采集 {total} 个竞品，并发度={max_workers}"
        )

        # 每个 worker 单独的实例（不共享 Playwright/session）
        # 重要：必须在每个 worker 内部独立克隆，避免多线程共享
        # Playwright 浏览器进程或 requests.Session，否则会触发
        # "Connection.init: Connection closed while reading from the driver"
        def _run_one(index: int, name: str, _unused) -> tuple:
            """单任务包装，捕获异常并上报进度。
            worker 参数保留仅为兼容签名；实际 worker 从当前线程 TLS 取
            （由 ThreadPoolExecutor 的 initializer 建立，每线程独立）。"""
            worker = _get_worker()
            if progress_callback:
                try:
                    progress_callback(index, total, name, "start", None)
                except Exception as cb_err:
                    logger.warning(f"进度回调(start)失败: {cb_err}")

            try:
                logger.info(
                    f"Crawler: [并行 {index}/{total}] 开始 - {name}"
                )
                data = worker.collect(name)
                if progress_callback:
                    try:
                        progress_callback(index, total, name, "done", data)
                    except Exception as cb_err:
                        logger.warning(f"进度回调(done)失败: {cb_err}")
                return name, data
            except Exception as e:
                logger.error(
                    f"Crawler: [并行 {index}/{total}] 失败 - {name}: {e}"
                )
                if progress_callback:
                    try:
                        progress_callback(index, total, name, "failed", e)
                    except Exception as cb_err:
                        logger.warning(f"进度回调(failed)失败: {cb_err}")
                return name, {
                    "name": name,
                    "website": None,
                    "features": {"core": [], "advanced": []},
                    "pricing": {"model": None, "plans": []},
                    "changelog": {
                        "latest_version": None,
                        "latest_release_date": None,
                        "recent_updates": [],
                        "update_frequency": None,
                    },
                    "company_info": {},
                    "target_users": [],
                    "platforms": [],
                    "crawled_pages": [],
                    "_error": str(e),
                    "_source": "error",
                }

        # ThreadPoolExecutor：I/O 密集型爬取适合线程
        # 关键：每个 worker 线程独立 clone 一份实例，避免共享 Playwright/session
        # 否则会触发 "Connection.init: Connection closed while reading from the driver"
        import threading as _threading
        _tls = _threading.local()

        def _init_worker():
            """每个 worker 线程入口：建立自己的独立实例"""
            _tls.instance = self._clone_for_worker()

        def _get_worker():
            w = getattr(_tls, "instance", None)
            if w is None:
                # 兜底：主线程也建一份（应该不会走到这里）
                w = self._clone_for_worker()
                _tls.instance = w
            return w

        # 同步 Playwright 必须在调用线程运行，不能放进 ThreadPoolExecutor。
        # 仍保留 requests 模式的并发能力；浏览器模式下串行处理竞品，确保动态
        # 页面可用且不会产生 Windows 的 NotImplementedError。
        if self.use_playwright:
            logger.info(
                "Crawler: Playwright 模式使用调用线程串行采集（避免 Windows 线程池子进程限制）"
            )
            for i, name in enumerate(tasks):
                result_name, data = _run_one(i + 1, name, None)
                results[result_name] = data
            return results

        with ThreadPoolExecutor(max_workers=max_workers,
                                thread_name_prefix="CrawlerWorker",
                                initializer=_init_worker) as executor:
            # 按 index 提交，便于 progress_callback 拿到确定顺序
            # worker 由 _run_one 内部 _get_worker() 在 worker 线程取
            future_to_index = {
                executor.submit(_run_one, i + 1, name, None): i
                for i, name in enumerate(tasks)
            }
            for future in as_completed(future_to_index):
                try:
                    name, data = future.result()
                except Exception as e:
                    # _run_one 内部已捕获，理论上到不了这里
                    idx = future_to_index[future]
                    name = tasks[idx]
                    logger.error(f"Crawler: 任务执行异常 {name}: {e}")
                    data = {"_error": str(e), "_source": "error", "name": name}
                results[name] = data

        ok = sum(1 for v in results.values() if not v.get("_error"))
        logger.info(
            f"Crawler: 并行采集完成 {ok}/{total} 成功"
        )
        return results
    
    def _get_random_user_agent(self) -> str:
        """随机获取User-Agent"""
        return random.choice(self.user_agents)
    
    def _random_delay(self, min_seconds: float = 0.3, max_seconds: float = 1.0):
        """随机延迟（反爬虫）- 优化：减少延迟时间"""
        delay = random.uniform(min_seconds, max_seconds)
        time.sleep(delay)

    # ------------------------------------------------------------------
    # 磁盘缓存（提升爬虫成功率 + 避免重复触发限流/兜底）
    # ------------------------------------------------------------------
    def _crawl_cache_dir(self) -> str:
        """爬虫专用缓存目录：复用项目 .cache，避免写系统目录被沙箱拦截。"""
        d = os.environ.get("CRAWL_CACHE_DIR")
        if not d:
            d = os.path.join(os.getcwd(), ".cache", "crawl")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass
        return d

    def _cache_path(self, key: str, suffix: str = "html") -> str:
        h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:24]
        return os.path.join(self._crawl_cache_dir(), f"{suffix}_{h}.txt")

    def _cache_load(self, key: str, suffix: str = "html", ttl_seconds: int = 21600) -> Optional[str]:
        """读取缓存；过期或缺失返回 None（默认 TTL 6 小时）。"""
        try:
            p = self._cache_path(key, suffix)
            if not os.path.exists(p):
                return None
            if ttl_seconds and (time.time() - os.path.getmtime(p)) > ttl_seconds:
                return None
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return None

    def _record_cache_event(self, url: str, status: str) -> None:
        """记录页面是实时获取还是缓存回退，以及缓存原始时间。"""
        try:
            cache_file = self._cache_path(url, "html")
            captured_at = datetime.fromtimestamp(
                os.path.getmtime(cache_file), tz=datetime.now().astimezone().tzinfo
            ).isoformat(timespec="seconds") if os.path.exists(cache_file) else None
        except Exception:
            captured_at = None
        events = getattr(self, "_cache_events", None)
        if events is None:
            events = {}
            self._cache_events = events
        events[url] = {"status": status, "captured_at": captured_at}

    def _cache_save(self, key: str, content: str, suffix: str = "html") -> None:
        try:
            p = self._cache_path(key, suffix)
            with open(p, "w", encoding="utf-8", errors="ignore") as f:
                f.write(content)
        except Exception:
            pass

    def _cache_load_website(self, name: str) -> Optional[str]:
        return self._cache_load(name, "website", ttl_seconds=604800)

    def _cache_save_website(self, name: str, url: str) -> None:
        self._cache_save(name, url, "website")

    # ------------------------------------------------------------------
    # sitemap / robots.txt 发现（绕过 JS 首页，稳定枚举真实内容页）
    # ------------------------------------------------------------------
    def _discover_via_sitemap(self, website: str) -> List[str]:
        """通过 robots.txt 的 Sitemap 指令 + /sitemap.xml 发现真实内容页 URL。"""
        import urllib.parse
        discovered: List[str] = []
        try:
            base = website.rstrip("/")
            domain = urllib.parse.urlparse(website).netloc.lower()
            entries = [base + "/robots.txt", base + "/sitemap.xml", base + "/sitemap_index.xml"]
            sitemap_urls = set()
            for c in entries:
                try:
                    txt = self._cache_load(c, "sitemap") or self._crawl_page_with_requests(c)
                    if not txt:
                        continue
                    self._cache_save(c, txt, "sitemap")
                except Exception:
                    continue
                for line in txt.splitlines():
                    low = line.lower().strip()
                    if low.startswith("sitemap:"):
                        sm = line.split(":", 1)[1].strip()
                        if sm:
                            sitemap_urls.add(sm)
                if "<?xml" in txt or "<urlset" in txt or "<sitemapindex" in txt:
                    sitemap_urls.add(c)
            kw = ("pricing", "price", "plan", "feature", "product", "changelog",
                  "release", "update", "version", "whats-new", "news", "blog",
                  "about", "download", "定价", "价格", "功能", "特性", "产品",
                  "更新", "版本", "日志", "动态", "公告", "关于", "下载")
            for sm in list(sitemap_urls)[:5]:
                try:
                    xml = self._cache_load(sm, "sitemap") or self._crawl_page_with_requests(sm)
                    if not xml:
                        continue
                    self._cache_save(sm, xml, "sitemap")
                except Exception:
                    continue
                for m in re.finditer(r"<loc>(.*?)</loc>", xml, re.DOTALL | re.IGNORECASE):
                    loc = m.group(1).strip()
                    pl = urllib.parse.urlparse(loc).netloc.lower()
                    if domain not in pl and not pl.endswith("." + domain):
                        continue
                    low = loc.lower()
                    if any(k in low for k in kw):
                        if loc not in discovered:
                            discovered.append(loc)
            discovered = discovered[:12]
            if discovered:
                logger.info(f"[Sitemap] 从 {website} 发现 {len(discovered)} 条内容页")
        except Exception as e:
            logger.debug(f"[Sitemap] 发现失败 {website}: {e}")
        return discovered

    def _find_website(self, competitor_name: str) -> tuple:
        """
        查找竞品官网，返回 (url, method) 元组。
        method ∈ {"whitelist", "llm_verified", "guess", "llm", None}

        查找策略（按顺序）：
        1. 白名单精确/模糊匹配（最快最准）
        2. LLM 推理 + 实际访问验证（推荐方案，无需 API Key）
        3. 常见 URL 格式猜测 + 验证（快速兜底）
        4. LLM 推理（无验证，最后手段）
        """

        # ========== 1. 硬编码白名单：常见中国/海外产品的官方域名 ==========
        whitelist = self._get_website_whitelist()
        name_clean = (competitor_name or "").strip()
        name_lower = name_clean.lower()

        # 1.1 精确匹配
        if name_clean in whitelist:
            url = whitelist[name_clean]
            logger.info(f"[Whitelist] 精确命中: {name_clean} -> {url}")
            return url, "whitelist"
        # 1.2 模糊匹配（小写 + 去掉空格）
        name_normalized = name_lower.replace(" ", "").replace("-", "")
        for k, v in whitelist.items():
            k_norm = k.lower().replace(" ", "").replace("-", "")
            if name_normalized == k_norm or name_normalized in k_norm or k_norm in name_normalized:
                url = v
                logger.info(f"[Whitelist] 模糊命中: {name_clean} ~ {k} -> {url}")
                return url, "whitelist"

        # ========== 1.5 官网缓存（避免重复 DDG/LLM 调用与限流/兜底）==========
        cached_site = self._cache_load_website(name_clean)
        if cached_site:
            logger.info(f"[SiteCache] 命中缓存官网: {name_clean} -> {cached_site}")
            return cached_site, "cache"

        # ========== 2. DuckDuckGo 搜索官网（免费无需 API Key）==========
        logger.info(f"[DuckDuckGo] 白名单未命中，使用 DuckDuckGo 搜索官网: {name_clean}")
        try:
            search = get_search_service()
            ddg_url = search.discover_competitor_website(name_clean)
            if ddg_url:
                verified_url = self._verify_url(ddg_url)
                if verified_url:
                    self._cache_save_website(name_clean, verified_url)
                    logger.info(f"[DuckDuckGo] 搜索发现官网验证成功: {name_clean} -> {verified_url}")
                    return verified_url, "duckduckgo"
                # 验证失败但来源可信（搜索引擎官方结果），best-effort 直爬：
                # 不再因反爬/地域拦截的裸 GET 误杀真实官网，导致全量 LLM 兜底
                logger.warning(f"[DuckDuckGo] 验证失败但来源可信，best-effort 直爬: {ddg_url}")
                self._cache_save_website(name_clean, ddg_url)
                return ddg_url, "duckduckgo_best_effort"
        except Exception as e:
            logger.warning(f"[DuckDuckGo] 搜索失败: {e}，继续使用 LLM")

        # ========== 3. LLM 推理（不强制验证，依赖后续真实抓取校验）==========
        # LLM 对知名产品官方域名准确率 >95%，裸 GET 验证常被反爬/地域拦截误杀，
        # 因此验证失败也 best-effort 直爬，由 _crawl_website 阶段真正访问校验。
        logger.info(f"[LLM] DuckDuckGo 未找到，使用 LLM 推理官网: {name_clean}")
        llm_url = self._find_website_with_llm(competitor_name)
        if llm_url:
            verified_url = self._verify_url(llm_url)
            if verified_url:
                self._cache_save_website(name_clean, verified_url)
                logger.info(f"[LLM] 推荐官网验证成功: {name_clean} -> {verified_url}")
                return verified_url, "llm_verified"
            logger.warning(f"[LLM] 验证失败但推荐可信，best-effort 直爬: {llm_url}")
            self._cache_save_website(name_clean, llm_url)
            return llm_url, "llm_verified_best_effort"

        # ========== 4. 常见 URL 格式猜测 + 验证（快速兜底，仍要求验证）==========
        common_formats = self._generate_url_candidates(name_clean)

        tried = []
        for url in common_formats:
            tried.append(url)
            try:
                logger.debug(f"尝试访问: {url}")
                found_url = self._verify_url(url)
                if found_url:
                    self._cache_save_website(name_clean, found_url)
                    logger.info(f"[Guess] URL猜测成功: {name_clean} -> {found_url}")
                    return found_url, "guess"
            except Exception as e:
                logger.debug(f"尝试 {url} 失败: {e}")
                continue

        logger.warning(f"[FindWebsite] 所有方法均未找到官网: {name_clean}")
        return None, None

    def _generate_url_candidates(self, product_name: str) -> list:
        """根据产品名生成候选 URL 列表"""
        name_lower = product_name.lower().replace(" ", "").replace("-", "")
        candidates = []

        # 英文产品名：尝试常见 TLD
        if all(ord(c) < 128 for c in product_name):
            tlds = [".com", ".cn", ".io", ".ai", ".co", ".app", ".dev", ".org", ".com.cn"]
            for tld in tlds:
                candidates.append(f"https://www.{name_lower}{tld}")
                candidates.append(f"https://{name_lower}{tld}")

        # 中文产品名：尝试拼音 + 常见域名
        else:
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
                "有道云笔记": "note.youdao",
                "印象笔记": "yinxiang",
                "腾讯会议": "meeting.tencent",
            }
            base = pinyin_map.get(product_name)
            if base and "." in base:
                candidates.append(f"https://{base}.com")
                candidates.append(f"https://{base}.cn")
            elif base:
                candidates.append(f"https://www.{base}.com")
                candidates.append(f"https://www.{base}.cn")

        return candidates

    def _verify_url(self, url: str) -> Optional[str]:
        """
        验证 URL 是否可访问，返回最终 URL（处理重定向）。
        如果无法访问，返回 None。
        """
        if not url:
            return None

        try:
            if self.use_playwright:
                return self._check_url_with_playwright(url)
            else:
                return self._check_url_with_requests(url)
        except Exception:
            return None

    def _get_website_whitelist(self) -> Dict[str, str]:
        """
        硬编码白名单：常见竞品的官方域名。
        解决"中文产品名（如 微信/钉钉/飞书）+ 通用模板猜错"的问题。
        Key 用产品中文常用名，Value 是官方主域名。
        """
        return {
            # ===== 腾讯系 =====
            "QQ": "https://im.qq.com",
            "qq": "https://im.qq.com",
            "微信": "https://weixin.qq.com",
            "wechat": "https://www.wechat.com",
            "WeChat": "https://www.wechat.com",
            "腾讯会议": "https://meeting.tencent.com",
            "腾讯文档": "https://docs.qq.com",
            "腾讯视频": "https://v.qq.com",
            "QQ音乐": "https://y.qq.com",
            "QQ邮箱": "https://mail.qq.com",
            "企业微信": "https://work.weixin.qq.com",

            # ===== 阿里系 =====
            "钉钉": "https://www.dingtalk.com",
            "DingTalk": "https://www.dingtalk.com",
            "dingtalk": "https://www.dingtalk.com",
            "阿里云": "https://www.aliyun.com",
            "淘宝": "https://www.taobao.com",
            "天猫": "https://www.tmall.com",
            "支付宝": "https://www.alipay.com",
            "闲鱼": "https://www.goofish.com",
            "钉钉文档": "https://docs.dingtalk.com",

            # ===== 字节系 =====
            "飞书": "https://www.feishu.cn",
            "Lark": "https://www.larksuite.com",
            "豆包": "https://www.doubao.com",
            "抖音": "https://www.douyin.com",
            "TikTok": "https://www.tiktok.com",
            "今日头条": "https://www.toutiao.com",
            "西瓜视频": "https://www.ixigua.com",
            
            # ===== 百度系 =====
            "百度网盘": "https://pan.baidu.com",
            "百度文库": "https://wenku.baidu.com",
            "百度知道": "https://zhidao.baidu.com",
            
            # ===== 网易系 =====
            "网易云音乐": "https://music.163.com",
            "有道云笔记": "https://note.youdao.com",
            
            # ===== 夸克 =====
            "夸克网盘": "https://www.quark.cn",
            "夸克": "https://www.quark.cn",
            
            # ===== AI 产品 =====
            "文心一言": "https://yiyan.baidu.com",
            "通义千问": "https://tongyi.aliyun.com",
            "讯飞星火": "https://xinghuo.xfyun.cn",
            "Kimi": "https://kimi.moonshot.cn",
            "智谱清言": "https://chatglm.cn",
            "ChatGPT": "https://chat.openai.com",
            "Claude": "https://claude.ai",
            "Notion AI": "https://www.notion.so",
            
            # ===== 网盘/云存储 =====
            "Notion": "https://www.notion.so",
            "Google Drive": "https://drive.google.com",
            "Dropbox": "https://www.dropbox.com",
            "OneDrive": "https://onedrive.live.com",
            "Lark": "https://www.larksuite.com",
            "lark": "https://www.larksuite.com",
            "抖音": "https://www.douyin.com",
            "今日头条": "https://www.toutiao.com",
            "西瓜视频": "https://www.ixigua.com",
            "剪映": "https://www.capcut.cn",
            "CapCut": "https://www.capcut.com",

            # ===== AI 助手 / 大模型 =====
            "豆包": "https://www.doubao.com",
            "doubao": "https://www.doubao.com",
            "Kimi": "https://kimi.moonshot.cn",
            "kimi": "https://kimi.moonshot.cn",
            "月之暗面": "https://www.moonshot.cn",
            "moonshot": "https://www.moonshot.cn",
            "通义千问": "https://tongyi.aliyun.com",
            "通义": "https://tongyi.aliyun.com",
            "文心一言": "https://yiyan.baidu.com",
            "文心": "https://yiyan.baidu.com",
            "ChatGLM": "https://chatglm.cn",
            "智谱": "https://chatglm.cn",
            "DeepSeek": "https://www.deepseek.com",
            "deepseek": "https://www.deepseek.com",
            "讯飞星火": "https://xinghuo.xfyun.cn",
            "星火": "https://xinghuo.xfyun.cn",
            "字节跳动": "https://www.bytedance.com",
            "bytedance": "https://www.bytedance.com",

            # ===== 笔记/知识管理 =====
            "Notion": "https://www.notion.so",
            "notion": "https://www.notion.so",
            "Obsidian": "https://obsidian.md",
            "obsidian": "https://obsidian.md",
            "印象笔记": "https://www.yinxiang.com",
            "有道云笔记": "https://note.youdao.com",
            "语雀": "https://www.yuque.com",
            "Roam Research": "https://roamresearch.com",
            "Logseq": "https://logseq.com",
            "Tana": "https://tana.inc",

            # ===== 待办/任务管理 =====
            "滴答清单": "https://www.dida365.com",
            "TickTick": "https://www.ticktick.com",
            "todoist": "https://todoist.com",
            "Todoist": "https://todoist.com",
            "Things": "https://culturedcode.com/things",
            "OmniFocus": "https://www.omnigroup.com/omnifocus",
            "Any.do": "https://www.any.do",
            "微软待办": "https://to-do.microsoft.com",
            "Microsoft To Do": "https://to-do.microsoft.com",

            # ===== 协作/项目管理 =====
            "Jira": "https://www.atlassian.com/software/jira",
            "Linear": "https://linear.app",
            "Asana": "https://asana.com",
            "Trello": "https://trello.com",
            "ClickUp": "https://clickup.com",
            "Monday": "https://monday.com",
            "Basecamp": "https://basecamp.com",

            # ===== 设计/创意 =====
            "Figma": "https://www.figma.com",
            "Sketch": "https://www.sketch.com",
            "Adobe XD": "https://www.adobe.com/products/xd.html",
            "XD": "https://www.adobe.com/products/xd.html",
            "Canva": "https://www.canva.com",
            "即时设计": "https://js.design",
            "Pixso": "https://pixso.cn",
            "MasterGo": "https://mastergo.com",

            # ===== 国外常见 SaaS =====
            "Slack": "https://slack.com",
            "Zoom": "https://zoom.us",
            "GitHub": "https://github.com",
            "GitLab": "https://about.gitlab.com",
            "Dropbox": "https://www.dropbox.com",
            "Google Docs": "https://docs.google.com",
            "Microsoft 365": "https://www.microsoft.com/microsoft-365",
            "Office 365": "https://www.microsoft.com/microsoft-365",

            # ===== 短视频/社交/内容（补全，减少兜底） =====
            "快手": "https://www.kuaishou.com",
            "kuaishou": "https://www.kuaishou.com",
            "Kwai": "https://www.kwai.com",
            "小红书": "https://www.xiaohongshu.com",
            "RED": "https://www.xiaohongshu.com",
            "哔哩哔哩": "https://www.bilibili.com",
            "B站": "https://www.bilibili.com",
            "bilibili": "https://www.bilibili.com",
            "微博": "https://weibo.com",
            "weibo": "https://weibo.com",
            "知乎": "https://www.zhihu.com",
            "Zhihu": "https://www.zhihu.com",
            "美团": "https://www.meituan.com",
            "京东": "https://www.jd.com",
            "JD": "https://www.jd.com",
            "jd": "https://www.jd.com",
            "拼多多": "https://www.pinduoduo.com",
            "百度": "https://www.baidu.com",
            "高德": "https://www.amap.com",
            "携程": "https://www.ctrip.com",
            "网易": "https://www.163.com",
            "搜狐": "https://www.sohu.com",
            "新浪": "https://www.sina.com.cn",
            "WPS": "https://www.wps.cn",
            "石墨文档": "https://shimo.im",
            "优酷": "https://v.youku.com",
            "爱奇艺": "https://www.iqiyi.com",
            "Boss直聘": "https://www.zhipin.com",
            "去哪儿": "https://www.qunar.com",
        }

    
    def _check_url_with_playwright(self, url: str) -> Optional[str]:
        """使用Playwright检查URL（处理JS重定向）"""
        browser = None
        try:
            with sync_playwright() as p:
                browser = _launch_playwright_chromium(p)
                context = browser.new_context(
                    user_agent=self._get_random_user_agent(),
                    viewport={'width': 1920, 'height': 1080}
                )
                page = context.new_page()
                
                # 访问页面 - 优化：使用domcontentloaded替代networkidle
                response = page.goto(url, timeout=15000, wait_until='domcontentloaded')
                
                if response and response.status < 400:
                    # 优化：减少等待时间
                    page.wait_for_timeout(500)
                    final_url = page.url
                    return final_url
                
        except Exception as e:
            logger.debug(f"Playwright访问 {url} 失败: {e}")
        finally:
            # 确保浏览器始终关闭
            if browser:
                try:
                    browser.close()
                except Exception as e:
                    logger.debug(f"关闭浏览器失败: {e}")
        
        return None
    
    def _check_url_with_requests(self, url: str) -> Optional[str]:
        """使用requests检查URL"""
        try:
            response = self._get_request_session().get(url, timeout=10, allow_redirects=True)
            if response.status_code == 200:
                return str(response.url)
        except Exception as e:
            logger.debug(f"Requests访问 {url} 失败: {e}")
        
        return None
    
    def _find_website_with_llm(self, competitor_name: str) -> Optional[str]:
        """使用LLM查找官网。

        修复：不再做二次验证（之前的 _check_url_with_playwright/requests 经常因
        站点地域限制/超时/反爬 而返回 None，导致 LLM 给出的"im.qq.com"等
        正确域名被白白放弃，触发 AI 兜底）。

        现在：LLM 给出的 URL 直接采用（LLM 是大模型知识库，对知名产品的官方域名
        准确率 > 95%）。后续 _crawl_website 阶段仍会真正访问，访问不到再降级。
        """

        prompt = ChatPromptTemplate.from_messages([
            ("system",
             "你是一位互联网搜索专家。请根据产品名称，返回其官方主域名 URL。"
             "要求：\n"
             "1. 只返回 URL（https:// 开头），不要任何解释\n"
             "2. 优先返回 .com 主站；如果产品有 .cn 官方站（如 飞书→feishu.cn），返回 .cn\n"
             "3. 不要返回帮助页/产品子页（如 docs/help/blog），只返回主域名根路径\n"
             "4. 知名品牌直接返回主域名即可（如 Notion→https://www.notion.so）"),
            ("user", "{competitor_name}")
        ])

        try:
            chain = prompt | self.llm
            response = chain.invoke({"competitor_name": competitor_name})

            url = response.content.strip().strip('"').strip("'").strip("`")

            # 基本格式校验
            if not url.startswith("http"):
                # 尝试补全
                if url.startswith("www."):
                    url = "https://" + url
                elif "." in url and " " not in url:
                    url = "https://" + url

            if url.startswith("http"):
                logger.info(f"[LLM] 直接采用 LLM 推断的官网: {url}")
                return url

        except Exception as e:
            logger.error(f"LLM查找官网失败: {e}")

        return None
    
    def _get_crawl_paths(self, competitor_name: str, website: str) -> List[str]:
        """
        根据产品名和域名，返回适合的爬取路径列表。

        之前硬编码 ["/features", "/pricing", "/about"] 对中文网站全部 404。
        现在按站点特征智能选择路径。
        """
        domain = (website or "").lower().replace("https://", "").replace("http://", "").split("/")[0].split(":")[0]

        # ---- 替代数据源映射（C端消费App主站是SPA，需用开放平台/创作者平台）----
        # 这些产品的主站是重度JS渲染的下载页/登录墙，实际产品信息在子站点
        alt_sources = {
            "douyin.com": [
                "https://open.douyin.com",
                "https://creator.douyin.com",
            ],
            "kuaishou.com": [
                "https://open.kuaishou.com",
                "https://cp.kuaishou.com",
            ],
            "xiaohongshu.com": [
                # 主站公开页偶尔能返回服务端渲染内容；子站通常需要登录，
                # 仍保留作为补充来源，但不能只依赖子站。
                "https://www.xiaohongshu.com/about",
                "https://www.xiaohongshu.com/explore",
                "https://creator.xiaohongshu.com",
                "https://ark.xiaohongshu.com",
            ],
            "bilibili.com": ["https://www.bilibili.com/v/kichiku/", "https://www.bilibili.com/"],
            "weibo.com": ["https://weibo.com/", "https://open.weibo.com"],
        }

        # 检查是否有替代数据源（优先于主站路径）
        for alt_domain, urls in alt_sources.items():
            if domain == alt_domain or domain.endswith("." + alt_domain):
                logger.info(f"[AltSource] {domain} 使用替代数据源: {urls}")
                return urls

        # ---- 中文产品路径映射 ----
        cn_paths = {
            # 腾讯系：信息集中在首页，子页用中文路径
            "qq.com":           ["", "/index.shtml", "/product/", "/intro.shtml"],
            "im.qq.com":        ["", "/productInfo/", "/intro.shtml"],
            "weixin.qq.com":    ["", "/product", "/doc", "/about"],
            "work.weixin.qq.com":["", "", "/"],  # 企业微信，重复首页确保拿到
            "feishu.cn":        ["", "/pricing", "/product", "/about-feishu/"],
            "larksuite.com":    ["", "/pricing", "/features", "/about"],
            "dingtalk.com":     ["", "/price", "/product", "/about"],
            "alipay.com":       ["", "/product", "/about"],
            "taobao.com":       ["", ""],
            "jd.com":           ["", ""],
            "bilibili.com":     ["", "/v", "/about"],
            "zhihu.com":        ["", "/about", "/people"],
            "douyin.com":       ["", "/product", "/about"],
            "capcut.cn":        ["", "/pricing", "/features", "/about"],
            "bytedance.com":    ["", "/products", "/about"],
            "doubao.com":       ["", "/product", "/chat", "/about"],
            # AI 助手（增加更多路径以获取更完整数据）
            "moonshot.cn":      ["", "/price", "/intro", "/about", "/news"],
            "kimi.moonshot.cn": ["", "/price", "/intro", "/about", "/news"],
            "tongyi.aliyun.com":["", "/pricing", "/about", "/help", "/news"],
            "yiyan.baidu.com":  ["", "/price", "/about", "/doc", "/news"],
            "chatglm.cn":       ["", "/price", "/product", "/about", "/news"],
            "deepseek.com":     ["", "/pricing", "/about", "/news", "/updates"],
            "xfyun.cn":         ["", "/price", "/product", "/about", "/news"],
            "yuque.com":        ["", "/pricing", "/about"],
            "notion.so":        ["", "/product", "/pricing", "/about-notion/"],
            "notion.site":      ["", "/pricing", "/product"],
            "slack.com":        ["", "/features", "/pricing", "/about"],
            "zoom.us":          ["", "/pricing", "/plans", "/about"],
            "github.com":       ["", "/features", "/pricing", "/about"],
            "figma.com":        ["", "/pricing", "/product", "/about"],
            "canva.com":        ["", "/pricing", "/features", "/about"],
            "atlassian.net":    ["", "/software/jira/pricing", "/software/jira/features"],
            "linear.app":       ["", "/pricing", "/features", "/about"],
            "asana.com":        ["", "/pricing", "/features", "/about"],
            "monday.com":       ["", "/pricing", "/features", "/about"],
            "clickup.com":      ["", "/pricing", "/features", "/all-features"],
            "trello.com":       ["", "/pricing", "/features", "/about"],
            "obsidian.md":      ["", "/pricing", "/publish"],
            "evernote.com":     ["", "/pricing", "/features", "/about"],
            "onedrive.live.com":["", ""],
            "dropbox.com":      ["", "/plans", "/features", "/about"],
            "airtable.com":     ["", "/pricing", "/product", "/about"],
            "notion.com":       ["", "/product", "/pricing", "/about"],
            "js.design":        ["", "/pricing", "/product", "/about"],
            "pixso.cn":         ["", "/pricing", "/product", "/about"],
            "mastergo.com":     ["", "/pricing", "/product", "/about"],
            "dida365.com":      ["", "/webapp/#p/6641a07e3e5e", "/about"],
            "ticktick.com":     ["", "/pricing", "/product", "/about"],
            "mubu.com":         ["", "/pricing", "/download", "/about"],
            "xmind.cn":         ["", "/pricing", "/download", "/about"],
            # 网盘/云存储
            "quark.cn":         ["", "/download", "/help", "/about"],
            "www.quark.cn":     ["", "/download", "/help", "/about"],
            "pan.baidu.com":    ["", "/info", "/disk/main#/help", "/about"],
        }

        # 1. 域名精确匹配
        if domain in cn_paths:
            paths = cn_paths[domain]
            logger.info(f"[PathMap] 域名精确命中: {domain} -> {paths}")
            return paths

        # 2. 主域名模糊匹配（如 *.qq.com 匹配 qq.com）
        for known_domain, paths in cn_paths.items():
            if domain == known_domain or domain.endswith("." + known_domain):
                logger.info(f"[PathMap] 域名模糊命中: {domain} ~ {known_domain} -> {paths}")
                return paths

        # ========= 新增：使用 DuckDuckGo 动态发现路径 =========
        try:
            search = get_search_service()
            feature_pages = search.discover_feature_pages(website, competitor_name)
            if feature_pages:
                # 转换为相对路径
                import urllib.parse
                base_domain = urllib.parse.urlparse(website).netloc
                ddg_paths = []
                for page_url in feature_pages:
                    parsed = urllib.parse.urlparse(page_url)
                    if parsed.netloc == base_domain or parsed.netloc.endswith("." + base_domain):
                        # 同域名，提取路径
                        path = parsed.path
                        if path and path not in ddg_paths:
                            ddg_paths.append(path)
                
                if ddg_paths:
                    logger.info(f"[DuckDuckGo] 动态发现路径: {competitor_name} -> {ddg_paths}")
                    return [""] + ddg_paths  # 包含首页
        except Exception as e:
            logger.warning(f"[DuckDuckGo] 路径发现失败: {e}，继续使用默认路径")

        # 3. 中文产品名判断 → 用通用中文路径
        is_chinese = any('\u4e00' <= c <= '\u9fff' for c in (competitor_name or ""))
        if is_chinese:
            paths = ["", "/product", "/功能", "/功能介绍", "/产品", "/产品特性",
                     "/about", "/intro", "/help", "/news", "/更新日志", "/动态"]
            logger.info(f"[PathMap] 中文产品默认路径: {competitor_name} -> {paths}")
            return paths

        # 4. 默认英文路径
        paths = ["", "/features", "/product", "/pricing", "/capabilities", "/function",
                 "/about", "/docs", "/changelog", "/releases", "/updates", "/news"]
        logger.info(f"[PathMap] 默认英文路径: {domain} -> {paths}")
        return paths

    def _discover_paths_from_homepage(self, website: str) -> List[str]:
        """
        探测式路径发现：抓取首页 HTML，解析所有 <a href>，
        用关键词筛选出可能包含产品信息的子页面路径。

        返回去重后的路径列表（不含首页 ""）。
        """
        import urllib.parse
        from bs4 import BeautifulSoup

        keywords = [
            # 英文
            "pricing", "price", "plan", "subscribe", "payment",
            "feature", "product", "capability", "function",
            "about", "company", "team", "contact", "help",
            "changelog", "release", "update", "version", "whats-new", "news",
            "blog", "article", "doc", "documentation", "guide", "tutorial",
            "download", "install", "get-started", "start",
            # 中文
            "定价", "价格", "收费", "购买", "套餐", "方案",
            "功能", "特性", "产品", "介绍", "能力",
            "关于", "公司", "团队", "联系", "帮助", "客服",
            "更新", "版本", "发布", "日志", "动态", "公告",
            "博客", "文章", "文档", "教程", "指南",
            "下载", "安装", "开始", "入门",
        ]

        discovered = []
        try:
            # 获取首页 HTML（用 requests 轻量获取，不启动 Playwright）
            html = self._crawl_page_with_requests(website)
            if not html:
                logger.debug(f"探测式路径：首页获取失败，跳过 {website}")
                return []

            soup = BeautifulSoup(html, 'html.parser')
            base_domain = urllib.parse.urlparse(website).netloc.lower()

            for a in soup.find_all('a', href=True):
                href = a['href'].strip()
                if not href or href.startswith('#') or href.startswith('javascript:'):
                    continue

                # 转为绝对 URL
                full_url = urllib.parse.urljoin(website, href)
                parsed = urllib.parse.urlparse(full_url)

                # 只保留同域名的链接
                if parsed.netloc.lower() != base_domain:
                    continue

                # 提取路径部分
                path = parsed.path or ""
                if not path or path == "/":
                    continue

                # 路径名（不含查询参数）转为小写做关键词匹配
                path_lower = path.lower()

                # 匹配关键词
                matched = any(kw in path_lower for kw in keywords)
                if matched and path not in discovered:
                    discovered.append(path)
                    logger.debug(f"探测式路径发现: {path} (来自 {href})")

            # 限制最多发现 8 条，避免爬取过多
            discovered = discovered[:8]
            if discovered:
                logger.info(f"[PathDiscover] 从 {website} 发现 {len(discovered)} 条相关路径: {discovered}")
            else:
                logger.debug(f"[PathDiscover] 从 {website} 未发现有价值的路径")

        except Exception as e:
            logger.debug(f"探测式路径失败 {website}: {e}")

        return discovered

    def _crawl_website(self, website: str, competitor_name: str = "", best_effort: bool = False) -> Dict[str, str]:
        """
        爬取网站多个页面。

        改进：
        - 根据域名智能选择爬取路径（不再硬编码 /features,/pricing,/about）
        - 首页始终优先且重试次数更多
        - 探测式路径发现：从首页 <a> 标签自动发现相关页面
        - sitemap.xml / robots.txt 发现真实内容页（绕过 JS 首页）
        - 当官网直爬失败时，尝试搜索引擎辅助抓取
        """
        # 1. 智能路径（域名映射表）
        paths_to_crawl = self._get_crawl_paths(competitor_name, website)

        # 2. 探测式路径发现（补充域名映射表未覆盖的路径）
        discovered = self._discover_paths_from_homepage(website)
        for p in discovered:
            if p not in paths_to_crawl:
                paths_to_crawl.append(p)

        # 3. sitemap / robots.txt 发现（绕开 JS 渲染首页，稳定枚举真实内容页）
        try:
            sm_paths = self._discover_via_sitemap(website)
            for u in sm_paths:
                if u not in paths_to_crawl:
                    paths_to_crawl.append(u)
        except Exception as e:
            logger.debug(f"sitemap 发现异常 {website}: {e}")

        logger.info(f"[CrawlPaths] 最终爬取路径（{len(paths_to_crawl)} 条）: {paths_to_crawl}")

        if self.use_playwright:
            raw_data = self._crawl_website_with_reused_browser(website, paths_to_crawl, best_effort=best_effort)
        else:
            raw_data = self._crawl_website_concurrent(website, paths_to_crawl, best_effort=best_effort)

        # Playwright 可能已启动但页面因网络策略或站点拦截全部为空；
        # 再走 requests 可以命中过期缓存，也能覆盖浏览器临时失败。
        if not raw_data and self.use_playwright:
            logger.warning(f"Playwright 未返回页面，回退 requests/缓存: {competitor_name}")
            raw_data = self._crawl_website_concurrent(
                website, paths_to_crawl, best_effort=best_effort
            )

        # 如果直爬结果为空（所有页面都失败了），尝试搜索引擎辅助
        if not raw_data and competitor_name:
            logger.warning(f"官网直爬无数据，尝试搜索引擎辅助: {competitor_name}")
            raw_data = self._crawl_via_search_engine(competitor_name)

        logger.info(f"_crawl_website 完成: {len(raw_data)} 个页面")
        return raw_data

    def _crawl_via_search_engine(self, competitor_name: str) -> Dict[str, str]:
        """当官网直爬失败时，通过搜索引擎获取产品介绍页面的 HTML 内容。"""
        import urllib.parse

        # 构造搜索 URL
        query = f"{competitor_name} 官网 功能介绍 产品特性"
        encoded_query = urllib.parse.quote(query)
        search_urls = [
            f"https://www.bing.com/search?q={encoded_query}&setlang=zh-Hans",
            f"https://www.google.com/search?q={encoded_query}&hl=zh-CN",
        ]

        raw_data = {}
        for search_url in search_urls:
            try:
                html = self._crawl_page_with_requests(search_url)
                if html and len(html) > 1000:
                    raw_data[f"search:{competitor_name}"] = html
                    logger.info(f"搜索引擎辅助成功: {search_url} ({len(html)} bytes)")
                    break  # 一个搜索结果就够了
            except Exception as e:
                logger.debug(f"搜索引擎 {search_url} 失败: {e}")

        return raw_data
    
    def _crawl_website_with_reused_browser(self, website: str, paths_to_crawl: List[str], best_effort: bool = False) -> Dict[str, str]:
        """使用复用的Playwright浏览器实例爬取网站（方案1）"""
        raw_data = {}
        
        try:
            with sync_playwright() as p:
                # 只启动一次浏览器！
                browser = _launch_playwright_chromium(p)
                context = browser.new_context(
                    user_agent=self._get_random_user_agent(),
                    viewport={'width': 1920, 'height': 1080},
                    locale='en-US'
                )
                
                # 添加额外的请求头
                context.set_extra_http_headers({
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
                })
                
                page = context.new_page()
                
                # 遍历所有页面
                for path in paths_to_crawl:
                    # 支持两种格式：相对路径（/product）和完整URL（https://open.douyin.com）
                    if path.startswith("http"):
                        page_url = path  # 完整URL（替代数据源）
                    else:
                        page_url = website.rstrip("/") + path
                    
                    # 重试机制
                    for attempt in range(self.max_retries):
                        try:
                            logger.debug(f"爬取 (尝试 {attempt + 1}/{self.max_retries}): {page_url}")
                            
                            # 方案2：减少延迟
                            self._random_delay(0.3, 1.0)
                            
                            # 使用已存在的page对象
                            html_content = self._crawl_single_page_with_page(page, page_url, best_effort=best_effort)
                            
                            if html_content:
                                raw_data[page_url] = html_content
                                logger.debug(f"成功: {page_url} ({len(html_content)} bytes)")
                                break  # 成功，跳出重试循环
                            else:
                                logger.warning(f"爬取返回空内容: {page_url}")
                                
                        except Exception as e:
                            logger.warning(f"爬取失败 {page_url} (尝试 {attempt + 1}/{self.max_retries}): {e}")
                            
                            if attempt < self.max_retries - 1:
                                # 等待后重试
                                time.sleep(2 ** attempt)  # 指数退避
                            else:
                                logger.error(f"爬取失败，已达最大重试次数: {page_url}")
                
                browser.close()
                logger.info(f"Playwright浏览器复用模式完成，爬取了 {len(raw_data)} 个页面")
        
        except Exception as e:
            logger.error(f"Playwright浏览器复用模式失败: {e}")
            # 降级到普通模式
            return self._crawl_website_fallback(website, paths_to_crawl, best_effort=best_effort)
        
        return raw_data
    
    def _crawl_single_page_with_page(self, page, url: str, best_effort: bool = False) -> Optional[str]:
        """使用已存在的page对象爬取单个页面（方案1辅助方法）"""
        # 缓存优先：跨模式/跨运行复用真实 HTML
        cached = self._cache_load(url, "html")
        if cached:
            self._record_cache_event(url, "fresh_cache")
            logger.debug(f"[Cache] 命中: {url} ({len(cached)} bytes)")
            return cached
        # 刷新失败时保留旧页面，避免临时网络/反爬导致来源数直接归零。
        stale_cached = self._cache_load(url, "html", ttl_seconds=0)
        try:
            # 优化：减少等待时间，快速获取内容
            response = page.goto(url, timeout=20000, wait_until='domcontentloaded')

            if response and response.status < 400:
                # 等待网络空闲 + 额外渲染时间，让 XHR/JS 注入的内容（新闻、更新日志、
                # 版本公告等）真正进入 DOM，否则只抓到导航外壳 -> 抽取不到版本信息
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                page.wait_for_timeout(1500)

                # 获取 HTML 内容
                html_content = page.content()

                # 验证 HTML 是否有实质内容（best_effort 放宽阈值）
                threshold = 200 if best_effort else 500
                if html_content and len(html_content) > threshold:
                    self._cache_save(url, html_content, "html")
                    return html_content
                else:
                    logger.warning(f"页面内容过少({len(html_content) if html_content else 0} bytes): {url}")
                    if stale_cached:
                        self._record_cache_event(url, "stale_cache")
                        logger.warning(f"[Cache] Playwright 内容过少，使用过期缓存: {url}")
                        return stale_cached
                    return None

        except PlaywrightTimeout:
            logger.warning(f"Playwright超时: {url}")
        except Exception as e:
            logger.debug(f"爬取页面失败 {url}: {e}")

        if stale_cached:
            self._record_cache_event(url, "stale_cache")
            logger.warning(f"[Cache] Playwright 请求失败，使用过期缓存: {url}")
            return stale_cached
        return None
    
    def _crawl_website_concurrent(self, website: str, paths_to_crawl: List[str], best_effort: bool = False) -> Dict[str, str]:
        """使用并发方式爬取网站（方案4 - requests模式）"""
        
        def crawl_single_url(path: str):
            """爬取单个URL的辅助函数"""
            # 支持完整 URL（替代数据源）和相对路径
            if path.startswith("http"):
                page_url = path
            else:
                page_url = website.rstrip("/") + path
            
            # _crawl_page_with_requests 内部已经完成重试、退避和过期缓存回退。
            # 外层再重试会把一次 URL 放大为 max_retries² 次请求，导致慢站长时间
            # 阻塞并触发重复限流。
            try:
                logger.debug(f"并发爬取: {page_url}")
                self._random_delay(0.3, 1.0)
                html_content = self._crawl_page_with_requests(
                    page_url, best_effort=best_effort
                )
                if html_content:
                    logger.debug(f"成功: {page_url} ({len(html_content)} bytes)")
                    return page_url, html_content
                logger.warning(f"爬取返回空内容: {page_url}")
            except Exception as e:
                logger.error(f"并发爬取失败: {page_url}: {e}")
            return page_url, None
        
        raw_data = {}
        
        # 使用线程池并发爬取
        with ThreadPoolExecutor(max_workers=3) as executor:
            # 提交所有任务
            future_to_url = {
                executor.submit(crawl_single_url, path): path 
                for path in paths_to_crawl
            }
            
            # 收集结果
            for future in as_completed(future_to_url):
                page_url, html_content = future.result()
                if html_content:
                    raw_data[page_url] = html_content
        
        logger.info(f"并发爬取完成，爬取了 {len(raw_data)} 个页面")
        return raw_data
    
    def _crawl_website_fallback(self, website: str, paths_to_crawl: List[str], best_effort: bool = False) -> Dict[str, str]:
        """降级方案：串行爬取（当并发或浏览器复用失败时）"""
        raw_data = {}
        
        for path in paths_to_crawl:
            # 替代数据源路径可能是完整 URL，不能再次拼接主站域名。
            page_url = path if path.startswith("http") else website.rstrip("/") + path
            
            # requests 方法本身已经负责重试；降级路径不再套一层重试。
            try:
                logger.debug(f"降级爬取: {page_url}")
                self._random_delay(0.3, 1.0)
                html_content = self._crawl_page_with_requests(
                    page_url, best_effort=best_effort
                )
                if html_content:
                    raw_data[page_url] = html_content
                    logger.debug(f"成功: {page_url} ({len(html_content)} bytes)")
                else:
                    logger.warning(f"爬取返回空内容: {page_url}")
            except Exception as e:
                logger.error(f"降级爬取失败: {page_url}: {e}")
        
        return raw_data
    
    def _crawl_page_with_playwright(self, url: str) -> Optional[str]:
        """使用Playwright爬取页面（支持JavaScript渲染）- 保留用于_check_url_with_playwright"""
        try:
            with sync_playwright() as p:
                browser = _launch_playwright_chromium(p)
                context = browser.new_context(
                    user_agent=self._get_random_user_agent(),
                    viewport={'width': 1920, 'height': 1080},
                    locale='en-US'
                )
                
                context.set_extra_http_headers({
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
                })
                
                page = context.new_page()
                
                # 方案2：优化等待策略
                response = page.goto(url, timeout=15000, wait_until='domcontentloaded')
                
                if response and response.status < 400:
                    page.wait_for_timeout(1000)
                    
                    html_content = page.content()
                    browser.close()
                    return html_content
                
                browser.close()
                
        except PlaywrightTimeout:
            logger.warning(f"Playwright超时: {url}")
        except Exception as e:
            logger.error(f"Playwright爬取 {url} 失败: {e}")
        
        return None
    
    def _crawl_page_with_requests(self, url: str, best_effort: bool = False) -> Optional[str]:
        """使用requests爬取页面（静态内容）—— 增强版：缓存 + 退避 + Retry-After + 完整伪装"""
        # 0. 缓存优先（跨运行复用真实 HTML，避免重复触发限流/兜底）
        cached = self._cache_load(url, "html")
        if cached:
            self._record_cache_event(url, "fresh_cache")
            logger.debug(f"[Cache] 命中: {url} ({len(cached)} bytes)")
            return cached
        # 刷新失败时保留旧页面，避免临时网络/反爬导致来源数直接归零。
        stale_cached = self._cache_load(url, "html", ttl_seconds=0)

        anti_scrape_markers = [
            "access denied", "forbidden", "captcha", "验证码", "人机验证",
            "cloudflare", "just a moment", "checking your browser",
            "please verify you are a human", "403 forbidden",
        ]

        for attempt in range(self.max_retries):
            try:
                # 完整浏览器 User-Agent 轮换
                user_agent = self._get_random_user_agent()
                headers = {
                    "User-Agent": user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                    "Cache-Control": "max-age=0",
                    "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
                    "sec-ch-ua-mobile": "?0",
                    "sec-ch-ua-platform": '"Windows"',
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-User": "?1",
                }
                session = self._get_request_session()
                session.headers.update(headers)

                # 连接 15s，读取 45s（适配慢站）
                response = session.get(
                    url,
                    timeout=(15, 45),
                    allow_redirects=True
                )

                if response.status_code == 200:
                    content = response.text
                    content_lower = content.lower()[:2000]
                    is_blocked = any(marker in content_lower for marker in anti_scrape_markers)
                    if is_blocked:
                        logger.warning(f"被反爬拦截: {url} (可能是 Cloudflare/验证码)")
                        if stale_cached:
                            self._record_cache_event(url, "stale_cache")
                            logger.warning(f"[Cache] 刷新被拦截，使用过期缓存: {url}")
                            return stale_cached
                        return None  # 不缓存拦截页，交给上层 Playwright/搜索兜底

                    if len(content) > 200:  # 至少有实质内容
                        self._cache_save(url, content, "html")
                        self._record_cache_event(url, "live")
                        return content
                    logger.warning(f"页面内容过少({len(content)} bytes): {url}")
                    if stale_cached:
                        self._record_cache_event(url, "stale_cache")
                        logger.warning(f"[Cache] 刷新内容过少，使用过期缓存: {url}")
                        return stale_cached
                    return None
                elif response.status_code == 429:
                    # 尊重 Retry-After，否则指数退避 + 随机抖动
                    retry_after = response.headers.get("Retry-After")
                    wait = float(retry_after) if (retry_after and retry_after.strip().isdigit()) else (2 ** attempt)
                    wait += random.uniform(0, 1.0)
                    logger.warning(f"429 限流 {url}，等待 {wait:.1f}s 后重试 ({attempt + 1}/{self.max_retries})")
                    if attempt < self.max_retries - 1:
                        time.sleep(wait)
                        continue
                    if stale_cached:
                        self._record_cache_event(url, "stale_cache")
                        logger.warning(f"[Cache] 429 限流，使用过期缓存: {url}")
                        return stale_cached
                    return None
                elif response.status_code in (401, 403):
                    logger.warning(f"{response.status_code} 反爬拦截: {url}")
                    if stale_cached:
                        self._record_cache_event(url, "stale_cache")
                        logger.warning(f"[Cache] {response.status_code} 拦截，使用过期缓存: {url}")
                        return stale_cached
                    return None
                else:
                    logger.debug(f"HTTP {response.status_code}: {url}")
                    if stale_cached:
                        self._record_cache_event(url, "stale_cache")
                        logger.warning(f"[Cache] HTTP {response.status_code}，使用过期缓存: {url}")
                        return stale_cached
                    return None

            except Exception as e:
                wait = (2 ** attempt) + random.uniform(0, 1.0)  # 指数退避 + 抖动
                logger.warning(f"Requests爬取失败 {url} (尝试 {attempt + 1}/{self.max_retries}): {e}")
                if attempt < self.max_retries - 1:
                    if classify_connection_error(e) in {"network_blocked", "invalid_auth", "forbidden"}:
                        logger.error(f"Requests不可恢复错误，停止重试 {url}: {classify_connection_error(e)}")
                        break
                    time.sleep(wait)
                else:
                    logger.error(f"Requests爬取 {url} 最终失败: {e}")
                    if stale_cached:
                        self._record_cache_event(url, "stale_cache")
                        logger.warning(f"[Cache] 请求失败，使用过期缓存: {url}")
                        return stale_cached

        return None
    
    def _extract_structured_data(self, competitor_name: str, website: str, 
                                 raw_data: Dict[str, str]) -> Dict[str, Any]:
        """
        从原始HTML中提取结构化数据。

        改进（C 优化）：
        - 每个页面单独 LLM 提取，最后合并（避免单页被截断）
        - max_length 提升到 50000（适配大模型上下文）
        - 提示词强调"找不到就写 null，不要猜"
        - 优先保留非 null 值（多页合并时，后页不覆盖前页的非 null 值）
        """

        # ---- 策略：每页单独提取，最后合并 ----
        # 这比把多页合并成一个大文本更可靠：
        # 1) 不会出现某页信息被截断
        # 2) 每页 LLM 调用更专注，提取质量更高
        # 3) 合并时优先保留非 null 值

        merged = {
            "name": competitor_name,
            "website": website,
            "features": {"core": [], "advanced": []},
            "pricing": {},
            "changelog": {},
            "company_info": {},
            "target_users": [],
            "platforms": [],
            # 字段级来源：每个结构化字段都记录实际支撑它的页面 URL，
            # 供 Analyzer 判断“已验证”而不是仅凭 page_access 计分。
            "_field_evidence": {},
        }
        merge_count = 0

        for url, html in raw_data.items():
            page_data = self._extract_from_single_page(competitor_name, website, url, html)
            if not page_data:
                continue
            # 合并策略：非 null/非空 值优先
            self._merge_page_data(merged, page_data)
            self._record_field_evidence(merged, page_data, url)
            merge_count += 1

        if merge_count == 0:
            logger.warning(f"Crawler: {competitor_name} 所有页面 LLM 提取均无结果，返回空数据")
            return self._create_empty_data(competitor_name, website)

        merged["crawled_pages"] = list(raw_data.keys())
        logger.info(f"Crawler: {competitor_name} 从 {merge_count} 个页面提取并合并了结构化数据")
        return merged

    def _record_field_evidence(self, merged: Dict, page_data: Dict, url: str) -> None:
        """记录单页抽取结果对应的 URL，避免把整页访问误当成字段证据。"""
        if not url or not isinstance(page_data, dict):
            return
        evidence = merged.setdefault("_field_evidence", {})

        features = page_data.get("features")
        if isinstance(features, dict):
            for key in ("core", "advanced"):
                value = features.get(key)
                if isinstance(value, list) and value:
                    evidence.setdefault(f"features.{key}", []).append(url)

        for key in ("pricing", "changelog", "company_info"):
            value = page_data.get(key)
            if isinstance(value, dict) and any(v not in (None, "", []) for v in value.values()):
                evidence.setdefault(key, []).append(url)

        for key in ("target_users", "platforms"):
            value = page_data.get(key)
            if isinstance(value, list) and value:
                evidence.setdefault(key, []).append(url)

    def _extract_from_single_page(self, competitor_name: str, website: str, url: str, html: str) -> Optional[Dict]:
        """从单个页面的 HTML 中提取结构化数据（调用一次 LLM）"""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            for script in soup(["script", "style", "noscript", "iframe"]):
                script.decompose()
            text = soup.get_text(separator="\n", strip=True)

            # 单页限制提升到 45000 字符（homepage/功能页常含大量营销文案与功能描述）
            max_length = 45000
            content = text[:max_length]

            prompt = ChatPromptTemplate.from_messages([
                ("system", """你是一位产品数据分析专家。请从网页内容中提取竞品的结构化信息。

【重要】严格遵守以下规则：
1. 只从给出的网页内容中提取信息，不要使用你的训练知识
2. 价格、版本号、公司信息（成立年份/总部/员工数）属于客观事实，网页没有明确给出时务必填 null，绝不要猜测或编造
3. 功能/能力属于可从页面描述归纳的信息，详见下方【功能提取】
4. 输出必须是合法的 JSON，不要有其他内容

【功能提取】从页面文本中识别"用户可独立使用的产品能力"：
- 既包括页面上明确的列表/按钮，也包括功能介绍、营销文案、FAQ 中描述的能力
  （例如页面写"支持 Markdown 编辑、可双向链接、团队协作编辑"，应识别为「Markdown 支持」「双向链接」「协作共享」等功能）
- 不要把导航栏、页脚链接、客服话术、营销口号、法律条款本身当成功能
- 功能名要简洁具体（如"实时协作""双向链接"），不要写成句子
- 尽量列出页面里出现的所有核心功能（通常 8-15 个），不要漏掉；
  只有页面完全没有任何功能相关信息时，core 才填 []
- 严禁凭空编造页面未提及的功能（可归纳，不可捏造）

【价格归一】pricing.plans 中 price 必须是数字（不要带货币符号或"起"等字），并注明币种：
- 若页面是人民币，在 plan 名或 model 中标注"¥/CNY"；美元标注"$/USD"
- period 用 "month" / "year" / "one-time"；买断制填 one-time
- 找不到价格填 null

【版本/更新提取】changelog 不只从专门的更新日志页提取；
- 也要从首页公告、产品页"新功能"/"What's New"/"最新动态"、新闻页等提取版本号、发布日期和近期更新
- 若网页没有明确版本号，可记录最近一次产品更新/模型发布的日期作为 latest_release_date
- 更新内容要简洁具体，每条用一句话概括，不要照抄整段营销文案
- 找不到就填 null 或空数组 []

请提取以下信息（JSON格式）：
{{
    "name": "产品名称",
    "features": {{
        "core": ["核心功能1", "核心功能2"],
        "advanced": ["高级功能1", "高级功能2"]
    }},
    "pricing": {{
        "model": "定价模式(free/subscription/one-time/freemium，找不到就填 null)",
        "plans": [
            {{"name": "方案名称(含币种如 ¥/$)", "price": 价格数字或 null, "period": "month/year/one-time"}}
        ]
    }},
    "changelog": {{
        "latest_version": "最新版本号（找不到就填 null）",
        "latest_release_date": "最新发布日期（找不到就填 null）",
        "recent_updates": ["更新内容1", "更新内容2"],
        "update_frequency": "更新频率描述（找不到就填 null）"
    }},
    "company_info": {{
        "founded": "成立年份（找不到就填 null）",
        "hq": "总部地点（找不到就填 null）",
        "employees": "员工数（找不到就填 null）"
    }},
    "target_users": ["目标用户1", "目标用户2（找不到就填 []）"],
    "platforms": ["支持平台1", "支持平台2（找不到就填 []）"]
}}"""),
                ("user", "产品名称: {competitor_name}\n来源页面: {url}\n\n网页内容:\n{content}")
            ])

            import time as time_mod
            t_start = time_mod.time()
            # 防御：并行 worker 若未正确复制 llm_extract，回退到 self.llm，避免抽取整体失败
            llm = getattr(self, "llm_extract", None) or self.llm
            chain = prompt | llm
            response = chain.invoke({
                "competitor_name": competitor_name,
                "url": url,
                "content": content
            })
            t_end = time_mod.time()

            usage = response.usage_metadata if hasattr(response, 'usage_metadata') else {}
            input_tokens = usage.get('input_tokens', 0)
            output_tokens = usage.get('output_tokens', 0)
            from agents.perf_tracker import get_tracker
            tracker = get_tracker()
            tracker.log_call('Crawler', '_extract_single_page', input_tokens, output_tokens, t_end - t_start)

            page_data = safe_extract_json(response.content, verbose=True)
            if page_data and isinstance(page_data, dict):
                # 合法 JSON 不代表真正提取到了字段。许多 JS/登录墙页面会让
                # 模型返回全空结构；将其单独标记，避免日志误报“提取成功”。
                extracted_features = page_data.get("features") or {}
                has_content = bool(
                    (extracted_features.get("core") if isinstance(extracted_features, dict) else [])
                    or (extracted_features.get("advanced") if isinstance(extracted_features, dict) else [])
                    or page_data.get("pricing")
                    or page_data.get("changelog")
                    or page_data.get("company_info")
                    or page_data.get("target_users")
                    or page_data.get("platforms")
                )
                if not has_content:
                    logger.warning(f"[Extract] {url}: 返回合法 JSON，但没有有效字段（可能是 JS/登录墙页面）")
                else:
                    logger.info(f"[Extract] {url}: 提取成功（{len(str(page_data))} bytes）")
                return page_data
            else:
                logger.warning(f"[Extract] {url}: JSON 解析失败")
                return None

        except Exception as e:
            logger.error(f"[Extract] {url}: 提取失败: {e}")
            return None

    def _merge_page_data(self, merged: Dict, page_data: Dict) -> None:
        """将单页提取的数据合并到 merged（优先保留非 null 值）"""
        for key in ["features", "pricing", "changelog", "company_info"]:
            if key not in page_data:
                continue
            page_val = page_data[key]
            if not isinstance(page_val, dict):
                continue
            merged.setdefault(key, {})
            for sub_key, sub_val in page_val.items():
                # 优先保留非 null/非空的值
                if sub_val is not None and sub_val != [] and sub_val != "":
                    merged[key][sub_key] = sub_val

        # 列表字段：合并去重
        for key in ["target_users", "platforms"]:
            if key in page_data and isinstance(page_data[key], list):
                existing = set(merged.get(key, []))
                for item in page_data[key]:
                    if item and item not in existing:
                        merged.setdefault(key, []).append(item)
                        existing.add(item)

        # features.core / advanced：合并去重
        if "features" in page_data and isinstance(page_data["features"], dict):
            for fk in ["core", "advanced"]:
                if page_data["features"].get(fk):
                    existing = set(merged["features"].get(fk, []))
                    for item in page_data["features"][fk]:
                        if item and item not in existing:
                            merged["features"].setdefault(fk, []).append(item)
                            existing.add(item)

    
    def _create_empty_data(self, competitor_name: str, website: str = None) -> Dict[str, Any]:
        """创建空数据结构"""
        
        return {
            "name": competitor_name,
            "website": website,
            "features": {
                "core": [],
                "advanced": []
            },
            "pricing": {
                "model": None,
                "plans": []
            },
            "changelog": {
                "latest_version": None,
                "latest_release_date": None,
                "recent_updates": [],
                "update_frequency": None
            },
            "company_info": {},
            "target_users": [],
            "platforms": [],
            "crawled_pages": []
        }
    
    def _llm_fallback_collect(self, competitor_name: str, website: str = None) -> Dict[str, Any]:
        """
        当爬虫失败或返回空数据时，使用 LLM 知识库生成结构化数据
        
        这是兜底方案：即使完全无法访问网站，用户仍能得到有价值的报告
        
        🔧 重构：使用 LLM 动态理解产品，无需任何手动白名单
        """
        
        # 🔧 第一步：用 LLM 动态理解产品（替代原来的 _detect_product_type 白名单）
        product_understanding = self._understand_product_with_llm(competitor_name, website)
        category = product_understanding.get("category", "通用")
        
        # 🔧 第二步：极简通用 Prompt（不做任何复杂字符串拼接）
        # 关键：system_prompt 是普通字符串，category 由 Python 提前填入
        # user 消息中的 {competitor_name} 和 {website} 由 LangChain 在 invoke 时填入
        system_text = (
            "你是一位资深的产品数据分析专家，擅长分析各类互联网产品。\n\n"
            "请基于你的知识，对以下产品进行全面的结构化分析，"
            "输出严格的 JSON 格式（不要有 markdown 代码块）。\n\n"
            "产品类别：" + category + "\n\n"
            "要求：\n"
            "1. features.core 至少列出 10 个核心功能（具体、可验证的功能名）\n"
            "2. features.advanced 列出高级功能\n"
            "3. pricing 分析定价策略\n"
            "4. changelog 分析版本更新：必须给出最近 6-12 个月内的重要更新；"
            "   如果该产品是在线服务/AI 模型/没有固定版本号，也请填写其最新模型版本、"
            "   重大能力发布或里程碑版本（如 DeepSeek-V3、豆包 1.5 等），并用发布日期作为 latest_release_date\n"
            "5. target_users 和 platforms 要具体\n"
            "6. 如果是知名产品，务必列出其标志性功能，不要遗漏\n\n"
            "输出格式（严格 JSON，不要有其他内容）：\n"
            "{{\n"
            '    "name": "产品名称",\n'
            '    "features": {{\n'
            '        "core": ["核心功能1", "核心功能2", ...],\n'
            '        "advanced": ["高级功能1", "高级功能2", ...]\n'
            '    }},\n'
            '    "pricing": {{"model": "...", "plans": [...]}},\n'
            '    "changelog": {{\n'
            '        "latest_version": "最新版本号或模型版本（如 v3.2.1 / DeepSeek-V3 / 豆包 1.5，找不到就填 null）",\n'
            '        "latest_release_date": "最新发布日期（YYYY-MM-DD，找不到就填 null）",\n'
            '        "recent_updates": ["近 6-12 个月最重要的更新1", "更新2", "更新3"],\n'
            '        "update_frequency": "更新频率描述（如每月、每季度、不定期，找不到就填 null）"\n'
            '    }},\n'
            '    "target_users": ["用户1", "用户2"],\n'
            '    "platforms": ["平台1", "平台2"]\n'
            "}}"
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_text),
            ("user",
                "产品名称：" + competitor_name + "\n"
                "官网：" + (website or "未知") + "\n\n"
                "请输出结构化 JSON。确保 features.core 包含所有核心功能；"
                "changelog 必须填写近 6-12 个月的重要更新或模型版本，不要留空。"
            )
        ])
        
        try:
            chain = prompt | self.llm
            response = chain.invoke({})
            
            # 清洗 LLM 返回内容（使用安全的解析函数）
            try:
                result = safe_extract_json(response.content, verbose=True)
            except ValueError as e:
                logger.error(f"JSON解析失败: {e}")
                return self._create_empty_data(competitor_name, website)
            
            result["website"] = website or result.get("website", "")
            result["name"] = competitor_name
            result["crawled_pages"] = []
            result["_source"] = "llm_fallback"
            result["_category"] = category
            
            logger.info(f"LLM兜底采集成功: {competitor_name} (类别: {category})")
            return result
            
        except Exception as e:
            logger.error(f"LLM兜底采集失败: {e}")
            return self._create_empty_data(competitor_name, website)
    def _understand_product_with_llm(self, product_name: str, website: str = None) -> Dict:
        """
        用 LLM 动态理解产品，无需任何手动白名单
        
        返回：{
            "category": "产品大类（如：即时通讯/笔记知识管理/招聘求职/电商/音乐...）",
            "core_features": ["功能1", "功能2", ...],
            "must_check_features": ["功能1", "功能2", ...],
            "typical_users": ["主要用户群体"],
            "key_competitors": ["主要竞品"]
        }
        """
        prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一位资深的产品分析专家，擅长理解各类互联网产品。

请分析用户提到的产品，输出严格的 JSON 格式（不要有 markdown 代码块）。

输出字段说明：
- category: 产品所属大类（从以下中选择最合适的一个，如都不合适请自己总结：
  即时通讯、笔记知识管理、招聘求职、电商、音乐、视频、办公协作、项目管理、设计工具、云服务、金融、教育、社交、游戏、出行、外卖、医疗、AI工具、开发工具、安全工具）
- core_features: 这个产品最最核心的 10-15 个功能（具体、可验证的功能名）
- must_check_features: 做竞品对比时，最应该重点对比的 8-12 个功能
- typical_users: 主要的目标用户群体（2-4个）
- key_competitors: 这个产品最主要的 3-5 个竞品名称

要求：
- 功能名称要标准化、简洁（2-6个字）
- 如果是知名产品，务必列出其标志性功能，不要遗漏
- 只输出 JSON，不要有其他内容"""),
            ("user", "产品名称：{product_name}\n官网：{website}\n\n请分析这个产品。")
        ])

        try:
            chain = prompt | self.llm
            response = chain.invoke({
                "product_name": product_name,
                "website": website or ""
            })
            result = safe_extract_json(response.content, verbose=True)
            logger.info(f"[Crawler] LLM产品理解成功: {product_name} → {result.get('category', '未知')}")
            return result
        except Exception as e:
            logger.warning(f"[Crawler] LLM产品理解失败: {e}，使用默认分类")
            return {
                "category": _infer_category_from_product_name(product_name) or "通用",
                "core_features": [],
                "must_check_features": [],
                "typical_users": [],
                "key_competitors": []
            }
    
    def _merge_crawl_and_llm(self, crawl_data: Dict, llm_data: Dict, competitor_name: str, website: str) -> Dict[str, Any]:
        """
        合并爬虫数据和 LLM 兜底数据
        爬虫数据优先，空白字段用 LLM 数据填充
        """
        result = crawl_data.copy() if crawl_data else {}
        
        # 确保基本字段存在
        result.setdefault("name", competitor_name)
        result.setdefault("website", website)
        result.setdefault("features", {"core": [], "advanced": []})
        result.setdefault("pricing", {})
        result.setdefault("changelog", {
            "latest_version": None,
            "latest_release_date": None,
            "recent_updates": [],
            "update_frequency": None
        })
        result.setdefault("company_info", {})
        result.setdefault("target_users", [])
        result.setdefault("platforms", [])
        result.setdefault("crawled_pages", [])
        
        # 用 LLM 数据填充空白
        if not result["features"].get("core"):
            result["features"]["core"] = llm_data.get("features", {}).get("core", [])
        if not result["features"].get("advanced"):
            result["features"]["advanced"] = llm_data.get("features", {}).get("advanced", [])
        if not result["pricing"].get("model"):
            result["pricing"] = llm_data.get("pricing", {})
        # changelog 合并：爬虫有 changelog 且 recent_updates 非空则保留，否则用 LLM 填充
        cl = result.get("changelog", {})
        llm_cl = llm_data.get("changelog", {})
        if not cl.get("latest_version") and llm_cl.get("latest_version"):
            result["changelog"]["latest_version"] = llm_cl["latest_version"]
        if not cl.get("recent_updates") and llm_cl.get("recent_updates"):
            result["changelog"]["recent_updates"] = llm_cl["recent_updates"]
        if not cl.get("update_frequency") and llm_cl.get("update_frequency"):
            result["changelog"]["update_frequency"] = llm_cl["update_frequency"]
        if not cl.get("latest_release_date") and llm_cl.get("latest_release_date"):
            result["changelog"]["latest_release_date"] = llm_cl["latest_release_date"]
        if not result["company_info"].get("founded"):
            result["company_info"] = llm_data.get("company_info", {})
        if not result["target_users"]:
            result["target_users"] = llm_data.get("target_users", [])
        if not result["platforms"]:
            result["platforms"] = llm_data.get("platforms", [])
        
        result["_merged"] = True
        result["_source"] = "merged"
        return result

    # ------------------------------------------------------------------
    # 字段级 AI 填充（替换原 _merge_crawl_and_llm）
    # ------------------------------------------------------------------
    def _fill_blank_fields_with_llm(self, crawl_data: Dict, competitor_name: str, website: str) -> Dict[str, Any]:
        """
        字段级 AI 填充：平衡策略（v3）

        核心原则：区分"绝对不能猜"和"可以合理推断"的字段
        - features / pricing / changelog（核心对比字段）：如果官网爬取为空，用 AI 知识库补充，并标记来源
        - target_users / platforms（可从产品性质推断）：允许 AI 根据已爬取内容合理推断
        - company_info（客观事实）：不编造，仅尝试从已爬取内容提取
        """
        result = crawl_data.copy()
        filled = []

        # ---- 判断哪些字段需要 AI 补充 ----
        features = result.get("features", {}) or {}
        pricing = result.get("pricing", {}) or {}
        changelog = result.get("changelog", {}) or {}

        has_features = bool(features.get("core") or features.get("advanced"))
        has_pricing = bool(pricing.get("model") or pricing.get("plans"))
        has_changelog = bool(
            changelog.get("latest_version")
            or changelog.get("latest_release_date")
            or changelog.get("recent_updates")
            or changelog.get("update_frequency")
        )

        # 三个核心字段都有真实数据 → 只尝试推断辅助字段
        if has_features and has_pricing and has_changelog:
            result = self._infer_auxiliary_fields(result, competitor_name)
            return result

        # 需要填充的核心字段
        need_fill = []
        if not has_features:
            need_fill.append("features")
        if not has_pricing:
            need_fill.append("pricing")
        if not has_changelog:
            need_fill.append("changelog")

        logger.info(f"Crawler: {competitor_name} 核心字段 {need_fill} 为空，调用 LLM 补充")

        try:
            llm_data = self._llm_fallback_collect(competitor_name, website)
        except Exception as e:
            logger.warning(f"Crawler: LLM 填充失败，保留原始爬取数据: {e}")
            result["_llm_filled_fields"] = []
            return result

        # 只填充核心字段
        if "features" in need_fill:
            llm_feat = llm_data.get("features", {}) or {}
            if not (result.get("features") or {}).get("core") and llm_feat.get("core"):
                if not result.get("features"):
                    result["features"] = {}
                result["features"]["core"] = llm_feat["core"]
                result["features"]["_core_source"] = "llm"
                filled.append("features.core")
            if not (result.get("features") or {}).get("advanced") and llm_feat.get("advanced"):
                if not result.get("features"):
                    result["features"] = {}
                result["features"]["advanced"] = llm_feat["advanced"]
                result["features"]["_advanced_source"] = "llm"
                filled.append("features.advanced")

        if "pricing" in need_fill:
            llm_price = llm_data.get("pricing", {}) or {}
            if not (result.get("pricing") or {}).get("model") and llm_price.get("model"):
                if not result.get("pricing"):
                    result["pricing"] = {}
                result["pricing"]["model"] = llm_price["model"]
                result["pricing"]["plans"] = llm_price.get("plans", [])
                result["_pricing_source"] = "llm"
                filled.append("pricing")

        if "changelog" in need_fill:
            llm_cl = llm_data.get("changelog", {}) or {}
            if not result.get("changelog"):
                result["changelog"] = {}
            if not changelog.get("latest_version") and llm_cl.get("latest_version"):
                result["changelog"]["latest_version"] = llm_cl["latest_version"]
                result["changelog"]["_latest_version_source"] = "llm"
                filled.append("changelog.latest_version")
            if not changelog.get("latest_release_date") and llm_cl.get("latest_release_date"):
                result["changelog"]["latest_release_date"] = llm_cl["latest_release_date"]
                result["changelog"]["_latest_release_date_source"] = "llm"
                filled.append("changelog.latest_release_date")
            if not changelog.get("recent_updates") and llm_cl.get("recent_updates"):
                result["changelog"]["recent_updates"] = llm_cl["recent_updates"]
                result["changelog"]["_recent_updates_source"] = "llm"
                filled.append("changelog.recent_updates")
            if not changelog.get("update_frequency") and llm_cl.get("update_frequency"):
                result["changelog"]["update_frequency"] = llm_cl["update_frequency"]
                result["changelog"]["_update_frequency_source"] = "llm"
                filled.append("changelog.update_frequency")
            if any(k.startswith("changelog.") for k in filled):
                result["changelog"]["_source"] = "llm"

        # 同时也尝试推断辅助字段
        result = self._infer_auxiliary_fields(result, competitor_name, llm_data)

        result["_llm_filled_fields"] = filled
        logger.info(f"Crawler: {competitor_name} AI 填充了 {filled}")
        return result

    def _infer_auxiliary_fields(self, data: Dict, competitor_name: str, llm_data: Dict = None) -> Dict:
        """
        智能推断辅助字段（target_users, platforms）。
        
        策略：
        1. 如果 features 中有内容描述，可以让 LLM 从中推断 target_users 和 platforms
        2. 如果 llm_data（AI 兜底数据）中有这些字段，且看起来合理，可以使用
        3. changelog 在 _fill_blank_fields_with_llm 中处理，不在此推断
        4. 不推断 company_info（客观事实，必须来自官网）
        """
        result = data.copy()
        inferred = []

        features_text = ""
        features = result.get("features", {}) or {}
        if features.get("core"):
            features_text = "核心功能: " + "; ".join(features["core"][:5])
        if features.get("advanced"):
            features_text += "\n高级功能: " + "; ".join(features["advanced"][:5])

        # 如果没有任何特征文本，无法推断
        if not features_text.strip():
            return result

        # 用轻量级 LLM 调用推断辅助字段
        try:
            prompt = ChatPromptTemplate.from_messages([
                ("system", """你是一位产品分析师。根据产品的功能描述，合理推断以下信息。

【重要规则】
1. 只根据给出的功能描述做合理推断，不要凭空编造
2. target_users：从这个产品的功能来看，它适合什么人群使用？（给出 2-4 个具体群体）
3. platforms：这类产品通常支持哪些平台？（Web/Windows/macOS/Linux/iOS/Android 等）
4. 输出 JSON 格式，不要其他内容

输出格式：
{{
    "target_users": ["用户群体1", "用户群体2"],
    "platforms": ["平台1", "平台2"]
}}"""),
                ("user", f"产品名称: {competitor_name}\n{features_text}")
            ])

            chain = prompt | self.llm
            response = chain.invoke({"competitor_name": competitor_name})
            inferred_data = safe_extract_json(response.content)

            if inferred_data and isinstance(inferred_data, dict):
                # 填充 target_users
                if not result.get("target_users") and inferred_data.get("target_users"):
                    result["target_users"] = inferred_data["target_users"]
                    result["_target_users_source"] = "inferred"
                    inferred.append("target_users")

                # 填充 platforms
                if not result.get("platforms") and inferred_data.get("platforms"):
                    result["platforms"] = inferred_data["platforms"]
                    result["_platforms_source"] = "inferred"
                    inferred.append("platforms")

                if inferred:
                    logger.info(f"[Infer] {competitor_name} 智能推断出: {inferred}")

        except Exception as e:
            logger.debug(f"[Infer] {competitor_name} 推断失败: {e}")

        # 标记仍不可用的字段
        unavailable = []
        changelog = result.get("changelog") or {}
        if not changelog.get("latest_version") and not changelog.get("recent_updates"):
            unavailable.append("changelog")
        company_info = result.get("company_info") or {}
        if not company_info.get("founded"):
            unavailable.append("company_info")

        if unavailable:
            result["_unavailable_fields"] = unavailable

        return result
    

# 测试代码
if __name__ == "__main__":
    # 测试Data Collection Agent
    import sys
    from pathlib import Path
    
    # 添加项目根目录到Python路径
    project_root = Path(__file__).parent.parent
    sys.path.insert(0, str(project_root))
    
    # 加载环境变量
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    
    # 测试1: 使用Playwright爬取（复用浏览器实例）
    print("测试1: 使用Playwright爬取Notion（优化版）...")
    crawler = DataCollectionAgent(use_playwright=True)
    
    data = crawler.collect("Notion")
    
    print("\n采集结果:")
    print(json.dumps(data, indent=2, ensure_ascii=False))
    
    # 测试2: 不使用Playwright（并发爬取）
    print("\n" + "="*60)
    print("测试2: 不使用Playwright（并发爬取）...")
    
    crawler_no_pw = DataCollectionAgent(use_playwright=False)
    data2 = crawler_no_pw.collect("Obsidian")
    
    print("\n采集结果:")
    print(json.dumps(data2, indent=2, ensure_ascii=False))
