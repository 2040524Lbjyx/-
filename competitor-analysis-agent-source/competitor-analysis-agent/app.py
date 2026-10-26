"""
竞品分析多Agent系统 - Streamlit Web界面（升级版）

本版本相对原版升级：
1. 并行爬取可视化 —— 把 coordinator 的 progress_callback (start/done/failed) 映射到
   实时竞品状态卡片（in_progress / done / failed）。
2. 并发度可调 —— 侧边栏 1-4 滑动条。
3. 结构化数据展示 —— 把 features / pricing / changelog 解析成卡片 + DataFrame。
4. 雷达图 / 价格对比柱图 —— 用 streamlit 原生 bar_chart 避免新依赖。
5. 错误/失败隔离 —— 单个竞品失败不影响其他，结果里以 ❌ 标记。
6. 后端调用 collect_many 而非串行 collect（与 crawler.py 升级配套）。
"""

import os
os.environ.setdefault("STREAMLIT_SERVER_FILE_WATCHER_TYPE", "none")  # 避免热重载卡死

import streamlit as st
import sys
import time
import json
import re
import logging
import threading
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

# 加载 .env
load_dotenv(Path(__file__).parent / ".env")

# Streamlit 默认只把日志写到启动终端；将完整异常持久化，便于区分
# 连接权限、代理、限流和页面反爬，而不是只在报告中显示 Connection error。
_log_dir = Path(__file__).parent / "logs"
try:
    _log_dir.mkdir(parents=True, exist_ok=True)
    _root_logger = logging.getLogger()
    if not any(getattr(handler, "_competitor_file_handler", False) for handler in _root_logger.handlers):
        _file_handler = logging.FileHandler(_log_dir / "app.log", encoding="utf-8")
        _file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        _file_handler._competitor_file_handler = True
        _root_logger.addHandler(_file_handler)
        _root_logger.setLevel(logging.INFO)
except Exception:
    # 日志目录不可写时不阻断网站启动，仍保留 Streamlit 默认日志输出。
    pass

# ==================== 环境检测 ====================
def check_env_file():
    """检查 .env 文件是否存在，不存在则自动创建"""
    env_file = Path(__file__).parent / ".env"
    env_example = Path(__file__).parent / ".env.example"
    
    if not env_file.exists():
        if env_example.exists():
            try:
                import shutil
                shutil.copy(env_example, env_file)
                return "warning", "⚠️ 未找到 .env 文件，已自动从 .env.example 创建\n请编辑 .env 文件，填入你的 API Key"
            except Exception as e:
                return "error", f"❌ 自动创建 .env 失败：{e}"
        else:
            return "error", "❌ 未找到 .env 和 .env.example 文件\n请手动创建 .env 文件并填入 API Key"
    return None, None

def check_playwright():
    """检查 Playwright 是否可用，支持复用本机 Chrome/Edge。"""
    try:
        import importlib.util
        if not importlib.util.find_spec("playwright"):
            return False, "当前 Python 环境未安装 Playwright 包"

        browser_candidates = [
            os.environ.get("CRAWL_BROWSER_EXECUTABLE"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ]
        for executable in browser_candidates:
            if executable and os.path.exists(executable):
                return True, f"使用本机浏览器：{executable}"

        # 没有系统浏览器时，才检查 Playwright 自带内核是否已经落盘。
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            bundled = p.chromium.executable_path
        if bundled and os.path.exists(bundled):
            return True, "使用 Playwright Chromium"
        return False, "未找到可用的 Chrome/Edge 或 Playwright Chromium"
    except Exception as e:
        return False, str(e)

# 运行 .env 检测
_env_status, _env_message = check_env_file()
if _env_status == "warning":
    st.warning(_env_message)
elif _env_status == "error":
    st.error(_env_message)

# 项目根路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))
from utils.runtime_health import check_llm_endpoint, connection_error_message

# Playwright 检测状态（使用 session_state 持久化）
if "playwright_checked" not in st.session_state:
    st.session_state.playwright_checked = False
    st.session_state.playwright_available = False
    st.session_state.playwright_error = ""

# ============================== 页面配置 ==============================
st.set_page_config(
    page_title="竞品分析多Agent系统",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 自定义 CSS：让状态卡片更醒目
st.markdown("""
<style>
.crawl-card {
    border: 1px solid rgba(120,120,120,0.25);
    border-radius: 10px;
    padding: 14px 16px;
    margin: 6px 0;
    background: rgba(255,255,255,0.6);
}
.crawl-card.in_progress { border-left: 5px solid #f5a623; background: #fff7e6; }
.crawl-card.done        { border-left: 5px solid #2ecc71; background: #eafff3; }
.crawl-card.failed      { border-left: 5px solid #e74c3c; background: #ffecec; }
.crawl-card.pending     { border-left: 5px solid #95a5a6; background: #f4f6f7; }
.crawl-card .name  { font-weight: 600; font-size: 1.05em; }
.crawl-card .meta  { color: #666; font-size: 0.85em; margin-top: 4px; }
</style>
""", unsafe_allow_html=True)

# ============================== 顶部 ==============================
st.title("📊 竞品分析多Agent系统")
st.caption("并行爬取 · 智能分析 · 自动报告")
st.markdown("---")


# ============================== 侧边栏 ==============================
st.sidebar.title("控制面板")
st.sidebar.subheader("分析设置")

output_format = st.sidebar.selectbox(
    "输出格式", options=["markdown", "html"], index=0
)
verbose_mode = st.sidebar.checkbox("详细模式（显示Agent执行过程）", value=False)
use_demo_mode = st.sidebar.checkbox(
    "演示模式（使用模拟数据，无需API Key）", value=True
)

if use_demo_mode:
    st.warning(
        "🎭 当前为演示模式：页面、报告和指标均使用固定模拟数据，"
        "仅用于展示交互流程，不能作为真实竞品结论。"
    )

# ==================== API 配置界面 ====================
with st.sidebar.expander("⚙️ API 配置", expanded=False):
    st.markdown("**配置 API Key（用于真实模式）**")
    
    # 从环境变量读取当前值
    current_key = os.getenv("OPENAI_API_KEY", "")
    current_base = os.getenv("OPENAI_BASE_URL", "")
    current_model = os.getenv("OPENAI_MODEL", "gpt-4")
    
    api_key = st.text_input(
        "API Key",
        value=current_key,
        type="password",
        help="输入你的 OpenAI 或 DeepSeek API Key"
    )
    
    api_base = st.text_input(
        "API Base URL（可选）",
        value=current_base,
        help="DeepSeek 用户填写：https://api.deepseek.com/v1"
    )
    
    api_model = st.text_input(
        "模型名称（可选）",
        value=current_model,
        help="例如：gpt-4, gpt-3.5-turbo, deepseek-chat"
    )
    
    if st.button("💾 保存配置", key="save_api_config"):
        # 保存到 .env 文件
        env_file = Path(__file__).parent / ".env"
        env_lines = []
        
        # 读取现有配置
        if env_file.exists():
            with open(env_file, "r", encoding="utf-8") as f:
                env_lines = f.readlines()
        
        # 更新或添加配置
        updated = {"OPENAI_API_KEY": api_key, "OPENAI_BASE_URL": api_base, "OPENAI_MODEL": api_model}
        new_lines = []
        updated_keys = set()
        
        for line in env_lines:
            for key, value in updated.items():
                if line.startswith(f"{key}="):
                    new_lines.append(f"{key}={value}\n")
                    updated_keys.add(key)
                    break
            else:
                new_lines.append(line)
        
        # 添加未找到的配置
        for key, value in updated.items():
            if key not in updated_keys:
                new_lines.append(f"{key}={value}\n")
        
        # 写回文件
        with open(env_file, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        
        # 更新环境变量
        os.environ["OPENAI_API_KEY"] = api_key
        if api_base:
            os.environ["OPENAI_BASE_URL"] = api_base
        if api_model:
            os.environ["OPENAI_MODEL"] = api_model
        
        st.success("✅ 配置已保存到 .env 文件")
        time.sleep(0.5)
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("⚡ 性能设置")
max_workers = st.sidebar.slider(
    "并发度（并行爬取的竞品数）",
    min_value=1, max_value=4, value=3,
    help="⚠️ 过高可能触发反爬虫，建议 2-4。1 = 串行。",
)
st.sidebar.caption(
    f"当前配置：{max_workers} 路并发 — 多个竞品同时爬取，总耗时 ≈ 单个最慢的"
)

st.sidebar.markdown("---")
st.sidebar.subheader("关于")
st.sidebar.info(
    "基于 LangGraph 的多 Agent 竞品分析系统。\n\n"
    "**Agent 角色**\n"
    "- 🎯 Coordinator: 调度\n"
    "- 🕷️ Crawler: 并行采集\n"
    "- 🧠 Analyzer: 数据分析\n"
    "- 📝 Reporter: 报告生成\n\n"
    "**核心升级**\n"
    "- ✅ 多竞品并行爬取（ThreadPoolExecutor）\n"
    "- ✅ Playwright 复用 + 请求加速\n"
    "- ✅ 单点失败隔离"
)


# ============================== 演示数据生成器（无 API Key 也可玩） ==============================

def _extract_competitors_from_query(query: str) -> list:
    """与真实模式的本地降级路径共用名称解析。"""
    from utils.query_parser import extract_competitors
    return extract_competitors(query)


def _select_example(query: str) -> None:
    st.session_state["__user_query_input__"] = query


def _strip_insight_prefix(text: str) -> str:
    """去掉洞察文本自带的 '洞察N：' 前缀，避免与报告标题重复标号（与 reporter 一致）。"""
    if not text:
        return text
    return re.sub(r"^\s*洞察\s*\d+\s*[:：]\s*", "", text).strip()


def _render_pricing_analysis(pf: dict) -> str:
    """把后端返回的 pricing_analysis 结构化字典渲染成易读的 Markdown。"""
    md = []

    # 1. 定价模式对比表
    pricing_models = pf.get("pricing_models") or {}
    if pricing_models:
        md.append("### 定价模式对比")
        md.append("| 竞品 | 定价模式 |")
        md.append("|---|---|")
        for comp, desc in pricing_models.items():
            md.append(f"| {comp} | {desc} |")
        md.append("")

    # 2. 价格区间
    price_range = pf.get("price_range") or {}
    if price_range and any(price_range.values()):
        md.append("### 价格区间")
        min_p = price_range.get("min")
        max_p = price_range.get("max")
        if min_p is not None and max_p is not None:
            md.append(f"- 最低价：**{min_p}** 美元/月")
            md.append(f"- 最高价：**{max_p}** 美元/月")
        md.append("")

    # 3. 详细分析
    analysis = pf.get("analysis", "")
    if analysis and isinstance(analysis, str):
        md.append("### 详细分析")
        md.append(analysis)
        md.append("")

    # 4. 建议
    recommendations = pf.get("recommendations", []) or []
    if recommendations:
        md.append("### 建议")
        for r in recommendations:
            md.append(f"- {r}")
        md.append("")

    return "\n".join(md)


def _detect_demo_category(competitors: list) -> str:
    """根据竞品名猜测演示模式所属的产品大类，让演示矩阵更贴近真实场景。"""
    names = " ".join(competitors).lower()
    if any(k in names for k in ["抖音", "快手", "tiktok", "kuaishou", "youtube", "bilibili", "哔哩哔哩", "视频", "直播"]):
        return "short_video"
    if any(k in names for k in ["notion", "obsidian", "logseq", "evernote", "onenote", "语雀", "wolai", "为知", "笔记", "知识"]):
        return "note"
    if any(k in names for k in ["飞书", "钉钉", "lark", "slack", "teams", "企业微信", "办公", "协作", "文档"]):
        return "office"
    if any(k in names for k in ["jira", "linear", "asana", "trello", "teambition", "tower", "禅道", "项目管理"]):
        return "pm"
    if any(k in names for k in ["figma", "sketch", "xd", "canva", "墨刀", "mastergo", "pixso", "设计"]):
        return "design"
    return "generic"


def _make_demo_data(competitors: list) -> dict:
    """生成结构化模拟数据，喂给可视化与表格"""
    import pandas as pd

    category = _detect_demo_category(competitors)
    feature_catalog = {
        "short_video": [
            "短视频拍摄", "滤镜特效", "视频剪辑", "直播", "推荐算法",
            "电商带货", "创作者工具", "社交互动", "私信", "青少年模式",
            "广告变现", "本地生活", "直播连麦", "合拍/同框", "评论区"
        ],
        "note": [
            "文档编辑", "双向链接", "图谱视图", "全文搜索", "Markdown",
            "模板", "标签", "导入导出", "离线访问", "移动端", "协作", "数据库", "插件扩展"
        ],
        "office": [
            "即时通讯", "文档协作", "表格", "日程/日历", "视频会议",
            "云盘", "审批/流程", "组织架构", "应用市场", "权限管理", "移动端", "API", "邮件"
        ],
        "pm": [
            "任务管理", "看板视图", "甘特图", "里程碑", "缺陷跟踪",
            "Sprint", "工时统计", "自动化工作流", "权限管理", "报表", "集成", "移动端"
        ],
        "design": [
            "矢量编辑", "原型设计", "组件库", "自动布局", "版本历史",
            "评论标注", "设计交付", "插件生态", "协作编辑", "设计系统", "导入导出", "离线访问"
        ],
        "generic": [
            "核心功能A", "核心功能B", "高级功能A", "数据管理", "协作",
            "移动端", "API", "安全", "扩展", "自动化", "分析", "导出", "导入"
        ],
    }
    feature_names = feature_catalog.get(category, feature_catalog["generic"])

    import random
    random.seed(42)  # 演示数据稳定
    matrix = {"功能": feature_names}
    for comp in competitors:
        matrix[comp] = [random.choice(["✅", "❌"]) for _ in feature_names]
    feature_matrix = pd.DataFrame(matrix)

    plans = []
    for comp in competitors:
        plans.append({
            "竞品": comp,
            "定价模式": random.choice(["订阅制(SaaS)", "买断制", "免费增值(Freemium)"]),
            "免费版": "有" if random.random() > 0.3 else "无",
            "起步价(¥/月)": random.choice([0, 19, 39, 59, 99]),
            "企业版": "有" if random.random() > 0.4 else "无",
        })
    pricing_df = pd.DataFrame(plans)

    changelogs = {}
    for comp in competitors:
        changelogs[comp] = {
            "latest_version": f"v{random.randint(2, 8)}.{random.randint(0, 9)}.{random.randint(0, 20)}",
            "latest_release_date": f"2026-0{random.randint(1,6)}-{random.randint(1,28):02d}",
            "recent_updates": [f"新增{random.choice(['AI 能力', '性能优化', '安全加固', '体验改进'])}模块" for _ in range(3)],
            "update_frequency": random.choice(["低", "中", "高", "极高"]),
        }
    changelog_df = pd.DataFrame(changelogs).T.reset_index().rename(columns={"index": "竞品"})

    # 演示模式：用户反馈（App Store 评分/评论）模拟
    app_feedback_analysis = {}
    for comp in competitors:
        app_feedback_analysis[comp] = {
            "available": True,
            "rating": round(random.uniform(3.8, 4.8), 1),
            "rating_count": random.randint(50000, 2000000),
            "sentiment": random.choice(["正面", "中性", "正面"]),
            "satisfaction_summary": f"{comp} 用户整体满意，核心功能口碑较好",
            "pain_points": ["部分高级功能需付费", "偶发卡顿", "客服响应偏慢"],
            "highlights": ["界面易用", "更新频繁", "免费额度友好"],
            "_source": "demo",
        }
    # 演示模式：官网文案变化模拟（首次基线）
    copy_changes_analysis = {}
    for comp in competitors:
        copy_changes_analysis[comp] = {
            "available": False,
            "baseline": True,
            "reason": "演示模式：首次采集已建立文案基线，真实运行下次可对比变化",
        }

    c0 = competitors[0]
    c1 = competitors[1] if len(competitors) > 1 else competitors[0]

    # 演示模式洞察也按产品大类生成，避免对抖音/快手输出"本地优先+云端同步"类错误结论
    if category == "short_video":
        insights = [
            f"洞察1：{c0} 拥有更强的推荐算法和电商闭环，适合创作者变现",
            f"洞察2：{c1} 在下沉市场用户基础和直播生态上更具优势",
            f"洞察3：两者都在短视频拍摄、滤镜特效和直播等核心功能上趋同，差异化主要在社区氛围和变现工具",
            "洞察4：市场机会在于垂直内容赛道（知识科普、本地生活、短剧）做差异化运营",
            "洞察5：新入局者应优先打磨内容分发效率和创作者激励，而非复制全功能"
        ]
    elif category == "note":
        insights = [
            f"洞察1：{c0} 主打团队协作 / 云端同步，适合企业用户",
            f"洞察2：{c1} 专注个人知识管理 / 本地优先，隐私性更优",
            f"洞察3：两者定位不同 — {c0} 偏协作工具，{c1} 偏笔记工具",
            "洞察4：市场机会在于结合两者优势 — 本地优先 + 选择性云同步",
            "洞察5：建议创业聚焦垂直场景（开发团队 / 学术研究）做差异化"
        ]
    elif category == "office":
        insights = [
            f"洞察1：{c0} 在即时通讯和组织协同上更成熟，适合大型企业",
            f"洞察2：{c1} 在文档协作和第三方集成上更有优势",
            f"洞察3：两者都围绕'云+协作'构建，差异化在目标客群和生态开放度",
            "洞察4：市场机会在于 AI 助手与现有办公流程的深度结合",
            "洞察5：新入局者应避免正面竞争，聚焦垂直行业或特定团队规模"
        ]
    elif category == "pm":
        insights = [
            f"洞察1：{c0} 更适合敏捷开发团队，迭代和自动化能力强",
            f"洞察2：{c1} 在易用性和交互体验上更优，适合中小型团队",
            f"洞察3：两者核心功能趋同，差异主要在配置灵活性和上手门槛",
            "洞察4：市场机会在于 AI 辅助排期、风险预警和跨工具数据打通",
            "洞察5：新入局者应从特定场景（如游戏研发、硬件制造）切入"
        ]
    elif category == "design":
        insights = [
            f"洞察1：{c0} 在实时协作和组件生态上更完善，适合大型设计团队",
            f"洞察2：{c1} 在特定平台或轻量化场景上有优势",
            f"洞察3：两者都在向'设计系统+交付'一体化演进",
            "洞察4：市场机会在于 AI 生成设计与现有设计资产的结合",
            "洞察5：新入局者应避免做通用设计工具，聚焦垂直输出（如营销图、3D、动效）"
        ]
    else:
        insights = [
            f"洞察1：{c0} 在核心功能覆盖上更广，适合企业用户",
            f"洞察2：{c1} 在特定场景下体验更优，适合垂直用户",
            f"洞察3：两者定位存在差异，{c0} 偏全能，{c1} 偏专精",
            "洞察4：市场机会在于整合双方优势，提供更完整的解决方案",
            "洞察5：建议创业聚焦未被充分服务的细分场景，建立差异化壁垒"
        ]
    # 与 reporter 保持一致：去掉洞察自带前缀，避免与报告标题重复标号
    insights = [_strip_insight_prefix(x) for x in insights]
    return {
        "feature_matrix": feature_matrix,
        "pricing_df": pricing_df,
        "changelog_df": changelog_df,
        "app_feedback_analysis": app_feedback_analysis,
        "copy_changes_analysis": copy_changes_analysis,
        "insights": insights,
    }


def _generate_demo_report(user_query: str, competitors: list, data: dict,
                          output_format: str) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    matrix_md = data["feature_matrix"].to_markdown(index=False)
    pricing_md = data["pricing_df"].to_markdown(index=False)
    changelog_md = data["changelog_df"].to_markdown(index=False)
    insight_md = "\n".join(f"- {ins}" for ins in data["insights"])

    report = f"""# 竞品分析报告

> 生成时间: {timestamp} | 查询: {user_query} | 模式: **演示模式（模拟数据）**

---

## 一、执行摘要

- **竞品数量**: {len(competitors)}
- **功能维度**: {len(data['feature_matrix'])} 项
- **AI 洞察**: {len(data['insights'])} 条

---

## 二、功能对比矩阵

{matrix_md}

---

## 三、定价策略

{pricing_md}

---

## 四、版本更新活跃度

{changelog_md}

---

## 五、AI 洞察与建议

{insight_md}

---

*由竞品分析多 Agent 系统自动生成（演示模式）*
"""
    if output_format == "html":
        report = report.replace("\n", "<br>\n")
        report = f"<html><head><meta charset='utf-8'><title>竞品分析报告</title></head><body>{report}</body></html>"
    return report


# ============================== 状态卡片渲染 ==============================
def _render_crawl_cards(states: dict, placeholder: "st.delta_generator.DeltaGenerator"):
    """把 {name: {status, msg, ts}} 渲染成卡片网格"""
    if not states:
        placeholder.info("等待任务开始…")
        return
    cols = placeholder.columns(min(len(states), 4))
    icon = {"pending": "⏳", "in_progress": "🔄", "done": "✅", "failed": "❌"}
    label = {"pending": "等待中", "in_progress": "爬取中", "done": "完成", "failed": "失败"}
    for col, (name, s) in zip(cols, states.items()):
        st_ = s.get("status", "pending")
        meta = s.get("msg", "")
        ts = s.get("ts", "")
        col.markdown(
            f"""<div class="crawl-card {st_}">
                <div class="name">{icon.get(st_, '⏳')} {name}</div>
                <div class="meta">状态：{label.get(st_, st_)}</div>
                <div class="meta">{meta}</div>
                <div class="meta">⏱ {ts}</div>
            </div>""",
            unsafe_allow_html=True,
        )


def _embed_images_in_markdown(md: str, base_dir: str = "reports") -> str:
    """
    把 Markdown 里的 ![alt](rel_path.png) 图片引用替换为 base64 内嵌的 <img> 标签，
    这样 st.markdown(content, unsafe_allow_html=True) 能正确显示图表。

    - base_dir: 图片文件所在的根目录（相对于项目根）
    """
    import base64, os, re

    def _replace(match):
        alt = match.group(1)
        path = match.group(2)
        # 尝试绝对路径
        abs_path = path if os.path.isabs(path) else os.path.join(base_dir, path)
        if not os.path.isfile(abs_path):
            return match.group(0)  # 保留原样
        try:
            with open(abs_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("utf-8")
            ext = os.path.splitext(abs_path)[1].lower().lstrip(".")
            mime = f"image/{ext}" if ext in ("png", "jpg", "jpeg", "gif", "svg") else "image/png"
            return f'<img src="data:{mime};base64,{b64}" alt="{alt}" style="max-width:100%;">'
        except Exception:
            return match.group(0)

    return re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', _replace, md)


# ============================== 主 Tabs ==============================
tab1, tab2, tab3, tab4 = st.tabs(["📝 新建分析", "📊 分析结果", "🔍 向量搜索", "📚 历史记录"])

# ====== Tab 1 ======
with tab1:
    st.header("新建竞品分析")

    st.markdown("#### 1. 明确本次决策问题")
    purpose = st.selectbox(
        "分析目的",
        ["版本规划", "产品立项", "定价决策", "竞品汇报"],
        help="不同目的会影响系统重点关注的内容。",
    )
    own_product = st.text_input(
        "自身产品（可选）",
        placeholder="例如：我们的团队知识库产品",
        help="填写后，系统会把结论组织为相对于自身产品的机会与风险。",
    )
    d1, d2 = st.columns(2)
    with d1:
        target_users = st.text_input("目标用户（可选）", placeholder="例如：20～100人研发团队")
        market = st.text_input("市场范围", value="中国大陆", placeholder="地区 / 行业 / 币种")
    with d2:
        dimensions = st.multiselect(
            "分析维度",
            ["核心功能", "定价策略", "版本更新", "用户反馈", "官网文案"],
            default=["核心功能", "定价策略"],
        )
        time_scope = st.selectbox("数据时效", ["以当前可获取信息为准", "最近30天", "最近90天", "最近一年"])

    st.markdown("#### 2. 输入竞品")
    input_mode = st.radio("如何选择竞品", ["我已知道竞品", "帮我找竞品"], horizontal=True)
    confirmed_candidates = []
    if input_mode == "帮我找竞品":
        from ui.discovery import render_discovery
        confirmed_candidates = render_discovery(own_product, market, target_users)
        raw_query = "分析" + "、".join(c["name"] for c in confirmed_candidates) if confirmed_candidates else ""
    else:
        # 手动输入保持原有入口；自动发现仅在显式确认后进入分析。
        raw_query = st.text_input(
            "输入分析需求（自然语言）",
            placeholder="例如：分析Notion和Obsidian的功能和定价",
            help="用自然语言描述你想分析的竞品",
            key="__user_query_input__",
        ).strip()
    confirmed_names = [c["name"] for c in confirmed_candidates]
    context_parts = [
        f"分析目的：{purpose}",
        f"分析维度：{'、'.join(dimensions) if dimensions else '核心功能'}",
        f"市场范围：{market}",
        f"数据时效：{time_scope}",
    ]
    if own_product.strip():
        context_parts.append(f"自身产品：{own_product.strip()}")
    if target_users.strip():
        context_parts.append(f"目标用户：{target_users.strip()}")
    user_query = f"{raw_query}。{'；'.join(context_parts)}" if raw_query else ""

    if input_mode == "我已知道竞品":
        st.markdown("**示例查询：**")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.button("📝 Notion vs Obsidian", on_click=_select_example, args=("分析Notion和Obsidian",))
        with c2:
            st.button("🎨 Figma vs Sketch", on_click=_select_example, args=("对比Figma和Sketch",))
        with c3:
            st.button("📋 Jira vs Linear", on_click=_select_example, args=("分析Jira和Linear",))

    if raw_query:
        st.info(
            f"系统将分析：{raw_query}\n\n"
            f"目的：{purpose} ｜ 维度：{'、'.join(dimensions) if dimensions else '核心功能'} ｜ "
            f"范围：{market} ｜ 时效：{time_scope}"
        )

    can_start = bool(user_query) and (use_demo_mode or bool(os.getenv("OPENAI_API_KEY")))
    if not use_demo_mode and not os.getenv("OPENAI_API_KEY"):
        st.warning("⚠️ 真实模式需要 OPENAI_API_KEY，请先在 .env 中配置，或勾选演示模式")

    if st.button("🚀 开始分析", type="primary", disabled=not can_start):
        if not user_query:
            st.error("请输入分析需求！")
        else:
            # 进度区
            progress_bar = st.progress(0)
            status_text = st.empty()
            time_text = st.empty()

            # 并行爬取实时卡片区
            st.markdown("##### 🕷️ 并行爬取状态")
            crawl_cards_ph = st.empty()

            # 日志区
            log_container = st.container() if verbose_mode else None
            log_lines = []
            log_lock = threading.Lock()

            start_time = time.time()

            def fmt_time(s):
                return f"{int(s)}秒" if s < 60 else f"{int(s//60)}分{int(s%60)}秒"

            # 进度回调
            def progress_callback(progress: int, message: str):
                elapsed = time.time() - start_time
                remain = "计算中…" if progress <= 5 else fmt_time(max(0, elapsed / (progress / 100) - elapsed))
                progress_bar.progress(progress)
                status_text.text(f"🔄 {message}")
                time_text.text(f"⏱️ 已用时: {fmt_time(elapsed)} | 预估剩余: {remain}")

            # 日志回调
            def log_callback(message: str):
                if log_container is None:
                    return
                with log_lock:
                    log_lines.append(f"[{fmt_time(time.time()-start_time)}] {message}")
                    if len(log_lines) > 200:
                        log_lines.pop(0)
                log_container.empty()
                with log_container:
                    st.markdown("#### 📋 详细执行日志")
                    st.code("\n".join(log_lines), language="text")

            try:
                progress_callback(10, "📝 初始化…")

                if use_demo_mode:
                    # ====== 演示模式：模拟并行爬取的可视化效果 ======
                    # 从查询中识别竞品：优先用稳健提取（支持 N 个竞品），
                    # 否则回退到已知配对默认值
                    q = user_query.lower()
                    demo_map = {
                        "notion": ["Notion", "Obsidian"],
                        "obsidian": ["Notion", "Obsidian"],
                        "figma": ["Figma", "Sketch"],
                        "sketch": ["Figma", "Sketch"],
                        "jira": ["Jira", "Linear"],
                        "linear": ["Jira", "Linear"],
                    }
                    # 只从用户原始输入识别竞品，避免把“分析目的/市场范围”等上下文误识别为产品名。
                    extracted = confirmed_names or _extract_competitors_from_query(raw_query)
                    if len(extracted) >= 2:
                        competitors = extracted
                    else:
                        competitors = ["Notion", "Obsidian"]
                        for k, v in demo_map.items():
                            if k in q:
                                competitors = v
                                break

                    log_callback(f"识别到 {len(competitors)} 个竞品: {competitors}")
                    log_callback(f"并发度 = {max_workers}")

                    # 初始化所有卡片为 pending
                    crawl_states = {c: {"status": "pending", "msg": "等待调度", "ts": fmt_time(0)} for c in competitors}
                    _render_crawl_cards(crawl_states, crawl_cards_ph)

                    # 演示模式：用 ThreadPoolExecutor 真正并发 sleep，模拟并行爬取
                    progress_callback(20, f"🎭 演示模式（{len(competitors)} 个竞品，{max_workers} 路并发）")

                    import concurrent.futures
                    completed = []
                    # 每个竞品模拟不同的爬取耗时（秒），让并行效果肉眼可见
                    crawl_seconds = {
                        competitors[0][0].upper(): 1.8,
                        competitors[1][0].upper(): 1.2,
                    }
                    if len(competitors) > 2:
                        crawl_seconds[competitors[2][0].upper()] = 1.5
                    if len(competitors) > 3:
                        crawl_seconds[competitors[3][0].upper()] = 0.9

                    def _simulate_crawl(name: str):
                        """模拟单个竞品的爬取（sleep 不同时间）"""
                        sec = crawl_seconds.get(name[0].upper(), 1.0)
                        time.sleep(sec)
                        return name, sec

                    # 分批提交（每批最多 max_workers 个），批内真正并发
                    rounds = [
                        competitors[i:i + max_workers]
                        for i in range(0, len(competitors), max_workers)
                    ]

                    for r_idx, batch in enumerate(rounds):
                        # 本批全部标记为 in_progress
                        for name in batch:
                            crawl_states[name]["status"] = "in_progress"
                            crawl_states[name]["msg"] = f"正在下载 {name} 官网 / 功能 / 定价页…"
                            crawl_states[name]["ts"] = fmt_time(time.time() - start_time)
                        _render_crawl_cards(crawl_states, crawl_cards_ph)
                        log_callback(f"[演示] 并行批次 {r_idx+1}/{len(rounds)} 开始: {batch}")

                        # 真正并发 sleep
                        with concurrent.futures.ThreadPoolExecutor(max_workers=len(batch)) as ex:
                            futures = {ex.submit(_simulate_crawl, name): name for name in batch}
                            for fut in concurrent.futures.as_completed(futures):
                                name, sec = fut.result()
                                crawl_states[name]["status"] = "done"
                                crawl_states[name]["msg"] = "核心 2 / 高级 0 / 定价 2 项"
                                crawl_states[name]["ts"] = fmt_time(time.time() - start_time)
                                completed.append(name)
                                _render_crawl_cards(crawl_states, crawl_cards_ph)
                                log_callback(f"[演示] ✅ {name} 爬取完成（耗时 {sec}s）")

                        progress_callback(
                            30 + int(20 * len(completed) / max(1, len(competitors))),
                            f"✅ 已完成 {len(completed)}/{len(competitors)}",
                        )
                        log_callback(f"[演示] 批次 {r_idx+1}/{len(rounds)} 全部完成")

                    # 分析 & 报告
                    progress_callback(70, "🧠 分析功能对比与定价策略（模拟）…")
                    data = _make_demo_data(competitors)

                    progress_callback(90, "📝 生成分析报告…")
                    time.sleep(0.4)
                    report_content = _generate_demo_report(user_query, competitors, data, output_format)

                    # 演示报告与真实报告物理隔离，避免进入正式历史库和后续检索。
                    reports_dir = project_root / "reports" / "demo"
                    reports_dir.mkdir(parents=True, exist_ok=True)
                    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                    ext = ".md" if output_format == "markdown" else ".html"
                    report_path = str(reports_dir / f"DEMO_report_{ts}{ext}")
                    with open(report_path, "w", encoding="utf-8") as f:
                        f.write(report_content)

                    progress_callback(100, "✅ 分析完成！")
                    time_text.text(f"⏱️ 总用时: {fmt_time(time.time() - start_time)}")
                    st.session_state.last_result = {
                        "status": "success",
                        "report_path": report_path,
                        "competitors": competitors,
                        "data": data,
                        "elapsed": time.time() - start_time,
                        "max_workers": max_workers,
                        "errors": [],
                        "mode": "demo",
                        "task_context": {
                            "purpose": purpose,
                            "own_product": own_product,
                            "target_users": target_users,
                            "dimensions": dimensions,
                            "market": market,
                            "time_scope": time_scope,
                        },
                    }
                    st.success("✅ 演示分析完成。请打开上方“分析结果”标签查看完整结果。")
                    st.session_state.active_tab = "results"

                else:
                    # ====== 真实模式：调用 CoordinatorAgent ======
                    # 在启动浏览器和多阶段 Agent 前先检查 LLM 接口，避免用户等待后才发现
                    # 网络、鉴权或限流问题。
                    llm_ok, llm_category, llm_detail = check_llm_endpoint(
                        os.getenv("OPENAI_API_KEY", ""),
                        os.getenv("OPENAI_BASE_URL", "") or None,
                    )
                    if not llm_ok:
                        friendly = connection_error_message(llm_category)
                        error = f"PREFLIGHT: LLM连接检查失败（{llm_category}）：{friendly} 原始信息：{llm_detail}"
                        st.session_state.last_result = {
                            "status": "failed",
                            "mode": "real",
                            "competitors": [],
                            "data": {},
                            "errors": [error],
                            "elapsed": time.time() - start_time,
                            "max_workers": max_workers,
                        }
                        raise RuntimeError(error)
                    
                    # ==================== Playwright 检测 ====================
                    if not st.session_state.playwright_checked:
                        with st.spinner("⏳ 检测 Playwright 浏览器..."):
                            st.session_state.playwright_available, st.session_state.playwright_error = check_playwright()
                            st.session_state.playwright_checked = True
                            
                            if not st.session_state.playwright_available:
                                st.error(
                                    f"❌ Playwright 浏览器未安装！\n\n"
                                    f"错误信息：{st.session_state.playwright_error}\n\n"
                                    f"**解决方案：**\n"
                                    f"1. 自动安装（推荐）：点击下面的按钮\n"
                                    f"2. 手动安装：运行 `python -m playwright install`"
                                )
                                
                                if st.button("📥 自动安装 Playwright 浏览器", key="install_playwright"):
                                    with st.spinner("正在安装 Playwright 浏览器（~200MB）..."):
                                        try:
                                            import subprocess
                                            result = subprocess.run(
                                                [sys.executable, "-m", "playwright", "install"],
                                                capture_output=True,
                                                text=True,
                                                timeout=300
                                            )
                                            if result.returncode == 0:
                                                st.success('✅ Playwright 浏览器安装完成！请重新点击"开始分析"')
                                                st.rerun()
                                            else:
                                                st.error(f"❌ 安装失败：{result.stderr}")
                                        except Exception as e:
                                            st.error(f"❌ 安装失败：{e}")
                                
                                st.stop()
                    
                    from agents.coordinator import CoordinatorAgent

                    log_callback("🚀 启动竞品分析系统…")
                    log_callback(f"⚙️ 并发度 = {max_workers}")

                    coordinator = CoordinatorAgent()
                    # 通过实例属性传入并发度（避免 keyword argument 缓存问题）
                    coordinator._max_workers = max(1, min(max_workers, 4))

                    # 预创建卡片占位（coordinator 内部拿到 competitors 后才会填充）
                    crawl_states = {}
                    crawl_cards_ph.info("🚀 准备调度并行爬取，等待识别竞品…")

                    # 包装 progress_callback，监听 [并行 i/n] 消息
                    original_progress = progress_callback
                    crawl_events = []

                    def wrapped_progress(progress: int, message: str):
                        original_progress(progress, message)
                        # 解析 "🕷️ 正在爬取: X (1/3)"
                        if "正在爬取" in message or "已完成" in message or "爬取失败" in message:
                            crawl_events.append((progress, message))
                        # 解析 "[并行 i/total] 开始 - X"
                        if "并行" in message and "开始 - " in message:
                            try:
                                tail = message.split("开始 - ")[-1].strip()
                                if tail and tail not in crawl_states:
                                    crawl_states[tail] = {"status": "in_progress",
                                                          "msg": "正在爬取…", "ts": ""}
                                elif tail:
                                    crawl_states[tail]["status"] = "in_progress"
                            except Exception:
                                pass
                        if "✅" in message and "爬取完成" in message:
                            try:
                                name = message.split("✅")[-1].split("爬取完成")[0].strip()
                                if name in crawl_states:
                                    crawl_states[name]["status"] = "done"
                            except Exception:
                                pass
                        if "❌" in message and "失败" in message:
                            try:
                                # 消息形如 "❌ X 爬取失败 ..."
                                parts = message.split("❌")[1].split("爬取失败")
                                if parts:
                                    name = parts[0].strip()
                                    if name in crawl_states:
                                        crawl_states[name]["status"] = "failed"
                            except Exception:
                                pass
                        if crawl_states:
                            _render_crawl_cards(crawl_states, crawl_cards_ph)

                    result = coordinator.run(
                        user_query=user_query,
                        output_format=output_format,
                        verbose=verbose_mode,
                        callback=wrapped_progress,
                        log_callback=log_callback,
                        confirmed_competitors=confirmed_names or None,
                    )
                    st.session_state.last_result = result
                    st.session_state.last_result["mode"] = "real"
                    st.session_state.last_result["elapsed"] = time.time() - start_time
                    st.session_state.last_result["max_workers"] = max_workers
                    st.session_state.last_result["task_context"] = {
                        "purpose": purpose,
                        "own_product": own_product,
                        "target_users": target_users,
                        "dimensions": dimensions,
                        "market": market,
                        "time_scope": time_scope,
                    }
                    if result.get("status") == "success":
                        st.success(f"✅ 分析完成！报告: {result['report_path']}")
                    else:
                        st.warning(f"⚠️ 部分失败: {result.get('errors')}")

            except Exception as e:
                st.error(f"❌ 分析失败: {e}")
                import traceback
                if not str(e).startswith("PREFLIGHT:"):
                    st.error(traceback.format_exc())
            finally:
                # 保留最终状态，方便用户确认任务是否完整结束以及实际耗时。
                pass


# ====== Tab 2: 分析结果 ======
with tab2:
    st.header("分析结果")
    if "last_result" not in st.session_state:
        st.info('暂无分析结果，请先在"新建分析"标签页创建分析。')
    else:
        result = st.session_state.last_result
        if result.get("mode") == "demo":
            st.error(
                "🎭 演示结果：以下内容由固定模拟数据生成，不代表竞品真实功能、价格、"
                "评分或版本信息，请勿用于业务决策。"
            )
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("分析状态", result.get("status", "-"))
        c2.metric("竞品数量", len(result.get("competitors", [])))
        c3.metric("并发度", result.get("max_workers", "-"))
        c4.metric("总耗时(秒)", f"{result.get('elapsed', 0):.1f}" if result.get("elapsed") else "-")

        st.subheader("分析的竞品")
        st.write(", ".join(result.get("competitors", [])))
        task_context = result.get("task_context", {}) or {}
        if task_context:
            st.caption(
                f"分析目的：{task_context.get('purpose', '-')} ｜ "
                f"目标用户：{task_context.get('target_users') or '未指定'} ｜ "
                f"市场：{task_context.get('market', '-')} ｜ "
                f"维度：{'、'.join(task_context.get('dimensions') or []) or '-'}"
            )

        # 结构化数据
        data = result.get("data")
        if data:
            st.markdown("---")

            # Analyzer 内置真实性闸门（不新增 Agent）
            quality_report = data.get("quality_report", {}) or {}
            quality_items = quality_report.get("competitors", {}) or {}
            if quality_items:
                summary = quality_report.get("summary", {}) or {}
                st.subheader("🛡️ 数据真实性检测")
                q1, q2, q3, q4 = st.columns(4)
                q1.metric("平均质量分", f"{summary.get('average_score', 0)}/100")
                q2.metric("通过", summary.get("passed", 0))
                q3.metric("降级", summary.get("degraded", 0))
                q4.metric("失败", summary.get("failed", 0))
                quality_rows = []
                for name, item in quality_items.items():
                    quality_rows.append({
                        "竞品": name,
                        "状态": {"passed": "✅ 通过", "degraded": "⚠️ 降级", "failed": "❌ 失败"}.get(item.get("status"), "未知"),
                        "置信度": item.get("confidence", "unknown"),
                        "已验证功能": item.get("verified_feature_count", 0),
                        "可追溯来源": item.get("evidence_count", 0),
                        "主要问题": "；".join((item.get("issues") or [])[:3]),
                    })
                st.dataframe(quality_rows, width="stretch", hide_index=True)

            # 来源警告：展示每个竞品的数据来源信息
            competitor_sources = data.get("competitor_sources", {})
            if competitor_sources:
                # 顶部一行"数据来源概览"标签（绿色=crawl 完整，黄色=部分，红色=AI兜底）
                source_badges = []
                for name, src in competitor_sources.items():
                    s = src.get("_source", "unknown")
                    method = src.get("_find_method_cn", "")
                    website = src.get("_website", "")
                    if s == "crawl":
                        source_badges.append(f"✅ **{name}** · 官网爬取（{method}{' · ' + website if website else ''}）")
                    elif s == "crawl_partial":
                        source_badges.append(f"🟡 **{name}** · 部分爬取（{method}{' · ' + website if website else ''}）")
                    elif s == "llm_fallback":
                        source_badges.append(f"🔴 **{name}** · AI 知识库兜底（未找到官网）")
                    else:
                        source_badges.append(f"❓ **{name}** · 来源未知 ({s})")
                st.markdown("**数据来源：** " + "  ｜  ".join(source_badges))
                st.markdown("")

                for name, src in competitor_sources.items():
                    evidence_items = src.get("_evidence", []) or []
                    if evidence_items:
                        with st.expander(f"查看 {name} 的可追溯证据（{len(evidence_items)}）"):
                            for evidence in evidence_items:
                                if not isinstance(evidence, dict) or not evidence.get("url"):
                                    continue
                                fields = "、".join(evidence.get("fields", []) or []) or "页面访问"
                                captured_at = evidence.get("captured_at", "未知")
                                cache_status = evidence.get("cache_status", "live")
                                st.markdown(
                                    f"- [{evidence.get('source', 'source')}]({evidence['url']}) "
                                    f"· 支撑字段：{fields} · 采集时间：{captured_at} · 数据状态：{cache_status}"
                                )
                    cache_events = src.get("_cache_events", {}) or {}
                    stale_pages = [
                        url for url, event in cache_events.items()
                        if isinstance(event, dict) and event.get("status") == "stale_cache"
                    ]
                    if stale_pages:
                        st.warning(
                            f"⚠️ {name} 有 {len(stale_pages)} 个页面使用过期缓存；"
                            "本次结果不能视为完全实时。"
                        )

                warns = []
                infos = []  # 信息级提示（非警告）
                for name, src in competitor_sources.items():
                    s = src.get("_source", "")
                    if s == "llm_fallback":
                        warns.append(f"🔴 **{name}**：数据完全来自 AI 知识库，未经过官网爬取，可信度较低")
                    elif s == "crawl_partial":
                        warns.append(f"⚠️ **{name}**：有官网但爬取数据不足，部分字段为空")
                    # 核心 features/pricing 被 AI 补充（仅核心字段）
                    elif src.get("_llm_filled_fields"):
                        filled = src["_llm_filled_fields"]
                        warns.append(f"⚠️ **{name}**：核心字段由 AI 补充（官网未爬到）：{', '.join(filled)}")
                    # 非核心字段留空（不再编造）
                    if src.get("_unavailable_fields"):
                        unavail = src["_unavailable_fields"]
                        infos.append(f"ℹ️ **{name}**：以下字段未从官网获取，已留空：{', '.join(unavail)}")
                for w in warns:
                    st.warning(w)
                for i in infos:
                    st.info(i)
            elif data.get("_source") == "llm_fallback":
                st.error("⚠️ 此竞品数据完全来自 AI 知识库，未经过官网爬取，数据可信度较低，仅供参考。")
            elif data.get("_source") == "crawl_partial":
                st.warning("⚠️ 此竞品有官网但爬取数据不足，部分字段为空。")

            st.subheader("📊 功能对比矩阵")
            feature_meta = (data.get("analysis_metadata", {}) or {}).get("feature_matrix", {}) or {}
            if feature_meta.get("warning"):
                st.warning(feature_meta["warning"])
            fm = data.get("feature_matrix")
            if fm is not None:
                import pandas as pd
                if isinstance(fm, pd.DataFrame):
                    st.dataframe(fm, width="stretch", hide_index=True)
                elif isinstance(fm, str):
                    st.markdown(fm)
                elif isinstance(fm, dict):
                    # 判断是否是纯文本占位符（所有值都是短字符串）
                    vals = list(fm.values())
                    if all(isinstance(v, str) and len(v) < 200 for v in vals):
                        for v in vals:
                            st.markdown(v)
                    else:
                        try:
                            fm_df = pd.DataFrame(fm)
                            st.dataframe(fm_df, width="stretch", hide_index=True)
                        except Exception:
                            st.write(fm)
                else:
                    try:
                        st.dataframe(pd.DataFrame(fm), width="stretch", hide_index=True)
                    except Exception:
                        st.write(fm)
            else:
                st.info("功能对比矩阵数据不可用")

            st.subheader("💰 定价策略")
            pricing_meta = (data.get("analysis_metadata", {}) or {}).get("pricing", {}) or {}
            if pricing_meta.get("warning"):
                st.warning(pricing_meta["warning"])
            # DataFrame 不能参与 Python 的真值判断（会触发 ambiguous truth value）。
            pf = data.get("pricing_df")
            if pf is None:
                pf = data.get("pricing_analysis")
            if pf is not None:
                import pandas as pd
                if isinstance(pf, pd.DataFrame):
                    st.dataframe(pf, width="stretch", hide_index=True)
                elif isinstance(pf, str):
                    st.markdown(pf)
                elif isinstance(pf, dict):
                    # 🔧 优先按结构化 pricing_analysis 字典渲染（真实模式），避免显示原始 JSON
                    structured_keys = {"pricing_models", "price_range", "analysis", "recommendations"}
                    if isinstance(pf, dict) and any(k in pf for k in structured_keys):
                        st.markdown(_render_pricing_analysis(pf))
                    else:
                        vals = list(pf.values())
                        if all(isinstance(v, str) and len(v) < 200 for v in vals):
                            for v in vals:
                                st.markdown(v)
                        else:
                            try:
                                pf_df = pd.DataFrame(pf)
                                st.dataframe(pf_df, width="stretch", hide_index=True)
                            except Exception:
                                st.write(pf)
                else:
                    try:
                        st.dataframe(pd.DataFrame(pf), width="stretch", hide_index=True)
                    except Exception:
                        st.write(pf)
            else:
                st.info("定价策略数据不可用")

            st.subheader("📦 版本更新活跃度")
            cf = data.get("changelog_df")
            if cf is None:
                cf = data.get("changelog_analysis")
            if cf is not None:
                import pandas as pd
                if isinstance(cf, pd.DataFrame):
                    st.dataframe(cf, width="stretch", hide_index=True)
                elif isinstance(cf, str):
                    st.markdown(cf)
                elif isinstance(cf, dict):
                    vals = list(cf.values())
                    if all(isinstance(v, str) and len(v) < 200 for v in vals):
                        for v in vals:
                            st.markdown(v)
                    else:
                        try:
                            cf_df = pd.DataFrame(cf).T.reset_index().rename(columns={"index": "竞品"})
                            st.dataframe(cf_df, width="stretch", hide_index=True)
                        except Exception:
                            st.write(cf)
                else:
                    try:
                        cf_df = pd.DataFrame(cf).T.reset_index().rename(columns={"index": "竞品"})
                        st.dataframe(cf_df, width="stretch", hide_index=True)
                    except Exception:
                        st.write(cf)
            else:
                st.info("版本更新数据不可用")

            # 用户反馈分析（App Store 评分/评论）
            st.subheader("⭐ 用户反馈分析（App Store 评分 / 评论）")
            fb = data.get("app_feedback_analysis")
            if fb:
                for comp, d in fb.items():
                    if d.get("available"):
                        st.markdown(f"**{comp}** · 评分 {d.get('rating')}（{d.get('rating_count')} 人）")
                        if d.get("sentiment"):
                            st.markdown(f"- 情感倾向：{d['sentiment']}")
                        if d.get("satisfaction_summary"):
                            st.markdown(f"- 满意度：{d['satisfaction_summary']}")
                        if d.get("pain_points"):
                            st.markdown("**用户痛点：**")
                            for p in d["pain_points"]:
                                st.markdown(f"  - {p}")
                        if d.get("highlights"):
                            st.markdown("**用户好评点：**")
                            for h in d["highlights"]:
                                st.markdown(f"  - {h}")
                    else:
                        st.info(f"**{comp}**：{d.get('reason', '无用户反馈数据')}")
            else:
                st.info("用户反馈数据不可用（未获取到 App Store 评分/评论）")

            # 官网文案变化（快照 diff）
            st.subheader("✍️ 官网文案变化（营销方向）")
            cc = data.get("copy_changes_analysis")
            if cc:
                for comp, d in cc.items():
                    if d.get("available"):
                        st.markdown(f"**{comp}**")
                        if d.get("direction_changes"):
                            st.markdown("**方向调整：**")
                            for c in d["direction_changes"]:
                                st.markdown(f"  - {c}")
                        if d.get("emphasis_shift"):
                            st.markdown(f"**重心变化：** {d['emphasis_shift']}")
                        if d.get("ab_test_hint"):
                            st.markdown(f"**A/B 测试痕迹：** {d['ab_test_hint']}")
                    else:
                        st.info(f"**{comp}**：{d.get('reason', '无官网文案变化数据')}")
            else:
                st.info("官网文案变化数据不可用（首次运行已建立基线，下次可对比）")

            # 可视化：功能得分 / 价格对比（兼容演示模式和真实模式）
            import pandas as pd
            _fm = data.get("feature_matrix")
            _pf = data.get("pricing_df")
            # 只保留 DataFrame 类型用于可视化（dict/str 等非常量格式跳过图表）
            feature_matrix = _fm if isinstance(_fm, pd.DataFrame) else None
            pricing_df = _pf if isinstance(_pf, pd.DataFrame) else None
            competitors = result.get("competitors", [])

            if feature_matrix is not None or pricing_df is not None:
                st.markdown("---")
                st.subheader("📈 可视化对比")
                # 始终用 st.columns，保证返回的每个元素都支持 with 上下文
                # n_charts 可能为 1 或 2
                n_charts = sum([feature_matrix is not None, pricing_df is not None])
                cols = st.columns(n_charts)
                col_idx = 0

                if feature_matrix is not None:
                    with cols[col_idx]:
                        st.markdown("**功能支持率**")
                        try:
                            scores = (feature_matrix[competitors] == "✅").sum().to_frame("支持的功能数")
                            st.bar_chart(scores)
                        except Exception:
                            st.info("功能矩阵格式不支持可视化")
                    col_idx += 1

                if pricing_df is not None:
                    with cols[col_idx]:
                        st.markdown("**起步价对比（¥/月）**")
                        try:
                            price_df = pricing_df.set_index("竞品")[["起步价(¥/月)"]]
                            st.bar_chart(price_df)
                        except Exception:
                            st.info("定价数据格式不支持可视化")

        # 报告区
        rp = result.get("report_path")
        if rp and Path(rp).exists():
            st.markdown("---")
            st.subheader("📄 生成的报告")
            content = Path(rp).read_text(encoding="utf-8")
            if rp.endswith(".md"):
                # Markdown 报告：把图片引用替换为 base64 内嵌，否则 Streamlit 无法显示
                content = _embed_images_in_markdown(content, base_dir="reports")
                st.markdown(content, unsafe_allow_html=True)
            else:
                st.components.v1.html(content, height=600, scrolling=True)

            st.download_button(
                "📥 下载演示报告（模拟数据）" if result.get("mode") == "demo" else "📥 下载报告",
                data=content,
                file_name=Path(rp).name,
                mime="text/markdown" if rp.endswith(".md") else "text/html",
            )

        if result.get("errors"):
            st.markdown("---")
            st.subheader("⚠️ 错误信息")
            for err in result["errors"]:
                st.error(err)


# ====== Tab 3: 向量搜索 ======
with tab3:
    st.header("🔍 向量数据库搜索")
    try:
        from vector_store import CompetitorVectorStore
        if "vector_store" not in st.session_state:
            # ==================== 轻量模式（零模型下载） ====================
            # 🔧 与 Coordinator 的存储保持一致：使用 ChromaDB 内置轻量 embedding，
            # 避免 79MB SentenceTransformer 下载卡死，且保证与分析阶段写入的向量同构，
            # 否则"分析"写入的向量与"搜索"读取的向量 embedding 不一致，检索会失效。
            with st.spinner("⏳ 正在加载向量数据库（轻量模式，无需下载模型）..."):
                try:
                    st.info(
                        "💡 **轻量模式：**\n"
                        "向量数据库使用 ChromaDB 内置轻量 embedding（零下载），\n"
                        "与「新建分析」阶段写入的向量同构，搜索可直接命中历史分析结果。"
                    )
                    st.session_state.vector_store = CompetitorVectorStore(
                        force_lightweight=True, init_timeout=15
                    )
                    st.success("✅ 向量数据库加载完成！")
                except Exception as e:
                    st.error(f"❌ 向量数据库加载失败：{e}")
                    st.info(
                        "💡 **解决方案：**\n"
                        "1. 检查 ./data/chroma_db 目录是否可写\n"
                        "2. 确认已安装 chromadb：`pip install chromadb`"
                    )
                    st.stop()
        
        vs = st.session_state.vector_store
        stats = vs.get_collection_stats()
        st.metric("数据库中的竞品数量", stats.get("total_competitors", 0))
        st.markdown("---")
        
        q = st.text_input("输入搜索查询（自然语言）",
                          placeholder="例如：项目管理工具、团队协作软件",
                          key="search_query")
        n = st.slider("返回结果数量", 1, 10, 5)
        if st.button("🔍 搜索", disabled=not q):
            with st.spinner("搜索中…"):
                results = vs.search_similar(q, n_results=n)
                if results:
                    st.success(f"找到 {len(results)} 个相关竞品")
                    for i, r in enumerate(results, 1):
                        with st.expander(
                            f"{i}. {r['metadata'].get('name', '?')} "
                            f"(相似度: {1 - r['distance']:.2%})"
                        ):
                            st.markdown("**文档内容**")
                            st.text(r["document"][:500] + "…" if len(r["document"]) > 500 else r["document"])
                            st.markdown("**元数据**")
                            st.json(r["metadata"])
                else:
                    st.warning("未找到相关竞品")
        
        if st.checkbox("显示数据库中的所有竞品"):
            comps = vs.get_all_competitors()
            if comps:
                st.subheader(f"所有竞品 ({len(comps)} 个)")
                for c in comps:
                    st.write(f"- **{c['metadata'].get('name', '?')}**")
    except Exception as e:
        st.error(f"向量数据库加载失败: {e}")
        st.info("请确保已安装 chromadb: `pip install chromadb`")


# ====== Tab 4: 历史记录 ======
with tab4:
    st.header("📚 分析历史记录")
    reports_dir = project_root / "reports"
    if reports_dir.exists():
        files = list(reports_dir.glob("*.md")) + list(reports_dir.glob("*.html"))
        if files:
            files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            st.success(f"找到 {len(files)} 个历史报告")
            for f in files:
                with st.expander(f"📄 {f.name}"):
                    content = f.read_text(encoding="utf-8")
                    st.markdown(content[:500] + "…")
                    b1, b2 = st.columns(2)
                    if b1.button(f"📖 查看", key=f"view_{f.name}"):
                        st.session_state.viewing_report = str(f)
                        st.rerun()
                    if b2.button(f"🗑️ 删除", key=f"del_{f.name}"):
                        f.unlink()
                        st.success(f"已删除: {f.name}")
                        st.rerun()
            if "viewing_report" in st.session_state:
                st.markdown("---")
                st.subheader("📖 报告详情")
                rp = Path(st.session_state.viewing_report)
                if rp.exists():
                    content = rp.read_text(encoding="utf-8")
                    if rp.suffix == ".md":
                        st.markdown(content)
                    else:
                        st.components.v1.html(content, height=600, scrolling=True)
        else:
            st.info("暂无历史报告")
    else:
        st.info("reports 目录不存在")

# ============================== 页脚 ==============================
st.markdown("---")
st.caption("竞品分析多 Agent 系统 · Powered by LangGraph + GPT-4 + ChromaDB")
