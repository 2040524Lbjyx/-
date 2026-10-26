"""
apply_fix.py - 用 correct_llm_fallback.py 中的正确方法替换 crawler.py 中的损坏方法
"""
with open('correct_llm_fallback.py', 'r', encoding='utf-8') as f:
    correct_method = f.read()

with open('agents/crawler.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 找到损坏方法的起始位置
old_start = '    def _llm_fallback_collect(self, competitor_name: str, website: str = None) -> Dict[str, Any]:'
idx = content.find(old_start)
if idx == -1:
    print('ERROR: old method not found')
    exit(1)

# 找到方法结束位置（下一个 def）
rest = content[idx + len(old_start):]
next_def = rest.find('\n    def ')
if next_def == -1:
    next_def = len(rest)
else:
    # 回退到换行符
    next_def += 1  # 包含换行

old_full = content[idx:idx + len(old_start) + next_def]
print(f'Found old method: {len(old_full)} chars')

# 替换
new_content = content[:idx] + correct_method + content[idx + len(old_start) + next_def:]

with open('agents/crawler.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print(f'Successfully replaced with correct method ({len(correct_method)} chars)')

# 验证语法
import py_compile
try:
    py_compile.compile(new_content, 'agents/crawler.py')
    print('OK: syntax check passed')
except py_compile.PyCompileError as e:
    print(f'SYNTAX ERROR: {e}')
