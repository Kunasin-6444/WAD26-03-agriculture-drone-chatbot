import json
from unittest.mock import Mock, patch

import pytest

from app.rag import web_retrieval as retrieval
from app.rag import web_fallback as web


def test_plan_preserves_query_as_data_and_limits_domains_to_operator_policy():
    value = {'query': 'manufacturer agricultural drone battery propeller preflight manual', 'domains': ['dji.com']}
    with patch.object(retrieval, 'call_llm', return_value=json.dumps(value)) as model:
        plan = retrieval.plan_web_query('ถามเรื่องอุปกรณ์ผู้ผลิตต่างประเทศ')
    assert plan == value
    assert model.call_args.kwargs['max_attempts'] == 1
    assert model.call_args.kwargs['max_tokens'] == retrieval.WEB_PLAN_MAX_OUTPUT_TOKENS == 1200
    assert not model.call_args.kwargs['structured']


@pytest.mark.parametrize('value', [
    {'query': 'useful query', 'domains': ['attacker.example']},
    {'query': 'q\nother', 'domains': []}, {'query': '', 'domains': []},
    {'query': 'query', 'domains': 'dji.com'},
])
def test_invalid_query_plan_is_not_used_for_network_requests(value):
    with patch.object(retrieval, 'call_llm', return_value=json.dumps(value)):
        with pytest.raises(ValueError):
            retrieval.plan_web_query('question')


def test_search_snippets_are_discovery_only_and_extracted_original_is_evidence():
    url = 'https://ag.dji.com/manual?rev=2#checks'
    client = Mock()
    client.search.return_value = {'results': [{'url': url, 'content': 'snippet says 900 ml'},
                                             {'url': 'https://attacker.example/manual', 'content': 'bad'}]}
    client.extract.return_value = {'results': [
        {'url': url, 'raw_content': 'original says 250 ml'},
        {'url': 'https://dji.com/unrequested', 'raw_content': 'unrequested source'}]}
    with patch.object(retrieval, 'plan_web_query', return_value={'query': 'manual checks', 'domains': ['dji.com']}):
        sources = retrieval.retrieve_web('question', tavily_client=client)
    assert [(s.url, s.content) for s in sources] == [(url, 'original says 250 ml')]
    assert client.extract.call_args.kwargs['urls'] == [url]
    assert client.search.call_args.kwargs['include_domains'] == ['dji.com']


@pytest.mark.parametrize('stage', ['plan', 'search', 'extract'])
def test_timeout_stops_before_any_later_stage(stage):
    client = Mock()
    client.search.return_value = {'results': [{'url': 'https://dji.com/manual', 'content': 'snippet'}]}
    plan = {'query': 'manual checks', 'domains': ['dji.com']}
    if stage == 'search':client.search.side_effect = TimeoutError('synthetic')
    if stage == 'extract':client.extract.side_effect = TimeoutError('synthetic')
    diag=[]
    with patch.object(retrieval, 'plan_web_query', side_effect=TimeoutError('synthetic') if stage=='plan' else None,
                      return_value=plan):
        assert retrieval.retrieve_web('question', tavily_client=client, diagnostics=diag) == []
    assert diag[-1]['error_code'] == 'timeout'
    if stage=='plan':client.search.assert_not_called()
    if stage!='extract':client.extract.assert_not_called()


def test_caat_timeout_does_not_start_search_after_failed_designated_fetch():
    client=Mock();client.extract.side_effect=TimeoutError('synthetic')
    diag=[]
    assert retrieval.retrieve_web('กฎการบิน', True, tavily_client=client, diagnostics=diag) == []
    client.search.assert_not_called()
    assert diag[-1]['error_code'] == 'timeout'


def test_caat_search_snippet_cannot_replace_an_empty_designated_document():
    client=Mock()
    client.extract.return_value={'results':[]}
    client.search.return_value={'results':[{'url':'https://www.caat.or.th/guide',
                                           'content':'Unfetched search summary with legal claims'}]}
    assert retrieval.retrieve_web('กฎการบิน',True,tavily_client=client)==[]
    client.search.assert_not_called()


def test_caat_unrequested_urls_cannot_enter_the_evidence_even_on_a_trusted_domain():
    client=Mock()
    client.extract.return_value={'results':[{'url':'https://www.caat.or.th/unrequested',
                                            'raw_content':'Unrequested source'}]}
    assert retrieval.retrieve_web('กฎการบิน',True,tavily_client=client)==[]
    client.search.assert_not_called()


def test_fetched_web_text_is_not_discarded_by_a_hidden_line_or_three_chunk_limit():
    lines=['ข้อความบรรทัดยาว '+('ก'*5000)]+[f'ส่วนที่ {i} '+('ข'*2400) for i in range(7)]
    content='\n'.join(lines)
    sources=web.web_evidence([web.WebSearchResult('คู่มือ','https://doa.go.th/manual',content)])
    assert '\n'.join(s.content for s in sources)==content
    assert len(sources)>3


def test_partial_extraction_timeout_stops_instead_of_using_other_pages():
    client=Mock()
    client.search.return_value={'results':[{'url':'https://dji.com/manual','content':'snippet'}]}
    client.extract.return_value={'results':[{'url':'https://dji.com/manual','raw_content':'partial text'}],
        'failed_results':[{'url':'https://dji.com/other','error':'Request timed out'}]}
    diag=[]
    with patch.object(retrieval,'plan_web_query',return_value={'query':'manual checks','domains':['dji.com']}):
        assert retrieval.retrieve_web('question',tavily_client=client,diagnostics=diag)==[]
    assert diag[-1]['error_code']=='timeout'


@pytest.mark.parametrize('domain',['dji.com','ag.dji.com'])
def test_agricultural_manufacturer_preserves_allowed_planned_domain(domain):
    with patch.object(retrieval,'call_llm',return_value=json.dumps({
            'query':'manufacturer preflight manual','domains':[domain]})):
        assert retrieval.plan_web_query('โดรนเกษตรตรวจอะไร')['domains']==[domain]
    assert retrieval.application_domains(['dji.com'],'คู่มือ Inspire')==['dji.com']


def test_parent_domain_and_agricultural_section_both_remain_searchable():
    assert retrieval.application_domains(['ag.dji.com', 'dji.com'], 'คู่มือโดรนเกษตร') == ['ag.dji.com', 'dji.com']


def test_nonagricultural_product_pages_cannot_cross_the_planned_section_filter():
    client=Mock();client.search.return_value={'results':[
        {'url':'https://www.dji.com/support/product/inspire-1','content':'wrong family'},
        {'url':'https://ag.dji.com/manual','content':'agricultural manual'}]}
    client.extract.return_value={'results':[{'url':'https://ag.dji.com/manual','raw_content':'source facts'}]}
    with patch.object(retrieval,'plan_web_query',return_value={'query':'manual','domains':['ag.dji.com']}):
        result=retrieval.retrieve_web('question',tavily_client=client)
    assert [r.url for r in result]==['https://ag.dji.com/manual']
    assert client.extract.call_args.kwargs['urls']==['https://ag.dji.com/manual']
