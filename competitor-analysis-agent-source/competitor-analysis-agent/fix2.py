"""
修复 crawler.py：用极简版本替换 _llm_fallback_collect 方法
"""
with open('agents/crawler.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找到 _llm_fallback_collect 的起始和结束行
start = None
end = None
for i, line in enumerate(lines):
    if 'def _llm_fallback_collect(self' in line:
        start = i
    elif start is not None and i > start and line.startswith('    def _'):
        end = i
        break

if start is None:
    print('ERROR: method not found')
    exit(1)

if end is None:
    end = len(lines)

print(f'Replacing lines {start+1} to {end} ({end-start} lines)')

# 正确的极简方法实现
new_method = [
    '    def _llm_fallback_collect(self, competitor_name: str, website: str = None) -> Dict[str, Any]:\n',
    '        """\n',
    '        当爬虫失败或返回空数据时，使用 LLM 知识库生成结构化数据\n',
    '        \n',
    '        这是兜底方案：即使完全无法访问网站，用户仍能得到有价值的报告\n',
    '        \n',
    '        🆕 改进：使用 LLM 动态理解产品，无需任何手动白名单\n',
    '        """\n',
    '        \n',
    '        # 🆕 第一步：用 LLM 动态理解产品\n',
    '        product_understanding = self._understand_product_with_llm(competitor_name, website)\n',
    '        category = product_understanding.get("category", "通用")\n',
    '        \n',
    '        # 🆕 第二步：极简 f-string Prompt（无复杂字符串拼接）\n',
    '        prompt = ChatPromptTemplate.from_messages([\n',
    '            ("system", \n',
    '                "你是一位资深的产品数据分析专家，特别擅长分析各类互联网产品。\\n\\n"\n',
    '                "请基于你的知识，对以下产品进行全面的结构化分析，"\n',
    '                "输出严格的 JSON 格式（不要有 markdown 代码块）。\\n\\n"\n',
    '                "产品类别：" + category + "\\n"\n',
    '                "产品名称：" + competitor_name + "\\n\\n"\n',
    '                "要求：\\n"\n',
    '                "1. features.core 至少列出 10 个核心功能（具体、可验证）\\n"\n',
    '                "2. features.advanced 列出高级功能\\n"\n',
    '                "3. pricing 分析定价策略\\n"\n',
    '                "4. changelog 分析版本更新\\n"\n',
    '                "5. 如果是知名产品，务必列出标志性功能\\n"\n',
    '                "6. 输出严格 JSON，不要有其他内容\\n"\n',
    '                "JSON 格式示例：\\n"\n',
    '                "{{\\"name\\": \\"产品名\\", \\"features\\": {{\\"core\\": [...]}}}\\n"\n',
    '            ),\n',
    '            ("user", \n',
    '                "产品名称：" + competitor_name + "\\n"\n',
    '                "官网：" + (website or "未知") + "\\n\\n"\n',
    '                "请输出结构化 JSON。"\n',
    '            )\n',
    '        ])\n',
    '        \n',
    '        try:\n',
    '            chain = prompt | self.llm\n',
    '            response = chain.invoke({\n',
    '                "competitor_name": competitor_name,\n',
    '                "website": website or "未知"\n',
    '            })\n',
    '            \n',
    '            try:\n',
    '                result = safe_extract_json(response.content, verbose=True)\n',
    '            except ValueError as e:\n',
    '                logger.error(f"JSON解析失败: {e}")\n',
    '                return self._create_empty_data(competitor_name, website)\n',
    '            \n',
    '            result["website"] = website or result.get("website", "")\n',
    '            result["name"] = competitor_name\n',
    '            result["crawled_pages"] = []\n',
    '            result["_source"] = "llm_fallback"\n',
    '            result["_category"] = category\n',
    '            \n',
    '            logger.info(f"LLM兜底采集成功: {competitor_name} (类别: {category})")\n',
    '            return result\n',
    '            \n',
    '        except Exception as e:\n',
    '            logger.error(f"LLM兜底采集失败: {e}")\n',
    '            return self._create_empty_data(competitor_name, website)\n',
    '    \n',
]

# 替换
new_lines = lines[:start] + new_method + lines[end:]

with open('agents/crawler.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print('Successfully replaced _llm_fallback_collect() with simple version')
print('Verifying syntax...')
