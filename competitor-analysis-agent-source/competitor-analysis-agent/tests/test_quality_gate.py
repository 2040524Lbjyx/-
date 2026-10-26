"""Analyzer 内置数据真实性闸门的无网络测试。"""

import pandas as pd
import pytest

from agents.analyzer import AnalysisAgent
from agents.crawler import DataCollectionAgent
from agents.reporter import ReportAgent


def _analyzer_without_llm():
    return AnalysisAgent.__new__(AnalysisAgent)


@pytest.mark.parametrize("extra", [{}, {"_field_evidence": {}}, {
    "_source": "crawl", "_evidence": [
        {"url": "https://example.com", "fields": ["page_access"]}
    ]
}])
def test_unattributed_fields_are_never_verified(extra):
    data = {"features": {"core": ["搜索"]}, "pricing": {"model": "订阅"},
            "changelog": {"latest_version": "1.0"}, **extra}
    item = _analyzer_without_llm().assess_data_quality({"A": data})["competitors"]["A"]
    assert item["status"] == "degraded"
    assert item["verified_feature_count"] == 0
    assert item["verified_pricing"] is False
    assert item["verified_changelog"] is False
    assert item["analysis_mode"] == "inference_only"


def test_field_evidence_does_not_verify_unrelated_fields():
    data = {"_source": "crawl", "features": {"core": ["搜索"], "advanced": ["AI"]},
            "pricing": {"model": "订阅"}, "changelog": {"latest_version": "1.0"},
            "_field_evidence": {"features.core": ["https://example.com/features"]}}
    item = _analyzer_without_llm().assess_data_quality({"A": data})["competitors"]["A"]
    assert item["verified_feature_count"] == 1
    assert item["verified_pricing"] is False
    assert item["verified_changelog"] is False


@pytest.mark.parametrize("api_data", [
    {"github_releases": {"releases": [{"tag_name": "v1"}]}},
    {"app_store": {"version": "1.0", "rating": 4.5}},
    {"_source": "llm_fallback", "app_store": {"version": "1.0", "_url": "https://apps.apple.com/app/id1"}},
])
def test_release_api_requires_source_and_must_not_be_llm(api_data):
    item = _analyzer_without_llm().assess_data_quality({"A": api_data})["competitors"]["A"]
    assert item["verified_changelog"] is False


def test_traceable_release_api_is_still_verified():
    item = _analyzer_without_llm().assess_data_quality({"A": {
        "_source": "crawl", "github_releases": {
            "releases": [{"tag_name": "v1"}], "_url": "https://github.com/acme/app/releases"
        }
    }})["competitors"]["A"]
    assert item["verified_changelog"] is True


def test_quality_gate_passes_traceable_crawl_data():
    analyzer = _analyzer_without_llm()
    report = analyzer.assess_data_quality({
        "ProductA": {
            "_source": "crawl",
            "website": "https://example.com",
            "features": {"core": ["搜索", "分享"], "advanced": []},
            "pricing": {"model": "免费增值", "plans": ["Free", "Pro"]},
            "changelog": {"recent_updates": ["新增搜索"]},
            "_evidence": [
                {"source": "official_web", "url": "https://example.com/features", "fields": ["features"]},
                {"source": "official_web", "url": "https://example.com/pricing", "fields": ["pricing"]},
                {"source": "official_web", "url": "https://example.com/changelog", "fields": ["changelog"]},
            ],
        }
    })

    item = report["competitors"]["ProductA"]
    assert item["status"] == "passed"
    assert item["verified_feature_count"] == 2
    assert item["verified_pricing"] is True
    assert item["verified_changelog"] is True
    assert item["evidence_count"] == 3


def test_quality_gate_downgrades_zero_feature_crawl():
    analyzer = _analyzer_without_llm()
    report = analyzer.assess_data_quality({
        "ProductB": {
            "_source": "crawl_partial",
            "website": "https://example.org",
            "features": {"core": [], "advanced": []},
            "pricing": {"model": None, "plans": []},
            "changelog": {},
            "crawled_pages": ["https://example.org"],
        }
    })

    item = report["competitors"]["ProductB"]
    assert item["status"] == "degraded"
    assert item["confidence"] == "low"
    assert item["verified_feature_count"] == 0
    assert "未提取到可验证的官网功能" in item["issues"]


def test_quality_gate_never_counts_llm_fields_as_verified():
    analyzer = _analyzer_without_llm()
    report = analyzer.assess_data_quality({
        "ProductC": {
            "_source": "llm_fallback",
            "features": {"core": ["AI 生成的功能"], "advanced": []},
            "pricing": {"model": "订阅", "plans": []},
            "changelog": {"recent_updates": ["AI 生成的更新"]},
        }
    })

    item = report["competitors"]["ProductC"]
    assert item["status"] == "degraded"
    assert item["analysis_mode"] == "inference_only"
    assert item["verified_feature_count"] == 0
    assert item["verified_pricing"] is False
    assert item["verified_changelog"] is False


def test_quality_gate_fails_empty_error_payload():
    analyzer = _analyzer_without_llm()
    report = analyzer.assess_data_quality({"Broken": {"_source": "error", "_error": "boom"}})
    assert report["competitors"]["Broken"]["status"] == "failed"
    assert report["summary"]["status"] == "failed"


def test_report_exposes_quality_warning_and_evidence_link(tmp_path):
    quality_report = {
        "summary": {"total": 1, "passed": 0, "degraded": 1, "failed": 0, "average_score": 5},
        "competitors": {
            "ProductB": {
                "status": "degraded",
                "score": 5,
                "confidence": "low",
                "verified_feature_count": 0,
                "evidence_count": 1,
                "issues": ["未提取到可验证的官网功能"],
                "evidence": [
                    {"source": "official_web", "url": "https://example.org/features", "fields": ["features"]}
                ],
            }
        },
    }
    matrix = pd.DataFrame([{"功能": "搜索", "ProductB": "✅"}])
    reporter = ReportAgent(template_dir="templates", output_dir=str(tmp_path))
    path = reporter.generate(
        analysis_results={
            "feature_matrix": matrix,
            "pricing_analysis": {},
            "insights": ["【推测】仅供参考"],
            "quality_report": quality_report,
            "analysis_metadata": {
                "feature_matrix": {
                    "source": "llm_fallback",
                    "confidence": "low",
                    "warning": "官网未提取到可验证功能，功能矩阵完全来自 LLM 推测，仅供参考。",
                }
            },
        },
        competitors=["ProductB"],
        output_format="markdown",
    )

    content = open(path, encoding="utf-8").read()
    assert "数据可信度" in content
    assert "⚠️ 降级" in content
    assert "功能矩阵完全来自 LLM 推测" in content
    assert "[official_web](https://example.org/features)" in content


def test_evidence_manifest_only_claims_page_access_for_crawled_urls():
    crawler = DataCollectionAgent.__new__(DataCollectionAgent)
    data = crawler._attach_evidence_manifest({
        "crawled_pages": ["https://example.com/features"],
        "app_store": {
            "_url": "https://apps.apple.com/cn/app/id1",
            "_reviews_url": "https://itunes.apple.com/reviews/id1",
        },
        "github_releases": {"_url": "https://github.com/acme/app/releases"},
    })

    assert data["_evidence"][0]["source"] == "official_web"
    assert data["_evidence"][0]["url"] == "https://example.com/features"
    assert data["_evidence"][0]["fields"] == ["page_access"]
    assert data["_evidence"][0]["captured_at"]
    assert len(data["_evidence"]) == 4
