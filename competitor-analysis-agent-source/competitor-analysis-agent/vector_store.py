"""
向量数据库模块 - 使用ChromaDB存储和检索竞品数据

功能：
- 存储爬取的竞品数据（向量化）
- 语义搜索和相似度检索
- 支持增量更新
"""

import logging
import uuid
from typing import Dict, List, Optional, Any
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

logger = logging.getLogger(__name__)


def _check_st_model_cached(model_name: str = "all-MiniLM-L6-v2") -> bool:
    """检查 sentence-transformers 模型是否已缓存在本地（不需要下载）。"""
    from pathlib import Path
    cache_dir = Path.home() / ".cache" / "huggingface" / "hub" / f"models--sentence-transformers--{model_name}"
    # 需要至少有 model.safetensors 或 pytorch_model.bin 才算完整
    if cache_dir.exists():
        for p in cache_dir.rglob("*"):
            if p.is_file() and (p.name.endswith(".safetensors") or p.name == "pytorch_model.bin"):
                if p.stat().st_size > 10_000_000:  # 至少 10MB
                    return True
    return False


class CompetitorVectorStore:
    """竞品向量数据库"""

    def __init__(self, persist_directory: str = "./data/chroma_db", init_timeout: int = 15,
                 force_lightweight: bool = False):
        """
        初始化向量数据库

        Args:
            persist_directory: ChromaDB持久化目录
            init_timeout: 嵌入模型加载超时（秒）
            force_lightweight: 强制使用轻量模式，不尝试加载任何外部模型
        """
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)

        # 初始化ChromaDB客户端（持久化）
        self.client = chromadb.PersistentClient(
            path=str(self.persist_directory),
            settings=ChromaSettings(
                anonymized_telemetry=False,
                allow_reset=True,
            )
        )

        # 嵌入函数选择策略：
        # 1. force_lightweight=True → 直接用 ChromaDB 内置轻量嵌入（零下载）
        # 2. 模型未缓存 → 直接用轻量模式（避免触发 79MB 下载阻塞）
        # 3. 模型已缓存 → 尝试加载 SentenceTransformer
        self.embedding_function = None
        if not force_lightweight and _check_st_model_cached():
            try:
                from chromadb.utils import embedding_functions
                self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
                    model_name="all-MiniLM-L6-v2"
                )
                logger.info("SentenceTransformer 模型已从本地缓存加载")
            except Exception as e:
                logger.warning(f"SentenceTransformer 加载失败（即使模型已缓存）: {e}")

        if self.embedding_function is None:
            logger.info("使用 ChromaDB 默认轻量 embedding function（零依赖模式）")

        # 创建或获取collection
        self.collection = self._get_or_create_collection()

    def _get_or_create_collection(self):
        """创建或获取ChromaDB collection"""
        
        collection_name = "competitors"
        
        try:
            # 尝试获取已存在的collection
            collection = self.client.get_collection(
                name=collection_name,
                embedding_function=self.embedding_function
            )
            logger.info(f"获取到已存在的collection: {collection_name}")
            return collection
        
        except Exception:
            # 如果不存在，创建新的collection
            logger.info(f"创建新的collection: {collection_name}")
            collection = self.client.create_collection(
                name=collection_name,
                embedding_function=self.embedding_function,
                metadata={"hnsw:space": "cosine"}  # 使用cosine相似度
            )
            return collection
    
    def add_competitor(self, competitor_data: Dict[str, Any]) -> str:
        """
        添加竞品数据到向量数据库
        
        Args:
            competitor_data: 竞品数据字典（从Crawler提取的结构化数据）
        
        Returns:
            添加的文档ID
        """
        
        # 生成唯一ID
        doc_id = str(uuid.uuid4())
        
        # 将结构化数据转换为文本内容（用于向量化）
        document_text = self._data_to_text(competitor_data)
        
        # 准备元数据
        metadata = self._extract_metadata(competitor_data)
        
        try:
            # 添加到collection
            self.collection.add(
                documents=[document_text],
                metadatas=[metadata],
                ids=[doc_id]
            )
            
            logger.info(f"成功添加竞品数据: {competitor_data.get('name', 'Unknown')} (ID: {doc_id})")
            return doc_id
        
        except Exception as e:
            logger.error(f"添加竞品数据失败: {e}")
            raise
    
    def add_competitors_batch(self, competitors_data: List[Dict[str, Any]]) -> List[str]:
        """
        批量添加竞品数据
        
        Args:
            competitors_data: 竞品数据字典列表
        
        Returns:
            添加的文档ID列表
        """
        
        doc_ids = []
        documents = []
        metadatas = []
        
        for comp_data in competitors_data:
            doc_id = str(uuid.uuid4())
            doc_ids.append(doc_id)
            documents.append(self._data_to_text(comp_data))
            metadatas.append(self._extract_metadata(comp_data))
        
        try:
            self.collection.add(
                documents=documents,
                metadatas=metadatas,
                ids=doc_ids
            )
            
            logger.info(f"成功批量添加 {len(competitors_data)} 个竞品数据")
            return doc_ids
        
        except Exception as e:
            logger.error(f"批量添加竞品数据失败: {e}")
            raise
    
    def search_similar(self, query: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """
        语义搜索相似的竞品
        
        Args:
            query: 搜索查询（自然语言）
            n_results: 返回结果数量
        
        Returns:
            相似的竞品数据列表
        """
        
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=n_results
            )
            
            # 格式化结果
            formatted_results = []
            
            if results and 'ids' in results and len(results['ids']) > 0:
                for i in range(len(results['ids'][0])):
                    result = {
                        'id': results['ids'][0][i],
                        'document': results['documents'][0][i],
                        'metadata': results['metadatas'][0][i],
                        'distance': results['distances'][0][i] if 'distances' in results else None
                    }
                    formatted_results.append(result)
            
            logger.info(f"语义搜索 '{query}' 返回 {len(formatted_results)} 个结果")
            return formatted_results
        
        except Exception as e:
            logger.error(f"语义搜索失败: {e}")
            return []
    
    def get_competitor(self, competitor_name: str) -> Optional[Dict[str, Any]]:
        """
        根据竞品名称获取数据库中的数据
        
        Args:
            competitor_name: 竞品名称
        
        Returns:
            竞品数据（如果找到）
        """
        
        try:
            # 通过metadata过滤查询
            results = self.collection.get(
                where={"name": competitor_name}
            )
            
            if results and 'ids' in results and len(results['ids']) > 0:
                # 返回第一个匹配的结果
                return {
                    'id': results['ids'][0],
                    'document': results['documents'][0],
                    'metadata': results['metadatas'][0]
                }
            
            return None
        
        except Exception as e:
            logger.error(f"获取竞品数据失败: {e}")
            return None
    
    def get_all_competitors(self) -> List[Dict[str, Any]]:
        """
        获取所有竞品数据
        
        Returns:
            所有竞品数据列表
        """
        
        try:
            results = self.collection.get()
            
            formatted_results = []
            
            if results and 'ids' in results:
                for i in range(len(results['ids'])):
                    result = {
                        'id': results['ids'][i],
                        'document': results['documents'][i],
                        'metadata': results['metadatas'][i]
                    }
                    formatted_results.append(result)
            
            logger.info(f"获取到 {len(formatted_results)} 个竞品数据")
            return formatted_results
        
        except Exception as e:
            logger.error(f"获取所有竞品数据失败: {e}")
            return []
    
    def delete_competitor(self, doc_id: str) -> bool:
        """
        删除竞品数据
        
        Args:
            doc_id: 文档ID
        
        Returns:
            是否删除成功
        """
        
        try:
            self.collection.delete(ids=[doc_id])
            logger.info(f"成功删除竞品数据 (ID: {doc_id})")
            return True
        
        except Exception as e:
            logger.error(f"删除竞品数据失败: {e}")
            return False
    
    def update_competitor(self, doc_id: str, competitor_data: Dict[str, Any]) -> bool:
        """
        更新竞品数据
        
        Args:
            doc_id: 文档ID
            competitor_data: 新的竞品数据
        
        Returns:
            是否更新成功
        """
        
        try:
            # ChromaDB的update需要重新添加
            document_text = self._data_to_text(competitor_data)
            metadata = self._extract_metadata(competitor_data)
            
            self.collection.update(
                ids=[doc_id],
                documents=[document_text],
                metadatas=[metadata]
            )
            
            logger.info(f"成功更新竞品数据 (ID: {doc_id})")
            return True
        
        except Exception as e:
            logger.error(f"更新竞品数据失败: {e}")
            return False
    
    def _data_to_text(self, competitor_data: Dict[str, Any]) -> str:
        """
        将结构化数据转换为文本内容（用于向量化）
        
        Args:
            competitor_data: 竞品数据字典
        
        Returns:
            文本内容
        """
        
        text_parts = []
        
        # 基本信息
        if 'name' in competitor_data:
            text_parts.append(f"产品名称: {competitor_data['name']}")
        
        if 'website' in competitor_data:
            text_parts.append(f"官网: {competitor_data['website']}")
        
        # 功能特性
        if 'features' in competitor_data:
            features = competitor_data['features']
            if 'core' in features and features['core']:
                text_parts.append(f"核心功能: {', '.join(features['core'])}")
            if 'advanced' in features and features['advanced']:
                text_parts.append(f"高级功能: {', '.join(features['advanced'])}")
        
        # 定价信息
        if 'pricing' in competitor_data:
            pricing = competitor_data['pricing']
            if 'model' in pricing:
                text_parts.append(f"定价模式: {pricing['model']}")
            if 'plans' in pricing and pricing['plans']:
                plans_text = "; ".join([
                    f"{p.get('name', '')} - {p.get('price', 'N/A')}"
                    for p in pricing['plans']
                ])
                text_parts.append(f"定价方案: {plans_text}")
        
        # 公司信息
        if 'company_info' in competitor_data:
            company = competitor_data['company_info']
            if 'founded' in company:
                text_parts.append(f"成立年份: {company['founded']}")
            if 'hq' in company:
                text_parts.append(f"总部: {company['hq']}")
        
        # 目标用户
        if 'target_users' in competitor_data and competitor_data['target_users']:
            text_parts.append(f"目标用户: {', '.join(competitor_data['target_users'])}")
        
        # 支持平台
        if 'platforms' in competitor_data and competitor_data['platforms']:
            text_parts.append(f"支持平台: {', '.join(competitor_data['platforms'])}")
        
        return "\n".join(text_parts)
    
    def _extract_metadata(self, competitor_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        从竞品数据中提取元数据（用于过滤和检索）
        
        Args:
            competitor_data: 竞品数据字典
        
        Returns:
            元数据字典
        """
        
        metadata = {}
        
        # 基本元数据
        if 'name' in competitor_data:
            metadata['name'] = competitor_data['name']
        
        if 'website' in competitor_data:
            metadata['website'] = competitor_data['website']
        
        # 定价模式
        if 'pricing' in competitor_data and 'model' in competitor_data['pricing']:
            metadata['pricing_model'] = competitor_data['pricing']['model']
        
        # 核心功能数量
        if 'features' in competitor_data and 'core' in competitor_data['features']:
            metadata['core_features_count'] = len(competitor_data['features']['core'])
        
        # 公司成立年份
        if 'company_info' in competitor_data and 'founded' in competitor_data['company_info']:
            try:
                metadata['founded_year'] = int(competitor_data['company_info']['founded'])
            except (ValueError, TypeError):
                pass
        
        # Chroma metadata 只接受 string/int/float/bool；None 会导致整条记录入库失败。
        # 缺失字段直接省略，避免一次空定价字段阻断整个竞品写入。
        return {
            key: value
            for key, value in metadata.items()
            if value is not None and isinstance(value, (str, int, float, bool))
        }
    
    def get_collection_stats(self) -> Dict[str, Any]:
        """获取collection统计信息"""
        
        try:
            count = self.collection.count()
            return {
                'total_competitors': count,
                'collection_name': self.collection.name
            }
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {}


# 测试代码
if __name__ == "__main__":
    # 测试向量数据库
    import sys
    from pathlib import Path
    
    # 添加项目根目录到Python路径
    project_root = Path(__file__).parent
    sys.path.insert(0, str(project_root))
    
    # 初始化向量数据库
    print("初始化向量数据库...")
    vector_store = CompetitorVectorStore()
    
    # 测试数据
    test_data = {
        "name": "Notion",
        "website": "https://www.notion.so",
        "features": {
            "core": ["文档编辑", "数据库", "看板视图", "日历"],
            "advanced": ["API", "自动化", "权限管理"]
        },
        "pricing": {
            "model": "subscription",
            "plans": [
                {"name": "Free", "price": 0, "period": "month"},
                {"name": "Plus", "price": 8, "period": "month"}
            ]
        },
        "company_info": {
            "founded": "2016",
            "hq": "旧金山, 美国"
        },
        "target_users": ["团队", "个人", "企业"],
        "platforms": ["Web", "Windows", "Mac", "iOS", "Android"]
    }
    
    # 测试1: 添加数据
    print("\n测试1: 添加竞品数据...")
    doc_id = vector_store.add_competitor(test_data)
    print(f"添加成功! ID: {doc_id}")
    
    # 测试2: 语义搜索
    print("\n测试2: 语义搜索...")
    results = vector_store.search_similar("项目管理工具", n_results=3)
    print(f"搜索到 {len(results)} 个结果:")
    for r in results:
        print(f"  - {r['metadata'].get('name', 'Unknown')} (距离: {r['distance']:.4f})")
    
    # 测试3: 获取所有数据
    print("\n测试3: 获取所有竞品...")
    all_comps = vector_store.get_all_competitors()
    print(f"共有 {len(all_comps)} 个竞品")
    
    # 测试4: 统计信息
    print("\n测试4: 统计信息...")
    stats = vector_store.get_collection_stats()
    print(f"统计: {stats}")
    
    print("\n✅ 向量数据库测试完成!")
