# 可追溯竞品分析 Multi-Agent

输入 2～5 个竞品及决策目标，系统自动完成官网发现、并行采集、结构化分析、数据质量检查与报告生成。项目重点不是“让模型写一篇报告”，而是让每项重要结论都能区分事实、缺失信息与 AI 推测。

> 当前状态：可运行的求职演示项目。真实模式依赖外部网站与兼容 OpenAI API；演示模式使用固定模拟数据，并与真实报告物理隔离。

## 核心流程

```text
决策问题与竞品
  → Coordinator 拆解任务
  → Crawler 并行发现并采集官网 / 定价 / 版本等页面
  → Analyzer 生成对比并执行数据质量门禁
  → Reporter 输出带来源、采集时间和置信度的报告
```

## 为什么做这个项目

- 多竞品页面采集耗时长：使用并发采集和单点失败隔离。
- LLM 容易把未知信息写成事实：使用字段级证据、Schema 校验和质量降级。
- 报告难以复核：报告附来源 URL、采集时间、支持字段和置信度。

## 已实现能力

| 能力 | 状态 | 代码证据 |
|---|---|---|
| 自然语言输入与决策上下文 | 已实现 | `app.py` |
| Coordinator / Crawler / Analyzer / Reporter | 已实现 | `agents/` |
| 多竞品并行采集与失败隔离 | 已实现 | `agents/crawler.py` |
| Playwright + requests 降级 | 已实现 | `agents/crawler.py` |
| OpenAI 兼容模型接入 | 已实现 | `.env.example`、`agents/` |
| JSON Schema 校验与自动修复 | 已实现 | `utils/json_schema.py` |
| 数据真实性质量门禁 | 已实现 | `agents/analyzer.py` |
| 来源 URL、字段与采集时间追踪 | 已实现 | `agents/crawler.py`、`agents/reporter.py` |
| ChromaDB 历史数据检索 | 实验性 | `vector_store.py` |
| App Store / GitHub Release 数据 | 实验性，受网络与产品类型限制 | `agents/crawler.py` |
| PDF、API、定时监控、团队协作 | 未实现 | 仅为后续规划 |

“实验性”表示已有代码路径，但尚未在足够样本上形成稳定性结论。

## 快速演示

环境要求：Python 3.10+。

```bash
pip install -r requirements.txt
streamlit run app.py
```

页面默认进入演示模式，不需要 API Key。推荐演示路径：

1. 选择“版本规划”。
2. 输入“分析 Notion 和 Obsidian”。
3. 观察并行采集状态。
4. 在“分析结果”查看结构化对比。
5. 下载带 `DEMO` 标识的模拟报告。

真实分析需在 `.env` 中配置：

```env
OPENAI_API_KEY=your-key
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=your-model
```

随后取消“演示模式”。部分动态网站可能要求安装 Playwright 浏览器：

```bash
python -m playwright install chromium
```

## 验证

### 自动发现竞品

在“新建分析 → 输入竞品”选择 **帮我找竞品**，填写自己的产品网址或业务描述，点击“搜索竞品候选”。系统复用公开搜索与当前配置的 OpenAI 兼容模型，展示最多 5 个候选、匹配理由和搜索来源。勾选 2～5 个候选并点击“确认竞品，准备分析”，再点击“开始分析”进入原有采集与报告流程。

- 竞品发现始终使用真实搜索和模型，需要配置 API Key；侧栏演示模式只影响后续分析。
- 默认使用搜狗，空结果时尝试 Bing RSS。公共搜索可能遇到验证码或不相关结果；可在“搜索配置”填写 Exa Key，或在 `.env` 配置 `EXA_API_KEY`，改用 [Exa 搜索 API](https://exa.ai/docs/reference/search)。Exa 按其账户计费，本地不会保存页面中填写的 Key 到文件。
- 搜索无结果或模型响应无有效来源时会提示重试，不会以模型记忆替代搜索证据。
- 匹配理由是 AI 判断，来源可能是第三方比较文章；候选是否适合仍需用户确认。
- 修改网址、描述、产品名、市场或目标用户后需重新搜索；修改勾选项后需重新确认。
- 手动输入入口保留。已确认名称直接传给 Coordinator，不由后续模型重新选择。

### 离线回归

```bash
python -m pytest tests/test_competitor_discovery.py tests/test_confirmed_competitors.py tests/test_discovery_ui.py -q
python -m pytest tests/test_quality_gate.py tests/test_offline_fallbacks.py -q
python -m pytest tests -q
python tests/benchmark_crawl_accuracy.py
```

当前仓库不预设“准确率 85%”或“5 分钟完成”等结果。只有按 [评测说明](docs/EVALUATION.md) 产生原始样本、人工标注和运行记录后，才能在简历中引用对应数字。

## 关键技术取舍

- **为什么使用多 Agent**：采集、分析和报告的输入输出与失败方式不同，拆分后可以单独重试、测试和降级；简单任务不必强行多 Agent。
- **为什么使用 LangGraph**：显式管理步骤状态、条件分支和失败恢复，适合可观察的多阶段任务。
- **为什么保留 RAG**：复用历史竞品画像作为参考，但历史内容不能替代本次网页证据。
- **为什么需要质量门禁**：JSON 格式正确不代表内容真实，仍需检查来源、字段覆盖率和是否由 LLM 补全。

更多面试讲解见 [项目答辩说明](docs/INTERVIEW_GUIDE.md)。

## 已知边界

- 网页结构变化、登录墙和反爬策略会影响采集完整度。
- 搜索和 LLM 服务的可用性、延迟、费用由外部服务决定。
- 自动生成的洞察仍需人工判断；低置信度内容不能作为事实使用。
- 当前主要面向 SaaS 功能和定价分析，不适用于严肃投资或法律尽调。

## 项目结构

```text
app.py                  Streamlit 演示入口
main.py                 CLI 入口
agents/                 四类业务 Agent
multi_agent/            实验性多 Agent 编排
utils/json_schema.py    结构化输出校验
vector_store.py         历史竞品检索
templates/              报告模板
tests/                  离线测试与真实网站评测
docs/                   PRD、架构、评测和答辩文档
```

## 下一步

1. 固定一组 SaaS 基准样本并发布可复现实测结果。
2. 让每个功能矩阵单元格直接关联字段级证据。
3. 增加失败任务恢复和两次报告差异对比。
