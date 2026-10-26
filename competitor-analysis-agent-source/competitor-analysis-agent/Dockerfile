# 竞品分析多Agent系统 - Docker镜像

FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装Python依赖
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 安装Playwright浏览器
RUN playwright install --with-deps

# 复制项目文件
COPY . .

# 创建必要的目录
RUN mkdir -p /app/data/chromadb \
    /app/reports \
    /app/logs \
    /app/templates

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    OPENAI_API_KEY="" \
    CHROMA_PERSIST_DIRECTORY=/app/data/chromadb \
    LOG_LEVEL=INFO

# 暴露端口
EXPOSE 8000 8501

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import sys; sys.exit(0)" || exit 1

# 默认命令：启动Streamlit界面
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
