"""Offline end-to-end web adapter, source binding and failure contracts.

All provider contents below are synthetic fixtures, not verified web facts.
"""
import json
from unittest.mock import Mock, patch

import pytest

from app.rag import support_pipeline as support
from app.rag import web_fallback as web


@pytest.fixture(autouse=True)
def query_plan_without_provider_calls():
    with patch('app.rag.web_retrieval.plan_web_query', return_value={
            'query': 'official equipment manual', 'domains': web.allowed_domains()}):
        yield


def generated(text='อัตราการไหล 250 ml', sid='W1', quote='อัตราการไหล 250 ml'):
    return json.dumps({'status': 'sufficient', 'intro': '', 'claims': [{'text': text,
        'evidence': [{'source_id': sid, 'quote': quote}]}]}, ensure_ascii=False)


@pytest.mark.parametrize('query', ['หาข้อมูลจากเน็ตเรื่องหัวฉีด', 'ค้นอินเตอร์เน็ตเรื่องหัวฉีด',
                                  'ค้นหาเว็บเรื่องหัวฉีด',
                                  'หาคู่มือจากเว็บไซต์', 'ค้นข้อมูลออนไลน์', 'Internet nozzle guide',
                                  'WEB SEARCH nozzle guide'])
def test_explicit_web_wording_routes_to_web_without_ignoring_selected_kb(query):
    assert support.choose_source(query) == 'web'
    assert support.choose_source(query, 'kb') == 'kb'


def test_real_web_adapters_keep_exact_urls_and_discard_spoofed_domains_without_touching_kb():
    url = 'https://doa.go.th/manual?id=42&lang=th#flow'
    client = Mock()
    client.search.return_value = {'results': [
        {'url': 'https://doa.go.th.attacker.example/manual', 'content': 'อัตราการไหล 900 ml', 'score': 1},
        {'url': url, 'content': 'อัตราการไหล 250 ml', 'title': 'คู่มือจำลอง', 'score': 0.5}]}
    client.extract.return_value = {'results': [{'url': url, 'raw_content': 'อัตราการไหล 250 ml', 'title': 'คู่มือจำลอง'}]}
    with patch.object(web, 'get_tavily_client', return_value=client), \
         patch.object(support, 'retrieve_evidence', side_effect=AssertionError('Web must not use KB')), \
         patch.object(support, 'call_llm', return_value=generated()) as llm:
        result = support.run_support_pipeline('ค้นข้อมูลออนไลน์เรื่องหัวฉีด')
    assert result.citation_checks_passed and result.source_type == 'web_fallback'
    assert url in result.answer and 'attacker' not in result.answer
    payload = json.loads(llm.call_args.args[0][-1]['content'])
    assert [s['url'] for s in payload['sources']] == [url]
    assert result.evidence_trace[0]['evidence'][0]['url'] == url
    assert client.search.call_args.kwargs['include_domains_mode'] == 'restrict'
    assert client.extract.call_args.kwargs['urls'] == [url]
    assert llm.call_count == 1


def test_caat_route_uses_designated_fetch_and_keeps_only_caat_passages():
    url = web.CAAT_DESIGNATED_URLS[0]
    client = Mock()
    client.extract.return_value = {'results': [{'url': url, 'raw_content': 'รหัสเอกสารทดสอบ TEST-42'}]}
    client.search.return_value = {'results': [
        {'url': 'https://doa.go.th/unrelated', 'content': 'ข้อมูลที่ไม่ใช่ CAAT'},
        {'url': 'https://caat.or.th.attacker.example/guide', 'content': 'ข้อมูลปลอม'}]}
    with patch.object(web, 'get_tavily_client', return_value=client), \
         patch.object(support, 'retrieve_evidence', side_effect=AssertionError('No KB')), \
         patch.object(support, 'call_llm', return_value=generated('รหัสเอกสารทดสอบ TEST-42',
                      quote='รหัสเอกสารทดสอบ TEST-42')) as llm:
        result = support.run_support_pipeline('กฎการบินโดรนมีข้อมูลอะไร')
    assert result.source_type == 'caat_portal' and result.citation_checks_passed
    assert result.evidence_trace[0]['evidence'][0]['url'] == url
    assert client.extract.call_args.kwargs['urls'] == web.designated_caat_urls()
    client.search.assert_not_called()
    assert len(json.loads(llm.call_args.args[0][-1]['content'])['sources']) == 1


@pytest.mark.parametrize('failure', ['empty', 'timeout', 'untrusted'])
def test_web_failure_never_calls_generator_or_switches_to_kb(failure):
    client = Mock()
    if failure == 'timeout':
        client.search.side_effect = TimeoutError('synthetic timeout')
    else:
        client.search.return_value = {'results': [] if failure == 'empty' else [
            {'url': 'https://attacker.example/', 'content': 'อัตราการไหล 250 ml'}]}
    with patch.object(web, 'get_tavily_client', return_value=client), \
         patch.object(support, 'retrieve_evidence') as kb, \
         patch.object(support, 'call_llm') as llm:
        result = support.run_support_pipeline('ค้นเว็บเรื่องหัวฉีด', source='web')
    assert result.source_type == 'abstain'
    kb.assert_not_called()
    llm.assert_not_called()
    if failure == 'timeout':
        assert result.error_code
