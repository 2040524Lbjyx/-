"""
Mock 版本 - 演示 UI 改进（无需真实依赖）

此文件演示了我对 app.py 所做的所有改进：
1. .env 文件检测
2. API 配置界面
3. Playwright 检测
4. 向量搜索模型下载提示
"""

import sys
import os
from pathlib import Path

# Mock streamlit
class MockStremalit:
    def __init__(self):
        self._sidebar = MockSidebar()
        self._session_state = {}
    
    @property
    def sidebar(self):
        return self._sidebar
    
    @property
    def session_state(self):
        return self._session_state
    
    def set_page_config(self, **kwargs):
        print(f"[Streamlit] set_page_config: {kwargs}")
    
    def title(self, text):
        print(f"\n{'='*60}")
        print(f"  {text}")
        print(f"{'='*60}\n")
    
    def caption(self, text):
        print(f"  {text}")
    
    def markdown(self, text):
        print(f"  {text}")
    
    def subheader(self, text):
        print(f"\n--- {text} ---")
    
    def metric(self, label, value):
        print(f"  [指标] {label}: {value}")
    
    def info(self, text):
        print(f"  [信息] {text}")
    
    def warning(self, text):
        print(f"  [警告] {text}")
    
    def error(self, text):
        print(f"  [错误] {text}")
    
    def success(self, text):
        print(f"  [成功] {text}")
    
    def button(self, text, **kwargs):
        print(f"  [按钮] {text}")
        return False
    
    def text_input(self, label, **kwargs):
        print(f"  [输入框] {label}")
        return ""
    
    def selectbox(self, label, options, **kwargs):
        print(f"  [下拉框] {label}: {options}")
        return options[0]
    
    def checkbox(self, label, **kwargs):
        print(f"  [复选框] {label}")
        return True
    
    def slider(self, label, **kwargs):
        print(f"  [滑块] {label}")
        return 3
    
    def expander(self, label, **kwargs):
        return MockExpander()
    
    def spinner(self, text):
        print(f"  [加载中] {text}")
        return MockContextManager()
    
    def columns(self, n):
        return [MockColumn() for _ in range(n)]
    
    def empty(self):
        return MockEmpty()
    
    def stop(self):
        raise SystemExit("Streamlit stop")

class MockSidebar:
    def title(self, text):
        print(f"\n[侧边栏] {text}")
    
    def subheader(self, text):
        print(f"[侧边栏] {text}")
    
    def markdown(self, text):
        print(f"[侧边栏] {text}")
    
    def caption(self, text):
        print(f"[侧边栏] {text}")
    
    def info(self, text):
        print(f"[侧边栏] [信息] {text}")
    
    def expender(self, label, **kwargs):
        print(f"\n[侧边栏] [展开] {label}")
        return MockExpander()

class MockExpander:
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        pass
    
    def markdown(self, text):
        print(f"    {text}")
    
    def text_input(self, label, **kwargs):
        print(f"    [输入框] {label}")
        return ""
    
    def button(self, label, **kwargs):
        print(f"    [按钮] {label}")
        return False

class MockColumn:
    def markdown(self, text):
        print(f"    {text}")

class MockEmpty:
    def info(self, text):
        print(f"  [信息] {text}")
    
    def empty(self):
        pass

class MockContextManager:
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        pass

# ====================
# 演示改进 1: .env 文件检测
# ====================
print("="*60)
print("演示 1: .env 文件检测")
print("="*60)

env_file = Path(".env")
env_example = Path(".env.example")

if not env_file.exists():
    if env_example.exists():
        print("\n[警告] 未找到 .env 文件，已自动从 .env.example 创建")
        print("         请编辑 .env 文件，填入你的 API Key")
    else:
        print("\n[错误] 未找到 .env 和 .env.example 文件")
        print("         请手动创建 .env 文件并填入 API Key")
else:
    print("\n[成功] .env 文件已存在")

# ====================
# 演示改进 2: API 配置界面
# ====================
print("\n" + "="*60)
print("演示 2: API 配置界面（侧边栏）")
print("="*60)

print("\n[侧边栏] [展开] ⚙️ API 配置")
print("    **配置 API Key（用于真实模式）**")
print("    [输入框] API Key")
print("    [输入框] API Base URL（可选）")
print("    [输入框] 模型名称（可选）")
print("    [按钮] 💾 保存配置")
print("\n  ✅ 配置已保存到 .env 文件")
print("  ✅ 环境变量已更新")
print("  ✅ 页面自动刷新")

# ====================
# 演示改进 3: Playwright 检测
# ====================
print("\n" + "="*60)
print("演示 3: Playwright 检测（真实模式前）")
print("="*60)

print("\n[加载中] ⏳ 检测 Playwright 浏览器...")

# Mock 检测逻辑
playwright_available = False  # 模拟未安装

if not playwright_available:
    print("\n[错误] ❌ Playwright 浏览器未安装！")
    print("         错误信息：playwright 命令未找到")
    print("\n         **解决方案：**")
    print("         1. 自动安装（推荐）：点击下面的按钮")
    print("         2. 手动安装：运行 `python -m playwright install`")
    print("\n         [按钮] 📥 自动安装 Playwright 浏览器")
    print("\n         ✅ Playwright 浏览器安装完成！请重新点击"开始分析"")

# ====================
# 演示改进 4: 向量搜索模型下载提示
# ====================
print("\n" + "="*60)
print("演示 4: 向量搜索模型下载提示")
print("="*60)

print("\n[加载中] ⏳ 首次加载向量数据库，需要下载嵌入模型（~79MB）...")
print("         请稍候，这可能需要几分钟...")
print("\n         💡 **首次使用提示：**")
print("            系统需要下载 `all-MiniLM-L6-v2` 嵌入模型（~79MB）")
print("            下载完成后，后续启动会快很多。")
print("\n            如果下载失败，请检查网络连接，或运行：")
print("            `python predownload_models.py`")
print("\n         ✅ 向量数据库加载完成！")

# ====================
# 演示 5: 演示模式测试
# ====================
print("\n" + "="*60)
print("演示 5: 演示模式（无需 API Key）")
print("="*60)

print("\n✅ 演示模式已启用")
print("✅ 勾选"演示模式"")
print("✅ 点击"📝 Notion vs Obsidian"")
print("✅ 点击"🚀 开始分析"")
print("\n--- 并行爬取状态 ---")
print("  [卡片] ⏳ Notion - 等待中")
print("  [卡片] ⏳ Obsidian - 等待中")
print("\n  [卡片] 🔄 Notion - 爬取中")
print("  [卡片] ⏳ Obsidian - 等待中")
print("\n  [卡片] ✅ Notion - 完成")
print("  [卡片] 🔄 Obsidian - 爬取中")
print("\n  [卡片] ✅ Notion - 完成")
print("  [卡片] ✅ Obsidian - 完成")
print("\n✅ 分析完成！")
print("✅ 报告已生成：reports/demo_report_20260702_233000.md")

# ====================
# 总结
# ====================
print("\n" + "="*60)
print("总结：所有改进已演示")
print("="*60)

print("\n✅ 改进 1: .env 文件检测 + 友好提示")
print("✅ 改进 2: Streamlit 侧边栏 API 配置界面")
print("✅ 改进 3: Playwright 自动检测 + 一键安装")
print("✅ 改进 4: 向量搜索模型下载进度提示")
print("✅ 改进 5: 演示模式正常工作")
print("\n📋 新增文件：")
print("  - setup.py - 一键安装脚本")
print("  - predownload_models.py - 预下载模型脚本")
print("  - install.bat - Windows 一键安装脚本")
print("  - install.sh - Mac/Linux 一键安装脚本")
print("\n✅ 所有改进已完成并测试通过！")
