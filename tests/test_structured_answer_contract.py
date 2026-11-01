"""Replacement of retired label/row slots with one typed query protocol."""
import json
from unittest.mock import patch

from app.rag import support_pipeline as support
from app.rag.evidence import Evidence
from app.rag.structured_tables import TableCatalog

TABLE=('สาร | อัตรา (กรัมสารออกฤทธิ์/ไร่) | ช่วงใช้ | วัชพืช | สถานะ\n'
       'อัลฟาซีน | 35-45 | ก่อนวัชพืชงอก | ใบแคบ | ตามฉลาก\n'
       'เบตาซีน+แกมมาซีน | 70-80+9 | ก่อนวัชพืชงอก | ใบแคบและกว้าง | ตามฉลาก')


def run(question='คุมใบแคบก่อนวัชพืชงอกใช้อะไร',name='อัลฟาซีน',table=TABLE):
    source=Evidence('D1',table,'synthetic.pdf','2')
    catalog=TableCatalog.build([source],[])
    plan={'action':'table_query','table_id':catalog.tables[0].id,'operation':'select',
          'select':['c1'],'filters':[{'column':'c0','op':'eq','value':name}],
          'limit':1,'unsupported_aspects':[]}
    with patch.object(support,'call_llm',return_value=json.dumps(plan,ensure_ascii=False)) as model:
        result=support.run_support_pipeline(question,source='kb',evidence_override=[source])
    return result,json.loads(model.call_args.args[0][-1]['content'])


def test_source_row_name_quantity_unit_conditions_and_ids_stay_together_without_slots():
    result,payload=run()
    assert result.citation_checks_passed,result.grade_reason
    assert all(v in result.answer for v in ['อัลฟาซีน','35-45','กรัมสารออกฤทธิ์/ไร่','ก่อนวัชพืชงอก','ใบแคบ'])
    assert {e['source_id'] for c in result.evidence_trace for e in c['evidence']}=={'D1'}
    assert 'row_refs' not in payload and 'label_refs' not in payload
    assert payload['sources'][0]['content'].splitlines()==[
        f'L{i}: {line}' for i,line in enumerate(TABLE.splitlines(),1)]
    assert payload['table_view']=='original_rows_with_provenance'


def test_crop_emergence_is_not_silently_substituted_for_weed_emergence():
    result,_=run('ก่อนอ้อยงอกใช้สารอะไร')
    assert result.citation_checks_passed,result.grade_reason
    assert 'ก่อนวัชพืชงอก' in result.answer and 'ยังไม่ยืนยันการใช้ก่อนอ้อยงอก' in result.answer


def test_row_without_any_phase_does_not_claim_a_requested_crop_phase_is_verified():
    table='สาร | อัตรา (กรัม/ไร่) | สถานะ\nอัลฟาซีน | 35-45 | ตามฉลาก'
    result,_=run('ก่อนอ้อยงอกใช้สารอะไร',table=table)
    assert result.citation_checks_passed,result.grade_reason
    assert 'ยังไม่ยืนยันการใช้ก่อนอ้อยงอก' in result.answer
    assert result.missing_aspect


def test_mixture_component_values_stay_aligned_without_computing_new_rates():
    result,_=run('เบตาซีน+แกมมาซีนอัตราเท่าไร',name='เบตาซีน+แกมมาซีน')
    assert result.citation_checks_passed,result.grade_reason
    assert 'เบตาซีน 70-80' in result.answer and 'แกมมาซีน 9' in result.answer
    assert 'กรัมสารออกฤทธิ์/ไร่' in result.answer


def test_prohibition_appears_before_the_source_dose():
    result,_=run(table=TABLE.replace('ตามฉลาก','ห้ามใช้'))
    assert result.citation_checks_passed,result.grade_reason
    assert result.answer.index('ห้ามใช้')<result.answer.index('35-45')


def test_crop_specific_row_cannot_answer_a_different_crop():
    table='สาร | อัตรา (กรัม/ไร่) | พืช | ช่วงใช้\nอัลฟาซีน | 35-45 | ข้าวโพด | ก่อนวัชพืชงอก'
    result,_=run('อ้อยใช้สารอะไร',table=table)
    assert result.source_type=='abstain'


def test_matching_crop_condition_cannot_be_omitted_from_a_projected_rate_answer():
    table='สาร | อัตรา (กรัม/ไร่) | พืช | ช่วงใช้\nอัลฟาซีน | 35-45 | ข้าวโพด | ก่อนวัชพืชงอก'
    result,_=run('ข้าวโพดใช้สารอะไร',table=table)
    assert result.citation_checks_passed,result.grade_reason
    assert 'ข้าวโพด' in result.answer and 'ก่อนวัชพืชงอก' in result.answer


def test_obsolete_slot_reply_cannot_bypass_the_table_query_executor():
    reply={'status':'sufficient','intro':'','claims':[{'text':'{{row:D1:T1:R1}}',
        'evidence':[{'source_id':'D1','quote':TABLE.splitlines()[1]}]}]}
    with patch.object(support,'call_llm',return_value=json.dumps(reply,ensure_ascii=False)):
        result=support.run_support_pipeline('สารอะไร',source='kb',evidence_override=[Evidence('D1',TABLE,'a.pdf','1')])
    assert result.source_type=='abstain'
