"""
测试文件: 验证Agent协作功能

改进版本：
- 添加向量数据库测试
- 添加更详细的Agent功能测试
- 添加集成测试
"""

import sys
import os
import json
import pytest
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_coordinator():
    """测试Coordinator Agent"""
    print("\n" + "="*50)
    print("测试 1: Coordinator Agent")
    print("="*50)
    
    try:
        from agents.coordinator import CoordinatorAgent, WorkflowState, AgentStatus
        
        # 创建Coordinator
        coordinator = CoordinatorAgent()
        
        print("✅ Coordinator Agent 创建成功")
        print(f"   LLM模型: {coordinator.llm.model_name}")
        print(f"   工作流节点: {list(coordinator.workflow.nodes.keys())}")
        
        # 测试状态初始化
        print("\n  测试状态初始化...")
        initial_state = WorkflowState(
            user_query="分析Notion和Obsidian",
            competitors=[],
            plan=[],
            current_step=0,
            crawler_status=AgentStatus.PENDING,
            analyzer_status=AgentStatus.PENDING,
            reporter_status=AgentStatus.PENDING,
            crawled_data=None,
            analysis_results=None,
            report_path=None,
            errors=[],
            retry_count=0,
            output_format="markdown",
            verbose=False
        )
        print("  ✅ 状态初始化成功")
        
        return
    
    except Exception as e:
        print(f"❌ Coordinator Agent 测试失败: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError(f"Coordinator Agent 测试失败: {e}") from e


def test_crawler():
    """测试Data Collection Agent"""
    print("\n" + "="*50)
    print("测试 2: Data Collection Agent (Crawler)")
    print("="*50)
    
    try:
        from agents.crawler import DataCollectionAgent
        
        # 创建Crawler（不使用Playwright，加快测试速度）
        crawler = DataCollectionAgent(use_playwright=False)
        
        print("✅ Data Collection Agent 创建成功")
        print(f"   使用Playwright: {crawler.use_playwright}")
        print(f"   最大重试次数: {crawler.max_retries}")
        print(f"   User-Agent: {crawler.session.headers['User-Agent'][:50]}...")
        
        # 测试空数据创建
        print("\n  测试空数据创建...")
        empty_data = crawler._create_empty_data("TestProduct")
        assert empty_data["name"] == "TestProduct"
        assert empty_data["features"]["core"] == []
        print("  ✅ 空数据创建成功")
        
        return
    
    except Exception as e:
        print(f"❌ Data Collection Agent 测试失败: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError(f"Data Collection Agent 测试失败: {e}") from e


def test_crawler_with_playwright():
    """测试Crawler的Playwright功能（可选）"""
    print("\n" + "="*50)
    print("测试 2.1: Crawler Playwright功能")
    print("="*50)
    
    try:
        from agents.crawler import PLAYWRIGHT_AVAILABLE
        
        if not PLAYWRIGHT_AVAILABLE:
            print("⚠️  Playwright未安装，跳过此测试")
            return
        
        from agents.crawler import DataCollectionAgent
        
        # 创建Crawler（使用Playwright）
        crawler = DataCollectionAgent(use_playwright=True)
        
        print("✅ Playwright模式Crawler创建成功")
        print(f"   Playwright可用: {crawler.use_playwright}")
        
        return
    
    except Exception as e:
        print(f"❌ Crawler Playwright测试失败: {e}")
        raise AssertionError(f"Crawler Playwright测试失败: {e}") from e


def test_analyzer():
    """测试Analysis Agent"""
    print("\n" + "="*50)
    print("测试 3: Analysis Agent")
    print("="*50)
    
    try:
        from agents.analyzer import AnalysisAgent
        import pandas as pd
        
        # 创建Analyzer
        analyzer = AnalysisAgent()
        
        print("✅ Analysis Agent 创建成功")
        print(f"   LLM模型: {analyzer.llm.model_name}")
        
        # 测试功能对比
        print("\n  测试功能对比...")
        test_data = {
            "Notion": {
                "features": {
                    "core": ["文档编辑", "数据库", "看板视图"],
                    "advanced": ["API接口", "自动化"]
                }
            },
            "Obsidian": {
                "features": {
                    "core": ["文档编辑", "双向链接", "本地存储"],
                    "advanced": ["图谱视图", "插件系统"]
                }
            }
        }
        
        matrix = analyzer.compare_features(test_data)
        print(f"  ✅ 功能对比矩阵生成成功 ({len(matrix)} 个功能)")
        print("\n  功能对比矩阵预览:")
        print(matrix.to_string(index=False))
        
        # 测试定价分析
        print("\n  测试定价分析...")
        pricing_data = {
            "Notion": {
                "pricing": {
                    "model": "subscription",
                    "plans": [
                        {"name": "Free", "price": 0},
                        {"name": "Plus", "price": 8, "period": "month"}
                    ]
                }
            },
            "Obsidian": {
                "pricing": {
                    "model": "one-time",
                    "plans": [
                        {"name": "个人", "price": 0},
                        {"name": "商用", "price": 50, "period": "one-time"}
                    ]
                }
            }
        }
        
        pricing_analysis = analyzer.analyze_pricing(pricing_data)
        print(f"  ✅ 定价分析成功")
        print(f"   定价模式: {pricing_analysis['pricing_models']}")
        
        return
    
    except Exception as e:
        print(f"❌ Analysis Agent 测试失败: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError(f"Analysis Agent 测试失败: {e}") from e


def test_reporter():
    """测试Report Agent"""
    print("\n" + "="*50)
    print("测试 4: Report Agent")
    print("="*50)
    
    try:
        from agents.reporter import ReportAgent
        
        # 创建Reporter
        reporter = ReportAgent()
        
        print("✅ Report Agent 创建成功")
        print(f"   模板目录: {reporter.template_dir}")
        print(f"   输出目录: {reporter.output_dir}")
        
        # 测试目录创建
        assert reporter.output_dir.exists(), "输出目录未创建"
        print("  ✅ 输出目录已创建")
        
        return
    
    except Exception as e:
        print(f"❌ Report Agent 测试失败: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError(f"Report Agent 测试失败: {e}") from e


def test_vector_store():
    """测试向量数据库"""
    print("\n" + "="*50)
    print("测试 5: 向量数据库 (ChromaDB)")
    print("="*50)
    
    try:
        pytest.importorskip("chromadb")
        from vector_store import CompetitorVectorStore
        
        # 创建向量数据库
        vector_store = CompetitorVectorStore(persist_directory="./data/test_chroma_db")
        
        print("✅ 向量数据库创建成功")
        print(f"   持久化目录: {vector_store.persist_directory}")
        print(f"   Collection名称: {vector_store.collection.name}")
        
        # 测试添加数据
        print("\n  测试添加数据...")
        test_data = {
            "name": "TestNotion",
            "website": "https://www.notion.so",
            "features": {
                "core": ["文档编辑", "数据库", "看板视图"],
                "advanced": ["API", "自动化"]
            },
            "pricing": {
                "model": "subscription",
                "plans": [
                    {"name": "Free", "price": 0, "period": "month"}
                ]
            },
            "company_info": {
                "founded": "2016",
                "hq": "旧金山, 美国"
            },
            "target_users": ["团队", "个人"],
            "platforms": ["Web", "Desktop", "Mobile"]
        }
        
        doc_id = vector_store.add_competitor(test_data)
        print(f"  ✅ 数据添加成功 (ID: {doc_id})")
        
        # 测试语义搜索
        print("\n  测试语义搜索...")
        results = vector_store.search_similar("项目管理工具", n_results=3)
        print(f"  ✅ 语义搜索成功，返回 {len(results)} 个结果")
        for r in results:
            print(f"     - {r['metadata'].get('name', 'Unknown')} (距离: {r['distance']:.4f})")
        
        # 测试获取所有数据
        print("\n  测试获取所有数据...")
        all_data = vector_store.get_all_competitors()
        print(f"  ✅ 获取成功，共有 {len(all_data)} 个竞品")
        
        # 测试统计信息
        print("\n  测试统计信息...")
        stats = vector_store.get_collection_stats()
        print(f"  ✅ 统计信息: {stats}")
        
        return
    
    except Exception as e:
        print(f"❌ 向量数据库测试失败: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError(f"向量数据库测试失败: {e}") from e


def test_demo_analysis():
    """测试演示分析（不调用真实API）"""
    print("\n" + "="*50)
    print("测试 6: 演示分析（模拟数据）")
    print("="*50)
    
    try:
        import pandas as pd
        from agents.analyzer import AnalysisAgent
        from agents.reporter import ReportAgent
        
        # 模拟数据
        test_data = {
            "Notion": {
                "features": {
                    "core": ["文档编辑", "数据库", "看板视图"],
                    "advanced": ["API接口", "模板市场"]
                },
                "pricing": {
                    "model": "subscription",
                    "plans": [
                        {"name": "Free", "price": 0},
                        {"name": "Plus", "price": 10, "period": "month"}
                    ]
                }
            },
            "Obsidian": {
                "features": {
                    "core": ["文档编辑", "双向链接", "本地存储"],
                    "advanced": ["图谱视图", "插件系统"]
                },
                "pricing": {
                    "model": "one-time",
                    "plans": [
                        {"name": "个人", "price": 0},
                        {"name": "商用", "price": 50, "period": "one-time"}
                    ]
                }
            }
        }
        
        # 测试功能对比
        print("\n  测试功能对比...")
        analyzer = AnalysisAgent()
        matrix = analyzer.compare_features(test_data)
        print(f"  ✅ 功能对比矩阵生成成功 ({len(matrix)} 个功能)")
        print("\n  功能对比矩阵预览:")
        print(matrix.to_string(index=False))
        
        # 测试报告生成
        print("\n  测试报告生成...")
        reporter = ReportAgent()
        
        analysis_results = {
            "feature_matrix": matrix,
            "pricing_analysis": analyzer.analyze_pricing(test_data),
            "insights": [
                "洞察1：Notion主打团队协作，Obsidian专注个人知识管理",
                "洞察2：定价策略反映不同的商业模式"
            ]
        }
        
        report_path = reporter.generate(
            analysis_results=analysis_results,
            competitors=["Notion", "Obsidian"],
            output_format="markdown"
        )
        
        print(f"  ✅ 报告生成成功: {report_path}")
        
        # 验证报告文件
        assert Path(report_path).exists(), "报告文件未生成"
        print("  ✅ 报告文件验证成功")
        
        return
    
    except Exception as e:
        print(f"❌ 演示分析失败: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError(f"演示分析失败: {e}") from e


def test_integration():
    """集成测试：测试完整的Agent协作流程"""
    print("\n" + "="*50)
    print("测试 7: 集成测试（完整流程）")
    print("="*50)
    
    try:
        from agents.coordinator import CoordinatorAgent
        
        # 注意：这个测试需要真实的OpenAI API Key
        # 这里只测试初始化和工作流创建
        
        coordinator = CoordinatorAgent()
        
        print("✅ Coordinator初始化成功")
        print(f"   工作流编译成功: {coordinator.workflow is not None}")
        
        # 测试工作流图结构
        print("\n  测试工作流图结构...")
        # LangGraph的StateGraph编译后是CompiledGraph对象
        assert coordinator.workflow is not None
        print("  ✅ 工作流图结构正确")
        
        return
    
    except Exception as e:
        print(f"❌ 集成测试失败: {e}")
        import traceback
        traceback.print_exc()
        raise AssertionError(f"集成测试失败: {e}") from e


def cleanup_test_data():
    """清理测试数据"""
    print("\n" + "="*50)
    print("清理测试数据")
    print("="*50)
    
    try:
        import shutil
        
        # 删除测试数据库
        test_db_path = Path("./data/test_chroma_db")
        if test_db_path.exists():
            shutil.rmtree(test_db_path)
            print(f"✅ 删除测试数据库: {test_db_path}")
        
        return
    
    except Exception as e:
        print(f"⚠️  清理测试数据失败: {e}")
        raise AssertionError(f"清理测试数据失败: {e}") from e


def main():
    """运行所有测试"""
    
    print("\n")
    print("█" * 60)
    print("  竞品分析多Agent系统 - 单元测试")
    print("█" * 60)
    print("\n")
    
    # 运行测试
    results = []
    
    # 基础功能测试
    results.append(("Coordinator Agent", test_coordinator()))
    results.append(("Data Collection Agent", test_crawler()))
    results.append(("Crawler Playwright", test_crawler_with_playwright()))
    results.append(("Analysis Agent", test_analyzer()))
    results.append(("Report Agent", test_reporter()))
    
    # 向量数据库测试
    results.append(("向量数据库", test_vector_store()))
    
    # 集成测试
    results.append(("演示分析", test_demo_analysis()))
    results.append(("集成测试", test_integration()))
    
    # 清理测试数据
    cleanup_test_data()
    
    # 打印总结
    print("\n" + "="*50)
    print("测试总结")
    print("="*50)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{name}: {status}")
    
    print("\n" + "-"*50)
    print(f"总计: {passed}/{total} 通过")
    print("-"*50 + "\n")
    
    if passed == total:
        print("🎉 所有测试通过！系统可以正常运行。")
        return 0
    else:
        print(f"⚠️  有 {total - passed} 个测试失败，请检查错误信息。")
        return 1


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ 未处理的异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
