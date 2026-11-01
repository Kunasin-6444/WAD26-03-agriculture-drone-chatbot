"""Audit source presentation with frozen live traces, without provider calls.

The procedure reply is supplied from source excerpts; it does not measure LLM
answer quality. Other replies/plans are the real saved Claude responses. Before
code is loaded solely to reproduce the lost-source behavior for comparison.
"""
from __future__ import annotations

import hashlib
import argparse
import importlib.util
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'cache/eval/support_v17_design_audit_20261027'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-stem',default='offline_replay')
    args=parser.parse_args()
    if Path(args.output_stem).name!=args.output_stem or any(c in args.output_stem for c in '/\\:'):
        parser.error('output-stem must be a filename stem')
    target=OUT/(args.output_stem+'.json')
    if target.exists():
        raise FileExistsError(target)

    def no_network(*args,**kwargs):
        raise AssertionError('Design audit must not contact external providers')

    with patch.object(socket.socket,'connect',no_network):
        from app.rag import support_pipeline as support
        from app.rag.evidence import Evidence
        from app.rag.structured_tables import TableCatalog

        spec=importlib.util.spec_from_file_location('audit_before_support',OUT/'before/app/rag/support_pipeline.py')
        before=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(before)
        source_path=ROOT/'cache/eval/support_v16_claude_measurement_20261027_network/kb.json'
        row=json.loads(source_path.read_text(encoding='utf-8'))['rows'][0]
        evidence=[Evidence(**e) for e in row['pipeline_result']['post_selection_evidence']]
        # Find the printed rows by their coordinates, not a reference answer.
        first=next(e for e in evidence if e.page_number=='3' and any(
            line.startswith('1 |') for line in e.content.splitlines()))
        last=next(e for e in evidence if e.page_number=='4' and any(
            line.startswith('6 |') for line in e.content.splitlines()))
        first_quote=next(line for line in first.content.splitlines() if line.startswith('1 |'))
        last_quote=next(line for line in last.content.splitlines() if line.startswith('6 |'))
        supplied={'action':'answer','status':'sufficient','intro':'','claims':[
            {'text':'เริ่มเติมสารจากสูตรผง (WP, WG, SG, SP) โดยละลายในน้ำสะอาดให้หมดก่อน',
             'evidence':[{'source_id':first.id,'quote':first_quote}]},
            {'text':'สารจับใบ (Adjuvant) เติมเป็นลำดับสุดท้ายเสมอ',
             'evidence':[{'source_id':last.id,'quote':last_quote}]}]}
        raw=json.dumps(supplied,ensure_ascii=False)
        comparison={}
        for name,module in [('before',before),('after',support)]:
            messages=module.build_messages(row['query'],evidence,'kb',[])
            payload=json.loads(messages[1]['content'])
            with patch.object(module,'call_llm',return_value=raw) as model:
                result=module.run_support_pipeline(row['query'],source='kb',evidence_override=evidence,context_chars=16000)
            visible={e['id']:e['content'] for e in payload['sources']}
            comparison[name]={'profile':module.PROFILE,'first_row_visible':first_quote in visible.get(first.id,''),
                'last_row_visible':last_quote in visible.get(last.id,''),
                'message_chars':sum(len(m['content']) for m in messages),
                'system_chars':len(messages[0]['content']),
                'citation_checks_passed':result.citation_checks_passed,'answer':result.answer,
                'evidence_trace':result.evidence_trace,'mock_calls':model.call_count}
        assert not comparison['before']['citation_checks_passed']
        assert comparison['after']['citation_checks_passed']
        assert comparison['after']['first_row_visible'] and comparison['after']['last_row_visible']
        assert len(comparison['after']['evidence_trace'])==2

        old_path=ROOT/'cache/eval/support_v15_claude_measurement_20261027/kb.json'
        saved=json.loads(old_path.read_text(encoding='utf-8'))
        replays=[]
        for case_id in ['inv07','u03']:
            case=next(r for r in saved['rows'] if r['id']==case_id)
            inputs=[Evidence(**e) for e in case['pipeline_result']['post_selection_evidence']]
            coverage=[t for d in case['diagnostics'] for t in d.get('tables',[])]
            real_reply=case['trace']['generation'][0]['raw_answer']
            with patch.object(support,'call_llm',return_value=real_reply) as model:
                result=support.run_support_pipeline(case['query'],source='kb',evidence_override=inputs,
                    table_coverage_override=coverage,context_chars=16000)
            assert result.citation_checks_passed,(case_id,result.grade_reason)
            assert result.answer==case['answer'],case_id
            replays.append({'id':case_id,'saved_real_claude_reply':json.loads(real_reply),
                'answer_identical_to_live_v15':True,'citation_checks_passed':True,'mock_calls':model.call_count})

        report={'scope':'Offline source-presentation before/after and saved-plan replay, not new LLM/retrieval accuracy',
            'provider_calls':0,'embedding_calls':0,'search_calls':0,'kb_writes':0,
            'procedure_reply':'Supplied from printed source rows; not a new model completion',
            'procedure':comparison,'saved_plan_replays':replays,
            'trace_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source_path,old_path]},
            'code_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                json.loads((OUT/'before/manifest.json').read_text(encoding='utf-8'))
                if name.startswith(('app/','scripts/'))}}
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'provider_calls':0,'procedure_before':False,'procedure_after':True,
        'saved_real_plan_replays_identical':len(replays),'output':str(target)},ensure_ascii=False))


if __name__=='__main__':
    main()
