# 竞品分析多Agent系统 - 架构设计文档

## 一、架构概览

### 1.1 设计原则

1. **模块化**: 每个Agent独立开发和测试
2. **可扩展**: 易于添加新Agent或数据源
3. **容错性**: 单个Agent失败不影响整体系统
4. **可观测**: 完整的日志和监控

### 1.2 整体架构

采用**分层架构 + 多Agent协作**模式:

```
┌─────────────────────────────────────────────────────────┐
│                    Presentation Layer                    │
│  CLI / Web UI (Streamlit) / API (FastAPI)               │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────────┐
│                    Orchestration Layer                   │
│  Coordinator Agent (LangGraph State Machine)            │
│  - 意图理解                                              │
│  - 任务规划                                              │
│  - Agent调度                                             │
│  - 结果汇总                                              │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
┌───────▼─────┐ ┌───▼────┐ ┌────▼─────┐
│  Worker     │ │Analysis│ │  Report  │
│  Agents     │ │  Agent │ │  Agent   │
│  (Crawler)  │ │        │ │          │
└───────┬─────┘ └───┬────┘ └────┬─────┘
        │            │            │
┌───────┼────────────┼────────────┼────────────────────────┐
│       │    Technology Layer                           │
│  ┌────▼─────┐ ┌───▼────┐ ┌────▼─────┐                │
│  │Playwright│ │ GPT-4  │ │ Jinja2   │                │
│  │Beautiful │ │ API    │ │ Matplot  │                │
│  │ Soup     │ │        │ │  lib     │                │
│  └────┬─────┘ └───┬────┘ └────┬─────┘                │
│       │            │            │                      │
│  ┌────▼─────┐ ┌───▼────┐ ┌────▼─────┐                │
│  │ ChromaDB │ │ Redis  │ │ File     │                │
│  │(Vector)  │ │(Cache) │ │ System   │                │
│  └──────────┘ └────────┘ └──────────┘                │
└────────────────────────────────────────────────────────┘
```

---

## 二、Agent详细设计

### 2.1 Coordinator Agent

#### 2.1.1 状态定义 (LangGraph State)

```python
from typing import TypedDict, List, Optional
from enum import Enum

class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class WorkflowState(TypedDict):
    """LangGraph工作流的状态"""
    
    # 用户输入
    user_query: str
    competitors: List[str]
    
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
    retry_count: int
```

#### 2.1.2 工作流定义

```python
from langgraph.graph import StateGraph, END

def create_workflow():
    workflow = StateGraph(WorkflowState)
    
    # 添加节点
    workflow.add_node("understand_intent", understand_intent)
    workflow.add_node("create_plan", create_plan)
    workflow.add_node("crawler", run_crawler)
    workflow.add_node("analyzer", run_analyzer)
    workflow.add_node("reporter", run_reporter)
    workflow.add_node("handle_error", handle_error)
    
    # 定义边 (执行顺序)
    workflow.set_entry_point("understand_intent")
    
    workflow.add_edge("understand_intent", "create_plan")
    workflow.add_edge("create_plan", "crawler")
    workflow.add_edge("crawler", "analyzer")
    workflow.add_edge("analyzer", "reporter")
    workflow.add_edge("reporter", END)
    
    # 条件边 (错误处理)
    workflow.add_conditional_edges(
        "crawler",
        should_retry,
        {
            "retry": "crawler",
            "error": "handle_error",
            "continue": "analyzer"
        }
    )
    
    return workflow.compile()
```

#### 2.1.3 决策逻辑

```python
def should_retry(state: WorkflowState) -> str:
    """决定是否重试"""
    if state["crawler_status"] == AgentStatus.FAILED:
        if state["retry_count"] < 3:
            state["retry_count"] += 1
            return "retry"
        else:
            return "error"
    return "continue"
```

---

### 2.2 Data Collection Agent

#### 2.2.1 类设计

```python
class DataCollectionAgent:
    """数据采集Agent"""
    
    def __init__(self, use_playwright: bool = True):
        self.crawler = PlaywrightCrawler() if use_playwright else BeautifulSoupCrawler()
        self.llm = ChatOpenAI(model="gpt-4")
        self.vector_db = ChromaDB()
    
    def collect(self, competitor_name: str, website: str) -> Dict:
        """采集竞品数据"""
        
        # 1. 检查缓存
        cached = self.vector_db.get(competitor_name)
        if cached and not self.is_stale(cached):
            return cached
        
        # 2. 爬取数据
        raw_data = self.crawl_website(website)
        
        # 3. 提取结构化信息
        structured_data = self.extract_structured_data(raw_data)
        
        # 4. 存储到向量库
        self.vector_db.store(competitor_name, structured_data)
        
        return structured_data
    
    def crawl_website(self, url: str) -> str:
        """爬取网页"""
        pages_to_crawl = [
            url,
            url.rstrip("/") + "/features",
            url.rstrip("/") + "/pricing"
        ]
        
        results = {}
        for page_url in pages_to_crawl:
            try:
                html = self.crawler.crawl(page_url)
                results[page_url] = html
            except Exception as e:
                logger.error(f"Failed to crawl {page_url}: {e}")
        
        return results
    
    def extract_structured_data(self, raw_data: Dict) -> Dict:
        """使用LLM提取结构化数据"""
        
        prompt = f"""
        从以下网页内容中提取竞品信息：
        
        网页内容：
        {raw_data}
        
        请提取以下信息（JSON格式）：
        - 产品名称
        - 核心功能列表
        - 定价信息
        - 公司信息
        """
        
        response = self.llm.invoke(prompt)
        return json.loads(response.content)
```

#### 2.2.2 爬虫策略

```python
class PlaywrightCrawler:
    """使用Playwright处理动态页面"""
    
    def __init__(self):
        self.playwright = None
        self.browser = None
    
    def init_browser(self):
        """初始化浏览器"""
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=True)
    
    def crawl(self, url: str) -> str:
        """爬取页面"""
        if not self.browser:
            self.init_browser()
        
        page = self.browser.new_page()
        
        # 设置User-Agent
        page.set_extra_http_headers({
            "User-Agent": self.get_random_user_agent()
        })
        
        # 访问页面
        page.goto(url, wait_until="networkidle")
        
        # 等待动态内容加载
        page.wait_for_timeout(2000)
        
        # 获取HTML
        html = page.content()
        
        page.close()
        return html
    
    def get_random_user_agent(self) -> str:
        """随机User-Agent"""
        user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            # ...
        ]
        return random.choice(user_agents)
```

---

### 2.3 Analysis Agent

#### 2.3.1 功能对比实现

```python
class AnalysisAgent:
    """分析Agent"""
    
    def __init__(self):
        self.llm = ChatOpenAI(model="gpt-4")
    
    def compare_features(self, competitors_data: List[Dict]) -> pd.DataFrame:
        """功能对比"""
        
        # 1. 标准化功能名称
        standardized_features = self.standardize_features(competitors_data)
        
        # 2. 构建对比矩阵
        matrix = []
        for feature in standardized_features:
            row = {"功能": feature}
            for comp in competitors_data:
                row[comp["name"]] = self.has_feature(comp, feature)
            matrix.append(row)
        
        return pd.DataFrame(matrix)
    
    def standardize_features(self, competitors_data: List[Dict]) -> List[str]:
        """标准化功能名称"""
        
        # 收集所有功能
        all_features = []
        for comp in competitors_data:
            all_features.extend(comp["features"])
        
        # 使用LLM进行功能聚类
        prompt = f"""
        以下功能列表中,有些是同一个功能的不同表述,请进行标准化：
        
        {all_features}
        
        输出标准化后的功能列表（JSON数组）。
        """
        
        response = self.llm.invoke(prompt)
        return json.loads(response.content)
    
    def analyze_pricing(self, competitors_data: List[Dict]) -> Dict:
        """定价分析"""
        
        pricing_info = []
        for comp in competitors_data:
            pricing_info.append({
                "competitor": comp["name"],
                "pricing": comp["pricing"]
            })
        
        prompt = f"""
        分析以下竞品的定价策略：
        
        {pricing_info}
        
        请分析：
        1. 定价模式（订阅/一次性/免费增值）
        2. 价格区间
        3. 性价比
        4. 定价策略建议
        
        输出JSON格式。
        """
        
        response = self.llm.invoke(prompt)
        return json.loads(response.content)
    
    def generate_insights(self, feature_comparison: pd.DataFrame, 
                          pricing_analysis: Dict) -> List[str]:
        """生成AI洞察"""
        
        prompt = f"""
        你是一位资深的产品战略顾问。
        
        功能对比：
        {feature_comparison.to_markdown()}
        
        定价分析：
        {pricing_analysis}
        
        请生成3-5条有价值的商业洞察，包括：
        1. 差异化定位
        2. 优劣势分析
        3. 战略建议
        
        输出JSON格式：{{"insights": ["洞察1", "洞察2", ...]}}
        """
        
        response = self.llm.invoke(prompt)
        return json.loads(response.content)["insights"]
```

---

### 2.4 Report Agent

#### 2.4.1 报告生成

```python
class ReportAgent:
    """报告生成Agent"""
    
    def __init__(self, template_dir: str = "templates"):
        self.template_env = Environment(loader=FileSystemLoader(template_dir))
    
    def generate(self, analysis_results: Dict, output_format: str = "markdown") -> str:
        """生成报告"""
        
        if output_format == "markdown":
            return self.generate_markdown(analysis_results)
        elif output_format == "html":
            return self.generate_html(analysis_results)
        else:
            raise ValueError(f"Unsupported format: {output_format}")
    
    def generate_markdown(self, results: Dict) -> str:
        """生成Markdown报告"""
        
        template = self.template_env.get_template("report_template.md.j2")
        
        # 准备模板数据
        context = {
            "title": f"竞品分析报告: {results['competitors']}",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "executive_summary": results["insights"][0] if results["insights"] else "",
            "feature_matrix": results["feature_matrix"].to_markdown(),
            "pricing_analysis": results["pricing_analysis"],
            "insights": results["insights"],
            "charts": results.get("charts", [])
        }
        
        return template.render(**context)
    
    def generate_charts(self, results: Dict) -> List[str]:
        """生成可视化图表"""
        
        charts = []
        
        # 1. 功能覆盖度雷达图
        radar_chart = self.create_radar_chart(results["feature_matrix"])
        charts.append(radar_chart)
        
        # 2. 定价对比条形图
        pricing_chart = self.create_pricing_chart(results["pricing_analysis"])
        charts.append(pricing_chart)
        
        return charts
    
    def create_radar_chart(self, feature_matrix: pd.DataFrame) -> str:
        """创建雷达图"""
        
        # 实现略
        pass
```

---

## 三、数据流设计

### 3.1 数据流转图

```
用户输入: "分析Notion和Obsidian"
    ↓
[Coordinator: 理解意图]
    ↓
输出: {
  "competitors": ["Notion", "Obsidian"],
  "dimensions": ["features", "pricing"]
}
    ↓
[Coordinator: 任务规划]
    ↓
计划: [
  {"agent": "crawler", "target": "Notion"},
  {"agent": "crawler", "target": "Obsidian"},
  {"agent": "analyzer", "type": "features"},
  {"agent": "analyzer", "type": "pricing"},
  {"agent": "reporter", "format": "markdown"}
]
    ↓
执行...
    ↓
[Data Collection Agent]
    ↓
爬取: Notion官网 → features, pricing
爬取: Obsidian官网 → features, pricing
    ↓
输出: {
  "notion": {...},
  "obsidian": {...}
}
    ↓
[Analysis Agent]
    ↓
分析: 功能对比、定价分析
    ↓
输出: {
  "feature_matrix": DataFrame,
  "pricing_analysis": {...},
  "insights": [...]
}
    ↓
[Report Agent]
    ↓
生成: Markdown报告
    ↓
输出: report.md
```

### 3.2 数据存储策略

```python
# 缓存策略
cache_policy = {
    "raw_html": {
        "ttl": 86400,  # 1天
        "storage": "filesystem"
    },
    "structured_data": {
        "ttl": 604800,  # 7天
        "storage": "chromadb"
    },
    "analysis_results": {
        "ttl": 2592000,  # 30天
        "storage": "postgresql"
    }
}
```

---

## 四、错误处理设计

### 4.1 错误分类

```python
class AgentError(Exception):
    """Agent基础错误"""
    pass

class CrawlerError(AgentError):
    """爬虫错误"""
    pass

class LLMError(AgentError):
    """LLM调用错误"""
    pass

class AnalysisError(AgentError):
    """分析错误"""
    pass
```

### 4.2 重试策略

```python
from tenacity import retry, stop_after_attempt, wait_exponential

class RetryPolicy:
    """重试策略"""
    
    @staticmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    def call_with_retry(func, *args, **kwargs):
        """带重试的调用"""
        return func(*args, **kwargs)
```

### 4.3 降级策略

```python
def analyze_with_fallback(competitor_data):
    """分析失败时的降级策略"""
    
    try:
        # 主要方法: 使用LLM
        return analyze_with_llm(competitor_data)
    except LLMError:
        try:
            # 降级方法1: 使用规则
            return analyze_with_rules(competitor_data)
        except Exception:
            # 降级方法2: 返回原始数据
            return {
                "feature_matrix": competitor_data["features"],
                "insights": ["分析失败，请查看原始数据"]
            }
```

---

## 五、性能优化

### 5.1 并行处理

```python
from concurrent.futures import ThreadPoolExecutor

def crawl_competitors_parallel(competitors: List[str]) -> List[Dict]:
    """并行爬取多个竞品"""
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(crawler.collect, comp) 
            for comp in competitors
        ]
        results = [f.result() for f in futures]
    
    return results
```

### 5.2 缓存机制

```python
from functools import lru_cache

class Cache:
    """缓存层"""
    
    def __init__(self):
        self.redis = redis.Redis()
    
    def get(self, key: str):
        """获取缓存"""
        cached = self.redis.get(key)
        if cached:
            return json.loads(cached)
        return None
    
    def set(self, key: str, value: Any, ttl: int = 3600):
        """设置缓存"""
        self.redis.setex(key, ttl, json.dumps(value))
    
    @staticmethod
    def cache_key(func_name: str, *args) -> str:
        """生成缓存键"""
        return f"{func_name}:{hash(str(args))}"
```

### 5.3 异步处理

```python
import asyncio

async def analyze_competitors_async(competitors: List[str]):
    """异步分析"""
    
    tasks = [
        asyncio.create_task(analyze_competitor(comp))
        for comp in competitors
    ]
    
    results = await asyncio.gather(*tasks)
    return results
```

---

## 六、监控与日志

### 6.1 日志设计

```python
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('agent_system.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# 使用示例
logger.info("Coordinator Agent started")
logger.error("Crawler Agent failed", exc_info=True)
```

### 6.2 性能指标

```python
class Metrics:
    """性能指标收集"""
    
    def __init__(self):
        self.start_time = time.time()
        self.agent_times = {}
    
    def record_agent_time(self, agent_name: str, duration: float):
        """记录Agent执行时间"""
        self.agent_times[agent_name] = duration
    
    def get_summary(self) -> Dict:
        """获取性能摘要"""
        return {
            "total_time": time.time() - self.start_time,
            "agent_times": self.agent_times
        }
```

---

## 七、部署架构

### 7.1 Docker部署

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  app:
    build: .
    ports:
      - "8000:8000"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    depends_on:
      - postgres
      - redis
      - chromadb
  
  postgres:
    image: postgres:15
    environment:
      POSTGRES_PASSWORD: password
  
  redis:
    image: redis:7
  
  chromadb:
    image: chromadb/chroma:latest
    ports:
      - "8001:8000"
```

---

## 八、安全设计

### 8.1 API密钥管理

```python
from dotenv import load_dotenv
import os

# 从环境变量加载
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found")
```

### 8.2 爬取合规性

```python
import robotsparser

class ComplianceChecker:
    """合规性检查"""
    
    def __init__(self):
        self.parser = robotsparser.RobotFileParser()
    
    def can_crawl(self, url: str) -> bool:
        """检查是否可以爬取"""
        self.parser.set_url(url + "/robots.txt")
        self.parser.read()
        return self.parser.can_fetch("*", url)
```

---

## 九、扩展性设计

### 9.1 插件化数据源

```python
from abc import ABC, abstractmethod

class DataSource(ABC):
    """数据源基类"""
    
    @abstractmethod
    def fetch(self, competitor: str) -> Dict:
        """获取数据"""
        pass

class AppStoreDataSource(DataSource):
    """App Store数据源"""
    
    def fetch(self, competitor: str) -> Dict:
        # 实现
        pass

class NewsDataSource(DataSource):
    """新闻数据源"""
    
    def fetch(self, competitor: str) -> Dict:
        # 实现
        pass

# 注册数据源
data_sources = {
    "website": WebsiteDataSource(),
    "app_store": AppStoreDataSource(),
    "news": NewsDataSource()
}
```

---

## 十、测试策略

### 10.1 单元测试示例

```python
import pytest

def test_coordinator_intent_understanding():
    """测试Coordinator的意图理解"""
    
    coordinator = CoordinatorAgent()
    
    # 测试1: 基本功能
    result = coordinator.understand_intent("分析Notion和Obsidian")
    assert result["competitors"] == ["Notion", "Obsidian"]
    
    # 测试2: 边缘情况
    result = coordinator.understand_intent("对比")
    assert result["competitors"] == []
```

---

## 附录: 技术决策记录

### ADR-001: 选择LangGraph作为Agent框架

**状态**: 已接受

**背景**: 需要选择一个框架来实现多Agent协作

**考虑的方案**:
1. LangGraph - 工作流编排能力强
2. AutoGen - 对话能力强
3. CrewAI - 简单易用

**决策**: 选择LangGraph

**理由**:
- 与LangChain生态集成好
- 状态机模型清晰
- 社区活跃

**后果**:
- 学习成本中等
- 需要理解状态机概念

---

**文档结束**
