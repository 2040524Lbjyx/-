@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ==========================================
echo 竞品分析系统 - Windows 一键安装向导
echo ==========================================
echo.

:: 检查 Python
echo [1/6] 检查 Python 版本...
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ 未找到 Python，请先安装 Python 3.9+
    echo.
    echo 下载地址：https://www.python.org/downloads/
    pause
    exit /b 1
)
python --version

echo.
echo [2/6] 创建虚拟环境...
if not exist "venv" (
    python -m venv venv
    if errorlevel 1 (
        echo ❌ 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo ✅ 虚拟环境创建成功
) else (
    echo ⚠️ 虚拟环境已存在，跳过创建
)

echo.
echo [3/6] 激活虚拟环境...
call venv\Scripts\activate
if errorlevel 1 (
    echo ❌ 激活虚拟环境失败
    pause
    exit /b 1
)
echo ✅ 虚拟环境已激活

echo.
echo [4/6] 安装 Python 依赖...
pip install -r requirements.txt
if errorlevel 1 (
    echo ❌ 依赖安装失败
    pause
    exit /b 1
)
echo ✅ 依赖安装完成

echo.
echo [5/6] 安装 Playwright 浏览器...
python -m playwright install
if errorlevel 1 (
    echo ⚠️ Playwright 浏览器安装失败，你可以稍后手动运行：
    echo    python -m playwright install
) else (
    echo ✅ Playwright 浏览器安装完成
)

echo.
echo [6/6] 检查配置文件...
if not exist ".env" (
    if exist ".env.example" (
        echo ⚠️ 未找到 .env 文件，正在从 .env.example 创建...
        copy ".env.example" ".env" >nul
        echo ✅ 已创建 .env 文件，请编辑它并填入你的 API Key
    ) else (
        echo ⚠️ 未找到 .env 和 .env.example 文件
        echo    请手动创建 .env 文件并填入 API Key
    )
) else (
    echo ✅ .env 文件已存在
)

echo.
echo ==========================================
echo 🎉 安装完成！
echo ==========================================
echo.
echo 下一步：
echo 1. 编辑 .env 文件，填入你的 API Key
echo 2. 运行：streamlit run app.py
echo 3. 或使用演示模式（无需 API Key）：python main.py "分析Notion和Obsidian" --demo
echo.
echo 提示：
echo - 演示模式无需 API Key，可直接使用
echo - 首次使用向量搜索需要下载 ~79MB 模型
echo - 运行 python predownload_models.py 可预下载模型
echo.
pause
