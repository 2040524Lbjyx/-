"""
简化测试脚本 - 不依赖外部包，只测试代码逻辑
"""

import sys
import os
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

print("=" * 60)
print("竞品分析多Agent系统 - 简化测试（不依赖外部包）")
print("=" * 60)

# 测试1: 检查文件结构
print("\n测试 1: 检查文件结构...")
required_files = [
    "agents/__init__.py",
    "agents/coordinator.py",
    "agents/crawler.py",
    "agents/analyzer.py",
    "agents/reporter.py",
    "vector_store.py",
    "app.py",
    "main.py",
    "tests/test_agents.py",
    "requirements.txt"
]

missing_files = []
for f in required_files:
    if not Path(f).exists():
        missing_files.append(f)

if missing_files:
    print(f"❌ 缺少文件: {missing_files}")
else:
    print("✅ 所有必需文件存在")

# 测试2: 语法检查
print("\n测试 2: Python语法检查...")

python_files = [
    "agents/__init__.py",
    "agents/coordinator.py",
    "agents/crawler.py",
    "agents/analyzer.py",
    "agents/reporter.py",
    "vector_store.py",
    "app.py",
    "main.py",
    "tests/test_agents.py"
]

syntax_errors = []
for py_file in python_files:
    if Path(py_file).exists():
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                compile(f.read(), py_file, 'exec')
            print(f"  ✅ {py_file}")
        except SyntaxError as e:
            print(f"  ❌ {py_file}: {e}")
            syntax_errors.append(py_file)
        except Exception as e:
            print(f"  ⚠️  {py_file}: {e}")

if syntax_errors:
    print(f"\n❌ {len(syntax_errors)} 个文件有语法错误")
else:
    print("\n✅ 所有Python文件语法正确")

# 测试3: 检查代码关键功能（通过字符串匹配）
print("\n测试 3: 检查关键功能实现...")

# 检查 Crawler 的 Playwright 集成
print("\n  检查 Crawler Agent...")
with open("agents/crawler.py", 'r', encoding='utf-8') as f:
    crawler_code = f.read()

if "playwright" in crawler_code.lower():
    print("    ✅ Playwright 集成")
else:
    print("    ❌ Playwright 未集成")

if "max_retries" in crawler_code:
    print("    ✅ 重试机制")
else:
    print("    ❌ 重试机制未实现")

if "random_delay" in crawler_code:
    print("    ✅ 反爬虫延迟")
else:
    print("    ❌ 反爬虫延迟未实现")

# 检查向量数据库
print("\n  检查向量数据库...")
with open("vector_store.py", 'r', encoding='utf-8') as f:
    vector_code = f.read()

if "ChromaDB" in vector_code or "chromadb" in vector_code.lower():
    print("    ✅ ChromaDB 集成")
else:
    print("    ❌ ChromaDB 未集成")

if "search_similar" in vector_code:
    print("    ✅ 语义搜索功能")
else:
    print("    ❌ 语义搜索功能未实现")

if "add_competitor" in vector_code:
    print("    ✅ 添加竞品数据功能")
else:
    print("    ❌ 添加竞品数据功能未实现")

# 检查 Streamlit 界面
print("\n  检查 Streamlit Web界面...")
with open("app.py", 'r', encoding='utf-8') as f:
    app_code = f.read()

if "streamlit" in app_code.lower():
    print("    ✅ Streamlit 集成")
else:
    print("    ❌ Streamlit 未集成")

if "st.tabs" in app_code:
    print("    ✅ 多标签页界面")
else:
    print("    ❌ 多标签页界面未实现")

if "vector_store" in app_code:
    print("    ✅ 向量数据库搜索界面")
else:
    print("    ❌ 向量数据库搜索界面未实现")

# 测试4: 检查测试用例
print("\n  检查测试用例...")
with open("tests/test_agents.py", 'r', encoding='utf-8') as f:
    test_code = f.read()

test_count = test_code.count("def test_")
print(f"    ✅ 找到 {test_count} 个测试函数")

if "test_vector_store" in test_code:
    print("    ✅ 向量数据库测试")
else:
    print("    ❌ 向量数据库测试未实现")

if "test_integration" in test_code:
    print("    ✅ 集成测试")
else:
    print("    ❌ 集成测试未实现")

# 总结
print("\n" + "="*60)
print("测试总结")
print("="*60)

if not missing_files and not syntax_errors:
    print("\n✅ 代码基础检查通过！")
    print("\n下一步:")
    print("1. 安装依赖包: pip install -r requirements.txt")
    print("2. 安装 Playwright 浏览器: playwright install")
    print("3. 运行完整测试: python tests/test_agents.py")
    print("4. 启动 Web 界面: streamlit run app.py")
else:
    print("\n❌ 代码检查失败，请修复上述错误")
    sys.exit(1)

print("\n" + "="*60)
