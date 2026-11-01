"""Known crop scope and multi-row citations, preserving unknowns and provenance."""
import json
from unittest.mock import patch

import pytest

from app.rag import support_pipeline as support
from app.rag.evidence import Evidence, parse_grounded_result


def payload_and_result(question, source, raw):
    with patch.object(support,'call_llm',return_value=raw) as model:
        result=support.run_support_pipeline(question,source='kb',evidence_override=[source])
    return json.loads(model.call_args.args[0][-1]['content']),result


def test_single_crop_scope_drops_only_rows_explicitly_for_other_crops():
    source=Evidence('D1','ชื่อ | พืชที่ใช้ | อัตรา (ml)\n'
        'Alpha | ข้าวโพด | 10\nBeta | อ้อย | 20\nGamma | ไม่ระบุ | 30\nDelta | อ้อยและข้าวโพด | 40',
        'manual.pdf','4')
    raw=json.dumps({'action':'answer','status':'sufficient','claims':[
        {'text':'Beta 20 ml','evidence':[{'source_id':'D1','line':2}]}]},ensure_ascii=False)
    payload,result=payload_and_result('อัตรา Beta ในอ้อยเท่าไร',source,raw)
    visible=payload['sources'][0]['content']
    assert 'Alpha | ข้าวโพด' not in visible
    assert 'Beta | อ้อย | 20' in visible and 'Gamma | ไม่ระบุ | 30' in visible
    assert 'Delta | อ้อยและข้าวโพด | 40' in visible
    assert payload['row_scope']==[{'source_id':'D1','reason':'explicit_other_crops','removed_rows':1}]
    assert result.citation_checks_passed,result.grade_reason
    assert result.evidence_trace[0]['evidence'][0]['quote']=='Beta | อ้อย | 20'
    assert result.post_selection_evidence[0]['content']==source.content


@pytest.mark.parametrize('question',['เปรียบเทียบอ้อยกับข้าวโพด','ยกเว้นอ้อยมีพืชอะไร',
                                    'อ้อยและข้าวโพดใช้อะไร','พืชทั้งหมดใช้อะไร'])
def test_multi_crop_comparison_or_exclusion_does_not_hide_rows(question):
    source=Evidence('D1','ชื่อ | พืชที่ใช้ | อัตรา (ml)\nAlpha | ข้าวโพด | 10\nBeta | อ้อย | 20','manual.pdf','4')
    diag=[]
    assert support.scope_answer_sources(question,[source],diag)==[source]
    assert diag==[]


def test_unknown_crop_and_non_applicability_columns_are_not_inferred():
    source=Evidence('D1','ชื่อ | หมายเหตุ | อัตรา (ml)\nข้าวโพดพิเศษ | ไม่ระบุพืช | 10\nB | ทั่วไป | 20',
                    'manual.pdf','4')
    assert support.scope_answer_sources('ใช้ในอ้อยได้ไหม',[source],[])==[source]


def test_hidden_rows_cannot_be_referenced_by_guessing_original_line_numbers_or_quotes():
    source=Evidence('D1','ชื่อ | พืชที่ใช้ | อัตรา (ml)\nAlpha | ข้าวโพด | 10\nBeta | อ้อย | 20',
                    'manual.pdf','4')
    for citation in ({'source_id':'D1','line':2},{'source_id':'D1','quote':'Alpha | ข้าวโพด | 10'}):
        raw=json.dumps({'action':'answer','status':'sufficient','claims':[
            {'text':'Alpha 10 ml','evidence':[citation]}]},ensure_ascii=False)
        payload,result=payload_and_result('อ้อยใช้ Alpha เท่าไร',source,raw)
        assert 'Alpha | ข้าวโพด' not in payload['sources'][0]['content']
        assert result.source_type=='abstain' and not result.citation_checks_passed


def test_web_and_numeric_ranking_keep_original_scope():
    url='https://doa.go.th/example'
    source=Evidence('W1','ชื่อ | พืช | ค่า\nAlpha | ข้าวโพด | 10',url=url)
    assert support.scope_answer_sources('อ้อยใช้อะไร',[source],[])==[source]
    table=Evidence('D1','รุ่น | พืช | ราคา (บาท)\nA | ข้าวโพด | 10\nB | อ้อย | 20','models.pdf','1')
    payload=json.loads(support.build_messages('ราคาถูกที่สุดในอ้อย',[table],'kb',[])[1]['content'])
    assert payload['table_view']=='schema_for_calculation' and payload['row_scope']==[]


def rows_and_claim():
    names=['Alpha','Beta','Gamma','Delta','Echo','Foxtrot']
    lines=['รุ่น | อัตรา (ml)']+[f'{name} | {10*(i+1)}' for i,name in enumerate(names)]
    source=Evidence('D1','\n'.join(lines),'manual.pdf','9')
    text='; '.join(f'{name} {10*(i+1)} ml' for i,name in enumerate(names))
    refs=[{'source_id':'D1','line':i+2} for i in range(len(names))]
    return source,text,refs


def test_six_references_are_all_checked_and_preserved_without_weakening_legacy_default():
    source,text,refs=rows_and_claim()
    raw=json.dumps({'action':'answer','status':'sufficient','claims':[{'text':text,'evidence':refs}]},ensure_ascii=False)
    _,result=payload_and_result('ขออัตราทุกรุ่น',source,raw)
    assert result.citation_checks_passed,result.grade_reason
    assert len(result.evidence_trace[0]['evidence'])==6
    assert all(f'{n} ml' in result.answer for n in [10,20,30,40,50,60])
    resolved=json.loads(raw)
    support.resolve_line_references(resolved,[source],[])
    assert not parse_grounded_result(json.dumps(resolved,ensure_ascii=False),[source]).claims


def test_six_references_do_not_allow_swapped_values_or_an_invalid_last_source():
    source,text,refs=rows_and_claim()
    wrong=text.replace('Alpha 10 ml; Beta 20 ml','Alpha 20 ml; Beta 10 ml')
    bad_refs=refs[:-1]+[{'source_id':'D1','line':99}]
    for claim,citations in ((wrong,refs),(text,bad_refs)):
        raw=json.dumps({'action':'answer','status':'sufficient','claims':[{'text':claim,'evidence':citations}]},ensure_ascii=False)
        _,result=payload_and_result('ขออัตราทุกรุ่น',source,raw)
        assert result.source_type=='abstain' and not result.citation_checks_passed


def test_more_than_twenty_references_remains_bounded():
    source=Evidence('D1','\n'.join(f'ข้อ {i} ค่า {i} ml' for i in range(1,22)),'manual.pdf','1')
    refs=[{'source_id':'D1','line':i} for i in range(1,22)]
    raw=json.dumps({'action':'answer','status':'sufficient','claims':[{'text':'ข้อ 1 ค่า 1 ml','evidence':refs}]},ensure_ascii=False)
    _,result=payload_and_result('ขอข้อมูล',source,raw)
    assert result.source_type=='abstain' and not result.citation_checks_passed


def test_cross_source_table_rows_keep_each_value_bound_to_its_name():
    sources=[Evidence(f'D{i+1}', f'Model | Rate (ml)\n{name} | {10*(i+1)}', f'{i}.pdf','1')
             for i,name in enumerate(['Alpha','Beta','Gamma','Delta','Echo','Foxtrot'])]
    refs=[{'source_id':s.id,'line':2} for s in sources]
    correct='; '.join(f'{name} {10*(i+1)} ml' for i,name in enumerate(['Alpha','Beta','Gamma','Delta','Echo','Foxtrot']))
    for text, expected in [(correct,True), (correct.replace('Alpha 10 ml; Beta 20 ml','Alpha 20 ml; Beta 10 ml'),False)]:
        raw=json.dumps({'action':'answer','status':'sufficient','claims':[{'text':text,'evidence':refs}]})
        with patch.object(support,'call_llm',return_value=raw):
            result=support.run_support_pipeline('List rates',source='kb',evidence_override=sources)
        assert result.citation_checks_passed is expected, result.grade_reason


@pytest.mark.parametrize('second',[
    Evidence('D2','Model | Price (ml)\nBeta | 20','b.pdf','2'),
    Evidence('D2','Beta is 20 ml','b.pdf','2'),
])
def test_cross_source_numeric_claim_with_unmatched_schema_fails_closed(second):
    sources=[Evidence('D1','Model | Rate (ml)\nAlpha | 10','a.pdf','1'),second]
    refs=[{'source_id':'D1','line':2},{'source_id':'D2','line':2 if '|' in second.content else 1}]
    raw=json.dumps({'action':'answer','status':'sufficient','claims':[{'text':'Alpha 20 ml; Beta 10 ml','evidence':refs}]})
    with patch.object(support,'call_llm',return_value=raw):
        result=support.run_support_pipeline('List rates',source='kb',evidence_override=sources)
    assert result.source_type=='abstain' and not result.citation_checks_passed
