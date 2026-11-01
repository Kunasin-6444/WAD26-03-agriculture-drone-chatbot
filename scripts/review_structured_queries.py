"""Offline query/backend verification with frozen evidence and supplied plans.

Does not measure whether a real LLM translates questions correctly. No provider
calls, fresh embeddings, owner holdout, or KB writes are performed.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists')
    args.output.mkdir(parents=True,exist_ok=False)

    def no_network(*a,**kw):
        raise AssertionError('Structured query replay cannot access providers')

    with patch.object(socket.socket,'connect',no_network):
        from app.rag import support_pipeline as support
        from app.rag.evidence import Evidence
        from app.rag.structured_tables import TableCatalog
        old_path=ROOT/'cache/eval/support_v13_claude_measurement_20261027/kb.json'
        old=json.loads(old_path.read_text(encoding='utf-8'))
        assert old['config']['split']=='dev'
        cases={r['id']:r for r in old['rows']}

        def inputs(case_id):
            row=cases[case_id]
            evidence=[Evidence(**e) for e in row['pipeline_result']['post_selection_evidence']]
            coverage=[t for d in row['diagnostics'] for t in d.get('tables',[])]
            return evidence,coverage,TableCatalog.build(evidence,[{'tables':coverage}])

        evidence,coverage,catalog=inputs('inv07')
        price=next(t for t in catalog.tables if t.complete and any('ราคา' in c.name and 'RTF' in c.name for c in t.columns))
        column=lambda pattern:next(c.id for c in price.columns if pattern(c.name))
        money=column(lambda h:'ราคา' in h and 'RTF' in h)
        tank=column(lambda h:'ความจุถัง' in h)
        brand=column(lambda h:h=='บริษัท')
        model=column(lambda h:h=='รุ่น')
        speed=column(lambda h:'ความเร็ว' in h)
        base={'action':'table_query','table_id':price.id,'operation':'min','column':money,
              'order':'asc','limit':1,'select':[model,money],'filters':[],'unsupported_aspects':[]}
        tests=[
            ('minimum',cases['inv07']['query'],base,['5 Pro Lite']),
            ('filtered_minimum','รุ่นไหนราคาต่ำสุดเฉพาะDJIถัง20ลิตร',dict(base,filters=[
                {'column':brand,'op':'eq','value':'DJI'},{'column':tank,'op':'eq','value':'20','unit':'ลิตร'}]),['AGRAS T20P']),
            ('rank_three','ขอ3รุ่นที่ราคาต่ำสุดเรียงจากน้อยไปมาก',dict(base,operation='rank',limit=3),
                ['5 Pro Lite','EASY 3C','AR-10L/4']),
            ('maximum_speed','รุ่นไหนมีความเร็วบินสูงสุดในตาราง',dict(base,operation='max',column=speed,select=[model,speed]),['P100 Pro']),
        ]
        rows=[]
        for case_id,question,plan,expected in tests:
            with patch.object(support,'call_llm',return_value=json.dumps(plan,ensure_ascii=False)) as model_call, \
                    patch.object(support,'search_web_fallback',no_network):
                result=support.run_support_pipeline(question,source='kb',evidence_override=evidence,
                    table_coverage_override=coverage,context_chars=16000)
            assert result.source_type=='knowledge_base',(case_id,result.grade_reason)
            assert result.citation_checks_passed and model_call.call_count==1
            assert len(result.evidence_trace)==len(expected)
            assert all(label in claim['text'] for label,claim in zip(expected,result.evidence_trace))
            if case_id=='minimum':
                assert len(result.evidence_trace)==1 and 'รองลงมา' not in result.answer
            rows.append({'id':case_id,'question':question,'supplied_plan':plan,'result':asdict(result),
                         'mock_planner_calls':model_call.call_count})
        catalog.export_sqlite(args.output/'tables.sqlite3')
        # A real saved prose reply remains valid under the compact answer protocol.
        prose,proof,_=inputs('my04')
        raw=cases['my04']['trace']['generation'][0]['raw_answer']
        with patch.object(support,'call_llm',return_value=raw) as model_call:
            result=support.run_support_pipeline(cases['my04']['query'],source='kb',evidence_override=prose,
                table_coverage_override=proof,context_chars=16000)
        assert result.citation_checks_passed and '30%' in result.answer
        rows.append({'id':'saved_prose','result':asdict(result),'mock_planner_calls':model_call.call_count})
        new_messages=support.build_messages(cases['inv07']['query'],evidence,'kb',[{'tables':coverage}],catalog)
        before=cases['inv07']['trace']['generation'][0]['messages']
        report={'scope':'Frozen real evidence with manually supplied query plans; not new LLM translation or retrieval accuracy',
            'profile':support.PROFILE,'provider_calls':0,'embedding_calls':0,'source_trace_sha256':hashlib.sha256(old_path.read_bytes()).hexdigest(),
            'prompt_comparison':{'before_system_chars':len(before[0]['content']),'after_system_chars':len(new_messages[0]['content']),
                'before_message_chars':sum(len(m['content']) for m in before),'after_message_chars':sum(len(m['content']) for m in new_messages)},
            'catalog':{'tables':len(catalog.tables),'price_rows':len(price.rows),'price_complete':price.complete},
            'rows':rows,'code_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
                'app/rag/support_pipeline.py','app/rag/structured_tables.py','app/rag/table_query.py')}}
    (args.output/'replay.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'backend_cases':len(rows),'price_rows':len(price.rows),'prompt':report['prompt_comparison'],
                      'provider_calls':0,'output':str(args.output)},ensure_ascii=False))


if __name__=='__main__':main()
