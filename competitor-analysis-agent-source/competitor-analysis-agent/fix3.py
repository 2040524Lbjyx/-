"""
fix3.py - 用极简正确版本替换 _llm_fallback_collect 方法
"""
import re

with open('agents/crawler.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 找到 _llm_fallback_collect 方法的完整文本并替换
old_method_start = '    def _llm_fallback_collect(self, competitor_name: str, website: str = None) -> Dict[str, Any]:'

idx = content.find(old_method_start)
if idx == -1:
    print("ERROR: method not found")
    exit(1)

# 找到方法结束位置（下一个 def 或文件结尾）
rest = content[idx + len(old_method_start):]
next_def = rest.find('\n    def ')
if next_def == -1:
    next_def = len(rest)
else:
    next_def += 1  # 包含换行

old_full = content[idx:idx + len(old_method_start) + next_def]
print(f"Found old method: {len(old_full)} chars")

# 极简正确版本
new_method = '''    def _llm_fallback_collect(self, competitor_name: str, website: str = None) -> Dict[str, Any]:
        """
        当爬虫失败或返回空数据时，使用 LLM 知识库生成结构化数据
        
        这是兜底方案：即使完全无法访问网站，用户仍能得到有价值的报告
        
        🆕 改进：使用 LLM 动态理解产品，无需任何手动白名单
        """
        
        # 🆕 第一步：用 LLM 动态理解产品（替代原来的 _detect_product_type）
        product_understanding = self._understand_product_with_llm(competitor_name, website)
        category = product_understanding.get("category", "通用")
        
        # 🆕 第二步：极简 f-string Prompt（无复杂字符串拼接）
        # system prompt 用 f-string：Python 先填入 category 和 competitor_name
        # user prompt 用普通字符串：LangChain 在 invoke 时填入变量
        prompt = ChatPromptTemplate.from_messages([
            ("system", f"""你是一位资深的产品数据分析专家，特别擅长分析各类互联网产品。

请基于你的知识，对 {competitor_name}（类别：{category}）进行全面的结构化分析，输出严格的 JSON 格式（不要有 markdown 代码块）。

要求：
1. features.core 至少列出 10 个核心功能（具体、可验证的功能名）
2. features.advanced 列出高级功能
3. pricing 分析定价策略
4. changelog 分析版本更新
5. target_users 和 platforms 要具体
6. 如果是知名产品，务必列出其标志性功能，不要遗漏

输出格式（严格 JSON，不要有其他内容）：
{{
    "name": "产品名称",
    "features": {{
        "core": ["核心功能1", "核心功能2", ...],
        "advanced": ["高级功能1", "高级功能2", ...]
    }},
    "pricing": {{ ... }},
    "changelog": {{ ... }},
    "target_users": ["用户1", "用户2"],
    "platforms": ["平台1", "平台2"]
}}"""),
            ("user", "产品名称：{competitor_name}\n官网：{website}\n产品类别：{category}\n\n请分析这个产品，输出结构化 JSON。确保 features.core 包含所有核心功能，不要遗漏。")
        ])
        
        try:
            chain = prompt | self.llm
            response = chain.invoke({
                "competitor_name": competitor_name,
                "website": website or "未知",
                "category": category
            })
            
            # 清洗 LLM 返回内容（使用安全的解析函数）
            try:
                result = safe_extract_json(response.content, verbose=True)
            except ValueError as e:
                logger.error(f"JSON解析失败: {e}")
                return self._create_empty_data(competitor_name, website)
            
            result["website"] = website or result.get("website", "")
            result["name"] = competitor_name
            result["crawled_pages"] = []
            result["_source"] = "llm_fallback"
            result["_category"] = category
            
            logger.info(f"LLM兜底采集成功: {competitor_name} (类别: {category})")
            return result
            
        except Exception as e:
            logger.error(f"LLM兜底采集失败: {e}")
            return self._create_empty_data(competitor_name, website)
'''

content = content.replace(old_full, new_method)

with open('agents/crawler.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Successfully replaced _llm_fallback_collect() with simple version")
print("Verifying syntax...")
