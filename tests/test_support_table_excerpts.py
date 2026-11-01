"""Separate genuine non-adjacent table excerpts without repairing source facts."""
import json
from unittest.mock import patch

import pytest

from app.rag import support_pipeline as support
from app.rag.evidence import Evidence, parse_grounded_result

TABLE = 'รุ่น | ปริมาณ\nAlpha | 250 ml\nBeta | 400 ml\nGamma | 500 ml'


def data(quote, text='Alpha 250 ml และ Gamma 500 ml', sid='D1'):
    return {'status': 'sufficient', 'reason': '', 'intro': '', 'missing_aspects': [],
            'is_caat_topic': False, 'claims': [{'text': text,
                'evidence': [{'source_id': sid, 'quote': quote}]}]}


def test_nonadjacent_source_excerpt_utility_preserves_the_claim_without_rewriting_facts():
    value = data('Alpha | 250 ml\nGamma | 500 ml')
    evidence = [Evidence('D1', TABLE, 'example.pdf', '1')]
    raw = json.dumps(value, ensure_ascii=False)
    assert not parse_grounded_result(raw, evidence).claims  # demonstrates original failure
    support.split_exact_excerpts(value,evidence,[])
    checked=parse_grounded_result(json.dumps(value,ensure_ascii=False),evidence)
    assert checked.status=='sufficient'
    assert checked.claims[0].text==data('unused')['claims'][0]['text']
    assert [sid for sid,_ in checked.claims[0].quotes]==['D1','D1']
    assert len(checked.claims[0].quotes)==2


@pytest.mark.parametrize('quote,text,sid', [
    ('Alpha | 500 ml\nGamma | 250 ml', 'Alpha 500 ml และ Gamma 250 ml', 'D1'),
    ('Alpha | 250 ml\nDelta | 900 ml', 'Alpha 250 ml และ Delta 900 ml', 'D1'),
    ('Alpha | 250 ml\nGamma | 500 ml', 'Alpha 500 ml', 'D1'),
    ('Alpha | 250 ml\nGamma | 500 ml', 'Alpha 250 ลิตร และ Gamma 500 ลิตร', 'D1'),
    ('Alpha | 250 ml\nGamma | 500 ml', 'Alpha 250 ml และ Gamma 500 ml', 'D2'),
])
def test_wrong_row_value_unit_or_source_still_cannot_pass(quote, text, sid):
    evidence = [Evidence('D1', TABLE, 'example.pdf', '1'),
                Evidence('D2', 'ข้อมูลคนละเรื่อง', 'other.pdf', '2')]
    with patch.object(support, 'call_llm', return_value=json.dumps(data(quote, text, sid), ensure_ascii=False)):
        result = support.run_support_pipeline('ขอข้อมูลรุ่น', source='kb', evidence_override=evidence)
    assert result.source_type == 'abstain'
    value=data(quote,text,sid)
    support.split_exact_excerpts(value,evidence,[])
    assert not parse_grounded_result(json.dumps(value,ensure_ascii=False),evidence).claims


def test_separate_prose_sentences_are_not_normalized_as_table_rows():
    value = data('Alpha\nGamma')
    diagnostics = []
    support.split_exact_excerpts(value, [Evidence('D1', TABLE, 'example.pdf', '1')], diagnostics)
    assert value['claims'][0]['evidence'][0]['quote'] == 'Alpha\nGamma'
    assert not diagnostics


PROSE = ('ก่อนใช้งานทุกครั้ง\n● สายไฟต้องไม่มีสนิม\n● ใบพัดต้องไม่มีรอยแตก\n'
         '● แบตเตอรี่ต้องไม่บวม\n● โครงสร้างต้องยึดแน่น\n● มอเตอร์ต้องไม่คลอน')


def test_nonadjacent_complete_prose_lines_preserve_claim_raw_source_and_order():
    value = data('● สายไฟต้องไม่มีสนิม\n● แบตเตอรี่ต้องไม่บวม',
                 text='ตรวจสายไฟว่าไม่มีสนิม และตรวจแบตเตอรี่ว่าไม่บวม')
    evidence = [Evidence('D1', PROSE, 'checklist.pdf', '3')]
    raw = json.dumps(value, ensure_ascii=False)
    assert not parse_grounded_result(raw, evidence).claims
    with patch.object(support, 'call_llm', return_value=raw):
        result = support.run_support_pipeline('ต้องตรวจอะไร', source='kb', evidence_override=evidence)
    assert result.citation_checks_passed
    assert result.raw_answer == raw
    assert result.evidence_trace[0]['text'] == value['claims'][0]['text']
    assert [e['quote'] for e in result.evidence_trace[0]['evidence']] == value['claims'][0]['evidence'][0]['quote'].splitlines()


@pytest.mark.parametrize('quote,sid', [
    ('● แบตเตอรี่ต้องไม่บวม\n● สายไฟต้องไม่มีสนิม', 'D1'),  # reversed source order
    ('สายไฟต้องไม่มีสนิม\nแบตเตอรี่ต้องไม่บวม', 'D1'),  # fragments, not whole lines
    ('● สายไฟต้องไม่มีสนิม\n● แบตเตอรี่ต้องบวม', 'D1'),  # changed meaning
    ('● สายไฟต้องไม่มีสนิม\n● แบตเตอรี่ต้องไม่บวม', 'D2'),  # wrong source
])
def test_prose_excerpt_conversion_cannot_repair_facts_source_order_or_citation_limit(quote, sid):
    evidence = [Evidence('D1', PROSE, 'checklist.pdf', '3'),
                Evidence('D2', 'เอกสารคนละเรื่อง', 'other.pdf', '4')]
    raw = json.dumps(data(quote, text='ตรวจสายไฟว่าไม่มีสนิม และแบตเตอรี่ไม่บวม', sid=sid), ensure_ascii=False)
    with patch.object(support, 'call_llm', return_value=raw):
        result = support.run_support_pipeline('ต้องตรวจอะไร', source='kb', evidence_override=evidence)
    assert result.source_type == 'abstain'


def test_separating_nonadjacent_lines_cannot_exceed_evidence_limit():
    # The production limit is 20, not the historical value of four. Exercise
    # the actual boundary while keeping each source excerpt independently real.
    parts = [f'● รายการตรวจ {i}: สายไฟไม่มีสนิมและแบตเตอรี่ไม่บวม'
             for i in range(1, support.MAX_SUPPORT_EVIDENCE + 2)]
    evidence = [Evidence('D1', '\nบรรทัดคั่นแต่ละข้อ\n'.join(parts), 'checklist.pdf', '3')]
    raw = json.dumps(data('\n'.join(parts), text='ตรวจสายไฟว่าไม่มีสนิม และแบตเตอรี่ไม่บวม'), ensure_ascii=False)
    assert not parse_grounded_result(raw, evidence).claims
    with patch.object(support, 'call_llm', return_value=raw):
        result = support.run_support_pipeline('ต้องตรวจอะไร', source='kb', evidence_override=evidence)
    assert result.source_type == 'abstain'
