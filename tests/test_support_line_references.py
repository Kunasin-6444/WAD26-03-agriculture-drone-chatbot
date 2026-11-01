"""Untrusted line references become exact quotes; no provider calls."""
import json
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest.mock import patch
from unittest.mock import MagicMock

import pytest

from app.rag import support_pipeline as support
from app.rag.evidence import Evidence
from app.rag.structured_tables import TableCatalog


def make_answer(text, citations, status='sufficient', missing=None):
    return json.dumps({'action':'answer','status':status,'missing_aspects':missing or [],
        'claims':[{'text':text,'evidence':citations}]},ensure_ascii=False)


def run(question, sources, raw):
    with patch.object(support,'call_llm',return_value=raw) as llm:
        result=support.run_support_pipeline(question,source='kb',evidence_override=sources)
    return result,json.loads(llm.call_args.args[0][-1]['content'])


def xml_response(values):
    root=ET.Element('invoke',{'name':'respond'})
    for key,value in values.items():
        child=ET.SubElement(root,'parameter',{'name':key})
        child.text=json.dumps(value,ensure_ascii=False) if isinstance(value,(dict,list,int)) else value
    return ET.tostring(root,encoding='unicode')


def test_numbered_source_keeps_full_lines_and_server_resolves_real_quote_and_page():
    source=Evidence('D1','จุดตรวจ | รายละเอียด\nใบพัด | ไม่มีรอยร้าว\nมอเตอร์ | ไม่มีเสียงผิดปกติ','inspection.pdf','7')
    raw=make_answer('ตรวจใบพัดว่าไม่มีรอยร้าว',[{'source_id':'D1','line':2}])
    result,payload=run('ตรวจใบพัดอย่างไร',[source],raw)
    assert payload['sources'][0]['content'].splitlines()==[
        'L1: จุดตรวจ | รายละเอียด','L2: ใบพัด | ไม่มีรอยร้าว','L3: มอเตอร์ | ไม่มีเสียงผิดปกติ']
    assert payload['response_contract']['answer']['claims'][0]['evidence']==[{'source_id':'','line':1}]
    assert result.citation_checks_passed,result.grade_reason
    assert result.evidence_trace[0]['evidence'][0]['quote']=='ใบพัด | ไม่มีรอยร้าว'
    assert 'inspection.pdf, หน้า 7' in result.answer
    with patch.object(support,'resolve_line_references',lambda *args:None):
        with patch.object(support,'call_llm',return_value=raw):
            without_fix=support.run_support_pipeline('ตรวจใบพัดอย่างไร',source='kb',evidence_override=[source])
    assert without_fix.source_type=='abstain'


def test_header_denominator_is_cited_from_the_same_row_and_column_only():
    table=('ชื่อ | อัตราการใช้ (ต่อน้ำ 20 ลิตร)\n'
           'Alpha | 50-70 ซีซี\nBeta | 90-100 ซีซี')
    source=Evidence('D1',table,'manual.pdf','4')
    raw=make_answer('Alpha ใช้ 50-70 ซีซีต่อน้ำ 20 ลิตร',[{'source_id':'D1','line':2}])
    result,_=run('Alpha ใช้อัตราเท่าไร',[source],raw)
    assert result.citation_checks_passed, result.grade_reason
    assert {e['quote'] for e in result.evidence_trace[0]['evidence']} == {table.splitlines()[0],table.splitlines()[1]}
    with patch.object(support,'attach_table_denominator_headers',lambda *args: None):
        before,_=run('Alpha ใช้อัตราเท่าไร',[source],raw)
    assert before.source_type=='abstain'
    for wrong in ['Alpha ใช้ 90-100 ซีซีต่อน้ำ 20 ลิตร',
                  'Alpha ใช้ 50-70 ซีซีต่อน้ำ 25 ลิตร',
                  'Alpha ใช้ 50-70 กรัมต่อน้ำ 20 ลิตร']:
        bad,_=run('Alpha ใช้อัตราเท่าไร',[source],make_answer(wrong,[{'source_id':'D1','line':2}]))
        assert bad.source_type=='abstain', wrong


def test_unrelated_column_or_prose_cannot_supply_a_missing_denominator():
    table=('ชื่อ | ปริมาณ (ซีซี) | หมายเหตุ (ต่อน้ำ 20 ลิตร)\nAlpha | 50-70 | ทั่วไป')
    source=Evidence('D1',table,'manual.pdf','4')
    raw=make_answer('Alpha ใช้ 50-70 ซีซีต่อน้ำ 20 ลิตร',[{'source_id':'D1','line':2}])
    result,_=run('Alpha ใช้อัตราเท่าไร',[source],raw)
    assert result.source_type=='abstain'


@pytest.mark.parametrize('number', [0,-1,3,True,'2','L0','L2x',None,1.2])
def test_bad_or_ambiguous_line_id_never_resolves(number):
    source=Evidence('D1','หัวข้อ\nปั๊ม 250 ml','pump.pdf','2')
    raw=make_answer('ปั๊ม 250 ml',[{'source_id':'D1','line':number}])
    result,_=run('ปั๊มเท่าไร',[source],raw)
    assert result.source_type=='abstain'
    assert not result.citation_checks_passed


def test_l_prefix_is_the_same_displayed_line_and_other_source_ids_are_not_guessed():
    source=Evidence('D1','หัวข้อ\nปั๊ม 250 ml','pump.pdf','2')
    good,_=run('ปั๊มเท่าไร',[source],make_answer('ปั๊ม 250 ml',[{'source_id':'D1','line':'L2'}]))
    wrong,_=run('ปั๊มเท่าไร',[source],make_answer('ปั๊ม 250 ml',[{'source_id':'D2','line':2}]))
    assert good.citation_checks_passed and '250 ml' in good.answer
    assert wrong.source_type=='abstain'


def test_web_line_reference_preserves_the_fetched_url_and_never_uses_kb():
    url='https://doa.go.th/manual?id=42#flow'
    source=Evidence('W1','อัตราการไหล 250 ml',url=url,title='คู่มือ')
    raw=make_answer('อัตราการไหล 250 ml',[{'source_id':'W1','line':1}])
    with patch.object(support,'call_llm',return_value=raw), \
         patch.object(support,'retrieve_evidence') as kb, \
         patch.object(support,'search_web_fallback') as web:
        result=support.run_support_pipeline('อัตราเท่าไร',source='web',evidence_override=[source])
    kb.assert_not_called();web.assert_not_called()
    assert result.source_type=='web_fallback' and result.citation_checks_passed
    assert url in result.answer and result.evidence_trace[0]['evidence'][0]['url']==url


def test_a_reference_cannot_override_its_line_with_a_fabricated_quote():
    source=Evidence('D1','Alpha | 7 bar\nBeta | 35 bar','pump.pdf','2')
    raw=make_answer('Alpha 35 bar',[{'source_id':'D1','line':1,'quote':'Beta | 35 bar'}])
    result,_=run('Alpha pressure?',[source],raw)
    assert result.source_type=='abstain'


def test_wrong_number_from_another_line_is_still_rejected():
    source=Evidence('D1','รุ่น | แรงดัน (bar)\nAlpha | 7\nBeta | 35','pump.pdf','2')
    result,_=run('Alpha pressure?',[source],make_answer('Alpha 35 bar',[{'source_id':'D1','line':2}]))
    assert result.source_type=='abstain'


def test_bad_reference_drops_only_its_claim_and_marks_the_answer_partial():
    source=Evidence('D1','ใบพัดไม่มีรอยร้าว\nมอเตอร์ไม่มีเสียงผิดปกติ','inspection.pdf','1')
    raw=json.dumps({'action':'answer','status':'sufficient','claims':[
        {'text':'ใบพัดไม่มีรอยร้าว','evidence':[{'source_id':'D1','line':1}]},
        {'text':'มอเตอร์ไม่มีเสียงผิดปกติ','evidence':[{'source_id':'D1','line':99}]}]},ensure_ascii=False)
    result,_=run('ตรวจอะไร',[source],raw)
    assert result.source_type=='knowledge_base' and 'ใบพัดไม่มีรอยร้าว' in result.answer
    assert 'มอเตอร์ไม่มีเสียงผิดปกติ' not in result.answer
    assert 'ยังยืนยันไม่ได้' in result.answer and not result.citation_checks_passed


def test_long_line_cannot_be_misrepresented_as_a_short_reference_but_exact_quote_still_works():
    line='รายละเอียด '+('ก'*820)+' ค่า 250 ml'
    source=Evidence('D1',line,'long.pdf','1')
    invalid,_=run('ค่าเท่าไร',[source],make_answer('ค่า 250 ml',[{'source_id':'D1','line':1}]))
    exact,_=run('ค่าเท่าไร',[source],make_answer('ค่า 250 ml',[{'source_id':'D1','quote':'ค่า 250 ml'}]))
    assert invalid.source_type=='abstain'
    assert exact.citation_checks_passed and '250 ml' in exact.answer


def test_weed_emergence_alone_does_not_satisfy_a_request_about_crop_emergence():
    source=Evidence('D1','สาร | อัตรา (กรัม/ไร่) | ช่วงใช้\nอัลฟาซีน | 35-45 | ก่อนวัชพืชงอก','guide.pdf','18')
    raw=make_answer('อัลฟาซีน 35-45 กรัม/ไร่ พ่นก่อนวัชพืชงอก',[{'source_id':'D1','line':2}])
    result,_=run('ก่อนอ้อยงอกใช้สารอะไร',[source],raw)
    assert result.citation_checks_passed
    assert 'ก่อนวัชพืชงอก' in result.answer
    assert 'ยังไม่พบหลักฐานยืนยันเงื่อนไขก่อนอ้อยงอก' in result.answer
    assert result.missing_aspect and any(d.get('stage')=='question_condition' for d in result.diagnostics)


def test_requested_phase_with_no_phase_in_any_quote_is_also_marked_partial():
    source=Evidence('D1','อัลฟาซีน 35 กรัม/ไร่','guide.pdf','18')
    result,_=run('ก่อนอ้อยงอกใช้สารอะไร',[source],make_answer(source.content,[{'source_id':'D1','line':1}]))
    assert result.citation_checks_passed and 'ยังไม่พบหลักฐานยืนยันเงื่อนไขก่อนอ้อยงอก' in result.answer


def test_explicitly_cited_crop_phase_is_not_marked_missing():
    source=Evidence('D1','อัลฟาซีน พ่นก่อนอ้อยงอก','guide.pdf','18')
    result,_=run('ก่อนอ้อยงอกใช้สารอะไร',[source],make_answer(source.content,[{'source_id':'D1','line':1}]))
    assert result.citation_checks_passed and 'ยังไม่พบหลักฐานยืนยันเงื่อนไข' not in result.answer


def test_phase_from_an_unrelated_claim_cannot_complete_a_weed_only_row():
    sources=[Evidence('D1','อัลฟาซีน พ่นก่อนวัชพืชงอก','guide.pdf','18'),
             Evidence('D2','เบตาซีน พ่นก่อนอ้อยงอก','guide.pdf','19')]
    raw=json.dumps({'action':'answer','status':'sufficient','claims':[
        {'text':'อัลฟาซีน พ่นก่อนวัชพืชงอก','evidence':[{'source_id':'D1','line':1}]},
        {'text':'เบตาซีน พ่นก่อนอ้อยงอก','evidence':[{'source_id':'D2','line':1}]}]},ensure_ascii=False)
    result,_=run('ก่อนอ้อยงอกใช้สารอะไร',sources,raw)
    assert 'ยังไม่พบหลักฐานยืนยันเงื่อนไขก่อนอ้อยงอก' in result.answer


def test_phase_from_another_claim_cannot_complete_a_row_with_no_phase():
    sources=[Evidence('D1','อัลฟาซีน 35 กรัม/ไร่','guide.pdf','18'),
             Evidence('D2','เบตาซีน พ่นก่อนอ้อยงอก','guide.pdf','19')]
    raw=json.dumps({'action':'answer','status':'sufficient','claims':[
        {'text':'อัลฟาซีน 35 กรัม/ไร่','evidence':[{'source_id':'D1','line':1}]},
        {'text':'เบตาซีน พ่นก่อนอ้อยงอก','evidence':[{'source_id':'D2','line':1}]}]},ensure_ascii=False)
    result,_=run('ก่อนอ้อยงอกใช้สารอะไร',sources,raw)
    assert 'ยังไม่พบหลักฐานยืนยันเงื่อนไขก่อนอ้อยงอก' in result.answer


@pytest.mark.parametrize('raw', ['<invoke name="respond"><parameter name="action">answer</parameter></invoke>',
                                  '{"action":"answer","claims":['])
def test_markup_or_incomplete_json_is_never_parsed_as_a_valid_answer(raw):
    source=Evidence('D1','อัตรา 250 ml','pump.pdf','1')
    result,_=run('อัตราเท่าไร',[source],raw)
    assert result.source_type=='abstain' and result.error_code=='invalid_response'
    assert raw not in result.answer and not result.citation_checks_passed


def test_complete_respond_envelope_resolves_line_and_validates_facts_without_invoking_a_tool():
    source=Evidence('D1','อัตรา 250 ml','pump.pdf','1')
    raw=xml_response({'action':'answer','status':'sufficient','missing_aspects':[],
        'claims':[{'text':'อัตรา 250 ml','evidence':[{'source_id':'D1','line':1}]}]})
    result,_=run('อัตราเท่าไร',[source],raw)
    assert result.citation_checks_passed and '250 ml' in result.answer
    assert result.evidence_trace[0]['evidence'][0]['quote']==source.content
    assert any(d.get('format')=='respond_xml' for d in result.diagnostics)


@pytest.mark.parametrize('raw',[
    '<invoke name="tool"><parameter name="action">answer</parameter></invoke>',
    '<!DOCTYPE x [<!ENTITY a "250">]><invoke name="respond"></invoke>',
    '<invoke name="respond"><parameter name="action">answer</parameter><parameter name="action">answer</parameter></invoke>',
    '<invoke name="respond"><parameter name="action">answer</parameter><parameter name="url">https://bad.example</parameter></invoke>',
    '<invoke name="respond"><parameter name="action"><nested>answer</nested></parameter></invoke>',
])
def test_xml_envelope_rejects_tool_invocation_entities_and_unexpected_structure(raw):
    source=Evidence('D1','อัตรา 250 ml','pump.pdf','1')
    result,_=run('อัตราเท่าไร',[source],raw)
    assert result.source_type=='abstain' and not result.citation_checks_passed


def test_complete_xml_cannot_bypass_line_or_numeric_grounding():
    source=Evidence('D1','Alpha | 7 bar\nBeta | 35 bar','pump.pdf','1')
    raw=xml_response({'action':'answer','status':'sufficient','missing_aspects':[],
        'claims':[{'text':'Alpha 35 bar','evidence':[{'source_id':'D1','line':1}]}]})
    result,_=run('Alpha pressure?',[source],raw)
    assert result.source_type=='abstain' and not result.citation_checks_passed


def test_complete_xml_query_still_uses_the_verified_numeric_executor():
    source=Evidence('D1','รุ่น | ราคา (บาท)\nAlpha | 80\nBeta | 70','models.pdf','1')
    proof={'source_file':'models.pdf','table_id':'models','coverage':'complete','total_chunks':1,
           'included_chunks':[(source.source_file,source.page_number,source.content)]}
    catalog=TableCatalog.build([source],[{'tables':[proof]}])
    raw=xml_response({'action':'table_query','table_id':catalog.tables[0].id,'operation':'min',
        'column':'c1','limit':1,'select':['c0','c1'],'filters':[],'unsupported_aspects':[]})
    with patch.object(support,'call_llm',return_value=raw):
        result=support.run_support_pipeline('รุ่นไหนราคาถูกที่สุด',source='kb',evidence_override=[source],
                                            table_coverage_override=[proof])
    assert result.citation_checks_passed,result.grade_reason
    assert 'Beta' in result.answer and '70 บาท' in result.answer and 'Alpha' not in result.answer


def test_truncated_respond_envelope_is_not_repaired_or_passed_to_the_xml_parser():
    source=Evidence('D1','อัตรา 250 ml','pump.pdf','1')
    raw='<invoke name="respond"><parameter name="action">answer</parameter><parameter name="claims">['
    client=MagicMock()
    client.chat.completions.create.return_value=SimpleNamespace(choices=[SimpleNamespace(
        finish_reason='length',message=SimpleNamespace(content=raw))])
    with patch.object(support,'parse_response_envelope') as parser:
        result=support.run_support_pipeline('อัตราเท่าไร',client=client,source='kb',evidence_override=[source])
    parser.assert_not_called()
    assert result.error_code=='invalid_response' and result.raw_answer==raw
    assert result.source_type=='abstain' and not result.citation_checks_passed
    assert client.chat.completions.create.call_count==1
