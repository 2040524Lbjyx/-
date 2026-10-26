"""
Coordinator Agent - 协调者Agent
负责理解用户意图、制定分析计划、调度其他Agent
"""

from typing import TypedDict, List, Dict, Optional, Any
from enum import Enum
import json
import os
import logging
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import StateGraph, END

# 使用统一的环境变量加载器
from utils.env_loader import load_env, get_env, get_env_required
from utils.llm_parser import safe_extract_json
from utils.runtime_health import should_block_report

# 加载 .env 环境变量
load_env()

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class AgentStatus(str, Enum):
    """Agent执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkflowState(TypedDict):
    """LangGraph工作流状态"""
    
    # 用户输入
    user_query: str
    competitors: List[str]
    confirmed_competitors: List[str]
    dimensions: List[str]
    
    # 执行计划
    plan: List[Dict]
    current_step: int
    
    # Agent执行状态
    crawler_status: AgentStatus
    analyzer_status: AgentStatus
    reporter_status: AgentStatus
    
    # 数据传递
    crawled_data: Optional[Dict]
    analysis_results: Optional[Dict]
    report_path: Optional[str]
    
    # 错误处理
    errors: List[str]
    fatal_error: bool
    retry_count: int  # 保留用于向后兼容
    crawler_retry_count: int  # Crawler 独立重试计数
    analyzer_retry_count: int  # Analyzer 独立重试计数
    reporter_retry_count: int  # Reporter 独立重试计数
    
    # 配置
    output_format: str
    verbose: bool


class CoordinatorAgent:
    """协调者Agent"""
    
    def __init__(self, model: str = None, temperature: float = None):
        """
        初始化Coordinator Agent
        
        Args:
            model: LLM模型名称（默认从 OPENAI_MODEL 环境变量读取）
            temperature: 温度参数（默认从 OPENAI_TEMPERATURE 环境变量读取）
        """
        # 从环境变量读取配置，支持 DeepSeek / OpenAI 等 OpenAI 兼容接口
        api_key = get_env("OPENAI_API_KEY")
        base_url = get_env("OPENAI_BASE_URL")   # DeepSeek 填 https://api.deepseek.com
        model = model or get_env("OPENAI_MODEL", "deepseek-chat")  # DeepSeek 默认模型
        temperature = temperature if temperature is not None else float(get_env("OPENAI_TEMPERATURE", "0.7"))

        if not api_key:
            raise ValueError(
                "未找到 OPENAI_API_KEY，请在 .env 文件中配置 API Key"
            )

        self.llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=api_key,
            base_url=base_url or None,   # None 时使用 OpenAI 官方地址
            request_timeout=60,  # 🔧 修复问题7：添加超时配置（60秒）
            max_retries=2  # 🔧 修复问题7：添加重试配置
        )
        self.workflow = self._create_workflow()
    
    def _report(self, progress: int, message: str):
        """报告进度（内部辅助方法）"""
        if hasattr(self, '_callback') and self._callback:
            try:
                self._callback(progress, message)
            except Exception as e:
                logger.warning(f"进度回调失败: {e}")
    
    def _log(self, message: str):
        """记录详细日志（同时输出到 logger 和 log_callback）"""
        logger.info(message)
        if hasattr(self, '_log_callback') and self._log_callback:
            try:
                self._log_callback(message)
            except Exception as e:
                logger.warning(f"日志回调失败: {e}")
    
    def _create_workflow(self) -> StateGraph:
        """创建LangGraph工作流"""
        
        workflow = StateGraph(WorkflowState)
        
        # 添加节点
        workflow.add_node("understand_intent", self._understand_intent)
        workflow.add_node("create_plan", self._create_plan)
        workflow.add_node("crawler", self._run_crawler)
        workflow.add_node("analyzer", self._run_analyzer)
        workflow.add_node("reporter", self._run_reporter)
        workflow.add_node("handle_error", self._handle_error)
        
        # 设置入口点
        workflow.set_entry_point("understand_intent")
        
        # 添加边
        workflow.add_edge("understand_intent", "create_plan")
        workflow.add_edge("create_plan", "crawler")
        
        # 条件边: Crawler完成后根据状态决定下一步
        workflow.add_conditional_edges(
            "crawler",
            self._should_continue,
            {
                "continue": "analyzer",
                "retry": "crawler",
                "error": "handle_error"
            }
        )
        
        # Analyzer完成后根据状态决定
        workflow.add_conditional_edges(
            "analyzer",
            self._should_continue,
            {
                "continue": "reporter",
                "retry": "analyzer",
                "error": "handle_error"
            }
        )
        
        # Reporter 也必须通过状态判定，否则其失败时重试逻辑永远不可达。
        workflow.add_conditional_edges(
            "reporter",
            self._should_continue,
            {
                "continue": END,
                "retry": "reporter",
                "error": "handle_error"
            }
        )
        workflow.add_edge("handle_error", END)
        
        return workflow.compile()
    
    def _understand_intent(self, state: WorkflowState) -> WorkflowState:
        """
        理解用户意图
        
        从用户的自然语言输入中提取：
        1. 要分析的竞品名称
        2. 分析维度（功能、定价等）
        3. 输出格式
        """
        
        self._report(12, f"🔍 理解用户意图：{state['user_query'][:30]}...")
        
        self._log(f"[Coordinator] 理解用户意图: {state['user_query']}")
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一位竞品分析专家。请从用户的输入中提取以下信息：

1. 竞品名称列表
2. 分析维度 (features/pricing/changelog/app_feedback/copy_changes)
3. 输出格式 (markdown/html)

输出JSON格式：
{{
    "competitors": ["竞品1", "竞品2"],
    "dimensions": ["features", "pricing"],
    "output_format": "markdown"
}}

只输出JSON，不要有其他内容。"""),
            ("user", "{user_query}")
        ])
        
        try:
            chain = prompt | self.llm
            self._log("[Coordinator] 调用 LLM 提取竞品信息...")
            response = chain.invoke({"user_query": state["user_query"]})
            
            # 解析JSON（使用安全的解析函数）
            result = safe_extract_json(response.content, verbose=True)
            
            # 更新状态
            state["competitors"] = state.get("confirmed_competitors") or [
                str(name).strip() for name in (result.get("competitors", []) or [])
                if str(name).strip()
            ]
            if not state["competitors"]:
                state["competitors"] = self._extract_competitors_fallback(state["user_query"])
            raw_dimensions = result.get("dimensions", ["features", "pricing"])
            if isinstance(raw_dimensions, str):
                raw_dimensions = [raw_dimensions]
            if "both" in raw_dimensions:
                raw_dimensions = ["features", "pricing"]
            allowed_dimensions = {
                "features", "pricing", "changelog", "app_feedback", "copy_changes"
            }
            state["dimensions"] = [
                dimension for dimension in raw_dimensions
                if dimension in allowed_dimensions
            ] or ["features", "pricing"]
            
            self._log(f"[Coordinator] 提取到竞品: {state['competitors']}")
            self._log(f"[Coordinator] 分析维度: {state['dimensions']}")
            
            self._report(20, f"✅ 识别到 {len(state['competitors'])} 个竞品：{', '.join(state['competitors'])}")
            
        except Exception as e:
            fallback_competitors = state.get("confirmed_competitors") or self._extract_competitors_fallback(state["user_query"])
            # 网络/模型临时故障不等于任务失败：能从查询稳定提取竞品时继续执行。
            self._log(f"[Coordinator] ⚠️ 意图理解 LLM 不可用: {e}，使用本地规则提取")
            state["competitors"] = fallback_competitors
            state["dimensions"] = ["features", "pricing"]
            if fallback_competitors:
                self._report(20, f"⚠️ 已使用本地规则识别竞品：{', '.join(fallback_competitors)}")
            else:
                state["errors"].append(f"意图理解失败且未识别到竞品: {str(e)}")
                self._report(20, "❌ 未能从查询中识别竞品，请检查输入")
        
        return state
    
    def _extract_competitors_fallback(self, query: str) -> List[str]:
        """LLM 不可用时，使用与演示模式一致的本地解析。"""
        from utils.query_parser import extract_competitors
        return extract_competitors(query)

    def _create_plan(self, state: WorkflowState) -> WorkflowState:
        """
        制定分析计划
        
        根据用户输入生成详细的执行计划
        """
        
        self._log("[Coordinator] 制定分析计划")
        
        plan = []
        
        # 为每个竞品创建爬取任务
        for competitor in state["competitors"]:
            plan.append({
                "agent": "crawler",
                "action": "collect",
                "target": competitor,
                "status": AgentStatus.PENDING
            })
        
        # 添加分析任务
        plan.append({
            "agent": "analyzer",
            "action": "analyze",
            "target": "all",
            "status": AgentStatus.PENDING
        })
        
        # 添加报告生成任务
        plan.append({
            "agent": "reporter",
            "action": "generate",
            "target": "all",
            "status": AgentStatus.PENDING
        })
        
        state["plan"] = plan
        state["current_step"] = 0
        
        self._report(25, f"📋 制定分析计划：{len(state['competitors'])} 个竞品，3 个分析阶段")
        
        self._log(f"[Coordinator] 分析计划: {len(plan)} 个步骤")
        for i, step in enumerate(plan, 1):
            self._log(f"  步骤 {i}: {step['agent']}.{step['action']}({step['target']})")
        
        return state
    
    def _run_crawler(self, state: WorkflowState) -> WorkflowState:
        """运行Crawler Agent（并行采集多个竞品）"""

        self._log("[Coordinator] ========== 调用 Crawler Agent（并行模式） ==========")

        state["crawler_status"] = AgentStatus.RUNNING

        n_competitors = max(len(state["competitors"]), 1)
        self._report(30, f"🕷️ 开始并行爬取 {n_competitors} 个竞品数据...")

        try:
            # 导入Crawler Agent
            from agents.crawler import DataCollectionAgent

            self._log("[Crawler] 初始化 DataCollectionAgent...")
            crawler = DataCollectionAgent()

            # 向量库以"轻量模式"懒加载：优先 ChromaDB 内置 embedding（零外部模型下载），
            # 避免此前因下载 79MB 模型导致流程卡死；初始化失败则降级为 None，不影响主流程。
            vector_store = self._init_vector_store()
            self._vector_store = vector_store

            # 并发度：优先用 run() 传入的 _max_workers，否则自适应 2-4
            max_workers = getattr(self, "_max_workers", min(4, max(2, n_competitors)))
            self._log(f"[Crawler] 并发度 = {max_workers}（来自 UI 配置）")

            # ========== 进度回调：把单竞品的 start/done/failed 映射到 UI 进度条 ==========
            # 总进度区间 30% -> 50%，每个竞品占 20/max(n,1) 个百分点
            base_progress = 30
            span = 20  # 占 20% 总进度
            per_competitor_span = span / max(n_competitors, 1)

            def _on_progress(index: int, total: int, name: str,
                             status: str, payload: Any):
                if status == "start":
                    self._log(
                        f"[Crawler] [并行 {index}/{total}] 开始爬取: {name}"
                    )
                    self._report(
                        int(base_progress + per_competitor_span * (index - 1)),
                        f"🕷️ 正在爬取：{name} ({index}/{total})"
                    )
                elif status == "done":
                    data = payload or {}
                    features = data.get("features", {})
                    n_core = len(features.get("core", []))
                    n_advanced = len(features.get("advanced", []))
                    n_pricing = len(data.get("pricing", {}))
                    is_degraded = data.get("_source") in {"crawl_partial", "llm_fallback"} or not (n_core or n_advanced)
                    marker = "⚠️" if is_degraded else "✅"
                    self._log(
                        f"[Crawler] [并行 {index}/{total}] {marker} {name} 爬取完成: "
                        f"核心功能 {n_core} 项, 高级功能 {n_advanced} 项, 定价 {n_pricing} 项"
                    )
                    self._report(
                        int(base_progress + per_competitor_span * index),
                        f"{marker} 已完成：{name} ({index}/{total})"
                    )
                elif status == "failed":
                    err = payload
                    self._log(
                        f"[Crawler] [并行 {index}/{total}] ❌ {name} 失败: {err}"
                    )
                    self._report(
                        int(base_progress + per_competitor_span * index),
                        f"❌ {name} 爬取失败 ({index}/{total})"
                    )

            # ========== 并行采集（替代原 for 循环） ==========
            self._log(f"[Crawler] 调用 collect_many 并行采集 {n_competitors} 个竞品")
            crawled_data = crawler.collect_many(
                state["competitors"],
                max_workers=max_workers,
                progress_callback=_on_progress,
            )

            # ========== 向量库存储串行做（DB 写不抢并发） ==========
            for competitor, data in crawled_data.items():
                if data.get("_error"):
                    # 采集失败的跳过落库，便于后续追溯
                    self._log(
                        f"[Crawler] 跳过向量库存储（采集失败）: {competitor}"
                    )
                    continue
                if vector_store is None:
                    self._log(f"[Crawler] 跳过向量库存储（未初始化）: {competitor}")
                    continue
                try:
                    doc_id = vector_store.add_competitor(data)
                    self._log(
                        f"[Crawler] 已存储到向量数据库: {competitor} (ID: {doc_id})"
                    )
                except Exception as ve:
                    self._log(
                        f"[Crawler] ⚠️ 存储到向量数据库失败: {competitor} -> {ve}"
                    )

            # 统计成功/失败
            fail = sum(1 for v in crawled_data.values() if v.get("_error"))
            degraded = sum(
                1 for value in crawled_data.values()
                if not value.get("_error") and (
                    value.get("_source") in {"crawl_partial", "llm_fallback"}
                    or not any((value.get("features") or {}).get(key) for key in ("core", "advanced"))
                )
            )
            ok = n_competitors - fail - degraded
            state["crawled_data"] = crawled_data
            state["crawler_status"] = AgentStatus.COMPLETED
            if fail:
                failed_names = [
                    name for name, value in crawled_data.items()
                    if value.get("_error")
                ]
                state["errors"].append(
                    f"部分竞品采集失败 ({fail}/{n_competitors}): "
                    + ", ".join(failed_names)
                )
            msg = f"✅ 爬取完成：有效 {ok}，降级 {degraded}，失败 {fail}"
            if fail:
                msg += f"，失败 {fail}"
            self._report(50, msg)
            self._log(
                f"[Coordinator] ✅ Crawler Agent 完成，有效 {ok}，降级 {degraded}，失败 {fail}"
            )

        except Exception as e:
            self._log(f"[Coordinator] ❌ Crawler Agent 失败: {e}")
            state["crawler_status"] = AgentStatus.FAILED
            state["errors"].append(f"Crawler失败: {str(e)}")
            state["crawler_retry_count"] += 1  # 🔧 修复问题1：使用独立计数器
            self._report(50, f"❌ 爬取失败：{str(e)[:50]}")

        return state
    
    def _init_vector_store(self):
        """懒加载向量库（RAG 检索上下文来源）。

        使用 force_lightweight=True：优先 ChromaDB 内置轻量 embedding（零外部模型下载），
        避免此前因下载 79MB ONNX/SentenceTransformer 模型导致流程卡死的问题。
        任何初始化异常都会被捕获，向量库降级为 None，不影响主流程。
        """
        try:
            from vector_store import CompetitorVectorStore
            vs = CompetitorVectorStore(force_lightweight=True, init_timeout=15)
            self._log("[Crawler] ✅ 向量数据库已初始化（轻量模式，零模型下载）")
            return vs
        except Exception as e:
            self._log(
                f"[Crawler] ⚠️ 向量数据库初始化失败，已降级（RAG 检索不可用）: {e}"
            )
            return None

    def _build_rag_context(self, valid_data: Dict[str, Dict],
                            exclude_names: set = None) -> str:
        """检索向量库中相似的既往竞品数据，构建注入分析 Prompt 的参考上下文。

        向量库存储的是竞品结构化画像（功能/定价等），与"检索历史结论作为上下文"
        的意图一致：相似竞品的既有画像可作为分析参考，避免重复已知事实、辅助纠正偏差。
        无向量库或检索失败时返回空串（不影响原逻辑）。

        🔧 修复问题D：排除"本轮对比对象"（默认即 valid_data 的 key），避免把
        本轮另一个竞品的数据当成"历史相似竞品"注入，造成跨产品互相污染。
        """
        vs = getattr(self, "_vector_store", None)
        if vs is None:
            return ""

        # 需要排除的竞品名：显式传入优先，否则默认排除本轮所有对比对象
        exclude = set(exclude_names) if exclude_names else set(valid_data.keys())

        sections = []
        try:
            for comp_name, comp_data in valid_data.items():
                feats = comp_data.get("features", {}) or {}
                query = comp_name
                core = feats.get("core", []) or []
                if core:
                    query += " " + " ".join(core[:5])
                results = vs.search_similar(query, n_results=3)
                refs = []
                for r in results:
                    meta = r.get("metadata", {}) or {}
                    name = meta.get("name", "")
                    # 🔧 同时排除本轮对比对象与同名竞品
                    if name and name != comp_name and name not in exclude:
                        doc = (r.get("document", "") or "")[:200]
                        refs.append(f"- {name}：{doc}")
                if refs:
                    sections.append(
                        f"关于「{comp_name}」的相似竞品参考：\n" + "\n".join(refs)
                    )
        except Exception as e:
            self._log(f"[Analyzer] ⚠️ RAG 检索失败，跳过上下文注入: {e}")
            return ""

        if not sections:
            return ""
        return "\n\n".join(sections)

    def _run_analyzer(self, state: WorkflowState) -> WorkflowState:
        """运行Analysis Agent"""
        
        self._log("[Coordinator] ========== 调用 Analysis Agent ==========")
        
        state["analyzer_status"] = AgentStatus.RUNNING
        
        self._report(55, "🧠 开始分析竞品数据...")
        
        try:
            # 导入Analysis Agent
            from agents.analyzer import AnalysisAgent
            
            self._log("[Analyzer] 初始化 AnalysisAgent...")
            analyzer = AnalysisAgent()
            
            # 分析爬取的数据
            crawled_data = state["crawled_data"]
            
            # 🔧 修复问题3：过滤掉失败的数据（包含 _error 字段）
            valid_data = {
                name: data for name, data in crawled_data.items()
                if not data.get("_error")  # 只保留成功爬取的数据
            }
            
            if not valid_data:
                self._log("[Analyzer] ⚠️ 所有竞品数据爬取失败，无法进行分析")
                state["analyzer_status"] = AgentStatus.FAILED
                state["errors"].append("所有竞品数据爬取失败，无法进行分析")
                return state
            
            self._log(f"[Analyzer] 过滤后有效数据: {len(valid_data)}/{len(crawled_data)} 个竞品")

            # 轻量真实性闸门：在现有 Analyzer 内检测，不新增 Agent。
            quality_report = analyzer.assess_data_quality(valid_data)
            quality_summary = quality_report.get("summary", {})
            self._log(
                "[Analyzer] 数据质量检测: "
                f"通过 {quality_summary.get('passed', 0)}，"
                f"降级 {quality_summary.get('degraded', 0)}，"
                f"失败 {quality_summary.get('failed', 0)}，"
                f"平均分 {quality_summary.get('average_score', 0)}"
            )
            if quality_summary.get("status") != "passed":
                self._log(
                    "[Analyzer] ⚠️ 数据质量闸门未完全通过："
                    f"{quality_summary.get('degraded', 0)} 个降级，"
                    f"{quality_summary.get('failed', 0)} 个失败；报告已标注推测内容"
                )

            # 🆕 RAG：检索向量库中相似竞品作为分析参考上下文，注入各分析 Agent 的 Prompt
            rag_context = self._build_rag_context(valid_data)
            if rag_context:
                self._log(f"[Analyzer] 注入 RAG 上下文（{len(rag_context)} 字符）")
            
            dimensions = set(state.get("dimensions") or ["features", "pricing"])
            feature_matrix = None
            pricing_analysis = {}

            if "features" in dimensions:
                self._log("[Analyzer] 开始功能对比...")
                self._report(60, "🧠 正在对比功能矩阵...")
                feature_matrix = analyzer.compare_features(valid_data, rag_context=rag_context)
                self._log(f"[Analyzer] 功能对比完成: {len(feature_matrix)} 个功能维度")

            if "pricing" in dimensions:
                self._log("[Analyzer] 开始定价分析...")
                self._report(68, "💰 正在分析定价策略...")
                pricing_analysis = analyzer.analyze_pricing(valid_data, rag_context=rag_context)
                self._log(f"[Analyzer] 定价分析完成: {len(pricing_analysis)} 个分析项")

            feature_metadata = {
                "source": feature_matrix.attrs.get("source", "unknown") if feature_matrix is not None else "not_requested",
                "confidence": feature_matrix.attrs.get("confidence", "unknown") if feature_matrix is not None else "unknown",
                "warning": feature_matrix.attrs.get("warning", "") if feature_matrix is not None else "",
            }
            analysis_metadata = {
                "feature_matrix": feature_metadata,
                "pricing": {
                    "source": pricing_analysis.get("_source", "unknown") if isinstance(pricing_analysis, dict) else "unknown",
                    "confidence": pricing_analysis.get("_confidence", "unknown") if isinstance(pricing_analysis, dict) else "unknown",
                    "warning": pricing_analysis.get("_warning", "") if isinstance(pricing_analysis, dict) else "",
                },
            }
            if feature_metadata["source"] == "llm_fallback":
                self._log("[Analyzer] ⚠️ 官网功能证据为空，功能矩阵已降级为 LLM 推测")
            
            # 生成洞察
            self._log("[Analyzer] 开始生成 AI 洞察...")
            self._report(74, "💡 正在生成AI洞察...")
            insights = analyzer.generate_insights(
                feature_matrix, pricing_analysis,
                competitor_names=list(valid_data.keys()),  # 只传递有效竞品名称
                rag_context=rag_context,
            )
            self._log(f"[Analyzer] 洞察生成完成: {len(insights)} 条")

            # Changelog 分析（只使用有效数据）。即使用户只选择功能/定价，
            # 只要爬虫已经拿到 App Store 或 GitHub 版本信息，也自动做一次
            # 低成本结构化合并，避免报告出现“有来源但无 Changelog”。
            self._log("[Analyzer] 开始 Changelog 分析...")
            self._report(76, "📋 正在分析版本更新...")
            has_changelog_source = any(
                bool((data.get("changelog") or {}).get("latest_version")
                     or (data.get("changelog") or {}).get("recent_updates")
                     or (data.get("app_store") or {}).get("version")
                     or (data.get("app_store") or {}).get("release_notes")
                     or (data.get("github_releases") or {}).get("releases"))
                for data in valid_data.values()
            )
            changelog_analysis = (
                analyzer.analyze_changelog(valid_data)
                if "changelog" in dimensions or has_changelog_source else {}
            )
            self._log(f"[Analyzer] Changelog 分析完成: {len(changelog_analysis)} 个竞品")

            # 用户反馈分析（App Store 评分/评论）
            self._log("[Analyzer] 开始用户反馈分析...")
            self._report(78, "⭐ 正在分析用户反馈（评分/评论）...")
            has_feedback_source = any(
                bool((data.get("app_store") or {}).get("rating") is not None
                     or (data.get("app_store") or {}).get("reviews"))
                for data in valid_data.values()
            )
            app_feedback_analysis = (
                analyzer.analyze_app_feedback(valid_data)
                if "app_feedback" in dimensions or has_feedback_source else {}
            )

            # 官网文案变化分析（快照 diff）
            self._log("[Analyzer] 开始官网文案变化分析...")
            self._report(80, "✍️ 正在分析官网文案变化...")
            has_copy_snapshot = any(
                bool(data.get("copy_snapshots")) for data in valid_data.values()
            )
            copy_changes_analysis = (
                analyzer.analyze_copy_changes(valid_data)
                if "copy_changes" in dimensions or has_copy_snapshot else {}
            )

            # 质量门禁：如果抓取没有产生任何可验证字段，且功能/定价都退化为
            # LLM 兜底，停止工作流，避免生成一份看似完整的错误报告。
            if should_block_report(quality_report, analysis_metadata):
                message = (
                    "ANALYSIS_NOT_ACTIONABLE: 未获得任何可验证的功能、定价或版本字段；"
                    "当前结果只能作为推测，已停止生成正式报告。请检查网络/API连接后重试。"
                )
                self._log(f"[Analyzer] ❌ {message}")
                state["errors"].append(message)
                state["analyzer_status"] = AgentStatus.FAILED
                return state

            state["analysis_results"] = {
                "feature_matrix": feature_matrix,
                "pricing_analysis": pricing_analysis,
                "changelog_analysis": changelog_analysis,
                "app_feedback_analysis": app_feedback_analysis,
                "copy_changes_analysis": copy_changes_analysis,
                "insights": insights,
                "quality_report": quality_report,
                "analysis_metadata": analysis_metadata,
            }
            
            state["analyzer_status"] = AgentStatus.COMPLETED
            
            self._report(78, f"✅ 分析完成：{len(insights)} 条洞察已生成")
            self._log("[Coordinator] ✅ Analysis Agent 完成")
        
        except Exception as e:
            self._log(f"[Coordinator] ❌ Analysis Agent 失败: {e}")
            state["analyzer_status"] = AgentStatus.FAILED
            state["errors"].append(f"Analysis失败: {str(e)}")
            state["analyzer_retry_count"] += 1  # 🔧 修复问题1：使用独立计数器
            self._report(78, f"❌ 分析失败：{str(e)[:50]}")
        
        return state
    
    def _run_reporter(self, state: WorkflowState) -> WorkflowState:
        """运行Report Agent"""
        
        self._log("[Coordinator] ========== 调用 Report Agent ==========")
        
        state["reporter_status"] = AgentStatus.RUNNING
        
        self._report(82, "📝 正在生成分析报告...")
        
        try:
            # 导入Report Agent
            from agents.reporter import ReportAgent
            
            self._log("[Reporter] 初始化 ReportAgent...")
            reporter = ReportAgent()
            
            # 🔧 修复问题8：只传递实际可用的竞品（从 analysis_results 中提取）
            analysis_results = state["analysis_results"]
            if analysis_results and analysis_results.get("feature_matrix") is not None:
                # 从 feature_matrix 的列中提取实际可用的竞品
                import pandas as pd
                feature_matrix = analysis_results["feature_matrix"]
                if isinstance(feature_matrix, pd.DataFrame):
                    available_competitors = [
                        column for column in feature_matrix.columns.tolist()
                        if column not in {"功能", "feature", "Feature"}
                    ]
                else:
                    available_competitors = list(state["competitors"])
            else:
                # 没有功能矩阵时（例如仅定价分析），使用成功采集的竞品。
                available_competitors = [
                    name for name, value in (state.get("crawled_data") or {}).items()
                    if not value.get("_error")
                ]
            
            self._log(f"[Reporter] 传递竞品列表: {available_competitors} (过滤自 {len(state['competitors'])} 个)")
            
            # 生成报告
            self._log(f"[Reporter] 生成 {state['output_format']} 格式报告...")
            report_path = reporter.generate(
                analysis_results=analysis_results,
                competitors=available_competitors,  # 🔧 只传递实际可用的竞品
                output_format=state["output_format"]
            )
            
            state["report_path"] = report_path
            state["reporter_status"] = AgentStatus.COMPLETED
            
            report_name = report_path.split('/')[-1] if '/' in report_path else report_path.split('\\')[-1]
            self._report(95, f"📄 报告已生成：{report_name}")
            self._log(f"[Coordinator] ✅ Report Agent 完成: {report_path}")
        
        except Exception as e:
            logger.error(f"Report Agent 失败: {e}")
            state["reporter_status"] = AgentStatus.FAILED
            state["errors"].append(f"Report失败: {str(e)}")
            state["reporter_retry_count"] += 1  # 🔧 修复问题1：使用独立计数器
            self._report(95, f"❌ 报告生成失败：{str(e)[:50]}")
        
        return state
    
    def _handle_error(self, state: WorkflowState) -> WorkflowState:
        """处理错误"""
        
        logger.error(f"Coordinator: 处理错误 - {state['errors']}")
        
        # 生成错误报告
        error_report = f"""# 竞品分析报告（失败）

## 错误信息

{chr(10).join(state['errors'])}

## 建议

1. 检查网络连接
2. 验证OpenAI API Key
3. 查看日志文件获取详细信息
"""
        
        # 保存错误报告
        import os
        os.makedirs("./reports", exist_ok=True)
        
        error_path = "./reports/error_report.md"
        with open(error_path, "w", encoding="utf-8") as f:
            f.write(error_report)
        
        state["report_path"] = error_path
        state["fatal_error"] = True
        
        return state
    
    def _should_continue(self, state: WorkflowState) -> str:
        """
        决定是否继续、重试或报错
        
        🔧 修复问题1：使用每个Agent独立的重试计数器
        🔧 修复问题9：检查所有Agent的状态（包括Reporter）
        
        Returns:
            "continue": 继续下一步
            "retry": 重试当前步骤
            "error": 进入错误处理
        """
        
        # 检查Crawler状态（使用独立的 crawler_retry_count）
        if state["crawler_status"] == AgentStatus.FAILED:
            if state["crawler_retry_count"] < 3:
                self._log(f"[Coordinator] Crawler 失败，准备重试 ({state['crawler_retry_count'] + 1}/3)")
                return "retry"
            else:
                self._log("[Coordinator] Crawler 失败次数已达上限，进入错误处理")
                return "error"

        # 检查Analyzer状态（使用独立的 analyzer_retry_count）
        if state["analyzer_status"] == AgentStatus.FAILED:
            if any(str(error).startswith("ANALYSIS_NOT_ACTIONABLE:") for error in state.get("errors", [])):
                self._log("[Coordinator] 分析缺少可验证证据，不重试生成报告")
                return "error"
            if state["analyzer_retry_count"] < 3:
                self._log(f"[Coordinator] Analyzer 失败，准备重试 ({state['analyzer_retry_count'] + 1}/3)")
                return "retry"
            else:
                self._log("[Coordinator] Analyzer 失败次数已达上限，进入错误处理")
                return "error"
        
        # 🔧 修复问题9：检查Reporter状态（使用独立的 reporter_retry_count）
        if state["reporter_status"] == AgentStatus.FAILED:
            if state["reporter_retry_count"] < 3:
                self._log(f"[Coordinator] Reporter 失败，准备重试 ({state['reporter_retry_count'] + 1}/3)")
                return "retry"
            else:
                self._log("[Coordinator] Reporter 失败次数已达上限，进入错误处理")
                return "error"
        
        return "continue"
    
    def run(self, user_query: str, output_format: str = "markdown",
            verbose: bool = False, callback: Any = None,
            log_callback: Any = None, max_workers: int = 3,
            confirmed_competitors: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        运行竞品分析

        Args:
            user_query: 用户输入
            output_format: 输出格式 (markdown/html)
            verbose: 是否显示详细日志
            callback: 进度回调函数，接收 (progress: int, message: str) 参数
            log_callback: 日志回调函数，接收 (message: str) 参数，用于显示详细执行日志
            max_workers: 并行爬取的最大并发数（默认 3，建议 1-4）
            confirmed_competitors: 用户已确认的竞品，优先于模型解析，保留含空格的名称

        Returns:
            包含分析结果的字典
        """

        # 🔧 修复问题15：输入验证
        if not user_query or not user_query.strip():
            raise ValueError("用户输入不能为空")
        
        if output_format not in ["markdown", "html"]:
            raise ValueError(f"不支持的输出格式: {output_format}，仅支持 'markdown' 和 'html'")

        if confirmed_competitors is not None:
            if (not isinstance(confirmed_competitors, list)
                    or not 2 <= len(confirmed_competitors) <= 5
                    or any(not isinstance(name, str) or not name.strip() for name in confirmed_competitors)):
                raise ValueError("请确认 2～5 个有效竞品。")
            confirmed_competitors = [name.strip() for name in confirmed_competitors]
            if len({name.casefold() for name in confirmed_competitors}) != len(confirmed_competitors):
                raise ValueError("确认的竞品不能重复。")
        
        if max_workers < 1 or max_workers > 4:
            self._log(f"[Coordinator] ⚠️ max_workers={max_workers} 超出建议范围 [1-4]，已自动调整")
            max_workers = max(1, min(max_workers, 4))

        self._callback = callback
        self._log_callback = log_callback if verbose else None

        # 初始化状态（max_workers 注入到 state，供 _run_crawler 读取）
        initial_state = WorkflowState(
            user_query=user_query,
            competitors=[],
            confirmed_competitors=confirmed_competitors or [],
            dimensions=["features", "pricing"],
            plan=[],
            current_step=0,
            crawler_status=AgentStatus.PENDING,
            analyzer_status=AgentStatus.PENDING,
            reporter_status=AgentStatus.PENDING,
            crawled_data=None,
            analysis_results=None,
            report_path=None,
            errors=[],
            fatal_error=False,
            retry_count=0,  # 保留用于向后兼容
            crawler_retry_count=0,  # Crawler 独立重试计数
            analyzer_retry_count=0,  # Analyzer 独立重试计数
            reporter_retry_count=0,  # Reporter 独立重试计数
            output_format=output_format,
            verbose=verbose
        )
        # TypedDict 不支持任意键，用私有属性挂在对象上，
        # _run_crawler 通过 self 访问（见下方 _run_crawler 修改）
        self._max_workers = max(1, min(max_workers, 4))
        
        # 运行工作流
        logger.info("=" * 50)
        logger.info("开始竞品分析")
        logger.info("=" * 50)
        
        final_state = self.workflow.invoke(initial_state)
        
        if final_state.get("fatal_error"):
            self._report(100, "❌ 分析失败，已生成错误报告")
        else:
            self._report(100, "🎉 分析全部完成！")
        
        logger.info("=" * 50)
        logger.info("竞品分析失败" if final_state.get("fatal_error") else "竞品分析完成")
        logger.info("=" * 50)
        
        # 组织 data 字段（与演示模式 _make_demo_data() 输出格式一致）
        data = {}
        crawled_data = final_state.get("crawled_data", {})
        analysis_results = final_state.get("analysis_results", {})

        if analysis_results:
            # 功能对比矩阵
            feature_matrix = analysis_results.get("feature_matrix")
            if feature_matrix is not None:
                data["feature_matrix"] = feature_matrix

            # 定价策略
            pricing_analysis = analysis_results.get("pricing_analysis")
            if pricing_analysis is not None:
                data["pricing_analysis"] = pricing_analysis

            # 版本更新活跃度
            changelog_analysis = analysis_results.get("changelog_analysis")
            if changelog_analysis is not None:
                data["changelog_analysis"] = changelog_analysis

            # 用户反馈分析（App Store 评分/评论）
            app_feedback_analysis = analysis_results.get("app_feedback_analysis")
            if app_feedback_analysis is not None:
                data["app_feedback_analysis"] = app_feedback_analysis

            # 官网文案变化分析（快照 diff）
            copy_changes_analysis = analysis_results.get("copy_changes_analysis")
            if copy_changes_analysis is not None:
                data["copy_changes_analysis"] = copy_changes_analysis

            data["quality_report"] = analysis_results.get("quality_report", {})
            data["analysis_metadata"] = analysis_results.get("analysis_metadata", {})

        # 收集每个竞品的数据来源信息（用于 UI 展示警告）
        competitor_sources = {}
        for name, comp_data in crawled_data.items():
            if comp_data.get("_error"):
                competitor_sources[name] = {"_source": "error"}
            else:
                find_method = comp_data.get("_find_method", "unknown")
                find_method_cn = {
                    "whitelist": "白名单",
                    "guess": "启发式",
                    "llm": "LLM 推理",
                }.get(find_method, find_method)
                competitor_sources[name] = {
                    "_source": comp_data.get("_source", "unknown"),
                    "_source_warn": comp_data.get("_source_warn", ""),
                    "_llm_filled_fields": comp_data.get("_llm_filled_fields", []),
                    "_unavailable_fields": comp_data.get("_unavailable_fields", []),
                    "_find_method": find_method,
                    "_find_method_cn": find_method_cn,
                    "_website": comp_data.get("website", ""),
                    "_evidence": comp_data.get("_evidence", []),
                    "_cache_events": comp_data.get("_cache_events", {}),
                }
        data["competitor_sources"] = competitor_sources

        # 返回结果
        return {
            "status": (
                "failed" if final_state.get("fatal_error")
                else "success" if not final_state["errors"]
                else "partial_success"
            ),
            "report_path": final_state["report_path"],
            "competitors": final_state["competitors"],
            "data": data,
            "errors": final_state["errors"]
        }


# 测试代码
if __name__ == "__main__":
    # 测试Coordinator Agent
    coordinator = CoordinatorAgent()
    
    # 测试1: 基本功能
    result = coordinator.run(
        user_query="分析Notion和Obsidian",
        verbose=True
    )
    
    print(f"\n分析结果:")
    print(f"状态: {result['status']}")
    print(f"报告路径: {result['report_path']}")
    print(f"竞品: {result['competitors']}")
