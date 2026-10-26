# 测试发现（2026-09-07）

## 修复结果（2026-09-07）

以下四项缺陷均已修复并加入回归测试；下文保留的是修复前的复现记录。

- app.py 与 Coordinator 的本地降级路径共用 utils/query_parser.py：去除分析维度和页面附加上下文，支持 vs / VS. / versus / and 连接词。
- 示例按钮通过回调更新输入控件；当前输入是需求的唯一来源，清空或仅输入空白时禁用开始按钮。
- Analyzer 要求字段关联有效 HTTP(S) 来源 URL。只有页面访问记录不能验证功能、价格或版本；旧数据仅在有明确字段证据时兼容。
- 版本 API 同样需要来源 URL，LLM 降级数据不能借此被算作已验证更新。
- 测试先确认原缺陷导致断言失败，再修改实现。最终命令：

```powershell
& 'D:/graduate/python.exe' -m pytest tests/test_input_regressions.py tests/test_quality_gate.py tests/test_offline_fallbacks.py tests/test_parallel_crawler.py -q --tb=short
```

结果：30 passed in 24.73s。app.py、agents/analyzer.py、agents/coordinator.py、utils/query_parser.py 的 py_compile 检查通过。

本轮验证覆盖 Streamlit AppTest 输入交互和演示报告生成；向量库在输入测试中使用空库替身隔离，未验证真实网站/LLM 全链路。已有缺少字段证据的历史数据现在会降级，这是预期行为。字段关联 URL 并不等于人工核实了网页事实。

范围：当前 competitor-analysis-agent 项目。未修改业务代码。使用现有离线测试、生产函数的 AST 提取执行、Streamlit AppTest 页面交互和演示报告生成；未进行浏览器视觉测试或真实网站/LLM 全链路测试。

## 已确认缺陷

### 1. P1：没有来源证据的数据通过真实性门禁

- 位置：agents/analyzer.py:201–236、279。
- 复现：给 assess_data_quality 传入一个产品，仅含 core 功能、pricing.model、changelog.latest_version，_field_evidence 为空，没有任何 URL，也未声明数据来源。
- 实际：status=passed，score=65，analysis_mode=evidence_based，evidence_count=0，功能、定价和版本均计为已验证；同时 issues 又提示缺少来源 URL。
- 预期：缺少来源的数据应降级，不应宣称已验证或基于证据。
- 原因：空字段证据触发旧缓存兼容判断；功能只要不标记为 LLM 即计为已验证，定价和版本也未要求来源证据，最终通过条件只看功能数量和分数。

### 2. P1：页面自带示例被识别为错误竞品，仍生成成功报告

- 位置：app.py:262–280、744–747。
- 复现：演示模式输入“分析Notion和Obsidian的功能和定价”，点击开始分析。
- 实际：报告竞品是 ['Notion', 'Obsidian的功能', '定价']，任务 status=success。AppTest 全流程已确认。
- 补充：直接执行解析函数，输入“Notion vs Obsidian”得到 ['Notion', 'vs', 'Obsidian']。
- 预期：只分析 Notion、Obsidian，功能和定价作为分析维度。
- 原因：简单按连词和空白切分，没有剥离分析维度、所属语句和英文连接词。

### 3. P2：点击示例按钮不替换已有输入

- 位置：app.py:636–642、660–670。
- 复现：输入“分析抖音和快手”，然后点击“📝 Notion vs Obsidian”。
- 实际：输入框仍显示“分析抖音和快手”。AppTest 已确认。
- 预期：输入框和实际分析需求都切换到所点示例。
- 原因：按钮更新 user_query，但输入框绑定的是 __user_query_input__，已有控件状态未同步。

### 4. P2：清空输入后继续使用隐藏的历史需求

- 位置：app.py:644、679。
- 复现：执行上一条步骤，然后清空输入框。
- 实际：输入框为空，开始分析仍启用，提示“系统将分析：分析Notion和Obsidian”。AppTest 已确认。
- 预期：清空后禁用开始按钮，等待新需求。
- 原因：空输入被替换为 session_state.user_query 中的旧值。

## 验证结果与限制

- D:/graduate/python.exe -m pytest tests/test_quality_gate.py tests/test_offline_fallbacks.py -q：9 passed，60.94 秒。
- tmp_qa_probe.py：退出码 0；初始页面和演示任务均无 AppTest 异常；确认上述四项缺陷。原始结果见 tmp_qa_probe.log。
- 项目 venv 缺少 pytest；机器的 D:/graduate Python 可运行上述测试，但缺少 chromadb，故 AppTest 没有覆盖真实向量搜索。
- 另用项目 venv，在独立 tmp_qa_vector_db 中创建轻量向量库并写入 QA sample，退出码 0；不据此推断搜索功能完整通过。
- 测试创建了一份 reports/demo 下的演示报告及独立测试向量库，没有修改已有报告或正式数据库内容。
- 不应因现有 9 项测试通过而判定项目无问题；这些测试未覆盖上面的输入与页面状态场景。
