"""
移除 main.py 中的所有 emoji 字符
"""

import re

# 读取文件
with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

# 移除 emoji 字符（Unicode 范围）
# 常见 emoji 范围：U+1F300-U+1F9FF, U+2600-U+26FF, U+2700-U+27BF, U+FE00-U+FE0F
emoji_pattern = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F900-\U0001F9FF"  # supp symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map
    "\U0001F1E0-\U0001F1FF"  # flags (iOS)
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "]+",
    flags=re.UNICODE
)

# 替换 emoji 为对应的文本标记
replacements = {
    "🎭": "[演示]",
    "✅": "[完成]",
    "📄": "[报告]",
    "🏢": "[竞品]",
    "💡": "[提示]",
    "❌": "[错误]",
    "⚠️": "[警告]",
}

# 先替换已知的 emoji
for emoji, replacement in replacements.items():
    content = content.replace(emoji, replacement)

# 然后移除剩余的 emoji
content = emoji_pattern.sub("", content)

# 写回文件
with open("main.py", "w", encoding="utf-8") as f:
    f.write(content)

print("✅ 已移除所有 emoji 字符")
