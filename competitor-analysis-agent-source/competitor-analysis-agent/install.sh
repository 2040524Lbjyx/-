#!/bin/bash

# 竞品分析系统 - Mac/Linux 一键安装向导

echo "=========================================="
echo "  竞品分析系统 - 一键安装向导"
echo "=========================================="
echo ""

# 检测 Python 命令
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
else
    echo "❌ 未找到 Python，请先安装 Python 3.9+"
    echo ""
    echo "  下载地址：https://www.python.org/downloads/"
    echo "  Mac 用户：brew install python"
    echo "  Linux 用户：sudo apt install python3"
    exit 1
fi

# 检查 Python 版本
echo "[1/6] 检查 Python 版本..."
$PYTHON_CMD --version
PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | cut -d' ' -f2)
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d'.' -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d'.' -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 9 ]); then
    echo "❌ Python 版本过低：v$PYTHON_VERSION"
    echo "  需要 Python 3.9+，请升级 Python"
    exit 1
fi
echo "✅ Python 版本：v$PYTHON_VERSION"
echo ""

# 创建虚拟环境
echo "[2/6] 创建虚拟环境..."
if [ ! -d "venv" ]; then
    $PYTHON_CMD -m venv venv
    if [ $? -ne 0 ]; then
        echo "❌ 创建虚拟环境失败"
        exit 1
    fi
    echo "✅ 虚拟环境创建成功"
else
    echo "⚠️ 虚拟环境已存在，跳过创建"
fi
echo ""

# 激活虚拟环境
echo "[3/6] 激活虚拟环境..."
source venv/bin/activate
if [ $? -ne 0 ]; then
    echo "❌ 激活虚拟环境失败"
    exit 1
fi
echo "✅ 虚拟环境已激活"
echo ""

# 安装依赖
echo "[4/6] 安装 Python 依赖..."
pip install -r requirements.txt
if [ $? -ne 0 ]; then
    echo "❌ 依赖安装失败"
    exit 1
fi
echo "✅ 依赖安装完成"
echo ""

# 安装 Playwright 浏览器
echo "[5/6] 安装 Playwright 浏览器..."
python -m playwright install
if [ $? -ne 0 ]; then
    echo "⚠️ Playwright 浏览器安装失败，你可以稍后手动运行："
    echo "  python -m playwright install"
else
    echo "✅ Playwright 浏览器安装完成"
fi
echo ""

# 检查配置文件
echo "[6/6] 检查配置文件..."
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        echo "⚠️ 未找到 .env 文件，正在从 .env.example 创建..."
        cp ".env.example" ".env"
        echo "✅ 已创建 .env 文件，请编辑它并填入你的 API Key"
    else
        echo "⚠️ 未找到 .env 和 .env.example 文件"
        echo "  请手动创建 .env 文件并填入 API Key"
    fi
else
    echo "✅ .env 文件已存在"
fi
echo ""

# 完成
echo "=========================================="
echo "🎉 安装完成！"
echo "=========================================="
echo ""
echo "下一步："
echo "1. 编辑 .env 文件，填入你的 API Key"
echo "2. 运行：streamlit run app.py"
echo "3. 或使用演示模式（无需 API Key）："
echo "   python main.py '分析Notion和Obsidian' --demo"
echo ""
echo "提示："
echo "- 演示模式无需 API Key，可直接使用"
echo "- 首次使用向量搜索需要下载 ~79MB 模型"
echo "- 运行 python predownload_models.py 可预下载模型"
echo ""

exit 0
