"""
Report Agent - 报告生成Agent
负责渲染报告模板、生成可视化图表

修复说明（本版本）：
- 图表保存为相对文件名，Markdown 报告可正确引用
- HTML 报告将图表嵌入为 base64 data URI，生成自包含文件
- 所有图表共享同一个 timestamp，避免文件名不一致
- HTML 模板不使用 f-string，避免与 CSS/JS 中的 {} 冲突
"""

import os
import base64
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime
from pathlib import Path
import re

import pandas as pd
import matplotlib
matplotlib.use('Agg')  # 非交互式后端
import matplotlib.pyplot as plt
import matplotlib
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']  # 支持中文
matplotlib.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题

from jinja2 import Environment, FileSystemLoader


logger = logging.getLogger(__name__)


class ReportAgent:
    """报告生成Agent"""

    def __init__(self, template_dir: str = "templates", output_dir: str = "reports"):
        """
        初始化Report Agent

        Args:
            template_dir: 模板目录
            output_dir: 输出目录
        """
        self.template_dir = Path(template_dir)
        self.output_dir = Path(output_dir)

        # 创建目录
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.template_dir.mkdir(parents=True, exist_ok=True)

        # 初始化Jinja2环境
        self.template_env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=True
        )

    def generate(self, analysis_results: Dict[str, Any],
                 competitors: List[str],
                 output_format: str = "markdown") -> str:
        """
        生成报告

        Args:
            analysis_results: 分析结果
            competitors: 竞品列表
            output_format: 输出格式 (markdown/html)

        Returns:
            报告文件路径
        """

        logger.info(f"Reporter: 开始生成{output_format}报告")

        # 统一生成 timestamp，供图表命名和报告文件名共用
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # 步骤1: 准备模板数据
        context = self._prepare_context(analysis_results, competitors, timestamp)

        # 步骤2: 生成可视化图表，返回相对文件名列表
        chart_filenames = self._generate_charts(analysis_results, competitors, timestamp)
        context["charts"] = chart_filenames  # 相对文件名，供 Markdown 模板使用
        # 绝对路径，用于 HTML 中嵌入 base64
        context["chart_files"] = [str(self.output_dir / f) for f in chart_filenames]

        # 步骤3: 渲染模板
        if output_format == "markdown":
            report_content = self._render_markdown(context)
            file_ext = "md"
        elif output_format == "html":
            report_content = self._render_html(context)
            file_ext = "html"
        else:
            raise ValueError(f"不支持的格式: {output_format}")

        # 步骤4: 保存报告
        competitors_str = "_vs_".join(competitors[:2])  # 最多显示2个
        filename = f"{timestamp}_{competitors_str}.{file_ext}"
        filepath = self.output_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(report_content)

        logger.info(f"Reporter: 报告已生成 - {filepath}")

        return str(filepath)

    @staticmethod
    def _strip_insight_prefix(text: str) -> str:
        """去掉洞察文本自带的 '洞察N：' / '洞察 N:' 前缀，避免与报告里的 '### 洞察 N' 标题重复标号"""
        if not text:
            return text
        return re.sub(r"^\s*洞察\s*\d+\s*[:：]\s*", "", text).strip()

    def _prepare_context(self, results: Dict[str, Any], competitors: List[str], timestamp: str) -> Dict:
        """准备模板渲染数据"""

        feature_matrix = results.get("feature_matrix")
        pricing_analysis = results.get("pricing_analysis", {})
        raw_insights = results.get("insights", []) or []
        insights = [self._strip_insight_prefix(x) for x in raw_insights]
        changelog_analysis = results.get("changelog_analysis", {})  # 新增：Changelog 分析
        quality_report = results.get("quality_report", {}) or {}
        analysis_metadata = results.get("analysis_metadata", {}) or {}

        # 执行摘要：取首条洞察作为要点（已去前缀，避免与第4节整段重复）
        executive_summary = insights[0] if insights else "无"

        context = {
            "title": f"竞品分析报告: {' vs '.join(competitors)}",
            "generated_at": datetime.now().strftime("%Y年%m月%d日 %H:%M"),
            "competitors": competitors,
            "timestamp": timestamp,

            # 执行摘要
            "executive_summary": executive_summary,

            # 功能对比（index=False 去掉多余的行号列）
            "feature_matrix": feature_matrix.to_markdown(index=False) if isinstance(feature_matrix, pd.DataFrame) else "",
            "feature_matrix_html": feature_matrix.to_html(index=False) if isinstance(feature_matrix, pd.DataFrame) else "",

            # 定价分析
            "pricing_analysis": pricing_analysis,
            "pricing_table": self._format_pricing_table(pricing_analysis),

            # Changelog 分析（新增）
            "changelog_analysis": changelog_analysis,

            # 用户反馈分析（App Store 评分/评论）
            "app_feedback_analysis": results.get("app_feedback_analysis", {}),
            # 官网文案变化分析（快照 diff）
            "copy_changes_analysis": results.get("copy_changes_analysis", {}),

            # 数据真实性闸门与可追溯来源
            "quality_report": quality_report,
            "quality_table": self._format_quality_table(quality_report),
            "evidence_sources": self._format_evidence_sources(quality_report),
            "feature_metadata": analysis_metadata.get("feature_matrix", {}),
            "pricing_metadata": analysis_metadata.get("pricing", {}),

            # 洞察（已去前缀）
            "insights": insights,

            # 图表（相对文件名，供 Markdown 模板使用）
            "charts": [],
            # 图表绝对路径（供 HTML 嵌入使用，由 generate() 填充）
            "chart_files": [],
        }

        # 兼容旧调用方/旧 Streamlit 进程：模板新增字段必须始终有默认值。
        context.setdefault("feature_metadata", {})
        context.setdefault("pricing_metadata", {})
        context.setdefault("quality_table", "无数据质量检测结果")
        context.setdefault("evidence_sources", [])

        return context

    def _format_quality_table(self, quality_report: Dict[str, Any]) -> str:
        """将 Analyzer 的质量检测结果转为紧凑 Markdown 表格。"""
        competitors = quality_report.get("competitors", {}) or {}
        if not competitors:
            return "无数据质量检测结果"

        status_labels = {"passed": "✅ 通过", "degraded": "⚠️ 降级", "failed": "❌ 失败"}
        rows = [
            "| 竞品 | 状态 | 质量分 | 置信度 | 已验证功能 | 来源数 | 主要问题 |",
            "|---|---|---:|---|---:|---:|---|",
        ]
        for name, item in competitors.items():
            issues = "；".join((item.get("issues") or [])[:3]) or "无"
            rows.append(
                f"| {name} | {status_labels.get(item.get('status'), item.get('status', '未知'))} "
                f"| {item.get('score', 0)} | {item.get('confidence', 'unknown')} "
                f"| {item.get('verified_feature_count', 0)} | {item.get('evidence_count', 0)} | {issues} |"
            )
        return "\n".join(rows)

    def _format_evidence_sources(self, quality_report: Dict[str, Any]) -> List[Dict[str, Any]]:
        """整理已访问来源，避免把 LLM 内容伪装成引用。"""
        output = []
        for name, item in (quality_report.get("competitors", {}) or {}).items():
            sources = []
            for evidence in item.get("evidence", []) or []:
                if not isinstance(evidence, dict) or not evidence.get("url"):
                    continue
                sources.append({
                    "label": evidence.get("source", "source"),
                    "url": evidence["url"],
                    "fields": "、".join(evidence.get("fields", []) or []),
                    "captured_at": evidence.get("captured_at", "未知"),
                    "cache_status": evidence.get("cache_status", "live"),
                })
            output.append({"name": name, "sources": sources})
        return output

    def _format_pricing_table(self, pricing_analysis: Dict) -> str:
        """格式化定价表格"""

        pricing_models = pricing_analysis.get("pricing_models", {})

        if not pricing_models:
            return "无定价数据"

        table = "| 竞品 | 定价模式 |\n"
        table += "|------|----------|\n"

        for comp, model in pricing_models.items():
            table += f"| {comp} | {model} |\n"

        return table

    def _format_changelog_section(self, changelog_analysis: Dict) -> str:
        """格式化 Changelog 章节为 Markdown"""
        if not changelog_analysis:
            return "无 Changelog 数据\n"

        md = ""
        for comp, data in changelog_analysis.items():
            md += f"\n### {comp}\n\n"
            if data.get("latest_version"):
                md += f"**最新版本**: {data['latest_version']}  "
            if data.get("latest_release_date"):
                md += f"（发布日期: {data['latest_release_date']}）\n\n"
            if data.get("update_frequency"):
                md += f"**更新频率**: {data['update_frequency']}\n\n"
            recent = data.get("recent_updates", [])
            if recent:
                md += "**近期更新**:\n"
                for item in recent[:5]:
                    md += f"- {item}\n"
                md += "\n"
        return md

    def _generate_charts(self, results: Dict, competitors: List[str], timestamp: str) -> List[str]:
        """
        生成可视化图表，保存到 output_dir，返回相对文件名列表

        Returns:
            图表相对文件名列表（如 ["chart_radar.png", "chart_bar.png"]）
        """

        logger.info("Reporter: 生成可视化图表")

        charts = []

        # 图表1: 功能覆盖度条形图
        radar_file = self._create_radar_chart(results.get("feature_matrix"), competitors, timestamp)
        if radar_file:
            charts.append(radar_file)

        # 图表2: 功能数量对比条形图
        bar_file = self._create_bar_chart(results.get("feature_matrix"), competitors, timestamp)
        if bar_file:
            charts.append(bar_file)

        logger.info(f"Reporter: 生成了 {len(charts)} 个图表")

        return charts

    def _chart_path(self, timestamp: str, name: str) -> tuple:
        """
        返回图表的 (绝对路径, 相对文件名)
        绝对路径用于保存文件，相对文件名用于 Markdown 引用
        """
        filename = f"{timestamp}_{name}.png"
        abs_path = os.path.join(self.output_dir, filename)
        return abs_path, filename

    def _create_radar_chart(self, feature_matrix: pd.DataFrame,
                            competitors: List[str], timestamp: str) -> Optional[str]:
        """创建功能覆盖度条形图，返回相对文件名"""

        if feature_matrix is None or feature_matrix.empty:
            return None

        try:
            # 统计每个竞品的功能数量
            feature_counts = {}
            for comp in competitors:
                if comp in feature_matrix.columns:
                    count = (feature_matrix[comp] == "✅").sum()
                    feature_counts[comp] = count

            if not feature_counts:
                return None

            # 创建条形图
            fig, ax = plt.subplots(figsize=(8, 6))

            comps = list(feature_counts.keys())
            counts = list(feature_counts.values())

            ax.bar(comps, counts, color=['#FF6B6B', '#4ECDC4', '#45B7D1', '#F7DC6F', '#BB8FCE'])
            ax.set_xlabel('竞品')
            ax.set_ylabel('功能数量')
            ax.set_title('竞品功能覆盖度对比')
            plt.xticks(rotation=15)
            plt.tight_layout()

            # 保存图表
            abs_path, filename = self._chart_path(timestamp, "radar")
            plt.savefig(abs_path, dpi=100, bbox_inches='tight')
            plt.close()

            return filename

        except Exception as e:
            logger.error(f"雷达图生成失败: {e}")
            return None

    def _create_bar_chart(self, feature_matrix: pd.DataFrame,
                         competitors: List[str], timestamp: str) -> Optional[str]:
        """创建功能分类对比条形图，返回相对文件名"""

        if feature_matrix is None or feature_matrix.empty:
            return None

        try:
            # 统计每个竞品的功能数
            data = {}
            for comp in competitors:
                if comp in feature_matrix.columns:
                    total = (feature_matrix[comp] == "✅").sum()
                    data[comp] = total

            if not data:
                return None

            # 创建条形图
            fig, ax = plt.subplots(figsize=(10, 6))

            comps = list(data.keys())
            values = list(data.values())
            x = range(len(comps))
            width = 0.35

            ax.bar(x, values, width, label='功能数')
            ax.set_xlabel('竞品')
            ax.set_ylabel('功能数量')
            ax.set_title('竞品功能对比')
            ax.set_xticks(list(range(len(comps))))
            ax.set_xticklabels(comps, rotation=15)
            ax.legend()
            plt.tight_layout()

            # 保存图表
            abs_path, filename = self._chart_path(timestamp, "bar")
            plt.savefig(abs_path, dpi=100, bbox_inches='tight')
            plt.close()

            return filename

        except Exception as e:
            logger.error(f"条形图生成失败: {e}")
            return None

    def _image_to_base64(self, filepath: str) -> str:
        """将图片文件编码为 base64 data URI"""
        try:
            with open(filepath, "rb") as f:
                data = base64.b64encode(f.read()).decode("utf-8")
            return f"data:image/png;base64,{data}"
        except Exception as e:
            logger.error(f"图片 base64 编码失败: {e}")
            return ""

    def _render_markdown(self, context: Dict) -> str:
        """渲染Markdown模板"""

        # 如果没有模板文件，使用默认模板
        template_path = os.path.join(self.template_dir, "report_template.md.j2")

        if not os.path.exists(template_path):
            # 创建默认模板
            self._create_default_template()

        template = self.template_env.get_template("report_template.md.j2")
        return template.render(**context)

    def _render_html(self, context: Dict) -> str:
        """
        渲染HTML模板，图表以 base64 嵌入，生成自包含文件。
        注意：此方法不使用 f-string 来构建 HTML 模板，
        而是用普通字符串 + .format()/replace()，避免与 CSS 中的 {} 冲突。
        """

        # 先渲染 Markdown body
        md_content = self._render_markdown(context)

        # 将 Markdown 中的图表引用替换为 base64 嵌入的 <img> 标签
        html_body = self._markdown_to_html(md_content, context)

        # 用普通字符串构建 HTML（不用 f-string，避免 {} 冲突）
        css = (
            "body {"
            "  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;"
            "  max-width: 960px;"
            "  margin: 40px auto;"
            "  padding: 20px;"
            "  line-height: 1.7;"
            "  color: #333;"
            "  background: #fff;"
            "}"
            "h1 {"
            "  color: #1a1a1a;"
            "  border-bottom: 2px solid #333;"
            "  padding-bottom: 10px;"
            "  margin-top: 30px;"
            "}"
            "h2 {"
            "  color: #333;"
            "  margin-top: 35px;"
            "  border-bottom: 1px solid #eee;"
            "  padding-bottom: 6px;"
            "}"
            "h3 {"
            "  color: #444;"
            "  margin-top: 25px;"
            "}"
            "table {"
            "  border-collapse: collapse;"
            "  width: 100%;"
            "  margin: 20px 0;"
            "  font-size: 14px;"
            "}"
            "th, td {"
            "  border: 1px solid #ddd;"
            "  padding: 10px 12px;"
            "  text-align: left;"
            "}"
            "th {"
            "  background-color: #f5f5f5;"
            "  font-weight: 600;"
            "}"
            "tr:nth-child(even) {"
            "  background-color: #fafafa;"
            "}"
            "img {"
            "  max-width: 100%;"
            "  height: auto;"
            "  margin: 20px 0;"
            "  border: 1px solid #eee;"
            "  border-radius: 4px;"
            "}"
            "code {"
            "  background: #f4f4f4;"
            "  padding: 2px 6px;"
            "  border-radius: 3px;"
            "  font-size: 90%;"
            "}"
            "pre {"
            "  background: #f6f8fa;"
            "  padding: 16px;"
            "  overflow-x: auto;"
            "  border-radius: 6px;"
            "  border: 1px solid #e1e4e8;"
            "}"
            "hr {"
            "  border: none;"
            "  border-top: 1px solid #e1e4e8;"
            "  margin: 30px 0;"
            "}"
            "ul, ol {"
            "  padding-left: 24px;"
            "}"
            "blockquote {"
            "  border-left: 4px solid #ddd;"
            "  padding-left: 16px;"
            "  color: #666;"
            "  margin: 16px 0;"
            "}"
            "strong {"
            "  color: #1a1a1a;"
            "}"
        )

        html = (
            "<!DOCTYPE html>\n"
            "<html lang=\"zh-CN\">\n"
            "<head>\n"
            "  <meta charset=\"utf-8\">\n"
            "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">\n"
            "  <title>" + context['title'] + "</title>\n"
            "  <style>\n" + css + "\n  </style>\n"
            "</head>\n"
            "<body>\n"
            + html_body + "\n"
            "</body>\n"
            "</html>"
        )

        return html

    def _markdown_to_html(self, md: str, context: Dict = None) -> str:
        """
        将 Markdown 转换为 HTML，并嵌入图表（base64）。

        优先查找 context["chart_files"] 中对应的图片文件，
        将其编码为 base64 data URI 嵌入 <img> 标签。
        """

        html = md

        # 构建文件名 -> base64 data URI 的映射
        data_uris = {}
        if context and "chart_files" in context:
            for chart_abs in context["chart_files"]:
                basename = os.path.basename(chart_abs)
                data_uri = self._image_to_base64(chart_abs)
                if data_uri:
                    data_uris[basename] = data_uri

        # 替换 Markdown 图片语法 ![alt](path) 为 <img> 标签
        def replace_img(match):
            alt_text = match.group(1)
            path = match.group(2)
            basename = os.path.basename(path)

            if basename in data_uris:
                # 使用 base64 嵌入
                return '<img src="' + data_uris[basename] + '" alt="' + alt_text + '">'
            else:
                # 保留原路径
                return '<img src="' + path + '" alt="' + alt_text + '">'

        html = re.sub(r'!\[([^\]]*)\]\(([^)]+)\)', replace_img, html)
        # 普通 Markdown 链接（来源 URL）转为可点击链接
        html = re.sub(
            r'(?<!!)\[([^\]]+)\]\((https?://[^)]+)\)',
            r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
            html,
        )

        # 处理标题
        html = re.sub(r'^#### (.+)$', r'<h4>\1</h4>', html, flags=re.MULTILINE)
        html = re.sub(r'^### (.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
        html = re.sub(r'^## (.+)$', r'<h2>\1</h2>', html, flags=re.MULTILINE)
        html = re.sub(r'^# (.+)$', r'<h1>\1</h1>', html, flags=re.MULTILINE)

        # 处理粗体 **text**
        html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)

        # 处理表格
        html = self._convert_tables_to_html(html)

        # 处理列表项
        html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
        # 将连续的 <li> 包裹在 <ul> 中
        html = re.sub(r'(?:<li>.*?</li>\n?)+', lambda m: '<ul>\n' + m.group(0) + '</ul>\n', html, flags=re.DOTALL)

        # 处理水平线
        html = html.replace('---', '<hr>')

        # 处理段落
        lines = html.split('\n')
        result = []
        para_lines = []

        block_tags = ('<h1>', '<h2>', '<h3>', '<h4>', '<ul>', '<ol>', '<table>', '<img', '<hr>', '<pre>', '<blockquote')

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if para_lines:
                    result.append("<p>" + ' '.join(para_lines) + "</p>")
                    para_lines = []
                result.append('')
                continue

            if any(stripped.startswith(tag) for tag in block_tags):
                if para_lines:
                    result.append("<p>" + ' '.join(para_lines) + "</p>")
                    para_lines = []
                result.append(line)
            else:
                para_lines.append(line)

        if para_lines:
            result.append("<p>" + ' '.join(para_lines) + "</p>")

        return '\n'.join(result)

    def _convert_tables_to_html(self, text: str) -> str:
        """将 Markdown 表格转换为 HTML 表格"""
        lines = text.split('\n')
        result = []
        in_table = False
        table_lines = []

        for line in lines:
            stripped = line.strip()
            # 检测表格行（以 | 开头或包含 |）
            if '|' in stripped and stripped.startswith('|'):
                table_lines.append(stripped)
                in_table = True
            else:
                if in_table and table_lines:
                    # 处理表格
                    html_table = self._parse_markdown_table(table_lines)
                    result.append(html_table)
                    table_lines = []
                    in_table = False
                result.append(line)

        # 文件末尾还有表格
        if in_table and table_lines:
            html_table = self._parse_markdown_table(table_lines)
            result.append(html_table)

        return '\n'.join(result)

    def _parse_markdown_table(self, lines: List[str]) -> str:
        """解析 Markdown 表格为 HTML"""
        # 过滤分隔线（如 |---|---|）
        content_lines = []
        for line in lines:
            # 去掉分隔线
            cells = [c.strip() for c in line.strip().strip('|').split('|')]
            # 检查是否是分隔行
            is_separator = all(all(c in '-:' for c in cell) for cell in cells if cell)
            if not is_separator:
                content_lines.append(cells)

        if not content_lines:
            return '\n'.join(lines)

        html = '<table>\n<thead>\n<tr>\n'
        for cell in content_lines[0]:
            html += '<th>' + cell + '</th>\n'
        html += '</tr>\n</thead>\n<tbody>\n'

        for row in content_lines[1:]:
            html += '<tr>\n'
            for cell in row:
                html += '<td>' + cell + '</td>\n'
            html += '</tr>\n'

        html += '</tbody>\n</table>'
        return html

    def _create_default_template(self):
        """创建默认报告模板（包含 Changelog 章节）"""

        template_content = """# {{ title }}

**生成时间**: {{ generated_at }}

---

## 执行摘要

{{ executive_summary }}

### 数据可信度

{% if feature_metadata is defined and feature_metadata.warning %}> ⚠️ {{ feature_metadata.warning }}{% endif %}

{{ quality_table | default("无数据质量检测结果") }}

---

## 1. 功能对比分析

### 1.1 功能对比矩阵

{{ feature_matrix }}

### 1.2 功能覆盖度可视化

{% if charts %}
{% for chart in charts %}
![功能对比图表]({{ chart }})
{% endfor %}
{% endif %}

---

## 2. 定价分析

### 2.1 定价模式对比

{{ pricing_table }}

### 2.2 详细定价信息

{% if pricing_analysis %}
{{ pricing_analysis.analysis }}
{% endif %}

---

## 3. 版本更新分析（Changelog）

{% if changelog_analysis %}
{% for comp, data in changelog_analysis.items() %}
### {{ comp }}

{% if data.latest_version %}**最新版本**: {{ data.latest_version }}{% if data.latest_release_date %}（{{ data.latest_release_date }}）{% endif %}

{% endif %}
{% if data.update_frequency %}**更新频率**: {{ data.update_frequency }}

{% endif %}
{% if data.recent_updates %}**近期重要更新**:
{% for item in data.recent_updates[:5] %}
- {{ item }}
{% endfor %}

{% endif %}
{% endfor %}
{% else %}
无 Changelog 数据
{% endif %}

---

## 4. AI洞察与建议

{% if insights %}
{% for insight in insights %}
### 洞察 {{ loop.index }}

{{ insight }}

{% endfor %}
{% endif %}

---

## 5. 结论

基于以上分析，我们得出以下结论：

1. **差异化定位**: 各竞品在功能覆盖和定价策略上各有侧重
2. **竞争优势**: 需要根据目标用户群体选择合适的竞争策略
3. **建议**: 如果是创业者，建议在垂直领域寻找差异化机会

---

## 附录

### 数据来源

{% for competitor in evidence_sources | default([]) %}
**{{ competitor.name }}**
{% if competitor.sources %}
{% for source in competitor.sources %}
- [{{ source.label }}]({{ source.url }}){% if source.fields %}：{{ source.fields }}{% endif %}（采集时间：{{ source.captured_at }}；数据状态：{{ source.cache_status }}）
{% endfor %}
{% else %}
- 无可追溯 URL；相关内容均应视为推测
{% endif %}
{% endfor %}

### 分析方法

- 功能对比矩阵
- 定价策略分析
- 版本更新频率分析
- LLM生成的商业洞察

---

*本报告由竞品分析多Agent系统自动生成*
"""

        template_path = os.path.join(self.template_dir, "report_template.md.j2")
        with open(template_path, "w", encoding="utf-8") as f:
            f.write(template_content)


# 测试代码
if __name__ == "__main__":
    # 测试Report Agent
    reporter = ReportAgent()

    # 模拟分析结果（含 changelog）
    import pandas as pd

    test_results = {
        "feature_matrix": pd.DataFrame({
            "功能": ["文档编辑", "数据库", "双向链接"],
            "Notion": ["✅", "✅", "❌"],
            "Obsidian": ["✅", "❌", "✅"]
        }),
        "pricing_analysis": {
            "pricing_models": {"Notion": "订阅制", "Obsidian": "一次性买断"},
            "analysis": "Notion采用SaaS订阅模式，Obsidian采用买断制"
        },
        "changelog_analysis": {
            "Notion": {
                "latest_version": "v3.2.1",
                "latest_release_date": "2024-06-15",
                "recent_updates": ["新增AI助手功能", "优化数据库视图", "修复同步Bug"],
                "update_frequency": "每月一次"
            },
            "Obsidian": {
                "latest_version": "v1.6.0",
                "latest_release_date": "2024-06-10",
                "recent_updates": ["新增Canvas功能", "改进搜索性能"],
                "update_frequency": "每两周一次"
            }
        },
        "insights": [
            "洞察1：Notion主打团队协作，Obsidian专注个人知识管理",
            "洞察2：定价策略反映不同的目标用户群体"
        ]
    }

    # 生成报告
    report_path = reporter.generate(
        analysis_results=test_results,
        competitors=["Notion", "Obsidian"],
        output_format="html"
    )

    print(f"\n报告已生成: {report_path}")
