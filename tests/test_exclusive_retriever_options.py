"""The retrievers share LINE's routing and citation boundary."""
import json
import os
from unittest.mock import patch

from app.rag import exclusive_pipeline as exclusive
from app.rag.evidence import Evidence
from app.rag.web_fallback import WebSearchResult
from scripts.rag_evaluation_trace import capture_pipeline


def test_legacy_kb_receives_scope_before_search_and_traces_evidence():
    source = Evidence('D1', 'ตรวจใบพัดว่าไม่มีรอยร้าว', 'คู่มือ.pdf', '3')
    with patch.dict(os.environ, {'ANSWER_MODE': 'natural', 'RAG_KB_RETRIEVER': 'legacy'}), \
         patch.object(exclusive.legacy, 'llm_pool_error', return_value=''), \
         patch.object(exclusive.legacy, 'retrieve_evidence', return_value=[source]) as retrieve, \
         patch.object(exclusive.legacy, 'call_llm', return_value='ตรวจใบพัดว่าไม่มีรอยร้าว [D1]'), \
         capture_pipeline('exclusive') as trace:
        result = exclusive.run_exclusive_pipeline('ก่อนบินต้องตรวจอะไร')
    assert result.source_type == 'knowledge_base'
    assert not retrieve.call_args.kwargs['source_scope'].allows_source('UAV11 โดรนสำรวจ.pdf')
    assert 'คู่มือ.pdf, หน้า 3' in result.answer
    assert trace['retrieval'][0]['sources'][0]['source_file'] == 'คู่มือ.pdf'


def test_planned_web_reads_web_only_and_cites_fetched_url():
    from app.rag import web_retrieval
    source = WebSearchResult('ผู้ผลิต', 'https://dji.com/manual', 'Check propeller before flight', .9)
    with patch.dict(os.environ, {'ANSWER_MODE': 'natural', 'RAG_WEB_RETRIEVER': 'read'}), \
         patch.object(exclusive.legacy, 'llm_pool_error', return_value=''), \
         patch.object(exclusive.legacy, 'retrieve_evidence') as kb, \
         patch.object(web_retrieval, 'retrieve_web', return_value=[source]) as web, \
         patch.object(exclusive.legacy, 'call_llm', return_value='Check propeller before flight [W1]'):
        result = exclusive.run_exclusive_pipeline('ค้นเว็บวิธีตรวจใบพัด')
    kb.assert_not_called()
    assert web.called and result.source_type == 'web_fallback'
    assert 'https://dji.com/manual' in result.answer


def test_bad_selector_fails_closed_instead_of_falling_back_silently():
    with patch.dict(os.environ, {'RAG_KB_RETRIEVER': 'invalid'}), \
         patch.object(exclusive.legacy, 'llm_pool_error', return_value=''), \
         patch.object(exclusive.legacy, 'retrieve_evidence') as retrieve:
        result = exclusive.run_exclusive_pipeline('ก่อนบินต้องตรวจอะไร')
    retrieve.assert_not_called()
    assert result.error_code and result.source_type == 'abstain'


def test_agricultural_question_cannot_use_consumer_model_web_guide_as_general_rule():
    from app.rag import web_retrieval
    consumer = WebSearchResult('Flight Safety Guidelines', 'https://support.dji.com/consumer',
                               'DJI Mavic Series: Check battery and propellers before flight', .9)
    agricultural = WebSearchResult('Agras maintenance', 'https://ag.dji.com/maintenance',
                                   'Agricultural drone battery: check the battery cycles', .8)
    with patch.dict(os.environ, {'ANSWER_MODE': 'natural', 'RAG_WEB_RETRIEVER': 'read'}), \
         patch.object(exclusive.legacy, 'llm_pool_error', return_value=''), \
         patch.object(web_retrieval, 'retrieve_web', return_value=[consumer, agricultural]), \
         patch.object(exclusive.legacy, 'call_llm', return_value='Check the battery cycles [W1]') as model:
        result = exclusive.run_exclusive_pipeline('ค้นเว็บ DJI โดรนเกษตรตรวจแบตเตอรี่อย่างไร')
    payload = json.loads(model.call_args.args[0][1]['content'])
    assert [s['url'] for s in payload['sources']] == [agricultural.url]
    assert 'https://support.dji.com/consumer' not in result.answer
    assert 'https://ag.dji.com/maintenance' in result.answer


def test_explicit_consumer_model_question_keeps_its_guide():
    from app.rag.application_scope import web_source_applicable
    consumer = WebSearchResult('Mavic', 'https://support.dji.com/consumer', 'DJI Mavic preflight', .9)
    assert web_source_applicable('ค้นเว็บ DJI Mavic ตรวจอะไรก่อนบิน', consumer)
    assert not web_source_applicable('ค้นเว็บ DJI โดรนเกษตรตรวจอะไรก่อนบิน', consumer)
