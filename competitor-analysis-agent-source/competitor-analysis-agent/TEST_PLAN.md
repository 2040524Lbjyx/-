# 测试计划 - 竞品分析系统

## 测试目标
1. 测试演示模式（CLI + Streamlit）
2. 测试真实模式（需要 API Key）
3. 记录所有发现的问题

## 测试步骤

### 步骤 1：测试 CLI 演示模式
```bash
python main.py "分析Notion和Obsidian" --demo
```

**预期结果：**
- 使用模拟数据，不调用真实 API
- 生成报告文件
- 无错误输出

**已知问题：**
- ❌ 编码问题（emoji 字符导致 UnicodeEncodeError）
- ✅ 已修复：移除 main.py 中的 emoji 字符

### 步骤 2：测试 Streamlit 演示模式
```bash
streamlit run app.py
```

**测试操作：**
1. 勾选"演示模式"
2. 点击"📝 Notion vs Obsidian"
3. 点击"🚀 开始分析"
4. 观察进度条和并行爬取状态卡片

**预期结果：**
- 进度条正常更新
- 并行爬取状态卡片显示正确
- 生成报告并显示

**需要检查：**
- ✅ .env 文件检测
- ✅ API 配置界面
- ✅ Playwright 检测（演示模式不需要）
- ✅ 向量搜索模型下载提示

### 步骤 3：测试真实模式（需要 API Key）
```bash
# 编辑 .env 文件，填入 API Key
# 然后运行：
python main.py "分析Notion和Obsidian" --verbose
```

**或者运行：**
```bash
# 取消勾选"演示模式"
# 点击"🚀 开始分析"
```

**预期结果：**
- 调用真实的 LLM API
- 爬取竞品官网数据
- 生成真实的分析报告

**需要检查：**
- ✅ Playwright 浏览器是否已安装
- ✅ API Key 配置是否正确
- ✅ 爬虫是否能正常访问网站
- ✅ LLM 分析是否正常工作

## 问题记录

### 问题 1：编码问题（已修复）
- **现象：** `print()` 中的 emoji 字符导致 `UnicodeEncodeError`
- **原因：** Windows 控制台使用 GBK 编码，不支持 emoji
- **修复：** 移除 `main.py` 中的所有 emoji 字符

### 问题 2：依赖安装缓慢（进行中）
- **现象：** `pip install -r requirements.txt` 耗时超过 7 分钟
- **原因：** 需要编译 lxml 等依赖
- **状态：** 正在安装中...

### 问题 3：requirements.txt 版本过旧
- **现象：** 依赖版本较旧（langchain==0.1.0 等）
- **影响：** 可能与最新代码不兼容
- **建议：** 升级到最新稳定版本

## 下一步

1. 等待依赖安装完成
2. 运行测试
3. 记录结果
4. 修复发现的问题
