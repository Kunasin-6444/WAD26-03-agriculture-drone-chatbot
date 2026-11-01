"""Source presentation, failure visibility and calculation boundaries; offline."""
import json
import re
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.rag import rag_service, support_pipeline as support
from app.rag.evidence import Evidence, parse_grounded_result
from app.rag.structured_tables import TableCatalog
from app.rag.table_query import execute, QueryError
from scripts.rag_evaluation_trace import capture_pipeline


def original_content(numbered):
    return '\n'.join(re.sub(r'^L[1-9]\d*: ', '', line) for line in numbered.splitlines())


def reply(claims):
    return json.dumps({'action':'answer','status':'sufficient','intro':'','claims':claims},ensure_ascii=False)


def claim(text, source_id, quote):
    return {'text':text,'evidence':[{'source_id':source_id,'quote':quote}]}


def procedure():
    header = 'ลำดับ | งาน | เงื่อนไข'
    return [Evidence('D1',header+'\n1 | เปิดวาล์ว | ก่อนเปิดปั๊ม\n2 | เปิดปั๊ม | หลังเปิดวาล์ว','procedure.pdf','7'),
            Evidence('D2',header+'\n3 | ปิดปั๊ม | ก่อนปิดวาล์ว\n4 | ปิดวาล์ว | หลังปิดปั๊ม','procedure.pdf','8')]


def test_procedure_payload_preserves_each_original_row_order_condition_and_page():
    sources=procedure()
    payload=json.loads(support.build_messages('ขั้นตอนเริ่มจากอะไรและปิดวาล์วตอนไหน',sources,'kb',[])[1]['content'])
    assert [(original_content(e['content']),e['page_number']) for e in payload['sources']]==[(e.content,e.page_number) for e in sources]
    assert payload['table_schemas']==[]
    assert payload['table_view']=='original_rows_with_provenance'


def test_answer_can_cite_two_continuation_pages_without_merging_or_reassigning_sources():
    sources=procedure()
    raw=reply([claim('เริ่มจากเปิดวาล์วก่อนเปิดปั๊ม','D1',sources[0].content.splitlines()[1]),
               claim('ปิดวาล์วหลังปิดปั๊ม','D2',sources[1].content.splitlines()[2])])
    with patch.object(support,'call_llm',return_value=raw) as model:
        result=support.run_support_pipeline('ขั้นตอนเริ่มจากอะไรและปิดวาล์วตอนไหน',source='kb',evidence_override=sources)
    assert result.citation_checks_passed,result.grade_reason
    assert len(result.evidence_trace)==2 and model.call_count==1
    assert 'หน้า 7' in result.answer and 'หน้า 8' in result.answer
    assert result.post_selection_evidence[0]['content']==sources[0].content
    assert model.call_args.kwargs['allow_fallback'] is False


@pytest.mark.parametrize('content',[
    'งาน | เกณฑ์\nตรวจซีล | ไม่มีรอยรั่ว\nตรวจสาย | ฉนวนไม่ขาด',
    'Step | Action | Note\n1 | Open |\n2 | Close | After drain | unaligned note',
    'ตรวจวาล์ว A | B ตามตำแหน่งบนเครื่อง',
])
def test_text_only_ragged_tables_and_literal_pipes_are_never_silently_deleted(content):
    source=Evidence('D1',content,'manual.pdf','1')
    payload=json.loads(support.build_messages('ต้องตรวจอะไร', [source], 'kb', [])[1]['content'])
    assert original_content(payload['sources'][0]['content'])==content


def test_wrong_step_number_is_rejected_even_if_that_number_exists_elsewhere_on_the_page():
    sources=procedure()
    data=reply([claim('ลำดับที่ 2 เปิดวาล์ว','D1',sources[0].content.splitlines()[1])])
    assert not parse_grounded_result(data,sources).claims


def test_a_numeric_fact_cannot_borrow_its_value_from_outside_the_actual_quote():
    source=Evidence('D1','ตั้งแรงดัน 7 bar\nอุณหภูมิ 35 C','manual.pdf','1')
    bad=reply([claim('ตั้งแรงดัน 35 bar','D1','ตั้งแรงดัน 7 bar')])
    good=reply([claim('ตั้งแรงดัน 7 bar','D1','ตั้งแรงดัน 7 bar')])
    assert not parse_grounded_result(bad,[source]).claims
    assert parse_grounded_result(good,[source]).claims


def test_context_omissions_are_visible_to_the_model_and_do_not_mutate_kept_sources():
    sources=procedure(); diagnostics=[]
    kept=support.pack_context(sources,'kb',diagnostics,len(json.dumps(sources[0].__dict__,ensure_ascii=False)))
    payload=json.loads(support.build_messages('ขั้นตอนอะไร',kept,'kb',diagnostics)[1]['content'])
    assert payload['omitted_sources']==[{'source_id':'D2','reason':'whole_chunk_budget'}]
    assert original_content(payload['sources'][0]['content'])==sources[0].content


def test_duplicate_source_ids_fail_before_any_generation():
    sources=procedure(); sources[1]=Evidence('D1',sources[1].content,'procedure.pdf','8')
    with patch.object(support,'call_llm') as model:
        result=support.run_support_pipeline('ขั้นตอนอะไร',source='kb',evidence_override=sources)
    model.assert_not_called()
    assert result.error_code=='invalid_response'


def test_partial_answer_metadata_keeps_the_missing_aspect():
    source=Evidence('D1','ตรวจซีลว่าไม่มีรอยรั่ว','manual.pdf','1')
    data=json.loads(reply([claim(source.content,'D1',source.content)]))
    data.update(status='partial',missing_aspects=['ขั้นตอนปิดเครื่อง'])
    with patch.object(support,'call_llm',return_value=json.dumps(data,ensure_ascii=False)):
        result=support.run_support_pipeline('ตรวจซีลและปิดเครื่องอย่างไร',source='kb',evidence_override=[source])
    assert result.missing_aspect=='ขั้นตอนปิดเครื่อง'
    assert result.post_selection_evidence[0]['content']==source.content


def test_strict_single_call_does_not_fail_over_after_an_instant_quota_error():
    client=MagicMock(); error=RuntimeError('daily limit'); error.status_code=401
    client.chat.completions.create.side_effect=error
    with patch.dict(rag_service._EXHAUSTED_MODELS,{},clear=True), \
         patch.dict(rag_service._MODEL_FAILURES,{},clear=True), \
         patch.object(rag_service,'FALLBACK_MODELS',['another-model']), \
         patch.object(rag_service,'get_secondary_client') as secondary:
        with pytest.raises(rag_service.LLMUnavailableError):
            rag_service.call_llm([],client,preferred_model='pinned',allow_fallback=False,max_attempts=1)
    assert client.chat.completions.create.call_count==1
    secondary.assert_not_called()


def test_incomplete_completion_is_preserved_in_trace_but_never_delivered_as_an_answer():
    client=MagicMock()
    client.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
        finish_reason='length',message=SimpleNamespace(content='{"claims":['))])
    with patch.dict(rag_service._EXHAUSTED_MODELS,{},clear=True), \
         capture_pipeline('support') as trace:
        result=support.run_support_pipeline('ตรวจอะไร',client=client,source='kb',evidence_override=[
            Evidence('D1','ตรวจซีลว่าไม่มีรอยรั่ว','manual.pdf','1')])
    assert result.error_code=='invalid_response' and not result.generation_succeeded
    assert result.raw_answer=='{"claims":[' and result.raw_answer not in result.answer
    assert trace['generation'][0]['finish_reason']=='length'
    assert trace['generation'][0]['partial_response']==result.raw_answer
    assert client.chat.completions.create.call_count==1


def test_unbounded_lookup_no_longer_defaults_to_an_arbitrary_single_row():
    source=Evidence('D1','รุ่น | ถัง (ลิตร)\nAlpha | 12\nBeta | 20','models.pdf','1')
    catalog=TableCatalog.build([source],[])
    plan={'action':'table_query','table_id':catalog.tables[0].id,'operation':'select','select':['c0','c1']}
    _,rows,_,event=execute(catalog,plan)
    assert len(rows)==2 and not event['truncated']
    plan.update(column='c1',order='desc')
    _,rows,_,_=execute(catalog,plan)
    assert [row.cells[0] for row in rows]==['Beta','Alpha']
    plan['column']='not-a-column'
    with pytest.raises(QueryError):execute(catalog,plan)


def test_entity_price_conflict_cannot_be_hidden_by_a_changed_secondary_spec():
    source=Evidence('D1','รุ่น | ถัง (ลิตร) | ราคา (บาท)\nAlpha | 12 | 80000\nAlpha | 20 | 70000','models.pdf','1')
    proof={'source_file':'models.pdf','table_id':'models','coverage':'complete','total_chunks':1,
           'included_chunks':[(source.source_file,source.page_number,source.content)]}
    catalog=TableCatalog.build([source],[{'tables':[proof]}])
    plan={'action':'table_query','table_id':catalog.tables[0].id,'operation':'min','column':'c2'}
    with pytest.raises(QueryError,match='Conflicting'):execute(catalog,plan)


def test_another_table_on_the_same_page_cannot_supply_the_anchors_metadata():
    from app.rag.candidate.table_continuation import assemble_candidate_table_evidence
    anchor=Evidence('D1','ลำดับ | งาน\n1 | เปิดวาล์ว','manual.pdf','7')
    other=Evidence('D2','รุ่น | ราคา\nBeta | 80000','manual.pdf','7')
    assembled,diag=assemble_candidate_table_evidence([anchor],'ขอข้อมูลในตาราง',
        lookup_fn=lambda *args:[(other,{'table_id':'unrelated','row_start':'20'})])
    assert all(e.content!=other.content for e in assembled)
    assert all(t['table_id']!='unrelated' for t in diag['tables'])


def test_known_incomplete_extraction_cannot_be_certified_as_complete_table_coverage():
    from app.rag.candidate.table_continuation import assemble_candidate_table_evidence
    source=Evidence('D1','รุ่น | ราคา (บาท)\nAlpha | 80000','models.pdf','1')
    assembled,diag=assemble_candidate_table_evidence([source],'รุ่นไหนราคาถูกที่สุด',
        lookup_fn=lambda *args:[(source,{'table_id':'models','extraction_complete':'false'})])
    assert diag['tables'][0]['coverage']=='incomplete'
    assert diag['tables'][0]['extraction_incomplete_chunks']
    assert not TableCatalog.build(assembled,[diag]).tables[0].complete


def test_table_lookup_timeout_is_not_swallowed_as_unknown_but_usable_scope():
    from app.rag.candidate.table_continuation import assemble_candidate_table_evidence
    def timeout(*args):raise TimeoutError('exhausted lookup budget')
    with pytest.raises(TimeoutError):
        assemble_candidate_table_evidence([procedure()[0]],'ขอข้อมูลในตาราง',lookup_fn=timeout)


def test_strict_model_cooldown_keeps_its_actual_failure_code_and_does_not_call_another_model():
    import time
    client=MagicMock()
    with patch.dict(rag_service._EXHAUSTED_MODELS,{'pinned':time.monotonic()+3600},clear=True), \
         patch.dict(rag_service._MODEL_FAILURES,{'pinned':'quota_exhausted'},clear=True), \
         patch.object(rag_service,'FALLBACK_MODELS',['available-model']):
        with pytest.raises(rag_service.LLMUnavailableError) as error:
            rag_service.call_llm([],client,preferred_model='pinned',allow_fallback=False)
    assert error.value.error_code=='quota_exhausted'
    client.chat.completions.create.assert_not_called()


def test_a_requested_full_list_is_not_rejected_by_the_legacy_short_body_cap():
    lines=[f'จุดที่ {i} '+('ตรวจจุดเชื่อมต่อว่าแน่น ไม่มีรอยร้าวและไม่มีรอยรั่ว '*4) for i in range(1,11)]
    source=Evidence('D1','\n'.join(lines),'inspection.pdf','1')
    data=reply([claim(line,'D1',line) for line in lines])
    assert 1800<sum(len(line)+4 for line in lines)<3200
    assert not parse_grounded_result(data,[source],max_claims=32).claims
    with patch.object(support,'call_llm',return_value=data):
        result=support.run_support_pipeline('ขอจุดตรวจทั้งหมดพร้อมรายละเอียด',source='kb',evidence_override=[source])
    assert result.citation_checks_passed,result.grade_reason
    assert len(result.evidence_trace)==10


def test_rendered_abstention_cannot_be_reported_as_a_verified_knowledge_answer():
    sources=[Evidence(f'D{i}','ตรวจซีลว่าไม่มีรอยรั่ว','manual'+str(i)+('x'*220)+'.pdf',str(i)) for i in range(20)]
    data=reply([claim(e.content,e.id,e.content) for e in sources])
    with patch.object(support,'call_llm',return_value=data):
        result=support.run_support_pipeline('ขอข้อมูลทั้งหมด',source='kb',evidence_override=sources)
    assert result.source_type=='abstain' and not result.citation_checks_passed
    assert 'delivery size' in result.grade_reason
