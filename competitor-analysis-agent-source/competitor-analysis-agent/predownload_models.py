"""
预下载 ChromaDB 嵌入模型

此脚本会预下载 sentence-transformers 的 all-MiniLM-L6-v2 模型（~79MB）
这样在首次使用向量搜索时无需等待下载。

使用方法：
    python predownload_models.py
"""

import os
import sys
from pathlib import Path

def main():
    """主函数"""
    print("="*70)
    print("  预下载 ChromaDB 嵌入模型")
    print("="*70)
    print()
    
    # 设置缓存目录
    cache_dir = Path.home() / ".cache" / "sentence_transformers"
    hf_cache = Path.home() / ".cache" / "huggingface"
    
    os.environ["SENTENCE_TRANSFORMERS_HOME"] = str(cache_dir)
    os.environ["HF_HOME"] = str(hf_cache)
    
    print(f"📂 模型缓存位置：")
    print(f"   Sentence Transformers: {cache_dir}")
    print(f"   Hugging Face: {hf_cache}")
    print()
    
    try:
        from sentence_transformers import SentenceTransformer
        
        print("⏳ 正在下载 all-MiniLM-L6-v2 模型（~79MB）...")
        print("   请稍候，这可能需要几分钟...")
        print()
        
        # 下载模型
        model = SentenceTransformer('all-MiniLM-L6-v2')
        
        print()
        print("✅ 模型下载完成！")
        print(f"   模型位置：{cache_dir}")
        print()
        print("💡 提示：")
        print("   - 后续使用向量搜索时无需再次下载")
        print("   - 如果需要清理空间，可以删除缓存目录")
        print()
        
        return 0
        
    except ImportError as e:
        print(f"❌ 导入失败：{e}")
        print()
        print("💡 解决方案：")
        print("   1. 安装依赖：pip install sentence-transformers")
        print("   2. 或使用 setup.py 一键安装所有依赖")
        print()
        return 1
        
    except Exception as e:
        print(f"❌ 模型下载失败：{e}")
        print()
        print("💡 可能的原因：")
        print("   1. 网络连接问题")
        print("   2. 代理设置（如果需要）")
        print("   3. 磁盘空间不足（需要 ~200MB）")
        print()
        print("💡 解决方案：")
        print("   1. 检查网络连接")
        print("   2. 设置代理：set HTTP_PROXY=http://proxy:port")
        print("   3. 或跳过此步骤，模型将在首次使用时自动下载")
        print()
        return 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️ 下载被用户中断")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 下载失败：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
