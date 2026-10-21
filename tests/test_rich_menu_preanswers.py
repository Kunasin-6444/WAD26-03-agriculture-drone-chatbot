import unittest
from pathlib import Path

from app.services.ai_service import ask_ai
from app.services.rich_menu_service import (
    RICH_MENU_ITEMS,
    build_rich_menu_request,
    get_preanswers_dir,
    get_rich_menu_preanswer,
    load_rich_menu_preanswers,
)


class RichMenuPreanswersTests(unittest.TestCase):
    def test_preanswers_files_exist_and_load(self):
        preanswers_dir = get_preanswers_dir()
        self.assertTrue(preanswers_dir.exists())

        answers = load_rich_menu_preanswers(reload=True)
        self.assertEqual(len(answers), 6)
        for i in range(1, 7):
            self.assertIn(i, answers)
            self.assertGreater(len(answers[i]), 50, f"File {i}.txt is empty or too short")

    def test_all_six_rich_menu_triggers_return_expected_text(self):
        # 1. Drone registration
        ans1 = get_rich_menu_preanswer("ขึ้นทะเบียนโดรน")
        self.assertIsNotNone(ans1)
        self.assertIn("คู่มือการขึ้นทะเบียนโดรน", ans1)
        self.assertIn("uasportal.caat.or.th", ans1)

        # 2. Pilot registration
        ans2 = get_rich_menu_preanswer("ขึ้นทะเบียนนักบินโดรน")
        self.assertIsNotNone(ans2)
        self.assertIn("คู่มือการขึ้นทะเบียนผู้บังคับโดรน", ans2)

        # 3. Flight permission
        ans3 = get_rich_menu_preanswer("ขออนุญาตบินโดรน")
        self.assertIsNotNone(ans3)
        self.assertIn("คู่มือการขออนุญาตทำการบินโดรน", ans3)

        # 4. Air law
        ans4 = get_rich_menu_preanswer("กฎหมายการบินโดรน")
        self.assertIsNotNone(ans4)
        self.assertIn("คู่มือกฎหมายและข้อกำหนดการบินโดรนในประเทศไทย", ans4)

        # 5. Spraying & Nozzles
        ans5 = get_rich_menu_preanswer("โดรนฉีดพ่นและหัวฉีด")
        self.assertIsNotNone(ans5)
        self.assertIn("คู่มือโดรนฉีดพ่นทางการเกษตร", ans5)

        # 6. Herbicides
        ans6 = get_rich_menu_preanswer("การใช้สารกำจัดวัชพืช")
        self.assertIsNotNone(ans6)
        self.assertIn("คู่มือการใช้สารกำจัดวัชพืชอย่างปลอดภัย", ans6)

    def test_postback_aliases_return_expected_answers(self):
        for i in range(1, 7):
            postback_data = f"richmenu_{i}"
            ans = get_rich_menu_preanswer(postback_data)
            self.assertIsNotNone(ans, f"Failed for postback alias: {postback_data}")
            self.assertGreater(len(ans), 50)

    def test_non_rich_menu_query_returns_none(self):
        self.assertIsNone(get_rich_menu_preanswer("สภาพอากาศวันนี้เหมาะกับการบินไหม"))
        self.assertIsNone(get_rich_menu_preanswer("หัวฉีดแบบพัดส้มอัตราไหลเท่าไหร่"))
        self.assertIsNone(get_rich_menu_preanswer(""))
        self.assertIsNone(get_rich_menu_preanswer(None))

    def test_ask_ai_direct_call_returns_preanswer_fastpath(self):
        # Even when called directly, ask_ai returns pre-answers without invoking CRAG/LLM
        answer = ask_ai("ขึ้นทะเบียนโดรน")
        self.assertIn("คู่มือการขึ้นทะเบียนโดรน", answer)

    def test_build_rich_menu_request_has_six_valid_areas(self):
        req = build_rich_menu_request()
        self.assertEqual(req.size.width, 2500)
        self.assertEqual(req.size.height, 1686)
        self.assertEqual(len(req.areas), 6)

        # Verify area actions and bounds are valid
        for idx, area in enumerate(req.areas):
            self.assertEqual(area.action.type, "message")
            self.assertEqual(area.action.text, RICH_MENU_ITEMS[idx]["text"])
            self.assertGreater(area.bounds.width, 0)
            self.assertGreater(area.bounds.height, 0)


if __name__ == "__main__":
    unittest.main()
