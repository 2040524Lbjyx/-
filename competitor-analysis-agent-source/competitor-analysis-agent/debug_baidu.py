#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
调试百度搜索页面结构
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from playwright.sync_api import sync_playwright

print("调试百度搜索页面...")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    
    # 设置 User-Agent
    page.set_extra_http_headers({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    
    # 访问百度搜索
    url = "https://www.baidu.com/s?wd=夸克网盘官网"
    print(f"访问: {url}")
    page.goto(url, timeout=30000, wait_until="domcontentloaded")
    
    # 等待一下
    page.wait_for_timeout(3000)
    
    # 获取页面标题
    print(f"页面标题: {page.title()}")
    
    # 截图
    screenshot_path = "baidu_debug.png"
    page.screenshot(path=screenshot_path, full_page=True)
    print(f"截图已保存: {screenshot_path}")
    
    # 打印页面 HTML（前 2000 个字符）
    html = page.content()
    print(f"\n页面 HTML (前 2000 字符):\n{html[:2000]}\n")
    
    # 尝试查找搜索结果容器
    selectors_to_try = [
        "#content_left",
        ".result",
        ".c-container",
        "[id^='content_left']",
        "div[class*='result']"
    ]
    
    for selector in selectors_to_try:
        count = page.locator(selector).count()
        print(f"选择器 '{selector}': 找到 {count} 个元素")
    
    browser.close()

print("\n调试完成")
