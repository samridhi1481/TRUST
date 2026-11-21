import unittest

from backend.app.services.member4_detection import Member4DetectionEngine


class Member4DetectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_bundled_model_returns_prediction_and_separate_priority_score(self) -> None:
        event = {
            "event_id": "EVT-BACKEND-TEST",
            "event_type": "network_connection",
            "event_time": "2026-11-20T10:00:00Z",
            "severity": "medium",
            "evidence_status": "observed",
            "is_synthetic": True,
            "source_entity_id": "HOST-001",
            "source_system": "TRUSTRAIL_SYNTHETIC_SIMULATOR",
            "timestamp_semantics": "iso8601",
        }

        result = (await Member4DetectionEngine().predict_events([event]))[0]

        self.assertEqual(result["event_id"], event["event_id"])
        self.assertIn(result["prediction"], {"0", "1"})
        self.assertGreaterEqual(result["risk_score"], 0)
        self.assertLessEqual(result["risk_score"], 100)
        self.assertGreaterEqual(result["confidence"], 0)
        self.assertLessEqual(result["confidence"], 1)
        self.assertIn(result["risk_level"], {"low", "medium", "high", "critical"})
        self.assertEqual(result["model_confidence_percent"], round(result["confidence"] * 100))
