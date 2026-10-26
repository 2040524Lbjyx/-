"""运行时错误分类与结果质量闸门。

这些函数不访问网络，只负责把底层错误和分析结果转换为稳定的产品状态，
方便 CLI、Streamlit 和测试复用同一套判断。
"""

from typing import Any, Dict, Optional, Tuple
from urllib.parse import urljoin

import requests


def classify_connection_error(error: Any) -> str:
    """将网络/API异常归类为可展示、可处理的错误类型。"""
    text = str(error or "").lower()
    if "10013" in text or "access permissions" in text or "套接字" in text:
        return "network_blocked"
    if "401" in text or "unauthorized" in text or "invalid api key" in text:
        return "invalid_auth"
    if "403" in text or "forbidden" in text:
        return "forbidden"
    if "429" in text or "rate limit" in text or "too many requests" in text:
        return "rate_limited"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "connection" in text or "dns" in text or "name or service not known" in text:
        return "network_unreachable"
    return "unknown"


def connection_error_message(category: str) -> str:
    """为用户提供下一步可执行的提示。"""
    messages = {
        "network_blocked": "当前运行环境禁止建立外网连接，请检查防火墙、代理或启动权限。",
        "network_unreachable": "无法连接外部服务，请检查网络、DNS或代理配置。",
        "invalid_auth": "API Key无效或未被当前服务接受，请检查Key、Base URL和模型配置。",
        "forbidden": "外部服务拒绝访问，请检查权限、地区限制或接口地址。",
        "rate_limited": "外部服务触发限流，请降低并发、等待后重试。",
        "timeout": "外部服务响应超时，请检查网络或稍后重试。",
    }
    return messages.get(category, "外部服务调用失败，请查看日志中的原始错误。")


def check_llm_endpoint(api_key: str, base_url: Optional[str] = None, timeout: float = 8.0) -> Tuple[bool, str, str]:
    """只请求兼容接口的 models 端点，启动前发现网络和鉴权问题。"""
    if not api_key or api_key.strip() in {"", "your_api_key_here", "your-key"}:
        return False, "invalid_auth", "未配置有效的 OPENAI_API_KEY。"
    root = (base_url or "https://api.openai.com/v1").rstrip("/") + "/"
    endpoint = urljoin(root, "models")
    try:
        response = requests.get(
            endpoint,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        if response.status_code == 200:
            return True, "ok", "LLM接口连接正常。"
        category = classify_connection_error(f"HTTP {response.status_code} {response.text[:200]}")
        return False, category, f"LLM接口返回 HTTP {response.status_code}。"
    except Exception as exc:
        category = classify_connection_error(exc)
        return False, category, str(exc)


def should_block_report(quality_report: Dict[str, Any], metadata: Dict[str, Any]) -> bool:
    """没有任何可验证字段时阻止生成看似完整的分析报告。"""
    competitors = quality_report.get("competitors", {}) or {}
    for item in competitors.values():
        if not isinstance(item, dict):
            continue
        if (
            int(item.get("verified_feature_count", 0) or 0) > 0
            or bool(item.get("verified_pricing"))
            or bool(item.get("verified_changelog"))
        ):
            return False

    feature_source = (metadata.get("feature_matrix", {}) or {}).get("source", "")
    pricing_source = (metadata.get("pricing", {}) or {}).get("source", "")
    return feature_source in {"llm_fallback", "rule_fallback", "unknown", ""} and pricing_source in {
        "llm_fallback", "rule_fallback", "unknown", "", "not_requested"
    }
