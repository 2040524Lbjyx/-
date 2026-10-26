"""
Demo Script - 竞品分析多Agent系统工作流程演示
Compatible with Windows terminal (no emoji)
"""

from datetime import datetime


def demo_workflow():
    """演示完整的Agent工作流"""
    
    print("=" * 70)
    print("  Competitor Analysis Multi-Agent System - Workflow Demo")
    print("=" * 70)
    print()
    
    # 用户输入
    user_query = "Analyze Notion and Obsidian"
    print(f"[User] Input: {user_query}\n")
    
    # Step 1: Coordinator Agent - Understand Intent
    print("-" * 70)
    print("[Coordinator Agent] Step 1: Understanding User Intent")
    print("-" * 70)
    
    intent_result = {
        "competitors": ["Notion", "Obsidian"],
        "dimensions": ["features", "pricing"],
        "output_format": "markdown"
    }
    
    print(f"  -> Extracted competitors: {intent_result['competitors']}")
    print(f"  -> Analysis dimensions: {', '.join(intent_result['dimensions'])}")
    print()
    
    # Step 2: Coordinator Agent - Create Plan
    print("-" * 70)
    print("[Coordinator Agent] Step 2: Creating Analysis Plan")
    print("-" * 70)
    
    plan = [
        {"step": 1, "agent": "Crawler", "action": "Crawl Notion website"},
        {"step": 2, "agent": "Crawler", "action": "Crawl Obsidian website"},
        {"step": 3, "agent": "Analyzer", "action": "Feature comparison"},
        {"step": 4, "agent": "Analyzer", "action": "Pricing analysis"},
        {"step": 5, "agent": "Analyzer", "action": "Generate insights"},
        {"step": 6, "agent": "Reporter", "action": "Generate report"},
    ]
    
    for task in plan:
        print(f"  {task['step']}. {task['agent']:15s} - {task['action']}")
    
    print()
    
    # Step 3: Crawler Agent - Data Collection
    print("-" * 70)
    print("[Crawler Agent] Step 3: Data Collection")
    print("-" * 70)
    
    # Simulated crawl data
    crawled_data = {
        "Notion": {
            "name": "Notion",
            "website": "https://www.notion.so",
            "features": {
                "core": ["Document Editing", "Database", "Kanban View", "Calendar View"],
                "advanced": ["API", "Template Market", "AI Assistant"]
            },
            "pricing": {
                "model": "subscription",
                "plans": [
                    {"name": "Free", "price": 0, "period": "month"},
                    {"name": "Plus", "price": 10, "period": "month"},
                    {"name": "Business", "price": 18, "period": "month"}
                ]
            }
        },
        "Obsidian": {
            "name": "Obsidian",
            "website": "https://obsidian.md",
            "features": {
                "core": ["Document Editing", "Backlinks", "Tags", "Graph View"],
                "advanced": ["Plugins", "Publish", "Sync"]
            },
            "pricing": {
                "model": "one-time",
                "plans": [
                    {"name": "Personal", "price": 0, "period": "one-time"},
                    {"name": "Commercial", "price": 50, "period": "one-time"},
                    {"name": "Sync", "price": 10, "period": "month"},
                    {"name": "Publish", "price": 20, "period": "month"}
                ]
            }
        }
    }
    
    for comp_name, data in crawled_data.items():
        print(f"  [Success] {comp_name}:")
        print(f"      Website: {data['website']}")
        print(f"      Core features: {len(data['features']['core'])}")
        print(f"      Advanced features: {len(data['features']['advanced'])}")
        print(f"      Pricing plans: {len(data['pricing']['plans'])}")
    print()
    
    # Step 4: Analysis Agent - Feature Comparison
    print("-" * 70)
    print("[Analysis Agent] Step 4: Feature Comparison")
    print("-" * 70)
    
    # Generate feature comparison table
    all_features = []
    for comp_data in crawled_data.values():
        all_features.extend(comp_data["features"]["core"])
        all_features.extend(comp_data["features"]["advanced"])
    
    # Remove duplicates
    all_features = list(set(all_features))
    
    print("\n  Feature Comparison Matrix:")
    print("  " + "-" * 66)
    print(f"  {'Feature':<20} {'Notion':<20} {'Obsidian':<20}")
    print("  " + "-" * 66)
    
    for feature in all_features[:8]:  # Show first 8
        notion_has = "[Yes]" if (feature in crawled_data["Notion"]["features"]["core"] or 
                        feature in crawled_data["Notion"]["features"]["advanced"]) else "[No]"
        obsidian_has = "[Yes]" if (feature in crawled_data["Obsidian"]["features"]["core"] or 
                        feature in crawled_data["Obsidian"]["features"]["advanced"]) else "[No]"
        
        print(f"  {feature:<20} {notion_has:<20} {obsidian_has:<20}")
    
    print("  " + "-" * 66)
    print()
    
    # Step 5: Analysis Agent - Pricing Analysis
    print("-" * 70)
    print("[Analysis Agent] Step 5: Pricing Strategy Analysis")
    print("-" * 70)
    
    print("\n  Pricing Model Comparison:")
    for comp_name, data in crawled_data.items():
        model = data["pricing"]["model"]
        model_display = {"subscription": "Subscription", "one-time": "One-time"}.get(model, model)
        print(f"    {comp_name}: {model_display}")
    
    print("\n  Price Range:")
    for comp_name, data in crawled_data.items():
        prices = [p["price"] for p in data["pricing"]["plans"] if p["price"] > 0]
        if prices:
            min_price = min(prices)
            max_price = max(prices)
            print(f"    {comp_name}: ${min_price} - ${max_price}")
        else:
            print(f"    {comp_name}: Free")
    
    print()
    
    # Step 6: Analysis Agent - AI Insights
    print("-" * 70)
    print("[Analysis Agent] Step 6: Generating AI Insights")
    print("-" * 70)
    
    insights = [
        "Insight 1: Clear product positioning - Notion targets 'All-in-one' team collaboration, Obsidian focuses on personal knowledge management",
        "Insight 2: Pricing reflects business model - Notion uses SaaS subscription for recurring revenue, Obsidian uses one-time payment for word-of-mouth growth",
        "Insight 3: Feature trade-offs are strategic - Notion sacrifices offline for collaboration, Obsidian sacrifices real-time collaboration for privacy",
        "Insight 4: Market opportunity - Products between them have space (local-first + selective sync)",
        "Insight 5: Recommendation - If starting a business, focus on vertical scenarios (e.g., dev teams), combine both advantages"
    ]
    
    for i, insight in enumerate(insights, 1):
        print(f"\n  {insight}")
    
    print("\n")
    
    # Step 7: Report Agent - Generate Report
    print("-" * 70)
    print("[Report Agent] Step 7: Generating Analysis Report")
    print("-" * 70)
    
    report_filename = f"demo_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report_path = f"reports/{report_filename}"
    
    print(f"\n  [Success] Report generated: {report_path}")
    print(f"  [Success] Report includes:")
    print(f"     - Executive Summary")
    print(f"     - Feature Comparison Matrix")
    print(f"     - Pricing Analysis")
    print(f"     - AI Insights & Recommendations")
    print(f"     - Visualization Charts (3)")
    
    print("\n")
    
    # Summary
    print("=" * 70)
    print("  [Success] Analysis Complete!")
    print("=" * 70)
    print()
    print("Statistics:")
    print(f"  - Competitors analyzed: {len(crawled_data)}")
    print(f"  - Features compared: {len(all_features)}")
    print(f"  - Insights generated: {len(insights)}")
    print(f"  - Execution time: ~3 minutes (real) / ~30 seconds (demo)")
    print()
    print("Tip: To view the full report, open:")
    print(f"   {report_path}")
    print()


if __name__ == "__main__":
    try:
        demo_workflow()
    except KeyboardInterrupt:
        print("\n\n[Warning] Demo interrupted")
    except Exception as e:
        print(f"\n[Error] {e}")
        import traceback
        traceback.print_exc()
