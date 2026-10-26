"""演示模式与 Coordinator 共用的本地竞品名称解析。"""
import re


def extract_competitors(query: str) -> list[str]:
    # 页面附加的决策上下文不是竞品名称。
    text = re.split(r"[。；;\n]|(?:分析目的|分析维度|市场范围|数据时效|自身产品|目标用户)\s*[:：]", query, maxsplit=1)[0]
    text = re.sub(r"^(?:请|帮我|帮忙|一下|竞品分析|分析|对比|比较|竞品|产品|\s)+", "", text)
    # “A 和 B 的功能和定价”中，所属短语及之后的内容属于分析要求。
    text = re.split(r"的\s*(?:核心功能|功能|定价|价格|版本|更新|优缺点|差异|用户反馈)", text, maxsplit=1)[0]
    text = re.sub(r"\b(?:vs|versus|and)\b\.?", "、", text, flags=re.IGNORECASE)
    parts = re.split(r"[\s、，,/|与和及&]+", text)
    stop = {"功能", "核心功能", "定价", "价格", "功能对比", "定价策略", "版本更新"}
    result, seen = [], set()
    for part in parts:
        name = part.strip(" ：:。；;！!？?\"'“”")
        if len(name) > 1 and name not in stop and name.casefold() not in seen:
            seen.add(name.casefold())
            result.append(name)
    return result[:5]
