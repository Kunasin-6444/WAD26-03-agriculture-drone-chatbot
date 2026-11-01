"""Experimental JSON mode changes transport only; normal validation still applies."""
import json
from unittest.mock import patch

import pytest

from app.rag import rag_service, support_pipeline as support
from app.rag.evidence import Evidence
from tests.helpers import llm_client


def test_json_mode_is_explicit_and_does_not_enable_legacy_schema_or_fallback():
    client = llm_client('{}')
    with patch.object(rag_service, 'STRUCTURED_OUTPUT', False):
        assert rag_service.call_llm([{'role':'user','content':'JSON'}], client,
            preferred_model='test-json-only', structured=False, allow_fallback=False, json_mode=True) == '{}'
    assert client.chat.completions.create.call_args.kwargs['response_format'] == {'type':'json_object'}
    for options in ({'structured':True,'allow_fallback':False}, {'structured':False,'allow_fallback':True}):
        with pytest.raises(ValueError):
            rag_service.call_llm([], client, json_mode=True, **options)
    assert client.chat.completions.create.call_count == 1


def test_mode_off_sends_no_provider_format_and_mode_on_still_rejects_wrong_citations():
    source=Evidence('D1','Pump 250 ml','pump.pdf','1')
    for mode, value, accepted in [(False,250,True), (True,250,True), (True,500,False)]:
        raw=json.dumps({'action':'answer','status':'sufficient','claims':[
            {'text':f'Pump {value} ml','evidence':[{'source_id':'D1','line':1}]}]})
        with patch.object(support,'call_llm',return_value=raw) as llm:
            result=support.run_support_pipeline('Pump rate?',source='kb',evidence_override=[source],json_mode=mode)
        assert llm.call_args.kwargs.get('json_mode',False) is mode
        assert result.citation_checks_passed is accepted


def test_json_mode_does_not_accept_plaintext_or_schema_invalid_response():
    source=Evidence('D1','Pump 250 ml','pump.pdf','1')
    for raw in ['Pump 250 ml', '{"action":"answer","claims":"invalid"}']:
        with patch.object(support,'call_llm',return_value=raw):
            result=support.run_support_pipeline('Pump?',source='kb',evidence_override=[source],json_mode=True)
        assert not result.citation_checks_passed and result.source_type=='abstain'


def test_provider_rejection_does_not_retry_without_json_mode():
    source=Evidence('D1','Pump 250 ml','pump.pdf','1')
    client=llm_client()
    client.chat.completions.create.side_effect=RuntimeError('unsupported response format')
    with patch.object(rag_service, 'get_llm_client', return_value=client):
        result=support.run_support_pipeline('Pump?',source='kb',evidence_override=[source],json_mode=True)
    assert result.source_type == 'abstain' and result.error_code
    assert client.chat.completions.create.call_count == 1
    assert client.chat.completions.create.call_args.kwargs['response_format'] == {'type':'json_object'}
