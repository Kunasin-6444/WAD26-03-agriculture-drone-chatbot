"""Independent questions, evidence-checked answers, and preservation of partial KB facts."""
import json
import os
import unittest
from unittest.mock import patch

from app.rag import natural_answer as na
from app.rag.crag_service import CragResponse, run_crag_pipeline
from app.rag.evidence import Evidence
from app.rag.intent_router import route_intent
from app.rag.query_normalizer import normalize_query
from app.rag.web_fallback import WebSearchResult
from app.services import ai_service
from tests.helpers import llm_client

KB = Evidence('D1', 'หัวฉีดพัดส้มไหล 500 ml/หัวฉีด', 'nozzles.pdf', '4')
WEB = WebSearchResult('ราคาหัวฉีด', 'https://doa.go.th/nozzles/price', 'หัวฉีดพัดส้มราคา 120 บาท', .9)


class IndependentQuestions(unittest.TestCase):
    def test_a_new_short_question_does_not_inherit_the_previous_crop(self):
        def answer(query, **kwargs):
            text = kwargs.get('previous_question') or query
            return CragResponse(text, 'knowledge_base', 'CORRECT', '')

        with patch.dict(os.environ, {'ANSWER_CACHE_TTL_SECONDS': '0'}), \
             patch.object(ai_service, 'run_crag_pipeline', side_effect=answer):
            ai_service.ask_ai('ขอข้อมูลการฉีดพ่นสารกำจัดวัชพืชในไร่อ้อยอย่างละเอียด', 'user-A')
            self.assertEqual(ai_service.ask_ai('แบตเท่าไหร่ห้ามบิน', 'user-A'), 'แบตเท่าไหร่ห้ามบิน')
            self.assertEqual(ai_service.ask_ai('แบตเท่าไหร่ห้ามบิน', 'user-B'), 'แบตเท่าไหร่ห้ามบิน')
            self.assertEqual(ai_service.ask_ai('ช่วงเวลานี้ฉีดพ่นสารอะไรได้บ้าง', 'user-A'),
                             'ช่วงเวลานี้ฉีดพ่นสารอะไรได้บ้าง')

    def test_equipment_usage_is_not_bot_help(self):
        for query in ('หัวฉีดแบบพัดใช้งานยังไง', 'โดรนสำรวจใช้งานอย่างไร'):
            self.assertEqual(route_intent(query).intent, 'document_qa')
        for query in ('ใช้งานยังไง', 'บอตนี้ใช้งานอย่างไร', 'แนะนำวิธีพิมพ์คำถามเพื่อขอข้อมูลโดรนเกษตร'):
            self.assertEqual(route_intent(query).intent, 'bot_usage')

    def test_soil_herbicide_question_does_not_acquire_mulching_meaning(self):
        query = 'ต้องฉีดพ่นคุมดินต้องฉีดด้วยหัวฉีดอะไร'
        self.assertEqual(normalize_query(query), query)
        # Actual covering questions retain the owner's word as well.
        self.assertEqual(normalize_query('ใช้พลาสติกคลุมดินอย่างไร'), 'ใช้พลาสติกคลุมดินอย่างไร')
        client = llm_client('NOT_FOUND')
        with patch.dict(os.environ, {'ANSWER_MODE': 'natural'}), \
             patch('app.rag.crag_service.retrieve_evidence', return_value=[]), \
             patch('app.rag.crag_service.search_web_fallback', return_value=[]) as search:
            run_crag_pipeline(query, client=client)
        self.assertTrue(search.called)
        self.assertIn('คุมดิน', search.call_args.args[0])
        self.assertNotIn('คลุมดิน', search.call_args.args[0])

    def test_a_flow_question_is_not_replaced_with_a_menu_guide_without_flow_values(self):
        query = 'แนะนำการเลือกใช้หัวฉีดโดรนเกษตรและอัตราการไหล'
        with patch.object(ai_service, 'run_crag_pipeline', return_value=CragResponse(
                'หัวฉีดพัดส้ม 500 ml/หัวฉีด [1]', 'knowledge_base', 'CORRECT', '')) as run:
            answer = ai_service.ask_ai(query)
        self.assertIn('500 ml', answer)
        self.assertEqual(run.call_args.args[0], query)
        with patch.object(ai_service, 'run_crag_pipeline', side_effect=AssertionError('Menu should stay local')):
            self.assertIn('คู่มือโดรนฉีดพ่น', ai_service.ask_ai('richmenu_5'))

    def test_only_the_current_question_reaches_retrieval_and_generation(self):
        client = llm_client('หัวฉีดพัดส้มไหล 500 ml/หัวฉีด [D1]')
        with patch.dict(os.environ, {'ANSWER_MODE': 'natural'}), \
             patch('app.rag.crag_service.retrieve_evidence', return_value=[KB]) as retrieve, \
             patch('app.rag.crag_service.search_web_fallback', return_value=[]):
            response = run_crag_pipeline('หัวฉีดพัดส้มไหลเท่าไร', client=client)
        self.assertIn('500 ml', response.answer)
        self.assertEqual(retrieve.call_count, 1)
        self.assertEqual(retrieve.call_args.args[0], 'หัวฉีดพัดส้มไหลเท่าไร')
        payload = json.loads(client.chat.completions.create.call_args.kwargs['messages'][1]['content'])
        self.assertEqual(payload['question'], 'หัวฉีดพัดส้มไหลเท่าไร')
        self.assertNotIn('previous_question', payload)


class NoClarificationBypass(unittest.TestCase):
    def test_equivalent_baht_notation_passes_but_wrong_amounts_and_units_do_not(self):
        source = Evidence('W1', 'วงเงินคุ้มครองไม่น้อยกว่า 3.5 ล้านบาท', url='https://caat.or.th/example')
        valid = na.render('วงเงินคุ้มครองไม่น้อยกว่า 3,500,000 บาท [W1]', [source])
        self.assertIn('3,500,000 บาท', valid.text)
        for wrong in ('3.5 บาท', '350,000 บาท', '4 ล้านบาท', '3,500,000 กิโลกรัม'):
            with self.subTest(wrong=wrong):
                self.assertEqual(na.render('วงเงินคุ้มครองไม่น้อยกว่า ' + wrong + ' [W1]', [source]).text, '')

    def test_a_legacy_question_back_is_not_an_answer_even_with_a_valid_citation(self):
        for raw in ('ถามกลับ: หมายถึงหัวฉีดหรือเครื่องพ่น',
                    'ถามกลับ: หมายถึงหัวฉีดพัดส้มไหล 500 ml/หัวฉีด [D1]'):
            answer = na.render(raw, [KB])
            self.assertEqual(answer.text, '')
            self.assertTrue(answer.dropped)

    def test_fact_checks_still_reject_wrong_values_and_keep_valid_facts(self):
        answer = na.render('หัวฉีดพัดส้มไหล 900 ml/หัวฉีด [D1]\nหัวฉีดพัดส้มไหล 500 ml/หัวฉีด [D1]', [KB])
        self.assertNotIn('900', answer.text)
        self.assertIn('500 ml', answer.text)
        self.assertEqual(len(answer.dropped), 1)

    def test_a_question_back_does_not_trigger_an_unrelated_web_retry(self):
        with patch.dict(os.environ, {'ANSWER_MODE': 'natural'}), \
             patch('app.rag.crag_service.retrieve_evidence', return_value=[KB]), \
             patch('app.rag.crag_service.search_web_fallback', return_value=[]) as web:
            result = run_crag_pipeline('ข้อมูลหัวฉีด', client=llm_client('ถามกลับ: หัวฉีดหรือเครื่องพ่น'))
        self.assertEqual(result.source_type, 'abstain')
        self.assertNotIn('ถามกลับ', result.answer)
        web.assert_not_called()


class PartialKnowledgeAndWeb(unittest.TestCase):
    def setUp(self):
        for item in (patch.dict(os.environ, {'ANSWER_MODE': 'natural'}),
                     patch('app.rag.crag_service.retrieve_evidence', return_value=[KB])):
            item.start()
            self.addCleanup(item.stop)

    def run_partial(self, second):
        with patch('app.rag.crag_service.search_web_fallback', return_value=[WEB]) as search:
            client = llm_client('หัวฉีดพัดส้มไหล 500 ml/หัวฉีด [D1]\nยังไม่พบข้อมูล: ราคา', second)
            result = run_crag_pipeline('พัดส้มไหลเท่าไรและราคาเท่าไร', client=client)
        self.assertEqual(search.call_count, 1)
        self.assertIn('ราคา', search.call_args.args[0])
        return result

    def test_partial_kb_is_preserved_when_web_only_answers_the_missing_part(self):
        result = self.run_partial('หัวฉีดพัดส้มราคา 120 บาท [W1]')
        self.assertEqual(result.source_type, 'hybrid')
        self.assertIn('500 ml', result.answer)
        self.assertIn('120 บาท', result.answer)
        self.assertIn('nozzles.pdf, หน้า 4', result.answer)
        self.assertIn(WEB.url, result.answer)
        self.assertNotIn('ยังยืนยันไม่ได้', result.answer)

    def test_web_abstention_keeps_kb_and_its_explicit_gap(self):
        result = self.run_partial('NOT_FOUND')
        self.assertEqual(result.source_type, 'knowledge_base')
        self.assertIn('500 ml', result.answer)
        self.assertIn('ยังยืนยันไม่ได้: ราคา', result.answer)
        self.assertEqual(result.grade, 'AMBIGUOUS')

    def test_wrong_web_value_is_rejected_without_losing_kb(self):
        result = self.run_partial('หัวฉีดพัดส้มราคา 900 บาท [W1]')
        self.assertIn('500 ml', result.answer)
        self.assertNotIn('900', result.answer)
        self.assertIn('ยังยืนยันไม่ได้', result.answer)

    def test_web_model_failure_keeps_kb_and_reports_service_problem(self):
        with patch('app.rag.crag_service.search_web_fallback', return_value=[WEB]), \
             patch('app.rag.crag_service.call_llm', side_effect=[
                 'หัวฉีดพัดส้มไหล 500 ml/หัวฉีด [D1]\nยังไม่พบข้อมูล: ราคา', TimeoutError()]):
            result = run_crag_pipeline('พัดส้มไหลเท่าไรและราคาเท่าไร')
        self.assertIn('500 ml', result.answer)
        self.assertIn('หมดเวลา', result.answer)
        self.assertIn('ยังยืนยันไม่ได้: ราคา', result.answer)
        self.assertEqual(result.source_type, 'knowledge_base')

    def test_complete_kb_does_not_spend_a_web_request(self):
        with patch('app.rag.crag_service.search_web_fallback') as web:
            result = run_crag_pipeline('พัดส้มไหลเท่าไร', client=llm_client('หัวฉีดพัดส้มไหล 500 ml/หัวฉีด [D1]'))
        self.assertEqual(result.source_type, 'knowledge_base')
        web.assert_not_called()

    def test_web_only_answer_keeps_the_exact_url(self):
        result = self.run_partial('หัวฉีดพัดส้มราคา 120 บาท [W1]')
        self.assertIn(WEB.url, result.answer)
        with patch('app.rag.crag_service.retrieve_evidence', return_value=[]), \
             patch('app.rag.crag_service.search_web_fallback', return_value=[WEB]):
            result = run_crag_pipeline('หัวฉีดราคาเท่าไร', client=llm_client('หัวฉีดพัดส้มราคา 120 บาท [W1]'))
        self.assertEqual(result.source_type, 'web_fallback')
        self.assertIn(WEB.url, result.answer)
        self.assertNotIn('nozzles.pdf', result.answer)
