#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试百度搜索服务
"""

import sys
import io

# 设置标准输出编码为 UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 测试搜索服务
from services.search_service import SearchService

print("=" * 60)
print("测试百度搜索服务")
print("=" * 60)

search = SearchService()

# 测试 1: 发现竞品官网
print("\n测试 1: 发现竞品官网")
test_products = ["夸克网盘", "百度网盘", "Notion"]

for product in test_products:
    print(f"\n搜索 '{product}' 的官网...")
    website = search.discover_competitor_website(product)
    if website:
        print(f"  ✅ 找到官网: {website}")
    else:
        print(f"  ❌ 未找到官网")

# 测试 2: 验证功能是否存在
print("\n\n测试 2: 验证功能是否存在")
test_cases = [
    ("夸克网盘", "回收站"),
    ("夸克网盘", "4K画质"),
    ("百度网盘", "回收站"),
]

for product, feature in test_cases:
    print(f"\n验证 '{product}' 是否有 '{feature}' 功能...")
    result = search.verify_feature_exists(product, feature)
    print(f"  结果: exists={result['exists']}, confidence={result['confidence']}, source={result['source']}")

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)
