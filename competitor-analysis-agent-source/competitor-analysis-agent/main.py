"""
竞品分析多Agent系统 - 命令行入口
"""

import sys
import os
import argparse
import logging
from pathlib import Path

# Windows 控制台默认 GBK 时，日志中的中文和状态图标可能触发 UnicodeEncodeError。
for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

# 将项目根目录加入 sys.path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


def main():
    """命令行主入口"""

    # 解析命令行参数
    parser = argparse.ArgumentParser(
        description="竞品分析多Agent系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py "分析Notion和Obsidian"
  python main.py "Notion对比Obsidian" --format html
  python main.py "分析Notion" --verbose
        """
    )

    parser.add_argument(
        "query",
        type=str,
        help="要分析的竞品查询，例如：'分析Notion和Obsidian'"
    )

    parser.add_argument(
        "-f", "--format",
        type=str,
        choices=["markdown", "html"],
        default="markdown",
        help="输出格式 (默认: markdown)"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="显示详细执行过程"
    )

    parser.add_argument(
        "--demo",
        action="store_true",
        help="演示模式（不调用真实 API）"
    )

    args = parser.parse_args()

    # 启动横幅
    print("=" * 60)
    print("  竞品分析 Agent")
    print("  Competitor Analysis Multi-Agent System")
    print("=" * 60)
    print()

    # 检查运行环境
    if not args.demo:
        check_environment()

    # 根据模式运行
    if args.demo:
        result = run_demo(args.query, args.format)
    else:
        result = run_analysis(args.query, args.format, args.verbose)

    # 输出结果
    print_result(result)

    return 0 if result["status"] in {"success", "partial_success"} else 1


def check_environment():
    """检查运行环境（.env 与 API Key）"""

    logger.info("正在检查运行环境...")

    # 检查 .env 文件
    env_file = project_root / ".env"
    if not env_file.exists():
        logger.warning("未找到 .env 文件，请参考 .env.example")
        print("\n[警告] 未找到 .env 文件")
        print("请按以下步骤配置：")
        print("  cp .env.example .env")
        print("然后在 .env 中配置 OPENAI_API_KEY\n")

    # 检查 OpenAI API Key
    try:
        from dotenv import load_dotenv
        load_dotenv()

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key or api_key == "your_openai_api_key_here":
            logger.error("未配置 OPENAI_API_KEY")
            print("\n[错误] 未配置 OPENAI_API_KEY")
            print("请在 .env 中配置 OPENAI_API_KEY 后重试\n")
            sys.exit(1)

        logger.info("运行环境检查通过")

    except ImportError:
        logger.warning("未安装 python-dotenv，无法加载 .env 文件")


def run_analysis(query: str, output_format: str, verbose: bool) -> dict:
    """运行完整的竞品分析流程"""

    logger.info(f"开始分析: {query}")

    try:
        # Coordinator Agent
        from agents.coordinator import CoordinatorAgent

        # 初始化 Coordinator
        coordinator = CoordinatorAgent()

        # 运行分析
        result = coordinator.run(
            user_query=query,
            output_format=output_format,
            verbose=verbose
        )

        return result

    except Exception as e:
        logger.error(f"分析失败: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }


def run_demo(query: str, output_format: str) -> dict:
    """演示模式：使用内置示例数据生成报告（不调用真实 API）"""

    logger.info("演示模式：使用内置示例数据生成报告")

    print("\n[演示模式]")
    print("不调用真实 API，直接生成示例报告\n")

    # 解析竞品名称
    import pandas as pd

    if not query or not query.strip():
        return {"status": "error", "error": "分析需求不能为空", "errors": []}

    competitors = extract_competitors_from_query(query)
    if len(competitors) < 2:
        return {
            "status": "error",
            "error": "请至少输入两个可识别的竞品名称（例如：Notion 和 Obsidian）",
            "errors": [],
        }

    print(f"竞品: {', '.join(competitors)}\n")

    # 构造示例功能矩阵
    feature_values = {
        "Notion": ["✅", "✅", "❌", "✅", "✅", "⚠️"],
        "Obsidian": ["✅", "❌", "✅", "❌", "⚠️", "❌"],
    }
    feature_matrix = pd.DataFrame({"功能": ["文档编辑", "数据库", "双向链接", "实时协作", "模板系统", "AI助手"]})
    for index, competitor in enumerate(competitors):
        feature_matrix[competitor] = feature_values.get(
            competitor, ["⚠️", "⚠️", "⚠️", "⚠️", "⚠️", "⚠️"]
        )

    # 构造示例分析结果
    default_pricing = {
        "Notion": "SaaS 订阅制",
        "Obsidian": "买断 + 捐赠",
    }
    pricing_models = {
        competitor: default_pricing.get(competitor, "订阅制（待核验）")
        for competitor in competitors
    }
    analysis_results = {
        "feature_matrix": feature_matrix,
        "pricing_analysis": {
            "pricing_models": pricing_models,
            "analysis": "；".join(f"{name}：{model}" for name, model in pricing_models.items())
        },
        "insights": [
            f"本次比较覆盖：{'、'.join(competitors)}。",
            "不同产品的功能覆盖、协作方式和定价模式存在差异，建议结合实际证据判断。",
            "演示数据不代表真实产品能力，正式决策前应使用真实模式复核。"
        ]
    }

    # 生成报告
    try:
        from agents.reporter import ReportAgent

        demo_output_dir = project_root / "reports" / "demo"
        reporter = ReportAgent(output_dir=str(demo_output_dir))
        report_path = reporter.generate(
            analysis_results=analysis_results,
            competitors=competitors,
            output_format=output_format
        )

        # 演示报告与真实报告物理隔离，并显式带 DEMO 标识。
        generated_path = Path(report_path)
        demo_path = generated_path.with_name(f"DEMO_{generated_path.name}")
        generated_path.replace(demo_path)
        demo_content = demo_path.read_text(encoding="utf-8")
        demo_path.write_text(
            "> ⚠️ 演示报告：以下内容为固定模拟数据，仅用于展示流程，不可用于业务决策。\n\n"
            + demo_content,
            encoding="utf-8",
        )
        return {
            "status": "success",
            "report_path": str(demo_path),
            "competitors": competitors,
            "errors": []
        }

    except Exception as e:
        logger.error(f"报告生成失败: {e}")
        return {
            "status": "error",
            "error": str(e)
        }


def extract_competitors_from_query(query: str) -> list:
    """从查询文本中识别已知的竞品名称"""

    known_competitors = [
        "Notion", "Obsidian", "Logseq", "Evernote", "OneNote",
        "Jira", "Linear", "Asana", "Trello",
        "Figma", "Sketch", "Adobe XD"
    ]

    found = []
    for comp in known_competitors:
        if comp.lower() in query.lower():
            found.append(comp)

    return found


def print_result(result: dict):
    """格式化打印分析结果"""

    print("\n" + "=" * 60)
    print("  运行结果")
    print("=" * 60)

    if result["status"] in {"success", "partial_success"}:
        if result["status"] == "partial_success":
            print("\n[部分完成] 报告已生成，但存在数据质量警告")
        else:
            print("\n[成功] 分析完成！")
        print(f"\n报告路径: {result['report_path']}")
        print(f"竞品: {', '.join(result['competitors'])}")

        if result.get("errors"):
            print("\n质量警告:")
            for warning in result["errors"]:
                print(f"  - {warning}")

        # 提示打开报告
        if os.name == 'nt':  # Windows
            open_cmd = "start"
        elif os.uname().sysname == 'Darwin':  # macOS
            open_cmd = "open"
        else:  # Linux
            open_cmd = "xdg-open"

        print(f"\n打开报告:")
        print(f"   {open_cmd} {result['report_path']}")

    else:
        print("\n[失败] 分析未成功完成")
        if "error" in result:
            print(f"错误信息: {result['error']}")

        if result.get("errors"):
            print("\n错误详情:")
            for err in result["errors"]:
                print(f"  - {err}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n[已取消] 用户中断，程序退出")
        sys.exit(130)
    except Exception as e:
        logger.error(f"致命错误: {e}", exc_info=True)
        print(f"\n[致命错误] : {e}")
        sys.exit(1)
