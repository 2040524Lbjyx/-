"""
统一的环境变量加载工具

解决所有 Agent 文件中重复的环境变量加载逻辑。
使用 python-dotenv 安全加载 .env 文件，并提供统一的访问接口。
"""

import os
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 查找 .env 文件（按优先级：项目根目录 > 当前工作目录）
def find_env_file() -> Optional[Path]:
    """
    查找 .env 文件
    
    Returns:
        .env 文件路径，如果找不到返回 None
    """
    # 1. 项目根目录
    env_in_project = PROJECT_ROOT / ".env"
    if env_in_project.exists():
        return env_in_project
    
    # 2. 当前工作目录
    cwd = Path.cwd()
    env_in_cwd = cwd / ".env"
    if env_in_cwd.exists():
        return env_in_cwd
    
    return None


def load_env(override: bool = False) -> dict:
    """
    加载环境变量 from .env 文件
    
    Args:
        override: 是否覆盖已存在的环境变量（默认 False）
    
    Returns:
        加载的环境变量字典
    """
    try:
        from dotenv import load_dotenv, find_dotenv
    except ImportError:
        logger.warning("python-dotenv 未安装，无法加载 .env 文件")
        return dict(os.environ)
    
    env_file = find_env_file()
    
    if env_file:
        logger.info(f"加载环境变量文件: {env_file}")
        load_dotenv(dotenv_path=env_file, override=override)
    else:
        # 使用 dotenv 的自动查找
        logger.info("未找到 .env 文件，尝试自动查找")
        load_dotenv(override=override)
    
    return dict(os.environ)


def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """
    获取环境变量值
    
    Args:
        key: 环境变量名
        default: 默认值（如果环境变量不存在）
    
    Returns:
        环境变量值或默认值
    """
    return os.getenv(key, default)


def get_env_required(key: str) -> str:
    """
    获取必需的环境变量值
    
    Args:
        key: 环境变量名
    
    Returns:
        环境变量值
    
    Raises:
        ValueError: 如果环境变量不存在
    """
    value = os.getenv(key)
    if value is None:
        raise ValueError(f"必需的环境变量 {key} 未设置，请在 .env 文件中配置")
    return value


def check_required_env_vars(required_vars: list) -> tuple:
    """
    检查必需的环境变量是否都已设置
    
    Args:
        required_vars: 必需的环境变量列表
    
    Returns:
        (是否全部设置, 缺失的变量列表)
    """
    missing = []
    for var in required_vars:
        if not os.getenv(var):
            missing.append(var)
    
    return len(missing) == 0, missing


# 初始化时自动加载（可以被多次调用，dotenv 会处理）
load_env()
