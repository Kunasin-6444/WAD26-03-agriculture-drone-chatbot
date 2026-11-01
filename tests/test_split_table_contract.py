"""Replay the false rejections from the 2026-10-24 owner trial, without providers.

Fixture: the two extracted tables on UAV06 page 18, copied unchanged from
owner_trial_20261024/results.json. Tests assert document fidelity, not current
pesticide authorization or suitability for a crop age.
"""
from pathlib import Path
import unittest

from app.rag.evidence import Evidence
from app.rag.natural_answer import render


TABLES = Path(__file__).with_name('fixtures').joinpath('crop_table_split.txt').read_text(encoding='utf-8')


class SplitTableContract(unittest.TestCase):
    def result(self, text, content=TABLES):
        return render(text + ' [D5]', [Evidence('D5', content, 'UAV06.pdf', '18')])

    def test_mixture_in_second_table_is_not_a_single_substance_in_first(self):
        for text in (
            'เฮ็กซาซิโนน+ไดยูรอน 80-100+240 ควบคุมวัชพืชใบแคบและใบกว้าง',
            'เมทริบูซีน+2,4-D 320+240 ควบคุมวัชพืชใบแคบและใบกว้าง โดยเมทริบูซีน 320 และ 2,4-D 240',
        ):
            with self.subTest(text=text):
                self.assertEqual(self.result(text).dropped, [])
                self.assertIn(text, self.result(text).text)

    def test_warning_can_name_rows_in_different_tables_in_either_order(self):
        for text in (
            'ห้ามใช้พาราควอท 120-240 และแอทราซีน+พาราควอท 320-480+80 ตามสถานะในเอกสาร',
            'ห้ามใช้แอทราซีน+พาราควอท 320-480+80 และพาราควอท 120-240 ตามสถานะในเอกสาร',
        ):
            self.assertEqual(self.result(text).dropped, [])

    def test_another_rows_rate_or_weed_class_is_still_rejected(self):
        for text in (
            'เฮ็กซาซิโนน+ไดยูรอน 480-640 ควบคุมวัชพืชใบแคบและใบกว้าง',
            'เมทริบูซีน+2,4-D 480+240 ควบคุมวัชพืชใบแคบและใบกว้าง',
            'เฮ็กซาซิโนน+ไดยูรอน 80-100+240 ควบคุมเฉพาะวัชพืชใบแคบ',
            'ห้ามใช้พาราควอท 320-480 และแอทราซีน+พาราควอท 120-240+80 ตามสถานะในเอกสาร',
        ):
            with self.subTest(text=text):
                self.assertTrue(self.result(text).dropped)
                self.assertEqual(self.result(text).lines, [])

    def test_generic_rows_keep_their_own_values_across_tables(self):
        content = 'อุปกรณ์ | ปริมาณ (ml)\nปั๊มอัลฟา | 250\nปั๊มเบตา | 500\n\nอุปกรณ์ | ปริมาณ (ml)\nปั๊มแกมมา | 700\nปั๊มเดลตา | 250'
        self.assertEqual(self.result('ปั๊มอัลฟา 250 ml และปั๊มแกมมา 700 ml', content).dropped, [])
        self.assertTrue(self.result('ปั๊มอัลฟา 500 ml และปั๊มแกมมา 250 ml', content).dropped)

    def test_repeated_label_does_not_skip_the_first_tables_checks(self):
        content = 'อุปกรณ์ | ปริมาณ (ml)\nปั๊มอัลฟา | 250\nปั๊มเบตา | 500\n\nอุปกรณ์ | ปริมาณ (ml)\nปั๊มอัลฟา | 500\nปั๊มแกมมา | 700'
        self.assertTrue(self.result('ปั๊มอัลฟา 500 ml', content).dropped)
