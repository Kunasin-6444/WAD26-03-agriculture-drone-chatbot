"""Shared schema/query tests, including regressions for the wrong-price ranking."""
from copy import deepcopy
import json
from unittest.mock import patch

import pytest

from app.rag.evidence import Evidence
from app.rag.structured_tables import TableCatalog
from app.rag.table_query import execute, render_result, QueryError
from app.rag import support_pipeline as support


def dataset(rows=None, complete=True):
    rows = rows or ['Atlas | Alpha | 12 | 80000', 'Atlas | Beta | 20 | 125000',
                    'Nova | Gamma | 20 | 110000', 'Delta | Delta | 20 | 100000']
    header = 'บริษัท | รุ่น | ความจุถัง (ลิตร) | ราคาโดยประมาณ (บาท)'
    sources = [Evidence(f'D{i}', header+'\n'+row, 'synthetic.pdf', str(i)) for i,row in enumerate(rows,1)]
    coverage = {'source_file':'synthetic.pdf','table_id':'devices','coverage':'complete' if complete else 'unknown',
        'total_chunks':len(sources),'included_chunks':[(s.source_file,s.page_number,s.content) for s in sources],
        'missing_pages':[],'missing_chunks':[]}
    diagnostics = [{'tables':[coverage]}]
    return sources, diagnostics, TableCatalog.build(sources, diagnostics)


def plan(catalog, **changes):
    result = {'action':'table_query','table_id':catalog.tables[0].id,'operation':'min',
        'column':'c3','order':'asc','limit':1,'select':['c1','c3'],'filters':[],'unsupported_aspects':[]}
    result.update(changes)
    return result


def test_global_minimum_uses_all_rows_without_inventing_a_runner_up():
    sources, _, catalog = dataset()
    result = render_result('รุ่นไหนราคาถูกที่สุด', catalog, plan(catalog), sources)
    assert result.source_type == 'knowledge_base', result.grade_reason
    assert 'Alpha' in result.answer and '80000 บาท' in result.answer
    assert 'Beta' not in result.answer and 'Gamma' not in result.answer and 'รอง' not in result.answer
    assert len(result.evidence_trace)==1
    assert result.diagnostics[0]['source_rows']==4


def test_brand_and_capacity_filters_share_the_same_executor_as_global_minimum():
    sources, _, catalog = dataset()
    value = plan(catalog, filters=[{'column':'c0','op':'eq','value':'Atlas'},
        {'column':'c2','op':'eq','value':'20','unit':'ลิตร'}])
    result = render_result('ราคาต่ำสุดของAtlasเฉพาะถัง20ลิตร',catalog,value,sources)
    assert result.source_type=='knowledge_base', result.grade_reason
    assert 'Beta' in result.answer and '125000 บาท' in result.answer
    assert 'Alpha' not in result.answer
    assert result.diagnostics[0]['eligible_rows']==1


def test_numeric_ranking_is_decimal_and_includes_boundary_ties():
    sources, _, catalog = dataset(['Atlas | First | 12 | 9.75','Nova | Second | 20 | 10.25',
        'Delta | Third | 20 | 10.25','Delta | Last | 20 | 100'])
    _, rows, _, event = execute(catalog, plan(catalog,operation='rank',limit=2))
    assert [r.cells[1] for r in rows]==['First','Second','Third']
    assert event['result_rows']==3


def test_maximum_and_other_numeric_column_use_the_same_query_shape():
    _, _, catalog = dataset()
    _, rows, _, _ = execute(catalog, plan(catalog,operation='max'))
    assert [r.cells[1] for r in rows]==['Beta']
    _, rows, _, _ = execute(catalog, plan(catalog,operation='max',column='c2'))
    assert {r.cells[1] for r in rows}=={'Beta','Gamma','Delta'}


def test_schema_keeps_units_types_and_provenance_but_does_not_send_price_rows_to_the_model():
    sources, diagnostics, catalog = dataset()
    table = catalog.tables[0]
    assert table.complete and table.columns[2].unit=='ลิตร' and table.columns[3].kind=='decimal'
    assert table.rows[0].source is sources[0]
    assert table.rows[0].quote in sources[0].content
    messages=support.build_messages('ราคาต่ำสุด',sources,'kb',diagnostics,catalog)
    payload=json.loads(messages[-1]['content'])
    assert payload['sources']==[] and payload['table_schemas']
    assert '80000' not in messages[-1]['content']
    assert 'row_refs' not in payload and 'label_refs' not in payload


@pytest.mark.parametrize('changes', [
    {'table_id':'not-a-source-table'}, {'operation':'DELETE'}, {'column':'c3; DROP TABLE source_rows'},
    {'select':['c999']}, {'limit':True}, {'limit':1000}, {'order':'DESC; DROP TABLE x'},
    {'unsupported_aspects':['before crop emergence']},
    {'filters':[{'column':'c2','op':'eq','value':'20','unit':'kg'}]},
    {'filters':[{'column':'c0','op':'gt','value':'Atlas'}]},
    {'filters':[{'column':'c3','op':'eq','value':'10-20','unit':'บาท'}]},
])
def test_invalid_plan_or_units_fail_closed(changes):
    _, _, catalog = dataset()
    with pytest.raises(QueryError):
        execute(catalog, plan(catalog,**changes))


def test_filter_values_are_parameters_and_literal_wildcards_are_not_executable_sql():
    _, _, catalog = dataset()
    value=plan(catalog,filters=[{'column':'c0','op':'eq','value':"Atlas' OR 1=1 --"}])
    _, rows, _, event=execute(catalog,value)
    assert rows==[] and "OR 1=1" not in event['sql']
    assert event['parameters']==["Atlas' OR 1=1 --"]
    _, rows, _, _=execute(catalog,plan(catalog,filters=[{'column':'c0','op':'contains','value':'%'}]))
    assert rows==[]


def test_missing_comparison_value_is_not_zero_and_cannot_be_silently_ignored():
    source=Evidence('D1','บริษัท | รุ่น | ราคา (บาท) | ถัง (ลิตร)\nAtlas | Alpha | | 12\nNova | Beta | 100000 | 20','synthetic.pdf','1')
    proof={'source_file':'synthetic.pdf','table_id':'devices','coverage':'complete','total_chunks':1,
           'included_chunks':[(source.source_file,source.page_number,source.content)]}
    catalog=TableCatalog.build([source],[{'tables':[proof]}])
    with pytest.raises(QueryError,match='Missing comparison'):
        execute(catalog,plan(catalog,column='c2',select=['c2']))


def test_conflicting_values_for_same_entity_are_not_resolved_by_picking_the_lower_one():
    _, _, catalog=dataset(['Atlas | Alpha | 12 | 80000', 'Atlas | Alpha | 12 | 70000'])
    with pytest.raises(QueryError,match='Conflicting'):
        execute(catalog,plan(catalog))


def test_partial_table_can_supply_a_row_fact_but_cannot_claim_a_global_minimum():
    sources, _, catalog=dataset(complete=False)
    with pytest.raises(QueryError,match='complete table'):
        execute(catalog,plan(catalog))
    result=render_result('ราคาของAlpha',catalog,plan(catalog,operation='select',column=None,
        filters=[{'column':'c1','op':'eq','value':'Alpha'}]),sources)
    assert result.source_type=='knowledge_base',result.grade_reason
    assert '80000 บาท' in result.answer and result.missing_aspect


def test_pipeline_has_one_model_planning_call_and_no_second_model_answer():
    sources, diagnostics, catalog=dataset()
    coverage=deepcopy(diagnostics[0]['tables'])
    value=plan(catalog,filters=[{'column':'c0','op':'eq','value':'Atlas'}, {'column':'c2','op':'eq','value':'20','unit':'ลิตร'}])
    with patch.object(support,'call_llm',return_value=json.dumps(value)) as model:
        result=support.run_support_pipeline('รุ่นไหนราคาถูกที่สุดเฉพาะAtlasถัง20ลิตร',source='kb',
            evidence_override=sources,table_coverage_override=coverage)
    assert result.source_type=='knowledge_base',result.grade_reason
    assert model.call_count==1
    assert 'Beta' in result.answer and '125000 บาท' in result.answer
    assert coverage==diagnostics[0]['tables']


def test_old_wrong_ranking_cannot_be_accepted_as_free_text_against_hidden_table_rows():
    sources, diagnostics, _=dataset()
    bad={'action':'answer','status':'sufficient','intro':'','claims':[{'text':'รุ่นรองลงมาคือ Gamma ราคา110000บาท',
         'evidence':[{'source_id':'D3','quote':sources[2].content.splitlines()[1]}]}]}
    with patch.object(support,'call_llm',return_value=json.dumps(bad,ensure_ascii=False)):
        result=support.run_support_pipeline('รุ่นไหนราคาถูกที่สุด',source='kb',
            evidence_override=sources,table_coverage_override=diagnostics[0]['tables'])
    assert result.source_type=='abstain'
    assert not result.citation_checks_passed


def test_foreign_crop_source_is_not_substituted_for_requested_crop():
    source=Evidence('D1','สาร | พืช | อัตรา (กรัม/ไร่) | ช่วงใช้\nอัลฟาซีน | ข้าวโพด | 35 | ก่อนวัชพืชงอก','crop.pdf','1')
    catalog=TableCatalog.build([source],[])
    value={'action':'table_query','table_id':catalog.tables[0].id,'operation':'select','select':['c2'],
        'filters':[],'limit':1,'unsupported_aspects':[]}
    assert render_result('อ้อยใช้สารอะไร',catalog,value,[source]).source_type=='abstain'


def test_interval_filter_excludes_definitely_unmatched_values_but_does_not_guess_inside_a_range():
    _, _, catalog=dataset(['Atlas | Range | 16-17 | 80000','Nova | Exact | 20 | 100000'])
    assert catalog.tables[0].columns[2].kind=='quantity'
    _, rows, _, _=execute(catalog,plan(catalog,filters=[{'column':'c2','op':'eq','value':'20','unit':'ลิตร'}]))
    assert [r.cells[1] for r in rows]==['Exact']
    with pytest.raises(QueryError,match='ambiguous'):
        execute(catalog,plan(catalog,filters=[{'column':'c2','op':'eq','value':'16','unit':'ลิตร'}]))


def test_normalized_catalog_export_preserves_rows_cells_types_units_and_citations(tmp_path):
    import sqlite3
    _, _, catalog=dataset()
    target=tmp_path/'catalog.sqlite3'
    catalog.export_sqlite(target)
    with sqlite3.connect(target.as_uri()+'?mode=ro',uri=True) as db:
        assert db.execute('SELECT count(*) FROM source_rows').fetchone()[0]==4
        assert db.execute('SELECT count(*) FROM source_cells').fetchone()[0]==16
        assert db.execute("SELECT unit FROM source_columns WHERE id='c2'").fetchone()[0]=='ลิตร'
        assert db.execute('SELECT quote FROM source_rows ORDER BY row_id LIMIT 1').fetchone()[0]==catalog.tables[0].rows[0].quote
    with pytest.raises(FileExistsError):
        catalog.export_sqlite(target)


def test_evaluator_records_query_plan_and_does_not_confuse_schema_with_model_reading_rows():
    from scripts.rag_evaluation_trace import capture_pipeline,retrieval_diagnostics
    sources,diagnostics,catalog=dataset()
    with patch.object(support,'call_llm',return_value=json.dumps(plan(catalog))),capture_pipeline('support') as trace:
        result=support.run_support_pipeline('ราคาต่ำสุด',source='kb',evidence_override=sources,
            table_coverage_override=diagnostics[0]['tables'])
    assert result.citation_checks_passed and len(trace['table_queries'])==1
    case={'evidence_groups':[{'pages':[{'source_file':'synthetic.pdf','page_number':'1'}]}]}
    metrics=retrieval_diagnostics(case,trace)['generation'][0]
    assert metrics['gold_group_coverage']==0
    assert metrics['schema_only_gold_group_coverage']==1
    assert trace['table_queries'][0]['plan']['operation']=='min'


def test_experimental_json_mode_retains_table_query_execution():
    sources,diagnostics,catalog=dataset()
    with patch.object(support,'call_llm',return_value=json.dumps(plan(catalog))) as model:
        result=support.run_support_pipeline('ราคาต่ำสุด',source='kb',evidence_override=sources,
            table_coverage_override=diagnostics[0]['tables'],json_mode=True)
    assert model.call_args.kwargs['json_mode'] is True
    assert result.citation_checks_passed and '80000 บาท' in result.answer
