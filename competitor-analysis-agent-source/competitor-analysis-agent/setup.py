"""
竞品分析系统 - 一键环境配置脚本

此脚本会自动：
1. 检查 Python 版本
2. 安装 Python 依赖
3. 安装 Playwright 浏览器
4. 检查 .env 文件
5. 预下载 ChromaDB 嵌入模型

使用方法：
    python setup.py
"""

import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime

# 颜色代码（Windows 需要 colorama，这里用简单的文本）
GREEN = "✅"
RED = "❌"
YELLOW = "⚠️"
BLUE = "ℹ️"

def print_header(text):
    """打印标题"""
    print("\n" + "="*70)
    print(f"  {text}")
    print("="*70 + "\n")

def print_step(step, text):
    """打印步骤"""
    print(f"  [{step}] {text}")

def run_command(cmd, desc, timeout=None):
    """运行命令并返回成功/失败"""
    print_step("RUN", f"{desc}...")
    print(f"       命令: {cmd}")
    
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        
        if result.returncode == 0:
            print(f"  {GREEN} {desc} - 成功")
            if result.stdout.strip():
                print(f"       输出: {result.stdout.strip()[:200]}...")
            return True, result.stdout
        else:
            print(f"  {RED} {desc} - 失败")
            print(f"       错误: {result.stderr.strip()[:200]}...")
            return False, result.stderr
    except subprocess.TimeoutExpired:
        print(f"  {RED} {desc} - 超时（{timeout}秒）")
        return False, "Timeout"
    except Exception as e:
        print(f"  {RED} {desc} - 异常: {e}")
        return False, str(e)

def check_python_version():
    """检查 Python 版本"""
    print_step("CHECK", "检查 Python 版本...")
    
    version = sys.version_info
    if version < (3, 9):
        print(f"  {RED} Python 版本过低：{version.major}.{version.minor}.{version.micro}")
        print(f"  {YELLOW} 需要 Python 3.9+，请升级 Python")
        return False
    
    print(f"  {GREEN} Python 版本：{version.major}.{version.minor}.{version.micro}")
    return True

def check_pip():
    """检查 pip 是否可用"""
    print_step("CHECK", "检查 pip...")
    
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print(f"  {GREEN} pip 可用：{result.stdout.strip()}")
            return True
    except Exception:
        pass
    
    print(f"  {RED} pip 不可用")
    return False

def install_dependencies():
    """安装 Python 依赖"""
    print_step("INSTALL", "安装 Python 依赖（requirements.txt）...")
    
    req_file = Path(__file__).parent / "requirements.txt"
    if not req_file.exists():
        print(f"  {RED} 未找到 requirements.txt")
        return False
    
    success, output = run_command(
        f'"{sys.executable}" -m pip install -r "{req_file}"',
        "安装依赖",
        timeout=300
    )
    
    return success

def install_playwright():
    """安装 Playwright 浏览器"""
    print_step("INSTALL", "安装 Playwright 浏览器...")
    
    # 先检查 playwright 是否已安装
    success, _ = run_command(
        f'"{sys.executable}" -m playwright --version',
        "检查 Playwright",
        timeout=10
    )
    
    if not success:
        print(f"  {YELLOW} Playwright 未安装，正在安装...")
        success, _ = run_command(
            f'"{sys.executable}" -m pip install playwright',
            "安装 Playwright",
            timeout=120
        )
        if not success:
            return False
    
    # 安装浏览器
    success, output = run_command(
        f'"{sys.executable}" -m playwright install',
        "安装 Playwright 浏览器（~200MB）",
        timeout=300
    )
    
    return success

def check_env_file():
    """检查 .env 文件"""
    print_step("CHECK", "检查 .env 文件...")
    
    env_file = Path(__file__).parent / ".env"
    env_example = Path(__file__).parent / ".env.example"
    
    if env_file.exists():
        print(f"  {GREEN} .env 文件已存在")
        return True
    
    if env_example.exists():
        print(f"  {YELLOW} 未找到 .env 文件，正在从 .env.example 创建...")
        try:
            import shutil
            shutil.copy(env_example, env_file)
            print(f"  {GREEN} 已创建 .env 文件，请编辑它并填入你的 API Key")
            return True
        except Exception as e:
            print(f"  {RED} 创建 .env 文件失败：{e}")
            return False
    
    print(f"  {YELLOW} 未找到 .env 和 .env.example 文件")
    print(f"  {BLUE} 请手动创建 .env 文件并填入 API Key")
    return False

def predownload_models():
    """预下载 ChromaDB 嵌入模型"""
    print_step("DOWNLOAD", "预下载 ChromaDB 嵌入模型（~79MB）...")
    
    predownload_script = Path(__file__).parent / "predownload_models.py"
    
    if predownload_script.exists():
        success, output = run_command(
            f'"{sys.executable}" "{predownload_script}"',
            "预下载模型",
            timeout=300
        )
        return success
    else:
        print(f"  {YELLOW} 未找到 predownload_models.py，跳过预下载")
        print(f"  {BLUE} 模型将在首次使用时自动下载")
        return True

def main():
    """主函数"""
    print_header("竞品分析系统 - 环境配置向导")
    
    start_time = datetime.now()
    
    # 步骤 1: 检查 Python 版本
    if not check_python_version():
        sys.exit(1)
    
    # 步骤 2: 检查 pip
    if not check_pip():
        sys.exit(1)
    
    # 步骤 3: 安装依赖
    print_header("步骤 1/5: 安装 Python 依赖")
    if not install_dependencies():
        print(f"\n{RED} 依赖安装失败，请检查错误信息")
        sys.exit(1)
    
    # 步骤 4: 安装 Playwright
    print_header("步骤 2/5: 安装 Playwright 浏览器")
    if not install_playwright():
        print(f"\n{YELLOW} Playwright 安装失败，你可以稍后手动运行：")
        print(f"  python -m playwright install")
    
    # 步骤 5: 检查 .env 文件
    print_header("步骤 3/5: 检查配置文件")
    check_env_file()
    
    # 步骤 6: 预下载模型（可选）
    print_header("步骤 4/5: 预下载嵌入模型（可选）")
    print(f"{BLUE} 此步骤是可选的，模型将在首次使用时自动下载")
    response = input("是否现在预下载模型？(y/n) [推荐 y]: ").strip().lower()
    
    if response in ['y', 'yes', '']:
        predownload_models()
    else:
        print(f"{BLUE} 跳过预下载，模型将在首次使用时自动下载")
    
    # 完成
    elapsed = (datetime.now() - start_time).total_seconds()
    
    print_header("配置完成！")
    print(f"\n  {GREEN} 环境配置完成！耗时：{elapsed:.1f} 秒\n")
    print("  下一步：")
    print("  1. 编辑 .env 文件，填入你的 API Key")
    print("  2. 运行：streamlit run app.py")
    print("  3. 或者运行：python main.py '分析Notion和Obsidian' --demo")
    print("\n  演示模式无需 API Key，可直接使用！\n")
    
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW} 配置被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n{RED} 配置失败：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
