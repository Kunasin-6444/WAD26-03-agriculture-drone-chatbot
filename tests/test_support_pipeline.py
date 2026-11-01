"""Source isolation and claim/quote contracts; no provider calls."""
import json
from unittest.mock import patch

import pytest

from app.rag import support_pipeline as support
from app.rag.evidence import Evidence
from app.rag.web_fallback import WebSearchResult


def answer(text='อัตราการไหล 250 ml', sid='D1', quote='อัตราการไหล 250 ml'):
    return json.dumps({'status': 'sufficient', 'reason': '', 'is_caat_topic': False,
        'intro': '', 'missing_aspects': [], 'claims': [{'text': text,
        'evidence': [{'source_id': sid, 'quote': quote}]}]}, ensure_ascii=False)


def test_kb_mode_has_one_generation_and_no_web_or_auto_fallback():
    evidence = [Evidence('D1', 'อัตราการไหล 250 ml', 'pump.pdf', '2')]
    with patch.object(support, 'retrieve_evidence', return_value=evidence), \
         patch.object(support, 'search_web_fallback') as web, \
         patch.object(support, 'call_llm', return_value=answer()) as llm:
        result = support.run_support_pipeline('อัตราการไหลเท่าไร', source='kb')
    web.assert_not_called()
    assert llm.call_count == 1
    assert result.source_type == 'knowledge_base'
    assert '250 ml' in result.answer and 'pump.pdf, หน้า 2' in result.answer
    assert result.evidence_trace[0]['evidence'][0]['quote'] == 'อัตราการไหล 250 ml'
    assert result.semantic_quality == 'not_assessed'


def test_web_mode_never_retrieves_kb_and_preserves_exact_url():
    url = 'https://www.doa.go.th/guide?id=42&lang=th#flow'
    fetched = [WebSearchResult('คู่มือ', url, 'อัตราการไหล 250 ml')]
    with patch.object(support, 'retrieve_evidence') as kb, \
         patch.object(support, 'search_web_fallback', return_value=fetched), \
         patch.object(support, 'call_llm', return_value=answer(sid='W1')):
        result = support.run_support_pipeline('ค้นเว็บเรื่องอัตราการไหล', source='web')
    kb.assert_not_called()
    assert result.source_type == 'web_fallback'
    assert url in result.answer
    assert all(e['url'] for e in result.post_selection_evidence)


@pytest.mark.parametrize('source', ['kb', 'web'])
def test_empty_selected_source_abstains_without_switch_or_generation(source):
    with patch.object(support, 'retrieve_evidence', return_value=[]) as kb, \
         patch.object(support, 'search_web_fallback', return_value=[]) as web, \
         patch.object(support, 'call_llm') as llm:
        result = support.run_support_pipeline('อัตราการไหลเท่าไร', source=source)
    assert kb.call_count == (source == 'kb')
    assert web.call_count == (source == 'web')
    llm.assert_not_called()
    assert result.source_type == 'abstain'


@pytest.mark.parametrize('reply', [answer(sid='D9'), answer(sid='D1', quote='อัตราการไหล 900 ml'),
    answer('อัตราการไหล 250 ลิตร'), answer('Alpha 500 ml', quote='Alpha | 250 ml')])
def test_invalid_id_quote_unit_or_row_is_not_silently_rebound(reply):
    evidence = [Evidence('D1', 'อัตราการไหล 250 ml\nModel | Amount\nAlpha | 250 ml\nBeta | 500 ml', 'pump.pdf', '2'),
                Evidence('D2', 'อัตราการไหล 900 ml', 'other.pdf', '3')]
    with patch.object(support, 'call_llm', return_value=reply):
        result = support.run_support_pipeline('อัตราเท่าไร', source='kb', evidence_override=evidence)
    assert result.source_type == 'abstain'
    assert not result.citation_checks_passed
    assert result.raw_answer == reply


def test_wrong_source_is_rejected_even_when_correct_quote_is_in_another_source():
    evidence = [Evidence('D1', 'ข้อมูลการเตรียมเครื่อง', 'setup.pdf', '1'),
                Evidence('D3', 'อัตราการไหล 250 ml', 'rates.pdf', '2')]
    with patch.object(support, 'call_llm', return_value=answer()):
        result = support.run_support_pipeline('อัตราเท่าไร', source='kb', evidence_override=evidence)
    assert result.source_type == 'abstain'
    assert 'Quote not in supplied evidence' in result.grade_reason


def test_oracle_input_skips_retrieval_and_mixed_evidence_is_filtered():
    evidence = [Evidence('D1', 'อัตราการไหล 250 ml', 'pump.pdf', '2'),
                Evidence('W1', 'อัตราการไหล 900 ml', url='https://www.doa.go.th/guide')]
    with patch.object(support, 'retrieve_evidence') as kb, \
         patch.object(support, 'search_web_fallback') as web, \
         patch.object(support, 'call_llm', return_value=answer()) as llm:
        result = support.run_support_pipeline('อัตราเท่าไร', source='kb', evidence_override=evidence)
    kb.assert_not_called()
    web.assert_not_called()
    payload = json.loads(llm.call_args.args[0][-1]['content'])
    assert [e['id'] for e in payload['sources']] == ['D1']
    assert result.source_type == 'knowledge_base'


def test_web_mode_rejects_evidence_that_also_claims_to_be_a_kb_document():
    ambiguous = Evidence('W1', 'อัตราการไหล 250 ml', 'kb.pdf', '2', url='https://www.doa.go.th/guide')
    diagnostics = []
    assert support.pack_context([ambiguous], 'web', diagnostics, 24000) == []
    assert diagnostics[0]['reason'] == 'source_policy'


def test_caat_auto_uses_web_and_explicit_kb_does_not_call_a_provider():
    assert support.choose_source('กฎการบินโดรนล่าสุด') == 'web'
    assert support.choose_source('โดรนในตารางราคาถูกที่สุด') == 'kb'
    with patch.object(support, 'retrieve_evidence') as kb, \
         patch.object(support, 'search_web_fallback') as web, \
         patch.object(support, 'call_llm') as llm:
        result = support.run_support_pipeline('กฎการบินโดรนล่าสุด', source='kb')
    kb.assert_not_called()
    web.assert_not_called()
    llm.assert_not_called()
    assert result.source_type == 'abstain'


def test_whole_chunk_budget_cannot_claim_table_complete_after_dropping_a_row():
    first = Evidence('D1', 'Alpha | 250 ml', 'table.pdf', '1')
    second = Evidence('D2', 'Beta | 500 ml', 'table.pdf', '1')
    diagnostics = [{'tables': [{'coverage': 'complete', 'included_chunks': [
        (e.source_file, e.page_number, e.content) for e in (first, second)]}]}]
    budget = len(json.dumps(first.__dict__, ensure_ascii=False))
    selected = support.pack_context([first, second], 'kb', diagnostics, budget)
    assert selected == [first]
    assert diagnostics[0]['tables'][0]['coverage'] == 'incomplete'
    assert diagnostics[0]['tables'][0]['post_selection_dropped_chunks'] == 1


def test_invalid_json_is_reported_as_service_response_error_not_missing_knowledge():
    with patch.object(support, 'call_llm', return_value='{bad'):
        result = support.run_support_pipeline('อัตราเท่าไร', evidence_override=[
            Evidence('D1', 'อัตราการไหล 250 ml', 'pump.pdf', '2')])
    assert result.error_code == 'invalid_response'


def test_explicit_complete_list_can_exceed_eight_claims_without_relaxing_legacy_default():
    from app.rag.evidence import parse_grounded_result
    lines = [f'รายการที่ {i} มีค่า {i*10} ml' for i in range(1, 13)]
    evidence = [Evidence('D1', '\n'.join(lines), 'synthetic.pdf', '1')]
    data = json.loads(answer())
    data['claims'] = [{'text': line, 'evidence': [{'source_id': 'D1', 'quote': line}]} for line in lines]
    raw = json.dumps(data, ensure_ascii=False)
    assert not parse_grounded_result(raw, evidence).claims
    with patch.object(support, 'call_llm', return_value=raw):
        result = support.run_support_pipeline('ขอรายการทั้งหมดพร้อมค่า', source='kb', evidence_override=evidence)
    assert len(result.evidence_trace) == 12
    assert all(line in result.answer for line in lines)


def test_manual_support_source_selection_reaches_only_selected_provider_path():
    from fastapi.testclient import TestClient
    from app.playground import app
    url = 'https://www.doa.go.th/guide?id=42#flow'
    origin = 'http://127.0.0.1:8082'
    with patch.object(app.state, 'pipeline', 'support'), \
         patch.object(support, 'retrieve_evidence') as kb, \
         patch.object(support, 'search_web_fallback', return_value=[WebSearchResult('คู่มือ', url, 'อัตราการไหล 250 ml')]) as web, \
         patch.object(support, 'call_llm', return_value=answer(sid='W1')) as llm, \
         TestClient(app, base_url=origin, headers={'origin': origin}) as browser:
        browser.get('/')
        browser.post('/api/ask', json={'question': 'อัตราเท่าไร', 'source': 'web'})
        web.assert_not_called()
        llm.assert_not_called()
        response = browser.post('/api/ask', json={'question': 'อัตราเท่าไร', 'mode': 'live', 'source': 'web'})
    assert response.status_code == 200
    assert url in response.json()['answer']
    kb.assert_not_called()
    assert web.call_count == 1
    assert llm.call_count == 1


def test_evaluator_selects_support_and_captures_quoted_claims():
    import tempfile
    import os
    from pathlib import Path
    from types import SimpleNamespace
    from scripts import evaluate_answers as ev
    args = SimpleNamespace(pipeline='support', source='kb', model='model-a', prompt='full',
        judge_model='unused', skip_judge=True, split='dev', no_answer_only=True, limit=1,
        ids=None, gold=ev.GOLD, attempt_timeout=25, kb_budget=None, request_timeout=None,
        output='support-test', reasoning_effort='low', answer_mode='natural')
    case = {'id': 'synthetic', 'query': 'อัตราการไหลเท่าไร', 'expected_answer': '250 ml'}
    with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ), \
         patch.object(ev, 'OUT_DIR', Path(folder)), patch.object(ev, 'load_cases', return_value=[case]), \
         patch.object(support, 'retrieve_evidence', return_value=[Evidence('D1', 'อัตราการไหล 250 ml', 'pump.pdf', '2')]), \
         patch.object(support, 'call_llm', return_value=answer()), \
         patch('app.rag.rag_service.FALLBACK_MODELS', []), \
         patch('app.rag.rag_service.secondary_enabled', return_value=False):
        assert ev.run(args) == 0
        data = json.loads((Path(folder)/'support-test.json').read_text(encoding='utf-8'))
    assert data['config']['pipeline'] == 'support'
    assert data['config']['source_mode'] == 'kb'
    assert data['config']['prompt_profile'] == support.PROFILE
    assert '250 ml' in data['rows'][0]['answer']
    assert data['rows'][0]['trace']['generation'][0]['raw_answer'] == answer()
    assert data['summary']['quality_review']['pass_rate'] is None


def test_provided_table_coverage_is_preserved_and_downgraded_if_chunk_is_dropped():
    evidence = [Evidence('D1', 'Alpha | 250 ml', 'specs.pdf', '1'),
                Evidence('D2', 'Beta | 500 ml', 'specs.pdf', '2')]
    coverage = [{'source_file': 'specs.pdf', 'table_id': 'table-a', 'coverage': 'complete',
                 'included_chunks': [(e.source_file, e.page_number, e.content) for e in evidence]}]
    budget = len(json.dumps(evidence[0].__dict__, ensure_ascii=False))
    raw = json.dumps({'status': 'insufficient', 'intro': '', 'reason': '', 'claims': [], 'missing_aspects': []})
    with patch.object(support, 'call_llm', return_value=raw) as llm:
        support.run_support_pipeline('ขอข้อมูลตาราง', source='kb', evidence_override=evidence,
                                     table_coverage_override=coverage, context_chars=budget)
    payload = json.loads(llm.call_args.args[0][-1]['content'])
    assert payload['table_coverage'][0]['coverage'] == 'incomplete'
    assert coverage[0]['coverage'] == 'complete'  # input snapshot is immutable
    assert payload['table_coverage'][0]['post_selection_dropped_chunks'] == 1
