"""
Automated End-to-End Real-World Evaluation Test Suite
===================================================
Tests real customer scenarios against the live CRAG pipeline without mocks or hardcoding.
Verifies:
1. Strict Grounded RAG across the entire knowledge base (UAV06 to UAV12).
2. Rule R1 CAAT flight regulation routing and citations.
3. Live Web search fallback with URL citations and latency <= 12.0 seconds.
4. Informative, non-terse answers with clean LINE layout (bullet points, bottom citations, no raw Markdown).
5. Clean zero-hallucination abstain on out-of-scope/unrealistic queries.
"""
from __future__ import annotations

import time
import unittest

from app.rag.crag_service import run_crag_pipeline
from app.rag.web_fallback import CAAT_PORTAL_INFOGRAPHIC_URL


class TestRealUserScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print("\n" + "=" * 70)
        print("STARTING LIVE REAL-WORLD PIPELINE & LATENCY EVALUATION")
        print("=" * 70)

    def test_scenario_1_nozzle_specs_and_comparison_rag(self):
        """
        Customer scenario: Inquiring about nozzle options and differences for spraying drones.
        Knowledge source: UAV06 / UAV07.
        """
        query = "หัวฉีดพัดส้มกับพัดฟ้าต่างกันอย่างไร"
        t0 = time.time()
        res = run_crag_pipeline(query)
        latency = time.time() - t0

        print(f"\n[Scenario 1: Nozzle Specs] Latency: {latency:.2f}s | Source: {res.source_type}")
        print(f"Answer snippet:\n{res.answer}")

        # 1. Verification of RAG retrieval
        self.assertEqual(res.source_type, "knowledge_base", "Must retrieve from internal Knowledge Base")
        self.assertIn("พัดส้ม", res.answer, "Must contain orange fan nozzle")
        self.assertTrue(
            "พัดฟ้า" in res.answer or "พัดน้ำเงิน" in res.answer,
            "Must recognize colloquial blue fan / official blue fan nozzle",
        )
        self.assertTrue(
            "UAV06" in res.answer or "UAV07" in res.answer,
            "Must cite source document UAV06 or UAV07",
        )
        self.assertIn("แหล่งอ้างอิง", res.answer, "Must include bottom citation")

        # 2. Informative layout (not terse, structured with bullets or dashes, no raw markdown)
        self.assertGreater(len(res.answer), 100, "Answer must be informative and complete, not terse")
        self.assertTrue(
            "• " in res.answer or "- " in res.answer or "1." in res.answer,
            "Must format with bullets or list items for readability",
        )
        self.assertNotIn("**", res.answer, "Must not contain raw Markdown bold markers")
        self.assertNotIn("###", res.answer, "Must not contain raw Markdown headers")

        # 3. Latency constraint for internal KB RAG
        self.assertLessEqual(latency, 10.0, "Internal KB RAG should answer within 10.0s")

    def test_scenario_2_weed_control_herbicides_rag(self):
        """
        Customer scenario: Advice on chemical weed control and spraying precautions with drones.
        Knowledge source: UAV08 / UAV09.
        """
        query = "การใช้สารกำจัดวัชพืชและการพ่นด้วยโดรนในแปลงเกษตรมีข้อควรระวังอย่างไร"
        t0 = time.time()
        res = run_crag_pipeline(query)
        latency = time.time() - t0

        print(f"\n[Scenario 2: Weed Control] Latency: {latency:.2f}s | Source: {res.source_type}")
        print(f"Answer snippet:\n{res.answer}")

        # 1. Verification of RAG retrieval
        self.assertEqual(res.source_type, "knowledge_base", "Must retrieve from internal Knowledge Base")
        self.assertTrue(
            "UAV08" in res.answer or "UAV09" in res.answer or "UAV06" in res.answer,
            "Must cite source document UAV08, UAV09, or UAV06",
        )
        self.assertIn("แหล่งอ้างอิง", res.answer, "Must include bottom citation")

        # 2. Informative layout (not terse, structured with bullets or dashes)
        self.assertGreater(len(res.answer), 100, "Answer must provide actionable advice, not blunt cutoff")
        self.assertTrue("• " in res.answer or "- " in res.answer or "1." in res.answer, "Must format with list items")
        self.assertNotIn("**", res.answer, "Must not contain raw Markdown")

        # 3. Latency constraint
        self.assertLessEqual(latency, 10.0, "Internal KB RAG should answer within 10.0s")

    def test_scenario_3_aerial_survey_flight_settings_rag(self):
        """
        Customer scenario: Settings for drone aerial survey, photo overlap, and GSD resolution.
        Knowledge source: UAV10 / UAV12.
        """
        query = "การตั้งค่าการบินโดรนสำรวจเพื่อให้ภาพถ่ายมีคุณภาพและค่า GSD ที่ดีต้องทำอย่างไร"
        t0 = time.time()
        res = run_crag_pipeline(query)
        latency = time.time() - t0

        print(f"\n[Scenario 3: Aerial Survey Settings] Latency: {latency:.2f}s | Source: {res.source_type}")
        print(f"Answer snippet:\n{res.answer}")

        # 1. Verification of RAG retrieval
        self.assertEqual(res.source_type, "knowledge_base", "Must retrieve from internal Knowledge Base")
        self.assertTrue(
            "UAV10" in res.answer or "UAV11" in res.answer or "UAV12" in res.answer,
            "Must cite source document UAV10, UAV11, or UAV12",
        )
        self.assertIn("แหล่งอ้างอิง", res.answer, "Must include bottom citation")

        # 2. Informative layout
        self.assertGreater(len(res.answer), 100, "Answer must be informative and practical")
        self.assertTrue("• " in res.answer or "- " in res.answer or "1." in res.answer, "Must format with list items")
        self.assertNotIn("**", res.answer, "Must not contain raw Markdown")

        # 3. Latency constraint
        self.assertLessEqual(latency, 10.0, "Internal KB RAG should answer within 10.0s")

    def test_scenario_4_caat_air_law_and_flight_permit(self):
        """
        Customer scenario: Flying a drone at Khon Kaen University or legal registration workflow.
        Knowledge source: Rule R1 CAAT UAS Portal Infographic.
        """
        query = "อยากบินโดรนที่สวนเกษตร มข. ต้องขออนุญาตและมีเงื่อนไขอย่างไร"
        t0 = time.time()
        res = run_crag_pipeline(query)
        latency = time.time() - t0

        print(f"\n[Scenario 4: CAAT Legal Rules] Latency: {latency:.2f}s | Source: {res.source_type}")
        print(f"Answer snippet:\n{res.answer}")

        # 1. Verification of CAAT routing
        self.assertIn(
            res.source_type,
            ("caat_portal", "web_fallback"),
            "Must route to CAAT portal or verified web fallback",
        )
        self.assertIn(
            CAAT_PORTAL_INFOGRAPHIC_URL,
            res.answer,
            f"Must cite official CAAT URL: {CAAT_PORTAL_INFOGRAPHIC_URL}",
        )

        # 2. Informative and helpful response (explaining registration, insurance, permits)
        self.assertGreater(len(res.answer), 150, "Must provide detailed, helpful guidance to the user")
        self.assertTrue("• " in res.answer or "- " in res.answer or "1." in res.answer, "Must use list items or steps")
        self.assertNotIn("**", res.answer, "Must not contain raw Markdown")

        # 3. Latency constraint (<= 12.0s per requirement)
        self.assertLessEqual(latency, 12.0, "CAAT/Web fallback latency must not exceed 12.0s")

    def test_scenario_5_live_web_search_fallback_latency_under_12s(self):
        """
        Customer scenario: Inquiring about current agricultural diesel prices or DOA guidelines.
        Knowledge source: Live Tavily Web Search.
        Acceptance criteria:
        - Latency <= 12.0s
        - Factually grounded from live web sources with URL citation
        - Informative and useful (not terse)
        """
        query = "มาตรการหรือระเบียบการสนับสนุนโดรนเกษตรจากกรมวิชาการเกษตร"
        t0 = time.time()
        res = run_crag_pipeline(query)
        latency = time.time() - t0

        print(f"\n[Scenario 5: Live Web Fallback] Latency: {latency:.2f}s | Source: {res.source_type}")
        print(f"Answer snippet:\n{res.answer}")

        # 1. Verification of Web fallback
        self.assertEqual(res.source_type, "web_fallback", "Must route to Web Fallback")
        self.assertTrue(
            "http://" in res.answer or "https://" in res.answer,
            "Must contain official web URL citation",
        )
        self.assertIn("แหล่งอ้างอิง", res.answer, "Must isolate citation at bottom")

        # 2. Informative, useful content
        self.assertGreater(len(res.answer), 100, "Web grounded answer must be informative and complete")
        self.assertTrue("• " in res.answer or "- " in res.answer or "1." in res.answer, "Must format with list items")
        self.assertNotIn("**", res.answer, "Must not contain raw Markdown")

        # 3. Critical user requirement: Latency must NOT exceed 12.0 seconds!
        self.assertLessEqual(
            latency,
            12.0,
            f"Web search fallback latency ({latency:.2f}s) MUST NOT exceed 12.0 seconds!",
        )

    def test_scenario_6_unrealistic_hallucination_trap_abstains(self):
        """
        Customer scenario: Impossible or hallucination-trap query.
        System must abstain politely without guessing or fabricating citations.
        """
        query = "โดรนเกษตรดำน้ำไปฉีดปุ๋ยใต้ทะเลลึกได้ไหม"
        t0 = time.time()
        res = run_crag_pipeline(query)
        latency = time.time() - t0

        print(f"\n[Scenario 6: Hallucination Trap] Latency: {latency:.2f}s | Source: {res.source_type}")
        print(f"Answer snippet:\n{res.answer}")

        # 1. Verification of strict abstain
        self.assertEqual(res.source_type, "abstain", "Must abstain on impossible questions")
        self.assertIn("ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้", res.answer)

        # 2. Latency constraint (<= 12.0s per requirement)
        self.assertLessEqual(latency, 12.0, "Abstain decisions should complete within 12.0s")


if __name__ == "__main__":
    unittest.main()
