import unittest


class RuntimeGuardTests(unittest.TestCase):
    def test_classifies_windows_socket_permission_failure(self):
        from utils.runtime_health import classify_connection_error

        self.assertEqual(
            classify_connection_error(
                'HTTPSConnectionPool(host="example.com"): WinError 10013'
            ),
            "network_blocked",
        )

    def test_blocks_report_when_no_verified_evidence_exists(self):
        from utils.runtime_health import should_block_report

        self.assertTrue(
            should_block_report(
                {
                    "summary": {"passed": 0, "degraded": 2, "failed": 0},
                    "competitors": {
                        "A": {"verified_feature_count": 0, "verified_pricing": False, "evidence_count": 0},
                        "B": {"verified_feature_count": 0, "verified_pricing": False, "evidence_count": 0},
                    },
                },
                {"feature_matrix": {"source": "llm_fallback"}, "pricing": {"source": "llm_fallback"}},
            )
        )

    def test_keeps_report_when_at_least_one_competitor_has_verified_evidence(self):
        from utils.runtime_health import should_block_report

        self.assertFalse(
            should_block_report(
                {
                    "summary": {"passed": 1, "degraded": 1, "failed": 0},
                    "competitors": {
                        "A": {"verified_feature_count": 2, "verified_pricing": True, "evidence_count": 2},
                        "B": {"verified_feature_count": 0, "verified_pricing": False, "evidence_count": 0},
                    },
                },
                {"feature_matrix": {"source": "verified"}, "pricing": {"source": "verified"}},
            )
        )

    def test_vector_metadata_contains_only_chroma_scalar_values(self):
        from vector_store import CompetitorVectorStore

        store = CompetitorVectorStore.__new__(CompetitorVectorStore)
        metadata = store._extract_metadata({
            "name": "A",
            "website": "https://example.com",
            "pricing": {"model": None},
            "features": {"core": ["搜索"]},
            "company_info": {"founded": "unknown"},
        })
        self.assertNotIn(None, metadata.values())
        self.assertTrue(all(isinstance(value, (str, int, float, bool)) for value in metadata.values()))


if __name__ == "__main__":
    unittest.main()
