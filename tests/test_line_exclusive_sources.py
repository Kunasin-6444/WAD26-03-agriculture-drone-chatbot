"""LINE must send evidence from exactly one selected source per answer."""
import json
import os
from unittest.mock import patch

import pytest

from app.rag import exclusive_pipeline as exclusive
from app.rag.evidence import Evidence, parse_grounded_result
from app.services import ai_service
from tests.helpers import result_json


KB = Evidence('D1', 'Pump 250 ml', 'manual.pdf', '1')
WEB = Evidence('W1', 'Pump 300 ml', url='https://example.org/pump')


@pytest.mark.parametrize('mode', ['grounded', 'natural'])
@pytest.mark.parametrize('question,expected_source', [
    ('Pump rate?', 'knowledge_base'),
    ('ค้นเว็บ Pump rate ล่าสุด', 'web_fallback'),
])
def test_line_selects_one_source_without_mixing(mode, question, expected_source):
    chosen = KB if expected_source == 'knowledge_base' else WEB
    value = '250' if chosen is KB else '300'
    sid = chosen.id
    checked = parse_grounded_result(result_json(claims=[(f'Pump {value} ml', sid, chosen.content)]), [chosen])
    with patch.dict(os.environ, {'ANSWER_MODE': mode, 'ANSWER_CACHE_TTL_SECONDS': '0'}), \
         patch.object(exclusive.legacy, 'llm_pool_error', return_value=''), \
         patch.object(exclusive.legacy, 'retrieve_evidence', return_value=[KB, WEB]) as kb, \
         patch.object(exclusive.legacy, 'search_web_fallback', return_value=['result']) as web, \
         patch.object(exclusive.legacy, 'web_evidence', return_value=[WEB, KB]), \
         patch.object(exclusive.legacy, 'evaluate_evidence', return_value=checked) as grounded, \
         patch.object(exclusive.legacy, 'call_llm', return_value=f'Pump {value} ml [{sid}]') as natural:
        response = exclusive.run_exclusive_pipeline(question)
    assert response.source_type == expected_source, response.grade_reason
    assert kb.call_count == (expected_source == 'knowledge_base')
    assert web.call_count == (expected_source == 'web_fallback')
    if mode == 'grounded':
        assert grounded.call_args.args[1] == [chosen]
        natural.assert_not_called()
    else:
        assert chosen.content in natural.call_args.args[0][1]['content']
        assert (WEB.content if chosen is KB else KB.content) not in natural.call_args.args[0][1]['content']
        grounded.assert_not_called()


def test_partial_kb_answer_returns_kb_without_merging_web():
    partial = parse_grounded_result(result_json(status='partial', claims=[('Pump 250 ml', 'D1', KB.content)], missing=['x']), [KB])
    with patch.dict(os.environ, {'ANSWER_MODE': 'grounded'}), \
         patch.object(exclusive.legacy, 'llm_pool_error', return_value=''), \
         patch.object(exclusive.legacy, 'retrieve_evidence', return_value=[KB]), \
         patch.object(exclusive.legacy, 'search_web_fallback') as web, \
         patch.object(exclusive.legacy, 'evaluate_evidence', return_value=partial):
        result = exclusive.run_exclusive_pipeline('Pump rate?')
    web.assert_not_called()
    assert result.source_type == 'knowledge_base'


def test_kb_not_found_falls_back_to_web_exclusively_without_mixing_kb():
    with patch.dict(os.environ, {'ANSWER_MODE': 'natural'}), \
         patch.object(exclusive.legacy, 'llm_pool_error', return_value=''), \
         patch.object(exclusive.legacy, 'retrieve_evidence', return_value=[KB]), \
         patch.object(exclusive.legacy, 'search_web_fallback', return_value=['result']) as web, \
         patch.object(exclusive.legacy, 'web_evidence', return_value=[WEB]), \
         patch.object(exclusive.legacy, 'call_llm', side_effect=['NOT_FOUND', 'Pump 300 ml [W1]']) as llm:
        result = exclusive.run_exclusive_pipeline('รุ่นใหม่ที่ไม่มีในเอกสารใช้อัตราเท่าไร')
    assert web.call_count == 1
    assert llm.call_count == 2
    assert result.source_type == 'web_fallback'
    web_payload = json.loads(llm.call_args_list[1].args[0][1]['content'])
    assert [s['id'] for s in web_payload['sources']] == ['W1']
    assert KB.content not in llm.call_args_list[1].args[0][1]['content']


def test_queried_model_code_missing_from_kb_fast_skips_kb_llm_call():
    kb_t25 = Evidence('D1', 'DJI AGRAS T25 ถังพ่น 20 ลิตร', 'ฟีเจอร์การลงทุน.pdf', '10')
    web_t70p = Evidence('W1', 'DJI AGRAS T70P ถังพ่น 70 ลิตร', url='https://ag.dji.com/t70p/specs')
    with patch.dict(os.environ, {'ANSWER_MODE': 'natural'}), \
         patch.object(exclusive.legacy, 'llm_pool_error', return_value=''), \
         patch.object(exclusive.legacy, 'retrieve_evidence', return_value=[kb_t25]), \
         patch.object(exclusive.legacy, 'search_web_fallback', return_value=['result']) as web, \
         patch.object(exclusive.legacy, 'web_evidence', return_value=[web_t70p]), \
         patch.object(exclusive.legacy, 'call_llm', return_value='DJI AGRAS T70P ถังพ่น 70 ลิตร [W1]') as llm:
        result = exclusive.run_exclusive_pipeline('โดรนเกษตร DJI Agras T70P มีความจุถังพ่นเท่าไร')
    assert web.call_count == 1
    assert llm.call_count == 1
    assert result.source_type == 'web_fallback'
    assert any(d.get('stage') == 'kb_fast_skip' for d in result.diagnostics)


def test_comparing_in_kb_model_with_out_of_kb_model_abstains_without_llm_call():
    kb_t25 = Evidence('D1', 'DJI AGRAS T25 ถังพ่น 20 ลิตร', 'ฟีเจอร์การลงทุน.pdf', '10')
    with patch.dict(os.environ, {'ANSWER_MODE': 'natural'}), \
         patch.object(exclusive.legacy, 'llm_pool_error', return_value=''), \
         patch.object(exclusive.legacy, 'retrieve_evidence', return_value=[kb_t25]), \
         patch.object(exclusive.legacy, 'search_web_fallback') as web, \
         patch.object(exclusive.legacy, 'call_llm') as llm:
        result = exclusive.run_exclusive_pipeline('เปรียบเทียบความจุถังพ่นของ DJI Agras T25 กับ T70P')
    assert result.source_type == 'abstain'
    web.assert_not_called()
    llm.assert_not_called()


@pytest.mark.parametrize('question', [
    'ปลูกอ้อยตั้งแต่เดือนมกราคม จนถึงเดือนนี้ ตอนนี้ต้องพ่นอะไร',
    'ปลูกอ้อยตั้งแต่เดือนตุลาคมมาถึงเดือนนี้ ต้องฉีดสารอะไร',
    'เดือนนี้ต้องฉีดยาคุมวัชพืชตัวไหนในไร่อ้อย',
    'สภาพอากาศวันนี้ทำให้ข้าวเสี่ยงโรคอะไรตามคู่มือ',
    'ถ้าน้ำมันดีเซลวันนี้ลิตรละ 42 บาท ต้นทุนต่อไร่และจุดคุ้มทุนในตารางจะเปลี่ยนเป็นเท่าไร',
    'หัวฉีดพัดส้มมีอัตราการไหลเท่าไร และราคาน้ำมันดีเซลวันนี้ลิตรละกี่บาท',
    'ขึ้นทะเบียนโดรนกับ CAAT ต้องใช้อะไรบ้าง และก่อนบินต้องตรวจเช็กโดรนกี่จุด',
    'ความสูงบินฉีดพ่นอ้อยตามคู่มือกี่เมตร และกฎหมาย CAAT ห้ามบินเกินกี่เมตร',
])
def test_mixed_kb_and_realtime_or_web_questions_abstain_cleanly(question):
    with patch.dict(os.environ, {'ANSWER_MODE': 'natural'}), \
         patch.object(exclusive.legacy, 'llm_pool_error', return_value=''), \
         patch.object(exclusive.legacy, 'retrieve_evidence') as kb, \
         patch.object(exclusive.legacy, 'search_web_fallback') as web, \
         patch.object(exclusive.legacy, 'call_llm') as llm:
        result = exclusive.run_exclusive_pipeline(question)
    assert result.source_type == 'abstain'
    assert result.answer.startswith('ยังไม่พบหลักฐานเพียงพอ')
    kb.assert_not_called()
    web.assert_not_called()
    llm.assert_not_called()


def test_multipart_question_mixing_in_kb_and_out_of_kb_topics_abstains():
    raw_reply = 'เพนดิเมทาลินใช้อัตรา 250 ml [D1]\nยังไม่พบข้อมูล: ความจุถังพ่นของรุ่นใหม่ที่ไม่มีในเอกสาร'
    with patch.dict(os.environ, {'ANSWER_MODE': 'natural'}), \
         patch.object(exclusive.legacy, 'llm_pool_error', return_value=''), \
         patch.object(exclusive.legacy, 'retrieve_evidence', return_value=[KB]), \
         patch.object(exclusive.legacy, 'search_web_fallback') as web, \
         patch.object(exclusive.legacy, 'call_llm', return_value=raw_reply):
        result = exclusive.run_exclusive_pipeline('เพนดิเมทาลินใช้อัตราเท่าไร และโดรนรุ่นใหม่มีความจุถังพ่นกี่ลิตร')
    assert result.source_type == 'abstain'
    assert result.answer.startswith('ยังไม่พบหลักฐานเพียงพอ')
    web.assert_not_called()


def test_ai_service_is_connected_to_exclusive_pipeline():
    assert ai_service.run_crag_pipeline is exclusive.run_exclusive_pipeline


@pytest.mark.parametrize('question,survey_allowed', [
    ('ก่อนบินโดรนต้องตรวจอะไรบ้าง', False),
    ('ก่อนบินโดรนสำรวจต้องตรวจอะไรบ้าง', True),
    ('ตาม UAV11 ก่อนบินต้องตรวจอะไร', True),
])
def test_live_kb_preserves_requested_application_scope(question, survey_allowed):
    general = Evidence('D1', 'ก่อนบินตรวจใบพัดและแบตเตอรี่', 'ฟีเจอร์โดรนของฉัน.pdf', '1')
    survey = Evidence('D2', 'โดรนสำรวจ ตรวจแรงดัน 25.2 V', 'UAV11 การสาธิตการใช้โดรนสำรวจ.pdf', '6')
    with patch.dict(os.environ, {'ANSWER_MODE': 'natural'}), \
         patch.object(exclusive.legacy, 'llm_pool_error', return_value=''), \
         patch.object(exclusive.legacy, 'retrieve_evidence', return_value=[general, survey]), \
         patch.object(exclusive.legacy, 'call_llm', return_value='ก่อนบินตรวจใบพัดและแบตเตอรี่ [D1]' if not survey_allowed else 'โดรนสำรวจ ตรวจแรงดัน 25.2 V [D2]') as llm:
        response = exclusive.run_exclusive_pipeline(question)
    assert response.source_type == 'knowledge_base'
    payload = json.loads(llm.call_args.args[0][1]['content'])
    ids = {source['id'] for source in payload['sources']}
    assert ('D2' in ids) is survey_allowed
    if question.startswith('ตาม UAV11'):
        assert ids == {'D2'}


def test_survey_only_evidence_does_not_become_a_general_preflight_rule():
    survey = Evidence('D1', 'โดรนสำรวจ ตรวจแรงดัน 25.2 V', 'UAV11 การสาธิตการใช้โดรนสำรวจ.pdf', '6')
    with patch.dict(os.environ, {'ANSWER_MODE': 'natural'}), \
         patch.object(exclusive.legacy, 'llm_pool_error', return_value=''), \
         patch.object(exclusive.legacy, 'retrieve_evidence', return_value=[survey]), \
         patch.object(exclusive.legacy, 'call_llm') as llm:
        response = exclusive.run_exclusive_pipeline('ก่อนบินโดรนต้องตรวจอะไรบ้าง')
    assert response.source_type == 'abstain'
    llm.assert_not_called()


def test_caat_exam_answer_preserves_explicit_scope_of_cited_passage():
    from app.rag.natural_answer import render
    content = ('การสอบ E-Exam ไม่ผ่าน สอบใหม่หลังครบ 24 ชั่วโมง ไม่กำหนดจำนวนครั้ง '
               'ผู้ขอขึ้นทะเบียนได้รับหนังสือผู้บังคับฯ ขั้นพื้นฐานต่ำกว่า 25 กิโลกรัม')
    source = Evidence('W1', content, url='https://uasportal.caat.or.th/guideline.pdf', title='CAAT')
    result = render('สอบ E-Exam ใหม่ได้หลังครบ 24 ชั่วโมง ไม่จำกัดจำนวนครั้ง [W1]', [source])
    assert 'ขั้นพื้นฐาน ต่ำกว่า 25 กิโลกรัม [1]' in result.text
    assert 'https://uasportal.caat.or.th/guideline.pdf' in result.text


def test_caat_scope_is_not_inferred_without_a_matching_exam_context():
    from app.rag.natural_answer import render
    source = Evidence('W1', 'ผู้บังคับฯ ขั้นพื้นฐานต่ำกว่า 25 กิโลกรัม ค่าอบรม 24 ชั่วโมง',
                      url='https://uasportal.caat.or.th/guideline.pdf')
    result = render('สอบ E-Exam ใหม่ได้หลังครบ 24 ชั่วโมง [W1]', [source])
    assert 'ขอบเขตในเอกสาร' not in result.text
