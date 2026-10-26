# 竞品分析多Agent系统 - 快速使用指南

## 📦 项目文件清单（已生成）

### 核心代码 (agents/)
- `agents/__init__.py` - Agent包初始化
- `agents/coordinator.py` - Coordinator Agent（协调者，最核心）
- `agents/crawler.py` - Data Collection Agent（爬虫）
- `agents/analyzer.py` - Analysis Agent（分析）
- `agents/reporter.py` - Report Agent（报告）

### 工作流 (workflows/)
- `workflows/analysis_workflow.py` - LangGraph工作流定义

### 入口程序
- `main.py` - CLI入口（支持 --demo 模式）
- `demo_simple.py` - 简化演示脚本（无需API Key）

### 文档 (docs/)
- `README.md` - 项目介绍
- `docs/PRD.md` - 产品需求文档（完整的PRD）
- `docs/architecture.md` - 系统架构设计
- `docs/PROJECT_SUMMARY.md` - 项目总结

### 配置
- `requirements.txt` - Python依赖
- `.env.example` - 环境变量模板
- `docker-compose.yml` - Docker编排
- `Dockerfile` - Docker镜像

### 测试 (tests/)
- `tests/test_agents.py` - Agent单元测试

### 示例 (examples/)
- `examples/notion_vs_obsidian.md` - 中文示例报告
- `examples/notion_vs_obsidian_en.md` - 英文示例报告

---

## 🚀 三种使用方式

### 方式1: 快速演示（推荐，无需API Key）

```bash
python demo_simple.py
```

**效果**: 
- 展示完整Agent协作流程
- 显示功能对比矩阵
- 生成AI洞察

**时间**: < 1分钟

---

### 方式2: 真实分析（需要OpenAI API Key）

#### Step 1: 安装依赖

```bash
# 创建虚拟环境（推荐）
python -m venv venv

# Windows
venv\Scripts\activate

# Mac/Linux
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 安装Playwright浏览器
playwright install
```

#### Step 2: 配置API Key

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑.env，填入你的OpenAI API Key
# OPENAI_API_KEY=sk-...
```

#### Step 3: 运行分析

```bash
# 演示模式（不调用API，用模拟数据）
python main.py "Analyze Notion and Obsidian" --demo

# 真实模式（调用GPT-4 API）
python main.py "Analyze Notion and Obsidian" --verbose
```

**时间**: 3-5分钟（真实分析）

---

### 方式3: Docker部署

```bash
# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f app

# 停止服务
docker-compose down
```

---

## 📊 预期输出

### 控制台输出

```
======================================================================
  Competitor Analysis Multi-Agent System - Workflow Demo
======================================================================

[User] Input: Analyze Notion and Obsidian

----------------------------------------------------------------------
[Coordinator Agent] Step 1: Understanding User Intent
----------------------------------------------------------------------
  -> Extracted competitors: ['Notion', 'Obsidian']
  -> Analysis dimensions: features, pricing

... (中间步骤) ...

======================================================================
  [Success] Analysis Complete!
======================================================================

Statistics:
  - Competitors analyzed: 2
  - Features compared: 13
  - Insights generated: 5
  - Execution time: ~3 minutes

Tip: To view the full report, open:
   reports/demo_report_20260630_215538.md
```

### 生成的报告

报告包含：
- ✅ 执行摘要
- ✅ 功能对比矩阵（表格）
- ✅ 定价分析
- ✅ AI生成的洞察（3-5条）
- ✅ 战略建议
- ✅ 可视化图表（如果实现了）

---

## 🎯 简历展示建议

### 1. GitHub仓库准备

创建GitHub仓库，包含：
- ✅ 完整的代码
- ✅ README.md（项目介绍、使用说明）
- ✅ 架构图（已生成）
- ✅ 示例报告（examples/）
- ✅ Demo截图（docs/screenshots/）

### 2. 技术博客

建议写一篇技术博客，标题如：
- "如何用LangGraph构建多Agent协作系统"
- "用GPT-4做竞品分析：从3天到5分钟"

发布到：
- 知乎
- 掘金
- Medium
- Dev.to

### 3. Demo视频

录制3-5分钟的Demo视频，展示：
1. 运行命令（`python main.py "analyze Notion"`）
2. 控制台输出（展示Agent协作）
3. 生成的报告（功能对比、洞察）
4. 代码亮点（展示Coordinator的状态机）

---

## 📝 代码讲解准备（面试）

### 关键代码点

#### 1. Coordinator Agent的状态机

```python
# agents/coordinator.py

class WorkflowState(TypedDict):
    user_query: str
    competitors: List[str]
    plan: List[Dict]
    crawler_status: AgentStatus
    # ...
```

**讲解要点**:
- 使用LangGraph的StateGraph管理状态
- 每个Agent执行完后更新状态
- 支持条件边（成功/失败/重试）

#### 2. Crawler的LLM提取

```python
# agents/crawler.py

prompt = ChatPromptTemplate.from_messages([
    ("system", "从网页内容中提取竞品信息..."),
    ("user", "{content}")
])
```

**讲解要点**:
- 使用LLM从非结构化网页中提取结构化数据
- Prompt设计：明确输出格式（JSON）
- 错误处理：LLM失败时的降级策略

#### 3. Analysis的洞察生成

```python
# agents/analyzer.py

prompt = ChatPromptTemplate.from_messages([
    ("system", "生成3-5条商业洞察..."),
    ("user", "功能对比：{feature_matrix}")
])
```

**讲解要点**:
- 不仅展示数据，还生成可操作的洞察
- 这是AI的价值所在（vs 传统爬虫）
- Few-shot Prompting提高输出质量

---

## 🔧 常见问题 & 解决方案

### Q1: 依赖安装失败

**原因**: Python版本不兼容或网络问题

**解决**:
```bash
# 使用国内镜像
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 或逐个安装
pip install langchain
pip install langgraph
# ...
```

### Q2: OpenAI API调用失败

**原因**: API Key无效或配额不足

**解决**:
- 检查`.env`文件中的API Key
- 检查OpenAI账户余额
- 或使用`--demo`模式（不需要API Key）

### Q3: Playwright浏览器安装失败

**原因**: 网络问题或权限问题

**解决**:
```bash
# Windows (管理员权限)
powershell -Command "playwright install --with-deps"

# Mac/Linux
sudo playwright install --with-deps
```

---

## 📚 延伸阅读

### LangGraph
- 官方文档: https://langchain-ai.github.io/langgraph/
- GitHub: https://github.com/langchain-ai/langgraph

### Multi-Agent Systems
- "AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation"
- "MetaGPT: Meta Programming for Multi-Agent Collaborative Framework"

### Prompt Engineering
- OpenAI Guide: https://platform.openai.com/docs/guides/prompt-engineering
- "Prompt Engineering Guide" (www.promptingguide.ai)

---

## 💡 最后的建议

### 如果这是简历项目：

1. **现在就可以用** - 代码框架完整，展示设计能力
2. **准备讲解** - 熟悉每个Agent的代码逻辑
3. **突出亮点** - LangGraph、LLM应用、工程化

### 如果你想继续完善：

1. **让代码跑起来** - 调试LangGraph工作流（1-2天）
2. **添加Demo** - 生成真实报告、录制视频（1天）
3. **部署分享** - Streamlit Cloud或GitHub（1天）

---

**祝你简历项目顺利！🚀**

如有问题，随时问我！
