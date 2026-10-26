"""
修复 crawler.py 中损坏的 _get_dynamic_prompt 方法
"""
import re

with open('agents/crawler.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 找到损坏的方法并替换为正确版本
old = r'    def _get_dynamic_prompt(self, product_understanding: Dict) -> ChatPromptTemplate:'

# 找到方法结束位置（下一个 def 或类结束）
old_idx = content.find(old)
if old_idx == -1:
    print("ERROR: method signature not found")
    exit(1)

# 找到方法体结束位置
rest = content[old_idx + len(old):]
# 下一个 def 的位置
next_def = rest.find('\n    def ')
if next_def == -1:
    next_def = len(rest)
else:
    next_def += 1  # 包含换行

print(f"Found broken method at index {old_idx}, body length: {next_def}")

# 正确的方法实现
new_method = '''    def _get_dynamic_prompt(self, product_understanding: Dict) -> ChatPromptTemplate:
        """
        根据 LLM 产品理解结果，动态生成针对性 Prompt
        无需任何手动白名单，任何产品都能正确处理
        """
        category = product_understanding.get("category", "通用")
        must_check = product_understanding.get("must_check_features", [])
        typical_users = product_understanding.get("typical_users", [])

        # 构建功能检查清单
        if must_check:
            check_items = "\\n".join([f"{i+1}. {f}" for i, f in enumerate(must_check)])
            check_section = (
                "\u26a0\ufe0f \u91cd\u8981\uff1a\u8fd9\u662f\u3010" + category + "\u3011\u7c7b\u4ea7\u54c1\uff0c"
                "\u8bf7\u52a1\u5fc5\u51c6\u786e\u5217\u51fa\u4ee5\u4e0b\u6838\u5fc3\u529f\u80fd\uff08\u5982\u679c\u8be5\u4ea7\u54c1\u7684\u786e\u6709\uff09\uff1a\\n"
                + check_items + "\\n\\n"
                "\u5982\u679c\u8be5\u4ea7\u54c1\u660e\u663e\u5177\u6709\u4e0a\u8ff0\u529f\u80fd\uff0c\u4f46\u4f7f\u7528\u4e86\u4e0d\u540c\u7684\u540d\u79f0\uff0c"
                "\u4e5f\u8bf7\u5728 features.core \u4e2d\u4f7f\u7528\u6807\u51c6\u540d\u79f0\u5217\u51fa\u3002"
            )
        else:
            check_section = (
                "\u26a0\ufe0f \u91cd\u8981\uff1a\u8fd9\u662f\u3010" + category + "\u3011\u7c7b\u4ea7\u54c1\uff0c"
                "\u8bf7\u5168\u9762\u5217\u51fa\u5176\u6838\u5fc3\u529f\u80fd\uff08\u81f3\u5c11 10 \u4e2a\uff09\u3002"
            )

        user_hint = ""
        if typical_users:
            user_hint = "\\n\u76ee\u6807\u7528\u6237\u901a\u5e38\u5305\u542b\uff1a" + "\u3001".join(typical_users)

        system_text = (
            "\u4f60\u662f\u4e00\u4f4d\u6df1\u5ea6\u7684\u4ea7\u54c1\u6570\u636e\u5206\u6790\u4e13\u5bb6\uff0c\u7279\u522b\u64c5\u957f\u5206\u6790\u5404\u7c7b\u4e92\u8054\u7f51\u4ea7\u54c1\u3002\\n\\n"
            "\u8bf7\u57fa\u4e8e\u4f60\u7684\u77e5\u8bc6\uff0c\u5bf9\u4ee5\u4e0b\u4ea7\u54c1\u8fdb\u884c\u5168\u9762\u7684\u7ed3\u6784\u5316\u5206\u6790\uff0c"
            "\u8f93\u51fa\u4e25\u683c\u7684 JSON \u683c\u5f0f\uff08\u4e0d\u8981\u6709 markdown \u4ee3\u7801\u5757\uff09\u3002\\n\\n"
            + check_section
            + user_hint
            + "\\n\\n\u8f93\u51fa\u683c\u5f0f\uff08\u4e25\u683c JSON\uff0c\u4e0d\u8981\u6709\u5176\u4ed6\u5185\u5bb9\uff09\uff1a\\n"
            "{{\\n"
            '    "name": "\u4ea7\u54c1\u540d\u79f0",\n'
            '    "features": {{\n'
            '        "core": ["\u6838\u5fc3\u529f\u80fd1", ...],\n'
            '        "advanced": ["\u9ad8\u7ea7\u529f\u80fd1", ...]\n'
            "    }},\n"
            '    "pricing": {{\n'
            '        "model": "\u5b9a\u4ef7\u6a21\u5f0f",\n'
            '        "plans": []\n'
            "    }},\n"
            '    "changelog": {{\n'
            '        "latest_version": "\u6700\u65b0\u7248\u672c\u53f7",\n'
            '        "recent_updates": ["\u66f4\u65b01"]\n'
            "    }},\n"
            '    "target_users": ["\u7528\u62371", "\u7528\u62372"]\n'
            "}}"
        )

        return ChatPromptTemplate.from_messages([
            ("system", system_text),
            ("user",
                "\u4ea7\u54c1\u540d\u79f0\uff1a{competitor_name}\n"
                "\u5b98\u7f51\uff1a{website}\n"
                "\u4ea7\u54c1\u7c7b\u522b\uff1a{category}\n\\n"
                "\u8bf7\u5206\u6790\u8fd9\u4e2a\u4ea7\u54c1\uff0c\u8f93\u51fa\u7ed3\u6784\u5316 JSON\u3002"
                "\u786e\u4fdd features.core \u5305\u542b\u6240\u6709\u6838\u5fc3\u529f\u80fd\uff0c\u4e0d\u8981\u9057\u6f0f\u3002"
            )
        ])
'''

# 替换
new_content = content[:old_idx] + new_method + content[old_idx + len(old) + next_def:]

with open('agents/crawler.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Successfully replaced _get_dynamic_prompt() method")
print("Verifying syntax...")
