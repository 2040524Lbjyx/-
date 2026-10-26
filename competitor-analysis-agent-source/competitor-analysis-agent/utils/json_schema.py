"""
输出层 JSON Schema 校验与自动修复工具

为各分析模块（定价 / 功能对比 / 洞察 / 功能对齐）的 LLM 输出施加结构约束，
并在结构基本正确时自动修复（补全缺失必填字段、强制类型），
避免单次 schema 校验失败就导致整段分析被静默丢弃（这正是此前
analyze_pricing 等路径的隐患）。

设计原则：
- jsonschema 为可选依赖：安装则做严格校验并报告问题；未安装则退化为
  "按 schema 补默认 + 类型强制"，仍保证下游不 KeyError。
- 校验失败不抛异常、不中断流程（配合既有 except→LLM 兜底），只记录告警，
  便于后续基于日志反向迭代 Prompt（Bad Case 调优）。
"""

import logging
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

try:
    from jsonschema import Draft7Validator  # type: ignore
    _HAS_JSONSCHEMA = True
except Exception:  # pragma: no cover - 依赖可选
    Draft7Validator = None  # type: ignore
    _HAS_JSONSCHEMA = False


# ---------------------------------------------------------------------------
# 各分析模块的输出 Schema
# ---------------------------------------------------------------------------

PRICING_SCHEMA = {
    "type": "object",
    "properties": {
        "pricing_models": {"type": "object"},
        "price_range": {"type": "object"},
        "analysis": {"type": "string"},
        "recommendations": {"type": "array"},
    },
    "required": ["pricing_models", "analysis"],
}

COMPARE_SCHEMA = {
    "type": "object",
    "properties": {
        "matrix": {"type": "array", "items": {"type": "object"}},
    },
    "required": ["matrix"],
}

INSIGHTS_SCHEMA = {
    "type": "object",
    "properties": {
        "insights": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["insights"],
}


# 各类型的兜底默认值
_TYPE_DEFAULTS = {
    "object": {},
    "array": [],
    "string": "",
    "number": 0,
    "integer": 0,
    "boolean": False,
}


def _coerce_value(value: Any, expected_type: str) -> Any:
    """把 value 尽量强制成 expected_type；无法转换则返回该类型默认值。"""
    if expected_type == "array" and not isinstance(value, list):
        # 标量被 LLM 写成单值 -> 包成数组
        return [value] if value not in (None, "") else []
    if expected_type == "string" and not isinstance(value, str):
        return str(value)
    if expected_type in ("number", "integer") and not isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0
    if expected_type == "object" and not isinstance(value, dict):
        return {}
    if expected_type == "boolean" and not isinstance(value, bool):
        return bool(value)
    return value


def validate_and_repair(
    data: Any,
    schema: Dict[str, Any],
    context: str = "",
    auto_repair: bool = True,
) -> Tuple[Any, List[str]]:
    """
    校验并（在可能时）自动修复 LLM 输出的 JSON。

    Args:
        data: safe_extract_json 解析出的对象
        schema: JSON Schema 定义（只需 properties / required）
        context: 调用方标识，用于日志定位（如 "analyze_pricing"）
        auto_repair: 是否执行自动修复

    Returns:
        (修复后的 data, 问题列表) —— 问题列表为空表示一次通过
    """
    tag = f"[{context}]" if context else ""

    if not isinstance(data, dict):
        msg = f"{tag} 期望 object，实际为 {type(data).__name__}，无法应用 Schema"
        logger.warning(f"[JSONSchema] {msg}")
        return data, [msg]

    props = schema.get("properties", {})

    # ---- 1) 补全缺失的必填字段（不依赖 jsonschema） ----
    if auto_repair:
        for req in schema.get("required", []):
            if req not in data or data.get(req) is None:
                ptype = props.get(req, {}).get("type", "object")
                data[req] = _TYPE_DEFAULTS.get(ptype, {})
                logger.info(f"[JSONSchema] {tag} 补全缺失必填字段 '{req}' -> {ptype} 默认值")

    # ---- 2) 已知字段的类型强制（提升下游健壮性） ----
    if auto_repair:
        for name, pdef in props.items():
            if name in data and data.get(name) is not None:
                ptype = pdef.get("type")
                if ptype and isinstance(ptype, str):
                    repaired = _coerce_value(data[name], ptype)
                    if repaired != data[name]:
                        data[name] = repaired
                        logger.info(f"[JSONSchema] {tag} 字段 '{name}' 类型强制为 {ptype}")

    # ---- 3) 严格校验（可选依赖） ----
    issues: List[str] = []
    if _HAS_JSONSCHEMA and Draft7Validator is not None:
        validator = Draft7Validator(schema)
        for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
            loc = "/".join(str(p) for p in err.path) or "<root>"
            issues.append(f"{loc}: {err.message}")
        if issues:
            logger.warning(f"[JSONSchema] {tag} Schema 校验未通过（已尝试修复）: {issues}")
    else:
        if not _HAS_JSONSCHEMA:
            logger.debug("[JSONSchema] jsonschema 未安装，跳过严格校验（仅做结构兜底）")

    return data, issues


def validate_string_list(data: Any, context: str = "") -> List[str]:
    """
    校验功能对齐等返回的字符串数组：确保是 list[str]，长度与输入一致时原样返回，
    否则做尽力修复（非列表包成单元素、元素强制转字符串、缺失补空串）。

    Args:
        data: _llm_align_features 解析出的对象（预期为 list）
        context: 调用方标识

    Returns:
        修复后的字符串列表
    """
    tag = f"[{context}]" if context else ""
    if data is None:
        logger.warning(f"[JSONSchema] {tag} 功能对齐返回为空，退回原功能名")
        return []
    if not isinstance(data, list):
        logger.warning(f"[JSONSchema] {tag} 功能对齐期望数组，实际 {type(data).__name__}，包成单元素")
        return [str(data)]
    cleaned = [str(x) if x is not None else "" for x in data]
    if any(not isinstance(x, str) for x in data):
        logger.info(f"[JSONSchema] {tag} 功能对齐数组内存在非字符串元素，已强制转字符串")
    return cleaned
