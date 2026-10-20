"""Protect the evidence boundary and missing-input behavior."""

import unittest

from stresslens.evidence import SOURCES, build_summary, search_evidence


class EvidenceSearchTests(unittest.TestCase):
    def test_retrieval_returns_relevant_source_and_provenance(self):
        result = search_evidence("Dreaddit Reddit", limit=1)
        self.assertEqual(result[0]["id"], "dreaddit-2019")
        self.assertTrue(result[0]["url"].startswith("https://aclanthology.org/"))
        self.assertGreater(result[0]["score"], 0)

    def test_irrelevant_query_does_not_get_fallback_evidence(self):
        self.assertEqual(search_evidence("how to bake pizza with mozzarella"), [])
        self.assertEqual(search_evidence(""), [])
        self.assertEqual(search_evidence("what is it"), [])

    def test_retrieval_copies_records_and_respects_limit(self):
        self.assertEqual(search_evidence("stress", limit=0), [])
        results = search_evidence("stress", limit=2)
        self.assertEqual(len(results), 2)
        results[0]["summary"] = "Changed by a caller"
        self.assertFalse(any(source["summary"] == "Changed by a caller" for source in SOURCES))
        self.assertFalse(any("score" in source for source in SOURCES))


class SummaryTests(unittest.TestCase):
    def test_missing_inputs_are_explicit(self):
        summary = build_summary(None, None, None)
        self.assertIn("No self-reported", summary)
        self.assertIn("No text analysis", summary)
        self.assertIn("No face analysis", summary)
        self.assertIn("no validated combined stress score", summary)

    def test_zero_is_a_valid_self_report(self):
        summary = build_summary(None, None, 0)
        self.assertIn("0/10", summary)
        self.assertNotIn("No self-reported", summary)

    def test_no_face_does_not_become_low_stress(self):
        for status in ("no_face", "ok"):
            with self.subTest(status=status):
                summary = build_summary(None, {
                    "status": status, "mode": "image", "frames_analyzed": 1,
                    "face_frames": 0, "features": {},
                }, None)
                self.assertIn("No detectable face", summary)
                self.assertNotIn("low stress", summary.lower())

    def test_high_face_coefficients_do_not_infer_stress(self):
        summary = build_summary(None, {
            "status": "ok", "mode": "video", "frames_analyzed": 10,
            "face_frames": 8, "features": {"browDownLeft": 0.99},
        }, 3)
        self.assertIn("8 of 10 analyzed frames", summary)
        self.assertIn("do not determine your stress level", summary)
        self.assertNotIn("99%", summary)

    def test_text_score_is_uncalibrated_and_not_fused(self):
        summary = build_summary({
            "status": "ok", "label": "stress", "stress_probability": 0.92,
        }, None, 0)
        self.assertIn("uncalibrated stress-class score is 0.920", summary)
        self.assertIn("self-reported stress is 0/10", summary)
        self.assertIn("not your psychological stress level", summary)

    def test_unavailable_analysis_and_invalid_values_are_not_reported_as_results(self):
        summary = build_summary({"status": "error", "stress_probability": 0.99},
                                {"status": "error"}, 11)
        self.assertIn("Text analysis was unavailable", summary)
        self.assertIn("Face analysis was unavailable", summary)
        self.assertIn("rating is invalid", summary)
        self.assertNotIn("0.990", summary)
        for score in (float("nan"), float("inf"), -0.5, 1.5, True):
            with self.subTest(score=score):
                self.assertNotIn("score is", build_summary(
                    {"status": "ok", "label": "stress", "stress_probability": score},
                    None, None))


if __name__ == "__main__":
    unittest.main()
