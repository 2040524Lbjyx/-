    def _llm_fallback_collect(self, competitor_name: str, website: str = None) -> Dict[str, Any]:
        """
        当爬虫失败或返回空数据时，使用 LLM 知识库生成结构化数据
        
        这是兜底方案：即使完全无法访问网站，用户仍能得到有价值的报告
        
        🔧 重构：使用 LLM 动态理解产品，无需任何手动白名单
        """
        
        # 🔧 第一步：用 LLM 动态理解产品（替代原来的 _detect_product_type 白名单）
        product_understanding = self._understand_product_with_llm(competitor_name, website)
        category = product_understanding.get("category", "通用")
        
        # 🔧 第二步：极简通用 Prompt（不做任何复杂字符串拼接）
        # 关键：system_prompt 是普通字符串，category 由 Python 提前填入
        # user 消息中的 {competitor_name} 和 {website} 由 LangChain 在 invoke 时填入
        system_text = (
            "你是一位资深的产品数据分析专家，擅长分析各类互联网产品。\n\n"
            "请基于你的知识，对以下产品进行全面的结构化分析，"
            "输出严格的 JSON 格式（不要有 markdown 代码块）。\n\n"
            "产品类别：" + category + "\n\n"
            "要求：\n"
            "1. features.core 至少列出 10 个核心功能（具体、可验证的功能名）\n"
            "2. features.advanced 列出高级功能\n"
            "3. pricing 分析定价策略\ n"
            "4. changelog 分析版本更新\n"
            "5. target_users 和 platforms 要具体\ n"
            "6. 如果是知名产品，务必列出其标志性功能，不要遗漏\ n\n"
            "输出格式（严格 JSON，不要有其他内容）：\n"
            "{\n"
            '    "name": "产品名称",\n'
            '    "features": {\n'
            '        "core": ["核心功能1", "核心功能2", ...],\n'
            '        "advanced": ["高级功能1", "高级功能2", ...]\n'
            "    },\n"
            '    "pricing": {"model": "...", "plans": [...]},\n'
            '    "changelog": {"latest_version": "...", ...},\n'
            '    "target_users": ["用户1", "用户2"],\n'
            '    "platforms": ["平台1", "平台2"]\n'
            "}"
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_text),
            ("user",
                "产品名称：" + competitor_name + "\n"
                "官网：" + (website or "未知") + "\n\n"
                "请输出结构化 JSON。确保 features.core 包含所有核心功能，不要遗漏。"
            )
        ])
        
        try:
            chain = prompt | self.llm
            response = chain.invoke({})
            
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
