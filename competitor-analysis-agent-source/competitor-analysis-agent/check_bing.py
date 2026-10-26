#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查 Bing 搜索返回的内容
"""

import requests
from bs4 import BeautifulSoup

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}

url = "https://www.bing.com/search?q=夸克网盘官网"
print(f"访问: {url}")

response = requests.get(url, headers=headers, timeout=30)
print(f"状态码: {response.status_code}")
print(f"内容类型: {response.headers.get('Content-Type', 'unknown')}")
print(f"内容长度: {len(response.text)}")

# 检查是否是 gzip 压缩
if response.headers.get('Content-Encoding') == 'gzip':
    print("响应是 gzip 压缩的")
    import gzip
    content = gzip.decompress(response.content)
    html = content.decode('utf-8')
else:
    html = response.text

# 保存到文件
with open("bing_check.html", "w", encoding="utf-8") as f:
    f.write(html)
print("HTML 已保存到 bing_check.html")

# 解析
soup = BeautifulSoup(html, 'html.parser')
title = soup.find("title")
print(f"页面标题: {title.get_text() if title else 'No title'}")

# 查找搜索结果
results = soup.find_all(class_="b_algo")
print(f"找到 {len(results)} 个搜索结果 (.b_algo)")

# 如果没有找到，尝试其他选择器
if len(results) == 0:
    print("\n尝试其他选择器...")
    for selector in ["#b_results", ".b_title", "li.b_algo", "h2 a"]:
        count = len(soup.select(selector))
        print(f"  {selector}: {count} 个元素")
