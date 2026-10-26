"""
搜索服务 - 使用 requests 访问搜狗搜索

搜狗是中国的搜索引擎，访问更稳定
"""

import logging
import re
from typing import Optional, List, Dict
from urllib.parse import urlparse, quote
from bs4 import BeautifulSoup
import requests

logger = logging.getLogger(__name__)


class SearchService:
    """
    使用 requests 访问搜狗搜索
    
    完全免费，无需 API Key
    """
    
    def __init__(self):
        self.logger = logger
        self.logger.info("✅ 搜狗搜索服务已启用（免费，无需 API Key）")
        
        # 设置请求头
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
    
    def _resolve_sogou_url(self, url: str) -> str:
        """
        解析搜狗重定向 URL，获取真实 URL
        
        Args:
            url: 搜狗重定向 URL (如 /link?url=...)
            
        Returns:
            真实 URL
        """
        if not url or not url.startswith("/link?"):
            return url
        
        try:
            # 拼接完整 URL
            full_url = "https://www.sogou.com" + url
            
            # 跟随重定向，获取真实 URL
            self.logger.info(f"[搜狗] 解析重定向 URL: {url[:50]}...")
            response = requests.head(full_url, allow_redirects=True, timeout=10, headers=self.headers)
            actual_url = response.url
            
            self.logger.info(f"[搜狗] 真实 URL: {actual_url}")
            return actual_url
                
        except Exception as e:
            self.logger.warning(f"解析搜狗 URL 失败: {e}")
            return "https://www.sogou.com" + url if url.startswith("/") else url
    
    def search(self, query: str, num_results: int = 10) -> List[Dict]:
        """
        执行搜狗搜索，返回标准化结果
        
        Args:
            query: 搜索关键词
            num_results: 返回结果数量
            
        Returns:
            [{"title": ..., "link": ..., "snippet": ...}, ...]
        """
        results = []
        
        try:
            # 构建搜索 URL (搜狗)
            search_url = f"https://www.sogou.com/web?query={quote(query)}"
            self.logger.info(f"[搜狗搜索] 查询: {query}")
            
            # 发送请求
            response = requests.get(search_url, headers=self.headers, timeout=30)
            response.raise_for_status()
            
            # 解析 HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 查询可能包含 URL、斜杠或长描述，不能直接作为文件路径。
            # 搜索结果解析不应依赖调试文件是否可写。
            self.logger.debug("[搜狗搜索] 收到 HTML，长度=%d", len(response.text))
            
            # 搜狗搜索结果在 .vrwrap 下
            result_containers = soup.find_all(class_="vrwrap")
            
            self.logger.info(f"[搜狗搜索] 找到 {len(result_containers)} 个结果容器")
            
            for container in result_containers[:num_results]:
                try:
                    # 提取标题和链接
                    title_elem = container.find(class_="vr-title")
                    if not title_elem:
                        title_elem = container.find("h3")
                    
                    if not title_elem:
                        continue
                    
                    link_elem = title_elem.find("a")
                    if not link_elem:
                        continue
                    
                    title = title_elem.get_text(strip=True)
                    link = link_elem.get("href", "")
                    
                    # 提取摘要
                    snippet_elem = container.find(class_="ft")
                    if not snippet_elem:
                        snippet_elem = container.find("p")
                    snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""
                    
                    if title and link:
                        # 解析搜狗重定向 URL
                        if link.startswith("/link?"):
                            actual_link = self._resolve_sogou_url(link)
                            if actual_link:
                                link = actual_link
                            else:
                                # 如果解析失败，拼接完整 URL
                                link = "https://www.sogou.com" + link
                        
                        results.append({
                            "title": title,
                            "link": link,
                            "snippet": snippet
                        })
                except Exception as e:
                    self.logger.warning(f"解析搜索结果失败: {e}")
                    continue
            
        except Exception as e:
            self.logger.error(f"搜狗搜索失败: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return []
        
        self.logger.info(f"[搜狗搜索] 找到 {len(results)} 个结果")
        return results
    
    def discover_competitor_website(self, competitor_name: str) -> Optional[str]:
        """
        发现竞品官网
        
        Args:
            competitor_name: 竞品名称 (如 "夸克网盘")
            
        Returns:
            官网 URL，如果找不到返回 None
        """
        query = f"{competitor_name} 官网"
        results = self.search(query, num_results=5)
        
        if not results:
            self.logger.warning(f"⚠️ 搜狗搜索未找到结果: {competitor_name}")
            return None
        
        # 优先返回看起来像官网的结果
        for r in results:
            link = r["link"]
            title = r["title"]
            
            # 简单启发式：标题或链接包含"官网"、"官方"
            if any(kw in title or kw in link for kw in ["官网", "官方", "official"]):
                self.logger.info(f"✅ 搜狗搜索发现官网: {competitor_name} -> {link}")
                return link
        
        # fallback: 返回第一个结果
        self.logger.info(f"✅ 搜狗搜索发现官网 (第一个结果): {competitor_name} -> {results[0]['link']}")
        return results[0]["link"]
    
    def discover_feature_pages(self, website: str, competitor_name: str) -> List[str]:
        """
        发现网站的功能介绍页面
        
        Args:
            website: 官网 URL
            competitor_name: 竞品名称
            
        Returns:
            功能页 URL 列表
        """
        query = f"{competitor_name} 功能介绍"
        results = self.search(query, num_results=10)
        
        # 只保留同域名下的页面
        parsed_website = urlparse(website)
        base_domain = (parsed_website.hostname or "").lower().removeprefix("www.")
        
        feature_pages = []
        for r in results:
            link = r["link"]
            parsed_link = urlparse(link)
            link_domain = (parsed_link.hostname or "").lower().removeprefix("www.")
            same_domain = bool(base_domain and link_domain) and (
                link_domain == base_domain
                or link_domain.endswith("." + base_domain)
                or base_domain.endswith("." + link_domain)
            )
            if same_domain:
                feature_pages.append(link)
        
        return feature_pages[:5]  # 最多返回 5 个
    
    def verify_feature_exists(self, competitor_name: str, feature_name: str) -> Dict:
        """
        验证某个功能是否真实存在
        
        Args:
            competitor_name: 竞品名称
            feature_name: 功能名称 (如 "回收站")
            
        Returns:
            {"exists": bool, "confidence": float, "source": str}
        """
        query = f"{competitor_name} {feature_name}"
        results = self.search(query, num_results=5)
        
        if not results:
            return {"exists": False, "confidence": 0.0, "source": "no_search_results"}
        
        # 简单关键词匹配
        positive_keywords = ["支持", "提供", "包含", "功能", "有", "具备", "已支持"]
        negative_keywords = ["不支持", "不包含", "没有", "暂无", "不具备", "暂不支持"]
        
        for r in results:
            snippet = r.get("snippet", "")
            title = r.get("title", "")
            
            # 检查摘要和标题
            text = snippet + " " + title
            
            if any(pos in text for pos in positive_keywords):
                return {"exists": True, "confidence": 0.8, "source": r["link"]}
            if any(neg in text for neg in negative_keywords):
                return {"exists": False, "confidence": 0.8, "source": r["link"]}
        
        # 默认：搜索结果提到了这个功能，认为存在
        return {"exists": True, "confidence": 0.6, "source": results[0]["link"]}


# 全局搜索服务实例（单例模式）
_global_search_service = None

def get_search_service() -> SearchService:
    """获取全局搜索服务实例"""
    global _global_search_service
    if _global_search_service is None:
        _global_search_service = SearchService()
    return _global_search_service
