"""
Analysis Agent - 分析Agent
负责功能对比、定价分析、生成AI洞察
"""

import json
import os
import logging
from typing import Dict, List, Any, Optional
from collections import defaultdict

import pandas as pd
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

# 使用统一的环境变量加载器
from utils.env_loader import load_env, get_env
from utils.llm_parser import safe_extract_json
from utils.json_schema import (
    validate_and_repair,
    validate_string_list,
    PRICING_SCHEMA,
    COMPARE_SCHEMA,
    INSIGHTS_SCHEMA,
)

# 加载 .env 环境变量
load_env()

logger = logging.getLogger(__name__)

# 产品类型 → 标准功能对比维度清单
# 用于 _llm_fallback_compare，避免 LLM 对笔记/短视频等产品输出企业 SaaS 维度
_FEATURE_DIMENSION_CATALOG = {
    "笔记知识管理": [
        "文档编辑", "Markdown 支持", "双向链接", "图谱视图", "全文搜索",
        "标签系统", "模板库", "数据库/表格", "导入导出", "离线访问",
        "移动端应用", "插件/扩展生态", "协作共享", "权限管理", "版本历史",
        "Web 剪藏", "AI 助手", "任务/待办", "日历/日程集成"
    ],
    "办公协作": [
        "即时通讯", "文档协作", "电子表格", "演示文稿", "云存储",
        "视频会议", "日程/日历", "任务管理", "审批流程", "组织架构",
        "权限管理", "移动端应用", "API 集成", "应用市场", "邮件集成"
    ],
    "短视频": [
        "短视频拍摄", "滤镜特效", "视频剪辑", "直播", "推荐算法",
        "电商带货", "创作者工具", "社交互动", "私信", "青少年模式",
        "广告变现", "本地生活", "直播连麦", "合拍/同框", "评论区"
    ],
    "电商": [
        "商品搜索", "购物车", "在线支付", "物流跟踪", "售后服务",
        "直播带货", "优惠券", "会员体系", "店铺管理", "商品推荐",
        "评价系统", "秒杀/拼团", "客服系统", "多端同步"
    ],
    "社交": [
        "IM 聊天", "朋友圈/动态", "群聊", "附近的人", "视频通话",
        "内容社区", "关注/订阅", "点赞评论", "分享转发", "直播"
    ],
    "项目管理": [
        "任务管理", "看板视图", "甘特图", "里程碑", "缺陷跟踪",
        "Sprint 迭代", "工时统计", "自动化工作流", "权限管理", "报表",
        "第三方集成", "移动端应用", "需求管理"
    ],
    "设计工具": [
        "矢量编辑", "原型设计", "组件库", "自动布局", "版本历史",
        "评论标注", "设计交付", "插件生态", "协作编辑", "设计系统",
        "导入导出", "离线访问"
    ],
    "AI 工具": [
        "AI 对话", "AI 写作", "AI 代码辅助", "知识库问答", "模型选择",
        "API 调用", "插件扩展", "长上下文", "多模态", "提示词管理"
    ],
    "即时通讯": [
        "IM 聊天", "群聊", "视频通话", "语音通话", "文件传输",
        "已读回执", "消息搜索", "机器人", "多端同步", "屏幕共享"
    ],
    "通用": [
        "核心功能 A", "核心功能 B", "高级功能", "数据管理", "协作",
        "移动端", "API", "安全", "扩展", "自动化", "分析", "导出", "导入"
    ]
}

# 跨品类比较使用共同的用户价值/业务能力维度，避免把某一品类的专属
# 功能（例如 AI 工具的“长上下文”）强行套到另一类产品上。
_CROSS_CATEGORY_DIMENSIONS = [
    "目标用户与核心场景", "核心内容/服务能力", "内容生产与编辑",
    "搜索与发现", "个性化推荐", "用户互动", "创作者/开发者工具",
    "商业化与支付", "开放平台与生态", "移动端与多端体验",
]

# LLM/网络不可用时的最小产品类别兜底。仅用于选择正确的对比维度，
# 不会把任何功能直接当成已验证事实。
_PRODUCT_CATEGORY_HINTS = {
    "短视频": ["抖音", "快手", "tiktok", "youtube", "bilibili", "哔哩哔哩"],
    "笔记知识管理": ["notion", "obsidian", "logseq", "evernote", "onenote"],
    "项目管理": ["jira", "linear", "asana", "trello"],
    "设计工具": ["figma", "sketch", "adobe xd"],
    "即时通讯": ["微信", "wechat", "slack", "discord", "钉钉", "飞书"],
    "电商": ["淘宝", "京东", "拼多多", "amazon", "shopify"],
}


def _infer_category_from_product_name(product_name: str) -> str:
    """从常见产品名推断类别，供 LLM 连接失败时安全降级。"""
    normalized = (product_name or "").lower().strip()
    for category, aliases in _PRODUCT_CATEGORY_HINTS.items():
        if any(alias in normalized for alias in aliases):
            return category
    return ""


def _normalize_category_name(category: str) -> str:
    """把 LLM 返回的类别字符串归一化为标准维度键"""
    if not category:
        return "通用"
    c = category.lower().strip()
    if "笔记" in c or "知识管理" in c or "knowledge" in c or "note" in c:
        return "笔记知识管理"
    if "办公" in c or "协作" in c or "office" in c or "workspace" in c:
        return "办公协作"
    # LLM 常把抖音/快手归为“视频”或“内容平台”，这些别名仍应落到
    # 短视频维度；否则混合比较时会被当作“通用”而丢失正确类别。
    if ("短视频" in c or "视频" in c or "内容平台" in c
            or "short" in c or "video" in c or "content platform" in c):
        return "短视频"
    if "电商" in c or "e-commerce" in c or "shopping" in c:
        return "电商"
    if "社交" in c or "social" in c:
        return "社交"
    if "项目" in c or "project" in c or "pm" in c:
        return "项目管理"
    if "设计" in c or "design" in c or "figma" in c:
        return "设计工具"
    if "ai" in c or "人工智能" in c or "大模型" in c:
        return "AI 工具"
    if "即时" in c or "通讯" in c or "im" in c or "messaging" in c or "chat" in c:
        return "即时通讯"
    return "通用"


class AnalysisAgent:
    """分析Agent"""
    
    def __init__(self, model: str = None, temperature: float = None):
        """
        初始化Analysis Agent
        
        Args:
            model: LLM模型名称（默认从 OPENAI_MODEL 环境变量读取）
            temperature: 温度参数（默认从 OPENAI_TEMPERATURE 环境变量读取）
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

        # 🔧 抽取类低温实例：结构化抽取/兜底用低温(0.1)降低幻觉与格式漂移
        # 洞察等创意生成仍用 self.llm（默认 0.7）
        self.llm_extract = ChatOpenAI(
            model=model,
            temperature=0.1,
            api_key=api_key,
            base_url=base_url or None,
            request_timeout=60,
            max_retries=2
        )

    def assess_data_quality(self, competitors_data: Dict[str, Dict]) -> Dict[str, Any]:
        """在 Analyzer 内执行轻量真实性闸门，不引入额外 Agent。

        评分只奖励可追溯的爬取/API 数据；LLM 补全内容可以继续参与分析，
        但不会被计为已验证证据。
        """
        details: Dict[str, Dict[str, Any]] = {}

        for name, data in (competitors_data or {}).items():
            data = data or {}
            source = data.get("_source", "unknown")
            filled = set(data.get("_llm_filled_fields", []) or [])
            features = data.get("features", {}) or {}
            pricing = data.get("pricing", {}) or {}
            changelog = data.get("changelog", {}) or {}
            app_store = data.get("app_store", {}) or {}
            github = data.get("github_releases", {}) or {}

            core = list(features.get("core", []) or [])
            advanced = list(features.get("advanced", []) or [])
            raw_feature_count = len(core) + len(advanced)
            full_llm = source == "llm_fallback"
            # 只有关联了来源 URL 的字段才可验证。旧缓存也必须提供字段证据，
            # 仅有 page_access、website 或未标记为 LLM 均不足以验证内容。
            from urllib.parse import urlsplit

            def valid_url(url):
                if not isinstance(url, str):
                    return False
                try:
                    parsed = urlsplit(url)
                    return parsed.scheme in ("http", "https") and bool(parsed.netloc)
                except ValueError:
                    return False

            field_evidence = data.get("_field_evidence", {}) or {}
            evidence = [item for item in (data.get("_evidence", []) or [])
                        if isinstance(item, dict) and valid_url(item.get("url"))]
            for field, urls in field_evidence.items():
                for url in ([urls] if isinstance(urls, str) else (urls or [])):
                    if valid_url(url):
                        evidence.append({"source": "official_web", "url": url, "fields": [field]})

            def has_evidence(field):
                for item in evidence:
                    fields = item.get("fields", [])
                    if isinstance(fields, str):
                        fields = [fields]
                    if field in (fields or []):
                        return True
                    # 兼容有明确 features 证据的旧记录，但新版细分字段不可互相替代。
                    if ("_field_evidence" not in data and field.startswith("features.")
                            and "features" in (fields or [])):
                        return True
                return False

            core_has_evidence = has_evidence("features.core")
            advanced_has_evidence = has_evidence("features.advanced")
            verified_core = 0 if (
                full_llm or features.get("_core_source") == "llm"
                or "features.core" in filled
                or not core_has_evidence
            ) else len(core)
            verified_advanced = 0 if (
                full_llm or features.get("_advanced_source") == "llm"
                or "features.advanced" in filled
                or not advanced_has_evidence
            ) else len(advanced)
            verified_feature_count = verified_core + verified_advanced

            has_pricing = bool(pricing.get("model") or pricing.get("plans"))
            verified_pricing = bool(
                has_pricing
                and not full_llm
                and data.get("_pricing_source") != "llm"
                and "pricing" not in filled
                and has_evidence("pricing")
            )

            changelog_values = [
                changelog.get("latest_version"),
                changelog.get("latest_release_date"),
                changelog.get("recent_updates"),
                changelog.get("update_frequency"),
            ]
            has_changelog = any(bool(value) for value in changelog_values)
            changelog_is_llm = full_llm or changelog.get("_source") == "llm" or any(
                field.startswith("changelog.") for field in filled
            )
            verified_changelog = bool(has_changelog and not changelog_is_llm and has_evidence("changelog"))
            has_release_api = False
            for payload, source_name, value, fields in (
                (github, "github_releases", github.get("releases"), ["releases", "changelog"]),
                (app_store, "app_store", app_store.get("version"), ["version"]),
            ):
                if (value and not full_llm and payload.get("_source") != "llm"
                        and not any(field == source_name or field.startswith(source_name + ".") for field in filled)
                        and valid_url(payload.get("_url"))):
                    has_release_api = True
                    evidence.append({"source": source_name, "url": payload["_url"], "fields": fields})
            has_feedback = bool(app_store.get("rating") is not None or app_store.get("reviews"))

            if not evidence:
                evidence = [
                    {"source": "official_web", "url": url, "fields": ["website"]}
                    for url in (data.get("crawled_pages", []) or []) if valid_url(url)
                ]
            evidence_urls = list(dict.fromkeys(
                item.get("url") for item in evidence
                if isinstance(item, dict) and item.get("url")
            ))

            score = 0
            score += 35 if verified_feature_count else 0
            score += 15 if verified_pricing else 0
            score += 15 if (verified_changelog or has_release_api) else 0
            score += 10 if has_feedback else 0
            score += min(25, len(evidence_urls) * 5)
            score = min(100, score)

            issues: List[str] = []
            if not verified_feature_count:
                issues.append("未提取到可验证的官网功能")
            if not verified_pricing:
                issues.append("未获得可验证的定价/商业模式")
            if not (verified_changelog or has_release_api):
                issues.append("未获得可验证的近期更新")
            if not has_feedback:
                issues.append("未获得公开用户评分/评论")
            if not evidence_urls:
                issues.append("缺少可追溯来源 URL")
            if filled or full_llm:
                issues.append("部分结构化字段来自 LLM 推测")

            has_any_content = bool(
                raw_feature_count or has_pricing or has_changelog or has_feedback
                or evidence_urls or data.get("website")
            )
            if data.get("_error") or not has_any_content:
                status = "failed"
            elif verified_feature_count and score >= 50:
                status = "passed"
            else:
                status = "degraded"

            if verified_feature_count and score >= 70:
                confidence = "high"
            elif verified_feature_count and score >= 40:
                confidence = "medium"
            else:
                confidence = "low"

            if verified_feature_count:
                analysis_mode = "evidence_based" if not filled else "mixed"
            elif raw_feature_count or has_pricing or has_changelog:
                analysis_mode = "inference_only"
            else:
                analysis_mode = "insufficient"

            details[name] = {
                "status": status,
                "score": score,
                "confidence": confidence,
                "analysis_mode": analysis_mode,
                "source": source,
                "raw_feature_count": raw_feature_count,
                "verified_feature_count": verified_feature_count,
                "verified_pricing": verified_pricing,
                "verified_changelog": bool(verified_changelog or has_release_api),
                "has_user_feedback": has_feedback,
                "evidence_count": len(evidence_urls),
                "evidence": evidence,
                "issues": issues,
            }

        counts = {
            key: sum(1 for item in details.values() if item["status"] == key)
            for key in ("passed", "degraded", "failed")
        }
        average = round(
            sum(item["score"] for item in details.values()) / len(details), 1
        ) if details else 0.0
        return {
            "summary": {
                "total": len(details),
                **counts,
                "average_score": average,
                "status": "passed" if details and counts["passed"] == len(details)
                else "failed" if details and counts["failed"] == len(details)
                else "degraded",
            },
            "competitors": details,
        }
    
    def _rag_prompt_section(self, rag_context: str = None) -> str:
        """
        把向量库检索到的"历史相似竞品数据"格式化为可注入 Prompt 的段落。
        rag_context 为空时返回空串（保持向后兼容、不影响原逻辑）。
        """
        if rag_context and str(rag_context).strip():
            return (
                "\n\n【参考历史相似竞品数据（来自向量库检索，仅作参考）】\n"
                + str(rag_context).strip()
                + "\n请结合以上参考信息，优先复用可靠的既有结论，避免与已知事实矛盾；"
                "若发现参考信息明显有误，可在分析中明确纠正。\n"
            )
        return ""

    def _build_crawled_features_section(self, competitors_data: Dict[str, Dict]) -> str:
        """把实爬到的功能列表作为 ground truth 参考注入 Prompt。"""
        lines = ["【实爬功能参考（页面提取到的功能，可能不完整，仅作参考）】"]
        has_any = False
        for name, data in (competitors_data or {}).items():
            features = data.get("features", {}) or {}
            core = features.get("core", []) or []
            advanced = features.get("advanced", []) or []
            all_feat = [f for f in (core + advanced) if f]
            if all_feat:
                has_any = True
                lines.append(f"{name}：{', '.join(all_feat[:30])}")
        if not has_any:
            return ""
        return "\n".join(lines) + "\n"

    def compare_features(self, competitors_data: Dict[str, Dict],
                         rag_context: str = None) -> pd.DataFrame:
        """
        功能对比分析

        Args:
            competitors_data: 竞品数据字典 {竞品名: 数据}
            rag_context: 向量库检索到的相似竞品参考上下文（可选）

        Returns:
            功能对比矩阵 (DataFrame)
        """

        logger.info("Analyzer: 开始功能对比分析")

        # 步骤1: 收集所有功能
        all_features = self._collect_all_features(competitors_data)

        # 步骤2: 如果已知产品类别，优先用该类别标准维度 + LLM 打分，避免实爬功能名不全导致大量 ❌
        canonical_features = self._determine_feature_dimensions(competitors_data)
        if canonical_features:
            logger.info(f"Analyzer: 识别到统一/混合类别，使用标准维度 {len(canonical_features)} 个")
            return self._llm_fallback_compare(
                list(competitors_data.keys()),
                competitors_data=competitors_data,
                rag_context=rag_context,
                feature_list=canonical_features
            )

        # 步骤3: 如果爬取数据为空，使用 LLM 兜底生成
        if not all_features:
            logger.warning("爬取数据为空，使用LLM知识库生成功能对比")
            return self._llm_fallback_compare(
                list(competitors_data.keys()),
                competitors_data=competitors_data,
                rag_context=rag_context
            )

        # 步骤4: 标准化功能名称
        standardized_features = self._standardize_features(all_features)

        # 步骤5: 构建对比矩阵
        matrix = self._build_comparison_matrix(
            standardized_features,
            competitors_data
        )

        logger.info(f"Analyzer: 功能对比完成 ({len(matrix)} 个功能)")

        matrix.attrs["source"] = "crawl"
        matrix.attrs["confidence"] = "high"
        matrix.attrs["warning"] = ""
        return matrix

    def _llm_fallback_compare(self, competitor_names: List[str],
                               competitors_data: Dict[str, Dict] = None,
                               rag_context: str = None,
                               feature_list: Optional[List[str]] = None) -> pd.DataFrame:
        """
        当爬取数据不足或需要按标准维度对比时，使用 LLM 知识库生成功能对比矩阵。

        这是兜底方案：即使爬虫完全失败，用户仍能得到有价值的报告。
        🔧 关键修复：不再硬编码通用 SaaS 维度，而是根据产品实际类型（如短视频、电商、办公等）
        动态选择相关的功能维度，避免对抖音/快手输出"文档编辑/数据库"等无关维度。
        🔧 新增：允许调用方传入 feature_list 强制使用标准维度，并把实爬功能作为 ground truth 参考。
        """
        competitors_str = "、".join(competitor_names)

        # 收集产品类别信息并归一化，帮助 LLM 选择更贴切的维度
        competitors_data = competitors_data or {}
        categories = []
        normalized_categories = []
        for name in competitor_names:
            cd = competitors_data.get(name, {}) or {}
            cat = (
                cd.get("_category")
                or cd.get("category")
                or _infer_category_from_product_name(name)
                or "未提供"
            )
            categories.append(f"{name}: {cat}")
            norm = _normalize_category_name(cat)
            if norm != "通用":
                normalized_categories.append(norm)
        categories_str = "\n".join(categories) if categories else "未提供"

        # 维度选择：调用方强制指定 > 归一化单类别 > 归一化混合类别 > 未提供
        if feature_list:
            dimension_instruction = (
                "请严格使用以下标准维度清单进行对比，输出清单中每个维度的支持情况。"
                "禁止输出清单以外的维度，尤其禁止 SaaS/企业级/安全类无关维度（如 AI Agent、SAML 单点登录、域名验证、页面验证、基础表单、AI 会议笔记等）：\n"
                + "、".join(feature_list)
            )
        elif normalized_categories and len(set(normalized_categories)) == 1:
            cat_key = normalized_categories[0]
            dimensions = _FEATURE_DIMENSION_CATALOG.get(cat_key, _FEATURE_DIMENSION_CATALOG["通用"])
            dimension_instruction = (
                f"这些产品都属于【{cat_key}】类别。请严格使用以下维度列表进行对比，"
                f"禁止输出 SaaS/企业级/安全类无关维度（如 AI Agent、SAML 单点登录、域名验证、页面验证、基础表单、AI 会议笔记等）：\n"
                + "、".join(dimensions)
            )
        elif normalized_categories:
            all_dims = []
            seen = set()
            for ck in set(normalized_categories):
                for d in _FEATURE_DIMENSION_CATALOG.get(ck, _FEATURE_DIMENSION_CATALOG["通用"]):
                    if d not in seen:
                        seen.add(d)
                        all_dims.append(d)
            dimension_instruction = (
                "这些产品分属不同类别。请从以下维度中选择两者都适用或各自最核心、可对比的维度，"
                "同样禁止输出 SaaS/企业级/安全类无关维度（如 AI Agent、SAML 单点登录、域名验证、页面验证、基础表单、AI 会议笔记等）：\n"
                + "、".join(all_dims[:25])
            )
        else:
            dimension_instruction = (
                "未提供产品类别。请先判断每个产品分别属于哪一类（笔记知识管理/办公协作/短视频/电商/社交/项目管理/设计工具/AI 工具/即时通讯/通用工具），"
                "然后选择对应类别下真实存在的功能维度。禁止输出 SaaS/企业级/安全类维度（如 AI Agent、SAML 单点登录、域名验证、页面验证、基础表单、AI 会议笔记等）。"
            )

        # 实爬功能作为 ground truth 参考，帮助 LLM 避免把真实存在的功能标成 ❌
        crawled_features_section = self._build_crawled_features_section(competitors_data)

        prompt = ChatPromptTemplate.from_messages([
            ("system", (
                """你是一位资深的产品分析专家。请对以下竞品进行详细的功能对比。

【重要】必须根据这些产品的实际类型/行业选择对比维度，禁止默认使用通用 SaaS/企业级/安全类维度。

{dimension_instruction}

请基于你对这些产品的真实了解，输出至少 10 个真实、相关、可验证的功能维度对比。

输出严格的 JSON 格式（不要有 markdown 代码块）：
{{
    "matrix": [
        {{"功能": "短视频拍摄", "竞品A": "✅", "竞品B": "⚠️"}},
        ...
    ]
}}

注意：
- 使用 ✅ 表示支持/强，❌ 表示不支持/弱，⚠️ 表示部分支持
- 标记必须准确：不要"宁缺毋滥"。只要产品确实提供该能力，即使不是主打功能，也应标 ✅ 或 ⚠️，而不是 ❌
- 至少输出 10 个功能维度，且每个维度都必须是该产品类型下真实存在的功能
- 列名可直接使用真实产品名（如 "抖音"/"快手"），也可使用占位名（竞品A、产品A、Competitor1、Product1 等），
  系统会自动将占位名映射回真实竞品名
- 只输出 JSON，不要其他内容
{rag_context_section}"""
            )),
            ("user", "请对比以下产品：{competitors_str}\n\n已知产品类别信息：\n{categories_str}\n\n{crawled_features_section}请输出 JSON 矩阵。")
        ])

        try:
            import time as time_mod
            from agents.perf_tracker import get_tracker
            
            t_start = time_mod.time()
            chain = prompt | self.llm_extract
            response = chain.invoke({
                "dimension_instruction": dimension_instruction,
                "rag_context_section": self._rag_prompt_section(rag_context),
                "competitors_str": competitors_str,
                "categories_str": categories_str,
                "crawled_features_section": crawled_features_section,
            })
            t_end = time_mod.time()
            
            # 提取 token 用量
            usage = response.usage_metadata if hasattr(response, 'usage_metadata') else {}
            input_tokens = usage.get('input_tokens', 0)
            output_tokens = usage.get('output_tokens', 0)
            
            # 记录到全局统计器
            tracker = get_tracker()
            tracker.log_call('Analyzer', '_llm_fallback_compare', input_tokens, output_tokens, t_end - t_start)
            
            print(f"[PERF] Analyzer LLM call (fallback_compare): {t_end - t_start:.2f}s | Input: {input_tokens} | Output: {output_tokens}")
            
            # 使用安全的 JSON 解析函数
            try:
                result = safe_extract_json(response.content)
            except ValueError as e:
                logger.error(f"JSON 解析失败: {e}")
                raise

            # 输出层 Schema 约束：补全 matrix 等必填字段，避免下游 KeyError
            result, _ = validate_and_repair(
                result, COMPARE_SCHEMA, context="_llm_fallback_compare"
            )

            df = pd.DataFrame(result["matrix"])

            # 🔧 修复C/F：将通用占位名替换为真实竞品名，支持 N 个竞品
            # 覆盖 竞品A/B/...、产品A/B/...、CompetitorN、ProductN 四种写法
            col_map = {}
            for i, name in enumerate(competitor_names):
                suffix = chr(ord('A') + i) if i < 26 else str(i + 1)
                col_map[f"竞品{suffix}"] = name
                col_map[f"产品{suffix}"] = name
                col_map[f"Competitor{i+1}"] = name
                col_map[f"Product{i+1}"] = name
            df = df.rename(columns=col_map)
            # 剩余未映射的"竞品X/产品X"列直接丢弃，避免脏列进入报告

            quality = self.assess_data_quality(competitors_data)
            verified_count = sum(
                item.get("verified_feature_count", 0)
                for item in quality.get("competitors", {}).values()
            )
            matrix_source = "llm_assisted" if verified_count else "llm_fallback"
            df.attrs["source"] = matrix_source
            df.attrs["confidence"] = "medium" if verified_count else "low"
            df.attrs["warning"] = (
                "功能矩阵由 LLM 在官网证据辅助下生成，支持状态仍需人工核验。"
                if verified_count else
                "官网未提取到可验证功能，功能矩阵完全来自 LLM 推测，仅供参考。"
            )
            logger.info(f"LLM兜底生成功能对比矩阵 ({len(df)} 行, source={matrix_source})")
            return df

        except Exception as e:
            logger.error(f"LLM兜底功能对比失败: {e}")
            # 终极兜底：根据已识别类别返回默认矩阵，避免再输出通用 SaaS 维度
            fallback_data = []
            if normalized_categories and len(set(normalized_categories)) == 1:
                cat_key = normalized_categories[0]
                default_features = _FEATURE_DIMENSION_CATALOG.get(cat_key, _FEATURE_DIMENSION_CATALOG["通用"])
            else:
                default_features = [
                    "核心能力（待核验）", "内容/服务能力（待核验）",
                    "用户互动能力（待核验）", "商业化能力（待核验）",
                    "移动端体验（待核验）"
                ]
            for feat in default_features:
                row = {"功能": feat}
                for name in competitor_names:
                    # 规则兜底没有证据，必须标为待核验，不能显示成已确认支持。
                    row[name] = "⚠️"
                fallback_data.append(row)
            df = pd.DataFrame(fallback_data)
            df.attrs["source"] = "llm_fallback"
            df.attrs["confidence"] = "low"
            df.attrs["warning"] = "LLM 调用失败，当前矩阵为规则兜底推测，不可视为事实。"
            return df
    
    def _collect_all_features(self, competitors_data: Dict[str, Dict]) -> List[str]:
        """收集所有竞品的功能"""

        all_features = set()

        for comp_name, comp_data in competitors_data.items():
            features = comp_data.get("features", {}) or {}

            # 核心功能
            core_features = features.get("core", []) or []
            all_features.update(core_features)

            # 高级功能
            advanced_features = features.get("advanced", []) or []
            all_features.update(advanced_features)

        return list(all_features)

    def _determine_feature_dimensions(self, competitors_data: Dict[str, Dict]) -> Optional[List[str]]:
        """
        根据竞品类别返回标准功能维度清单。
        - 单一已知类别：返回该类别维度清单
        - 多个已知类别：合并去重（最多 25 个）
        - 全部未知：返回 None
        """
        normalized = []
        for comp_name, comp_data in competitors_data.items():
            cat = (
                comp_data.get("_category")
                or comp_data.get("category")
                or _infer_category_from_product_name(comp_name)
            )
            norm = _normalize_category_name(cat)
            if norm != "通用":
                normalized.append(norm)
        if not normalized:
            return None
        if len(set(normalized)) == 1:
            return list(_FEATURE_DIMENSION_CATALOG.get(normalized[0], _FEATURE_DIMENSION_CATALOG["通用"]))
        # 混合类别：使用双方都能理解的业务维度，不再简单拼接两套
        # 品类专属功能。这样“豆包 vs 抖音”不会退化成 AI 功能清单。
        return list(_CROSS_CATEGORY_DIMENSIONS)
    
    def _standardize_features(self, features: List[str]) -> List[str]:
        """
        标准化功能名称
        
        🆕 改进：始终使用 LLM 进行功能对齐（不再需要 >10 features 才触发）
        无需任何手动白名单，任何产品都能正确对齐
        """
        
        if not features:
            return []
        
        # 🆕 始终使用 LLM 进行功能对齐（无论 features 数量多少）
        return self._llm_align_features(features)

    def _llm_align_features(self, features: List[str]) -> List[str]:
        """
        使用 LLM 动态对齐功能名称（替代静态同义词表）
        
        无需任何手动白名单，任何产品的功能都能正确对齐
        """
        if not features or len(features) < 2:
            return features
        # 去重
        unique = list(set(features))
        if len(unique) < 2:
            return unique
        prompt = ChatPromptTemplate.from_messages([
            ("system", """你是产品功能标准化专家。
以下功能列表来自不同产品的爬取结果，命名可能不同但语义相同或相似。
请将它们对齐到统一的标准功能名。
规则：
1. 语义相同的功能合并为一个标准名
2. 标准名要简洁、准确（2-6个字）
3. 只合并真正相同的功能，不要强行合并
4. 输出 JSON 数组格式
示例：
输入：["文件传输", "发文件", "文件分享", "文件共享"]
输出：["文件传输", "文件传输", "文件传输", "文件传输"]
（说明：4个名称都对齐到"文件传输"）
"""),
            ("user", "功能列表：\n{features_text}\n\n请输出对齐后的功能名数组（顺序与原列表一致，每个元素是对齐后的标准名）。\n只输出JSON数组，不要有其他内容。")
        ])
        try:
            chain = prompt | self.llm
            response = chain.invoke({
                "features_text": "\n".join([f"- {f}" for f in unique])
            })
            aligned = safe_extract_json(response.content)
            aligned_list = validate_string_list(aligned, context="_llm_align_features")
            if aligned_list and len(aligned_list) == len(unique):
                # 构建映射表：原名 -> 对齐名
                mapping = {}
                for orig, aligned_name in zip(unique, aligned_list):
                    mapping[orig] = aligned_name
                # 应用映射
                result = [mapping.get(f, f) for f in features]
                logger.info(f"LLM功能对齐完成: {len(features)} 个功能")
                return result
            if aligned_list:
                logger.warning(
                    f"LLM功能对齐返回数量({len(aligned_list)})与原功能数({len(unique)})不符，退回原功能名"
                )
            return features
        except Exception as e:
            logger.warning(f"LLM功能对齐失败: {e}，使用原名")
            return features

    
    def _build_comparison_matrix(self, features: List[str], 
                                 competitors_data: Dict[str, Dict]) -> pd.DataFrame:
        """构建功能对比矩阵"""
        
        matrix_data = []
        
        for feature in features:
            row = {"功能": feature}
            
            for comp_name, comp_data in competitors_data.items():
                # 检查该功能是否存在
                has_feature = self._check_feature_exists(feature, comp_data)
                row[comp_name] = "✅" if has_feature else "❌"
            
            matrix_data.append(row)
        
        return pd.DataFrame(matrix_data)
    
    def _check_feature_exists(self, feature: str, comp_data: Dict) -> bool:
        """
        检查竞品是否具有某个功能
        
        🔧 修复：使用智能匹配（同义词、关键词、模糊匹配）
        解决功能名称表述不一致导致的误判问题
        """
        
        features = comp_data.get("features", {}) or {}
        
        all_comp_features = []
        all_comp_features.extend(features.get("core", []) or [])
        all_comp_features.extend(features.get("advanced", []) or [])
        
        # 注意：_llm_filled_fields 存的是字段路径字符串（如 "features.core"），
        # 不能当作功能名去匹配，因此竞品无结构化功能数据时直接返回 False
        if not all_comp_features:
            return False
        
        # 1. 直接字符串匹配（原逻辑）
        for comp_feature in all_comp_features:
            if feature in comp_feature or comp_feature in feature:
                return True
        
        # 2. 同义词/关键词匹配（新增）
        synonym_map = self._get_feature_synonym_map()
        keywords = synonym_map.get(feature, [])
        for keyword in keywords:
            for comp_feature in all_comp_features:
                if keyword in comp_feature or comp_feature in keyword:
                    return True
        
        # 3. 反向检查：该竞品是否有任何包含此功能关键词的特性
        feature_keywords = self._extract_keywords(feature)
        for comp_feature in all_comp_features:
            comp_keywords = self._extract_keywords(comp_feature)
            # 如果两个功能的关键词有重叠，认为匹配
            if set(feature_keywords) & set(comp_keywords):
                return True
        
        return False
    
    def _get_feature_synonym_map(self) -> Dict[str, List[str]]:
        """
        功能同义词/关键词映射表
        
        用于解决不同产品对同一功能的不同命名问题
        例如："文件传输" 可能也叫 "文件发送"、"文件共享"、"传输文件"
        """
        return {
            "文件传输": ["文件", "传输", "发送", "分享", "附件", "共享", "传文件"],
            "即时通讯": ["消息", "聊天", "通讯", "IM", "对话", "私信", "群聊"],
            "视频通话": ["视频", "通话", "视频聊天", "视频会议", "摄像头", "面对面"],
            "远程协助": ["远程", "协助", "控制", "屏幕共享", "桌面共享", "远程控制"],
            "语音通话": ["语音", "电话", "通话", "音频", "VoIP", "呼叫"],
            "文档编辑": ["文档", "编辑", "写作", "笔记", "文本编辑", "富文本"],
            "数据库": ["数据库", "存储", "知识库", "数据管理", "结构化数据"],
            "看板视图": ["看板", "Kanban", "任务板", "卡片", "项目管理"],
            "双向链接": ["链接", "关联", "引用", "回链", "双链", "wiki"],
            "本地存储": ["本地", "离线", "存储", "保存", "导出", "同步"],
            "实时协作": ["协作", "多人", "同时", "协同", "团队", "实时"],
            "图谱视图": ["图谱", "关系图", "网络图", "思维导图", "可视化"],
            "插件系统": ["插件", "扩展", "集成", "API", "第三方", "应用商店"],
            "AI助手": ["AI", "人工智能", "智能助手", "GPT", "Copilot", "自动化"],
            "模板市场": ["模板", "预设", "样例", "市场", "库", "资源"],
            "移动端": ["手机", "移动", "iOS", "Android", "App", "平板"],
            "API开放": ["API", "接口", "开发", "SDK", "集成", "开放平台"],
            "SSO": ["单点登录", "SSO", "认证", "身份", "权限", "LDAP"],
            "审计日志": ["日志", "审计", "记录", "追踪", "历史", "操作记录"],
            "离线访问": ["离线", "无网络", "断网", "本地访问", "缓存"],
            # 招聘/求职类 ⭐ 新增
            "修改手机号": ["手机", "修改", "更换", "绑定", "账号设置", "个人信息", "安全设置"],
            "登录账号": ["登录", "注册", "账号", "登入", "sign", "login"],
            "切换身份": ["切换", "身份", "角色", "招聘者", "求职者", "hr", "用户"],
            "隐藏/开放简历": ["简历", "隐藏", "开放", "隐私", "可见性", "resume"],
            "面试爽约处理": ["面试", "爽约", "取消", "日程", "安排", "interview"],
            "更换/解绑微信": ["微信", "解绑", "更换", "绑定", "关联", "wechat"],
            "修改职位": ["职位", "修改", "意向", "期望", "position", "目标"],
            "企业服务热线": ["客服", "热线", "服务", "电话", "联系", "help", "support"],
            "举报渠道": ["举报", "投诉", "反馈", "渠道", "不良", "违规"],
            "防骗指南": ["防骗", "指南", "安全", "诈骗", "反诈", "提醒", "提示"],
            # 电商类 ⭐ 新增
            "搜索商品": ["搜索", "查找", "商品", "产品", "浏览"],
            "购物车": ["购物车", "加购", "cart"],
            "下单支付": ["下单", "支付", "付款", "结算", "订单"],
            "物流追踪": ["物流", "快递", "追踪", "配送", "收货"],
            "退款退货": ["退款", "退货", "售后", "换货", "cancel"],
            # 音乐/视频类 ⭐ 新增
            "播放音乐": ["播放", "听歌", "音乐", "song", "play"],
            "创建歌单": ["歌单", "播放列表", "playlist", "收藏"],
            "下载离线": ["下载", "离线", "缓存", "本地下载"],
            "歌词显示": ["歌词", "lrc", "滚动歌词"],
            # 游戏类 ⭐ 新增
            "多人对战": ["对战", "多人", "联机", " multiplayer", "在线"],
            "成就系统": ["成就", "奖杯", "trophy", "achievement"],
        }
    
    def _extract_keywords(self, text: str) -> List[str]:
        """从功能名称中提取关键词"""
        import re
        # 提取中文词组（2-4字）
        chinese_words = re.findall(r'[\u4e00-\u9fa5]{2,}', text)
        # 提取英文单词
        english_words = re.findall(r'[a-zA-Z]{3,}', text)
        return chinese_words + english_words
    
    def analyze_pricing(self, competitors_data: Dict[str, Dict],
                         rag_context: str = None) -> Dict[str, Any]:
        """
        定价分析

        Args:
            competitors_data: 竞品数据字典
            rag_context: 向量库检索到的相似竞品参考上下文（可选）

        Returns:
            定价分析结果
        """

        logger.info("Analyzer: 开始定价分析")

        # 检查是否有真实的定价数据。LLM 补全的 pricing 不能作为真实价格
        # 参与后续区间计算，否则会把 Token 单价误写成月费。
        real_pricing_names = []
        pricing_info = []

        for comp_name, comp_data in competitors_data.items():
            pricing = comp_data.get("pricing", {}) or {}
            filled = set(comp_data.get("_llm_filled_fields", []) or [])
            is_llm_pricing = (
                comp_data.get("_source") == "llm_fallback"
                or comp_data.get("_pricing_source") == "llm"
                or "pricing" in filled
            )
            if (pricing.get("model") or pricing.get("plans")) and not is_llm_pricing:
                real_pricing_names.append(comp_name)
            pricing_info.append({
                "competitor": comp_name,
                "model": pricing.get("model"),
                "plans": pricing.get("plans", []) or [],
            })

        # 如果没有真实定价数据，使用 LLM 知识库
        if not real_pricing_names:
            logger.warning("爬取数据中无定价信息，使用LLM知识库生成")
            result = self._llm_fallback_pricing(
                list(competitors_data.keys()), rag_context=rag_context
            )
            result = self._sanitize_unverified_pricing(
                result, list(competitors_data.keys())
            )
            result["analysis"] = (
                "未抓取到可验证的官方定价。定价模式仅作为 AI 辅助线索，"
                "不提供具体金额或月度价格区间，请以官网最新页面为准。"
            )
            result["recommendations"] = ["访问各产品官方定价页并记录币种、计费单位和更新时间"]
            result["_source"] = "llm_fallback"
            result["_confidence"] = "low"
            result["_warning"] = "未抓取到可验证定价，以下定价分析来自 LLM 推测。"
            return result

        # 使用LLM进行定价分析（基于爬取到的数据）
        prompt = ChatPromptTemplate.from_messages([
            ("system", (
                """你是一位定价策略专家。请分析以下竞品的定价策略。

分析维度：
1. 定价模式（订阅/一次性/免费增值）
2. 价格区间
3. 性价比评估
4. 定价策略特点

输出JSON格式：
{{
    "pricing_models": {{"竞品1": "模式", "竞品2": "模式"}},
    "price_range": {{"min": 最低价, "max": 最高价}},
    "analysis": "定价分析文本",
    "recommendations": ["建议1", "建议2"]
}}"""
                + self._rag_prompt_section(rag_context)
            )),
            ("user", "{pricing_info}")
        ])

        try:
            chain = prompt | self.llm
            response = chain.invoke({
                "pricing_info": json.dumps(pricing_info, ensure_ascii=False)
            })

            result = safe_extract_json(response.content)

            # 输出层 Schema 约束：补全必填字段并强制类型
            result, _ = validate_and_repair(
                result, PRICING_SCHEMA, context="analyze_pricing"
            )
            missing_names = [
                item["competitor"] for item in pricing_info
                if item["competitor"] not in real_pricing_names
            ]
            if missing_names:
                # 对没有官网证据的竞品，不接受 LLM 返回的具体价格/模式，
                # 防止“部分真实”污染整张定价结论。
                result = self._sanitize_unverified_pricing(
                    result, missing_names, preserve_verified=True
                )
                result["analysis"] = (
                    "已获得部分竞品的官方定价；"
                    + "、".join(real_pricing_names)
                    + "可用于核验，"
                    + "、".join(missing_names)
                    + "未获取到官方价格，不能据此比较价格区间。"
                )
            else:
                result["price_range"] = self._derive_price_range(pricing_info)
            result["_source"] = "crawl_assisted"
            result["_confidence"] = "medium"
            result["_evidence_competitors"] = [
                item["competitor"] for item in pricing_info
                if item["competitor"] in real_pricing_names
            ]

            logger.info("Analyzer: 定价分析完成")
            
            return result
        
        except Exception as e:
            logger.error(f"定价分析失败: {e}")
            result = self._llm_fallback_pricing(
                list(competitors_data.keys()), rag_context=rag_context
            )
            result = self._sanitize_unverified_pricing(
                result, list(competitors_data.keys())
            )
            result["analysis"] = "定价分析请求失败，当前没有可验证的价格结论，请访问官网确认。"
            result["recommendations"] = ["检查网络/API 状态后重新抓取官方定价"]
            result["_source"] = "llm_fallback"
            result["_confidence"] = "low"
            result["_warning"] = "基于真实定价的分析失败，已降级为 LLM 推测。"
            return result

    def _sanitize_unverified_pricing(
        self,
        result: Dict[str, Any],
        unverified_names: List[str],
        preserve_verified: bool = False,
    ) -> Dict[str, Any]:
        """移除无来源的数字价格，并给 AI 补全明确标记。"""
        output = dict(result or {})
        models = dict(output.get("pricing_models") or {})
        for name in unverified_names:
            value = models.get(name)
            if preserve_verified and value and str(value).startswith("官方"):
                continue
            models[name] = (
                f"AI 推测：{value}" if value and "待核验" not in str(value)
                else "待核验（未抓取到官方定价）"
            )
        output["pricing_models"] = models
        # 区间无法在缺少官方套餐时可靠计算，禁止沿用 LLM 生成的数字。
        output["price_range"] = {"min": None, "max": None}
        return output

    def _derive_price_range(self, pricing_info: List[Dict[str, Any]]) -> Dict[str, Any]:
        """仅从已抓取套餐中的数值计算价格区间，不读取 LLM 生成的区间。"""
        values = []
        for item in pricing_info:
            for plan in item.get("plans", []) or []:
                if not isinstance(plan, dict):
                    continue
                price = plan.get("price")
                if isinstance(price, (int, float)) and price >= 0:
                    values.append(float(price))
        if not values:
            return {"min": None, "max": None}
        return {"min": min(values), "max": max(values)}

    def analyze_changelog(self, competitors_data: Dict[str, Dict]) -> Dict[str, Dict]:
        """
        分析 Changelog / 版本更新数据（合并 官网 changelog + App Store 版本页 + GitHub Releases）

        Args:
            competitors_data: 竞品数据字典（含 changelog / app_store / github_releases 字段）

        Returns:
            每个竞品的 Changelog 分析结果
            格式: {竞品名: {"latest_version": ..., "recent_updates": ..., ...}}
        """

        logger.info("Analyzer: 开始 Changelog 分析（合并 官网/App Store/GitHub 多源）")

        result = {}

        for comp_name, comp_data in competitors_data.items():
            cl = comp_data.get("changelog", {}) or {}

            # 收集 Changelog 数据（爬虫直接提取的，或 LLM 兜底的）
            comp_result = {
                "latest_version": cl.get("latest_version"),
                "latest_release_date": cl.get("latest_release_date"),
                "recent_updates": list(cl.get("recent_updates", []) or []),
                "update_frequency": cl.get("update_frequency"),
                "_sources": [],
            }

            # 合并 App Store 版本页（releaseNotes / version / 发布日期）
            app_store = comp_data.get("app_store") or {}
            if app_store.get("version") and not comp_result["latest_version"]:
                comp_result["latest_version"] = app_store.get("version")
            if app_store.get("release_date") and not comp_result["latest_release_date"]:
                comp_result["latest_release_date"] = (app_store.get("release_date") or "")[:10]
            if app_store.get("release_notes"):
                comp_result["recent_updates"].append("App Store: " + str(app_store["release_notes"])[:200])
                comp_result["_sources"].append("app_store")

            # 合并 GitHub Releases
            gh = comp_data.get("github_releases") or {}
            for rel in (gh.get("releases") or []):
                tag = rel.get("tag") or rel.get("name") or ""
                if tag and not comp_result["latest_version"]:
                    comp_result["latest_version"] = tag
                body = (rel.get("body") or "").strip()
                if body:
                    comp_result["recent_updates"].append(f"{tag or 'release'}: {body[:160]}")
                    comp_result["_sources"].append("github")

            # 去重 + 裁剪
            seen = set()
            deduped = []
            for u in comp_result["recent_updates"]:
                if u not in seen:
                    seen.add(u)
                    deduped.append(u)
            comp_result["recent_updates"] = deduped[:8]

            # 兜底：如果所有 changelog 字段都为空，用 LLM 知识库补充
            has_changelog = bool(
                comp_result["latest_version"]
                or comp_result["latest_release_date"]
                or comp_result["recent_updates"]
                or comp_result["update_frequency"]
            )
            if not has_changelog:
                logger.info(f"Analyzer: {comp_name} 无版本证据，保留未知，不调用模型猜测")

            from utils.release_records import release_records
            records = release_records(comp_data)
            comp_result['version_records'] = records
            # Multiple platforms cannot be represented as one universal latest version.
            comp_result['latest_version'] = records[0]['version'] if len(records) == 1 else None
            comp_result['latest_release_date'] = records[0]['date'] if len(records) == 1 else None
            comp_result['version_note'] = '最近获取的版本，非全平台最新保证；请核对来源。'
            result[comp_name] = comp_result

        logger.info(f"Analyzer: Changelog 分析完成，共 {len(result)} 个竞品")
        return result

    def analyze_app_feedback(self, competitors_data: Dict[str, Dict]) -> Dict[str, Dict]:
        """
        分析 App Store 评分 / 评论：用户满意度、痛点挖掘。
        无 App Store 数据的竞品标记为 unavailable，不阻断主流程。

        Returns: {竞品名: {available, rating, rating_count, sentiment, pain_points, highlights, ...}}
        """
        logger.info("Analyzer: 开始用户反馈分析（App Store 评分/评论）")
        result = {}
        for comp_name, comp_data in competitors_data.items():
            app_store = comp_data.get("app_store") or {}
            if not app_store or (app_store.get("rating") is None and not app_store.get("reviews")):
                result[comp_name] = {"available": False, "reason": "未获取到 App Store 评分/评论"}
                continue
            reviews = app_store.get("reviews", []) or []
            reviews_block = "\n".join(f"- {r[:200]}" for r in reviews[:12]) if reviews else "（无评论文本）"
            prompt = ChatPromptTemplate.from_messages([
                ("system", """你是用户反馈分析专家。基于 App Store 评分与评论，输出严格 JSON（不要 markdown 代码块）：
{{
  "sentiment": "正面/中性/负面",
  "satisfaction_summary": "一句话满意度总结",
  "pain_points": ["痛点1", "痛点2", "痛点3"],
  "highlights": ["亮点1", "亮点2"]
}}
要求：pain_points 从评论中归纳真实抱怨；highlights 归纳好评点；不要编造。只输出 JSON。"""),
                ("user", "产品：{competitor_name}\n评分：{rating}（{rating_count} 人评分）\n近期评论：\n{reviews}")
            ])
            try:
                chain = prompt | self.llm_extract
                resp = chain.invoke({
                    "competitor_name": comp_name,
                    "rating": app_store.get("rating"),
                    "rating_count": app_store.get("rating_count"),
                    "reviews": reviews_block,
                })
                parsed = safe_extract_json(resp.content)
                if not isinstance(parsed, dict):
                    parsed = {}
                parsed["rating"] = app_store.get("rating")
                parsed["rating_count"] = app_store.get("rating_count")
                parsed["available"] = True
                parsed["_source"] = "api"
                result[comp_name] = parsed
            except Exception as e:
                logger.warning(f"Analyzer: {comp_name} 反馈分析失败: {e}")
                result[comp_name] = {
                    "available": True,
                    "rating": app_store.get("rating"),
                    "rating_count": app_store.get("rating_count"),
                    "sentiment": None,
                    "satisfaction_summary": "评分已获取，评论分析失败",
                    "_source": "api",
                }
        return result

    def analyze_copy_changes(self, competitors_data: Dict[str, Dict]) -> Dict[str, Dict]:
        """
        分析官网文案快照 diff：营销方向调整（A/B 测试痕迹）判断。
        首次采集无历史基线、或本次无变化，均标记为 unavailable，不阻断主流程。

        Returns: {竞品名: {available, direction_changes, emphasis_shift, ab_test_hint, ...}}
        """
        logger.info("Analyzer: 开始官网文案变化分析（快照 diff）")
        result = {}
        for comp_name, comp_data in competitors_data.items():
            snap = comp_data.get("copy_snapshots") or {}
            if not snap:
                result[comp_name] = {"available": False, "reason": "无官网快照"}
                continue
            if not snap.get("has_previous"):
                result[comp_name] = {
                    "available": False,
                    "baseline": True,
                    "reason": "首次采集已建立文案基线，下次运行可对比变化",
                }
                continue
            diff = snap.get("diff") or ""
            if not diff.strip():
                result[comp_name] = {"available": False, "reason": "本次与上次文案无变化"}
                continue
            prompt = ChatPromptTemplate.from_messages([
                ("system", """你是营销文案分析专家。基于两次官网抓取的 diff，判断营销方向调整，输出严格 JSON：
{{
  "direction_changes": ["方向调整1", "方向调整2"],
  "emphasis_shift": "从X转向Y的概括",
  "ab_test_hint": "是否发现 A/B 测试痕迹（如多版本文案并存），给出判断与依据"
}}
要求：基于 diff 内容推断，不要编造；若无明确信号则如实说明。只输出 JSON。"""),
                ("user", "产品：{competitor_name}\n文案 diff（unified diff）：\n{diff}")
            ])
            try:
                chain = prompt | self.llm_extract
                resp = chain.invoke({"competitor_name": comp_name, "diff": diff[:4000]})
                parsed = safe_extract_json(resp.content)
                if not isinstance(parsed, dict):
                    parsed = {}
                parsed["available"] = True
                parsed["_source"] = "diff"
                result[comp_name] = parsed
            except Exception as e:
                logger.warning(f"Analyzer: {comp_name} 文案变化分析失败: {e}")
                result[comp_name] = {"available": True, "reason": "文案有变化但分析失败", "_source": "diff"}
        return result

    def _llm_fallback_changelog(self, competitor_name: str) -> Dict[str, Any]:
        """
        当爬取无 Changelog 数据时，用 LLM 知识库生成版本更新分析
        """
        prompt = ChatPromptTemplate.from_messages([
            ("system", """你是一位产品版本更新分析专家。请基于你的产品知识，分析该产品的近期版本更新情况。
输出严格的 JSON 格式（不要有 markdown 代码块）：
{{
    "latest_version": "最新版本号或模型版本（如 v3.2.1 / DeepSeek-V3 / 豆包 1.5，找不到就填 null）",
    "latest_release_date": "最新发布日期（YYYY-MM-DD，找不到就填 null）",
    "recent_updates": ["近 6-12 个月最重要的更新1", "更新2", "更新3"],
    "update_frequency": "更新频率描述（如每月、每季度、不定期，找不到就填 null）"
}}

要求：
- 对于在线服务、AI 模型、Web 应用等没有固定版本号的产品，请填写其最新模型版本或重大能力发布/里程碑
- recent_updates 至少列出 3 条近 6-12 个月的重要更新
- 不要编造，如果确实不了解则填 null
- 只输出 JSON，不要有其他内容"""),
            ("user", "产品名称：{competitor_name}\n请分析该产品的版本更新情况。")
        ])
        
        chain = prompt | self.llm_extract
        response = chain.invoke({"competitor_name": competitor_name})
        result = safe_extract_json(response.content)
        if not isinstance(result, dict):
            result = {}
        return {
            "latest_version": result.get("latest_version"),
            "latest_release_date": result.get("latest_release_date"),
            "recent_updates": result.get("recent_updates", []) or [],
            "update_frequency": result.get("update_frequency"),
        }

    def _llm_fallback_pricing(self, competitor_names: List[str],
                               rag_context: str = None) -> Dict[str, Any]:
        """
        当爬取无定价数据时，用 LLM 知识库生成定价分析
        """
        competitors_str = "、".join(competitor_names)

        prompt = ChatPromptTemplate.from_messages([
            ("system", (
                """你是一位定价策略专家。请分析以下产品的定价模式和信息。

输出严格的 JSON 格式（不要有 markdown 代码块）：
{{
    "pricing_models": {{"产品A": "定价模式描述", "产品B": "定价模式描述"}},
    "price_range": {{"min": 数字(最低价), "max": 数字(最高月价)}},
    "analysis": "详细的定价对比分析文本（至少100字）",
    "recommendations": ["建议1", "建议2"]
}}

注意：
- pricing_models 的 key 请直接使用真实产品名（如 "Notion"/"Obsidian"），也可用占位名（产品A、竞品A、Product1、Competitor1），
  系统会自动映射回真实竞品名
- price_range 的 min/max 必须为数字（人民币/美元请注明币种），表示月度价格区间；买断制定价可填一次性金额
- 请基于你的知识给出准确的定价信息。只输出 JSON。"""
                + self._rag_prompt_section(rag_context)
            )),
            ("user", f"请分析以下产品的定价：{competitors_str}")
        ])

        try:
            chain = prompt | self.llm_extract
            response = chain.invoke({"products": competitors_str})

            result = safe_extract_json(response.content)

            # 输出层 Schema 约束
            result, _ = validate_and_repair(
                result, PRICING_SCHEMA, context="_llm_fallback_pricing"
            )

            # 🔧 修复B/F：将通用占位名映射回真实竞品名，支持 N 个竞品
            models = result.get("pricing_models", {})
            new_models = {}

            # 1) 真实名直接保留（LLM 已用真实名作 key 的情况）
            real_name_set = set(competitor_names)
            for k, v in models.items():
                if k in real_name_set:
                    new_models[k] = v

            # 2) 缺失的竞品，用通用占位名补齐（产品A/B、竞品A/B、ProductN、CompetitorN）
            missing = [n for n in competitor_names if n not in new_models]
            for name in missing:
                idx = competitor_names.index(name)
                suffix = chr(ord('A') + idx) if idx < 26 else str(idx + 1)
                cand_keys = [
                    f"产品{suffix}", f"竞品{suffix}",
                    f"Product{idx+1}", f"Competitor{idx+1}",
                ]
                for ck in cand_keys:
                    if ck in models and ck not in new_models:
                        new_models[name] = models[ck]
                        break

            if not new_models:
                new_models = models

            result["pricing_models"] = new_models
            logger.info("LLM兜底生成定价分析完成")
            return result

        except Exception as e:
            logger.error(f"LLM兜底定价分析失败: {e}")
            return {
                "pricing_models": {name: "需查询官网确认" for name in competitor_names},
                "price_range": {"min": 0, "max": 0},
                "analysis": f"无法获取{'、'.join(competitor_names)}的详细定价信息，请访问各官网查看最新报价。",
                "recommendations": ["建议访问各产品官网确认最新定价"]
            }
    
    def generate_insights(self, feature_matrix: pd.DataFrame,
                          pricing_analysis: Dict[str, Any],
                          competitor_names: List[str] = None,
                          rag_context: str = None) -> List[str]:
        """
        生成AI洞察

        Args:
            feature_matrix: 功能对比矩阵
            pricing_analysis: 定价分析结果
            competitor_names: 竞品名称列表（用于兜底）
            rag_context: 向量库检索到的相似竞品参考上下文（可选）

        Returns:
            洞察列表
        """

        logger.info("Analyzer: 生成AI洞察")

        # 如果功能矩阵为空，使用竞品名称直接生成洞察
        if feature_matrix is None or (isinstance(feature_matrix, pd.DataFrame) and feature_matrix.empty):
            if competitor_names:
                logger.warning("功能矩阵为空，基于竞品名称生成洞察")
                return self._llm_fallback_insights(
                    competitor_names, pricing_analysis, rag_context=rag_context
                )
            return ["数据不足，无法生成有效洞察"]

        prompt = ChatPromptTemplate.from_messages([
            ("system", (
                """你是一位资深的产品战略顾问。

请基于以下竞品对比数据，生成3-5条有价值的商业洞察。

洞察要求：
1. 指出竞品的差异化定位
2. 分析各自的优劣势
3. 给出战略建议（如果是创业者，应该如何应对）

每条洞察必须满足：
- 引用支撑证据：明确指出它依据的是哪个具体功能或定价事实（例如"Obsidian 无原生实时协作，见功能矩阵/定价"）
- 标注性质：在句首用【事实】或【推测】标明该结论是已确认事实还是推断/建议
- 洞察之间不重复同一论点，避免与"执行摘要"之外的上下文冗余罗列

输出JSON格式：
{{
    "insights": [
        "【事实】洞察1：...（依据：...）",
        "【推测】洞察2：...（依据：...）",
        "【推测】洞察3：..."
    ]
}}

只输出JSON，不要有其他内容。"""
                + self._rag_prompt_section(rag_context)
            )),
            ("user", "证据约束：{evidence_instruction}\n\n功能对比：\n{feature_matrix}\n\n定价分析：\n{pricing_analysis}")
        ])
        
        try:
            chain = prompt | self.llm
            
            # 转换DataFrame为Markdown
            feature_matrix_md = feature_matrix.to_markdown()
            matrix_source = feature_matrix.attrs.get("source", "unknown")
            # llm_assisted 仍然是模型生成的整张矩阵，单元格未必有一一对应
            # 的官网证据；洞察不能因为存在少量真实功能就被标成“事实”。
            inference_only = matrix_source in {"llm_fallback", "llm_assisted"}
            evidence_instruction = (
                "功能矩阵包含 LLM 生成或辅助内容，单元格没有逐项证据映射。所有引用该矩阵的洞察必须标为【推测】，禁止标为【事实】。"
                if inference_only else
                "功能矩阵含真实爬取证据，但 LLM 辅助项仍应标为【推测】。"
            )
            
            response = chain.invoke({
                "feature_matrix": feature_matrix_md,
                "pricing_analysis": json.dumps(pricing_analysis, ensure_ascii=False),
                "evidence_instruction": evidence_instruction,
            })
            
            # 使用安全解析器处理 LLM 可能返回的 markdown 代码块
            result = safe_extract_json(response.content)

            # 输出层 Schema 约束：确保 insights 为字符串数组
            result, _ = validate_and_repair(
                result, INSIGHTS_SCHEMA, context="generate_insights"
            )

            if inference_only:
                result["insights"] = [
                    insight.replace("【事实】", "【推测】")
                    for insight in result["insights"]
                ]

            logger.info(f"Analyzer: 生成了 {len(result['insights'])} 条洞察")
            
            return result["insights"]
        
        except Exception as e:
            # 洞察属于报告的最后一步，不能因为一次网络/API 波动把整个结果
            # 变成“洞察生成失败”。基于已经存在的矩阵生成可解释的本地摘要，
            # 并明确标注为推测，避免把未知状态误写成事实。
            logger.error(f"洞察生成失败: {e}")
            fallback = self._deterministic_insights(
                feature_matrix,
                pricing_analysis,
                competitor_names=competitor_names,
                llm_error=str(e),
            )
            return fallback or ["数据不足，无法生成有效洞察；请检查网络或 API 配置后重试"]

    def _deterministic_insights(
        self,
        feature_matrix: Optional[pd.DataFrame],
        pricing_analysis: Dict[str, Any],
        competitor_names: Optional[List[str]] = None,
        llm_error: str = "",
    ) -> List[str]:
        """LLM 不可用时，从现有证据生成安全的本地摘要。

        这里只统计矩阵中已经出现的标记，不推断产品是否真的具备某项能力。
        因此所有输出都使用“推测”标签；当矩阵全为 ``⚠️`` 时只报告数据缺口，
        不制造竞品优劣结论。
        """
        if not isinstance(feature_matrix, pd.DataFrame) or feature_matrix.empty:
            return []

        names = list(competitor_names or [])
        if not names:
            names = [
                str(col) for col in feature_matrix.columns
                if str(col) not in {"功能", "feature", "Feature"}
            ]
        if not names:
            return []

        stats: Dict[str, Dict[str, int]] = {}
        for name in names:
            values = feature_matrix[name].astype(str).tolist() if name in feature_matrix else []
            stats[name] = {
                "verified": sum("✅" in value for value in values),
                "partial": sum("⚠️" in value for value in values),
                "unsupported": sum("❌" in value for value in values),
                "total": len(values),
            }

        insights: List[str] = []
        verified_total = sum(item["verified"] for item in stats.values())
        partial_total = sum(item["partial"] for item in stats.values())
        if verified_total == 0 and partial_total:
            insights.append(
                "【推测】当前功能矩阵没有可验证的官网功能，"
                f"{partial_total} 个单元格处于待核验状态，暂时不能据此判断竞品功能差异。"
            )
        else:
            ranked = sorted(
                stats.items(), key=lambda pair: pair[1]["verified"], reverse=True
            )
            leader, leader_stats = ranked[0]
            insights.append(
                "【推测】按当前矩阵标记，"
                f"{leader} 的已确认功能数最多（{leader_stats['verified']} 项）；"
                "该排序仅反映当前证据覆盖度，不等同于产品能力排名。"
            )

        missing = [
            f"{name}（{item['partial']} 项待核验）"
            for name, item in stats.items()
            if item["partial"]
        ]
        if missing:
            insights.append(
                "【推测】下一步应优先补充官方功能页、产品文档或应用商店证据："
                + "、".join(missing)
                + "。"
            )

        pricing = pricing_analysis or {}
        pricing_models = pricing.get("pricing_models", {}) if isinstance(pricing, dict) else {}
        if not pricing_models or all(
            not value or "确认" in str(value) or "未知" in str(value)
            for value in pricing_models.values()
        ):
            insights.append(
                "【推测】定价字段缺少可验证来源，建议分别访问官方定价页并记录抓取时间，"
                "不要用本次结果做成本或商业化决策。"
            )
        if llm_error:
            insights.append(
                "【推测】本次自动洞察因 LLM 请求失败而改用本地摘要；"
                "可检查网络、代理和 API 服务状态后重新运行。"
            )
        return insights[:5]

    def _llm_fallback_insights(self, competitor_names: List[str],
                                pricing_analysis: Dict[str, Any],
                                rag_context: str = None) -> List[str]:
        """
        当功能矩阵为空时，基于竞品名称生成洞察（LLM知识库兜底）
        """
        competitors_str = "、".join(competitor_names)

        # 🔧 修复：使用普通字符串拼接构建 system prompt
        # 原因：f-string + 内部 JSON 花括号会导致 LangChain 报错：
        # "Invalid format specifier in f-string template. Nested replacement fields are not allowed."
        _ins = '"insights": ["洞察1：...", "洞察2：...", "洞察3：...", "洞察4：...", "洞察5：..."]'
        system_text = (
            "你是一位资深的产品战略顾问。\n\n"
            "请针对以下竞品，生成 5 条有价值的商业洞察和战略建议：\n\n"
            "洞察要求：\n"
            "1. 指出各产品的核心定位和差异化特点\n"
            "2. 分析目标用户群体的差异\n"
            "3. 对比各自的优劣势\n"
            "4. 市场趋势判断\n"
            "5. 给创业者或产品经理的战略建议\n\n"
            "输出严格的 JSON 格式（不要有 markdown 代码块）：\n"
            "{{" + _ins + "}}\n\n"
            "每条洞察至少 50 字，要有深度。只输出 JSON。"
            + self._rag_prompt_section(rag_context)
        )

        try:
            prompt = ChatPromptTemplate.from_messages([
                ("system", system_text),
                ("user", "请分析以下产品：" + competitors_str)
            ])
            chain = prompt | self.llm
            response = chain.invoke({"products": competitors_str})

            result = safe_extract_json(response.content)

            # 输出层 Schema 约束
            result, _ = validate_and_repair(
                result, INSIGHTS_SCHEMA, context="_llm_fallback_insights"
            )
            insights = result.get("insights", [])
            logger.info(f"LLM兜底生成了 {len(insights)} 条洞察")
            return insights

        except Exception as e:
            logger.error(f"LLM兜底洞察生成失败: {e}")
            # 这里原先使用 competitors_str[0]/[1]，会把“抖音”拆成“抖/音”。
            # 使用完整产品名，并明确标记为推测，避免产生误导性摘要。
            first = competitor_names[0] if competitor_names else "产品A"
            second = competitor_names[1] if len(competitor_names or []) > 1 else "竞品"
            return [
                f"【推测】{first}与{second}的产品定位和用户场景需要进一步核验，当前缺少足够的结构化证据。",
                "【推测】建议从官方功能页、应用商店和实际体验补齐证据，再比较用户场景与产品优劣势。",
                "【推测】关注各产品的生态系统和社区活跃度，这些因素可能影响长期价值。"
            ]
    
    def calculate_similarity(self, comp1_data: Dict, comp2_data: Dict) -> float:
        """
        计算两个竞品的相似度
        
        Args:
            comp1_data: 竞品1数据
            comp2_data: 竞品2数据
        
        Returns:
            相似度 (0-1)
        """
        
        # 基于功能的相似度
        features1 = set(self._get_all_features(comp1_data))
        features2 = set(self._get_all_features(comp2_data))
        
        if not features1 or not features2:
            return 0.0
        
        # Jaccard相似度
        intersection = len(features1 & features2)
        union = len(features1 | features2)
        
        similarity = intersection / union if union > 0 else 0.0
        
        return similarity
    
    def _get_all_features(self, comp_data: Dict) -> List[str]:
        """获取竞品的所有功能"""

        features = comp_data.get("features", {}) or {}

        all_features = []
        all_features.extend(features.get("core", []) or [])
        all_features.extend(features.get("advanced", []) or [])
        
        return all_features


# 测试代码
if __name__ == "__main__":
    # 测试Analysis Agent
    analyzer = AnalysisAgent()
    
    # 模拟数据
    test_data = {
        "Notion": {
            "features": {
                "core": ["文档编辑", "数据库", "看板视图"],
                "advanced": ["API接口", "模板市场"]
            },
            "pricing": {
                "model": "subscription",
                "plans": [
                    {"name": "Free", "price": 0},
                    {"name": "Plus", "price": 10, "period": "month"}
                ]
            }
        },
        "Obsidian": {
            "features": {
                "core": ["文档编辑", "双向链接", "本地存储"],
                "advanced": ["图谱视图", "插件系统"]
            },
            "pricing": {
                "model": "one-time",
                "plans": [
                    {"name": "个人", "price": 0},
                    {"name": "商用", "price": 50, "period": "one-time"}
                ]
            }
        }
    }
    
    # 测试功能对比
    matrix = analyzer.compare_features(test_data)
    print("\n功能对比矩阵:")
    print(matrix.to_markdown())
    
    # 测试定价分析
    pricing = analyzer.analyze_pricing(test_data)
    print("\n定价分析:")
    print(json.dumps(pricing, indent=2, ensure_ascii=False))
    
    # 测试洞察生成
    insights = analyzer.generate_insights(matrix, pricing)
    print("\nAI洞察:")
    for i, insight in enumerate(insights, 1):
        print(f"{i}. {insight}")
