"""
安全的 LLM 响应解析工具

提供健壮的方法来解析 LLM 返回的 JSON 数据，处理各种格式问题。
"""

import json
import re
import logging

logger = logging.getLogger(__name__)


def safe_extract_json(response_text: str, verbose: bool = False) -> dict:
    """
    安全提取 LLM 返回的 JSON
    
    处理以下情况：
    1. 直接返回 JSON
    2. 返回 ```json ... ``` 代码块
    3. 返回 ``` ... ``` 代码块（无语言标识）
    4. 包含额外文本的 JSON
    5. JSON 中有注释
    
    Args:
        response_text: LLM 的原始响应文本
        verbose: 是否输出详细日志
    
    Returns:
        解析后的 JSON 字典
    
    Raises:
        ValueError: 如果无法解析 JSON
    """
    if not response_text or not response_text.strip():
        raise ValueError("LLM 响应为空")
    
    text = response_text.strip()
    
    # 方法1: 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # 方法2: 提取 ```json ... ``` 代码块
    pattern_json = r'```json\s*([\s\S]*?)\s*```'
    match = re.search(pattern_json, text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError as e:
            logger.debug(f"方法2解析失败: {e}")
    
    # 方法3: 提取 ``` ... ``` 代码块（无语言标识）
    pattern_generic = r'```\s*([\s\S]*?)\s*```'
    match = re.search(pattern_generic, text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError as e:
            logger.debug(f"方法3解析失败: {e}")
    
    # 方法4: 尝试提取 JSON 对象（从第一个 { 到最后一个 }）
    try:
        start = text.index('{')
        end = text.rindex('}') + 1
        json_str = text[start:end]
        return json.loads(json_str)
    except (ValueError, json.JSONDecodeError):
        pass
    
    # 方法5: 尝试提取 JSON 数组（从第一个 [ 到最后一个 ]）
    try:
        start = text.index('[')
        end = text.rindex(']') + 1
        json_str = text[start:end]
        return json.loads(json_str)
    except (ValueError, json.JSONDecodeError):
        pass
    
    # 所有方法都失败，记录详细错误
    error_msg = f"无法解析 LLM 响应为 JSON"
    logger.error(error_msg)
    if verbose:
        logger.error(f"原始响应（前 500 字符）: {text[:500]}")
        logger.error(f"原始响应（后 500 字符）: {text[-500:]}")
    
    raise ValueError(f"{error_msg}\n响应内容: {text[:200]}...")


def safe_extract_json_list(response_text: str, verbose: bool = False) -> list:
    """
    安全提取 LLM 返回的 JSON 数组
    
    Args:
        response_text: LLM 的原始响应文本
        verbose: 是否输出详细日志
    
    Returns:
        解析后的 JSON 数组
    
    Raises:
        ValueError: 如果无法解析为 JSON 数组
    """
    result = safe_extract_json(response_text, verbose)
    
    if isinstance(result, list):
        return result
    elif isinstance(result, dict):
        # 有些 LLM 会返回 {"data": [...]} 格式
        for key, value in result.items():
            if isinstance(value, list):
                return value
        # 如果不是列表，包装成列表
        return [result]
    else:
        raise ValueError(f"期望 JSON 数组，但得到 {type(result)}")


def safe_extract_text_between(response_text: str, start_marker: str, end_marker: str) -> str:
    """
    提取两个标记之间的文本
    
    Args:
        response_text: 响应文本
        start_marker: 开始标记
        end_marker: 结束标记
    
    Returns:
        标记之间的文本
    """
    try:
        start_idx = response_text.index(start_marker) + len(start_marker)
        end_idx = response_text.index(end_marker, start_idx)
        return response_text[start_idx:end_idx].strip()
    except ValueError:
        return ""


def clean_llm_response(text: str) -> str:
    """
    清理 LLM 响应文本
    
    移除常见的问题：
    1. 开头的 "Here is..." 等废话
    2. 结尾的 "I hope..." 等废话
    3. 解释性文本
    
    Args:
        text: 原始响应文本
    
    Returns:
        清理后的文本
    """
    # 移除常见的开头废话
    prefixes_to_remove = [
        "Here is",
        "Here's",
        "Sure, here is",
        "Certainly, here is",
        "Of course, here is",
    ]
    
    cleaned = text.strip()
    
    # 如果响应包含 JSON 代码块，只保留代码块
    if "```json" in cleaned or "```" in cleaned:
        pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
        match = re.search(pattern, cleaned)
        if match:
            return match.group(1).strip()
    
    return cleaned
