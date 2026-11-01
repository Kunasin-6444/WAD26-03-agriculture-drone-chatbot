"""Offline analysis of the saved u01 retrieval and one multi-citation claim."""
from __future__ import annotations

import hashlib
import argparse
import importlib.util
import json
from pathlib import Path
import re
import socket
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'cache/eval/support_v20_crop_scope_20261027'
TRACE=ROOT/'cache/eval/support_v19_claude_measurement_20261027/kb.json'
USAGE=TRACE.with_name('usage.json')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output-stem',default='offline_replay')
    stem=parser.parse_args().output_stem
    if not re.fullmatch(r'[A-Za-z0-9_-]+',stem):raise ValueError('Invalid output stem')
    target=OUT/(stem+'.json')
    if target.exists():raise FileExistsError(target)
    def no_network(*args,**kwargs):raise AssertionError('Offline replay cannot contact a provider')
    with patch.object(socket.socket,'connect',no_network):
        from app.rag import support_pipeline as after
        from app.rag.evidence import Evidence
        spec=importlib.util.spec_from_file_location('v19_support',OUT/'before/app/rag/support_pipeline.py')
        before=importlib.util.module_from_spec(spec);spec.loader.exec_module(before)
        row=json.loads(TRACE.read_text(encoding='utf-8'))['rows'][0]
        if row['id']!='u01':raise ValueError('Unexpected saved development case')
        sources=[Evidence(**e) for e in row['pipeline_result']['post_selection_evidence']]
        diag=[]
        scoped=after.scope_answer_sources(row['query'],sources,diag)
        original={e.id:e for e in sources};visible={e.id:e for e in scoped}
        changes=[]
        for event in diag:
            sid=event['source_id'];lines=original[sid].content.splitlines()
            removed=[lines[i-1] for i in event['removed_original_lines']]
            assert all(line not in visible[sid].content.splitlines() for line in removed)
            changes.append({'source_id':sid,'source_file':original[sid].source_file,
                'page':original[sid].page_number,'removed_original_lines':event['removed_original_lines'],
                'removed_exact_rows':removed,'retained_content':visible[sid].content})
        assert changes and set(original)==set(visible)
        payload=json.loads(after.build_messages(row['query'],sources,'kb',[])[1]['content'])
        model_visible={e['id']:e['content'] for e in payload['sources']}
        assert all(sid in model_visible for sid in original)

        # Extract a fully closed claim object from an otherwise incomplete saved
        # response solely as an offline test fixture. Never present it as an answer
        # produced or accepted by the live run.
        usage=json.loads(USAGE.read_text(encoding='utf-8'))
        raw=usage['calls'][-1]['choices'][0]['content']
        pos=re.search(r'"claims"\s*:\s*\[',raw).end();decoder=json.JSONDecoder();claims=[]
        while True:
            while pos<len(raw) and raw[pos] in ' \r\n\t,':pos+=1
            try:claim,end=decoder.raw_decode(raw,pos)
            except ValueError:break
            if not isinstance(claim,dict):break
            claims.append(claim);pos=end
        candidate=next(c for c in claims if len(c.get('evidence',[]))==6)
        fixture=json.dumps({'action':'answer','status':'sufficient','missing_aspects':[],
                            'claims':[candidate]},ensure_ascii=False)
        compared={}
        for label,module in [('before',before),('after',after)]:
            with patch.object(module,'call_llm',return_value=fixture):
                result=module.run_support_pipeline(row['query'],source='kb',evidence_override=sources,context_chars=16000)
            compared[label]={'source_type':result.source_type,'citation_checks_passed':result.citation_checks_passed,
                'reason':result.grade_reason,'missing_aspect':result.missing_aspect,
                'evidence_count':sum(len(c['evidence']) for c in result.evidence_trace)}
        assert not compared['before']['citation_checks_passed']
        assert compared['after']['citation_checks_passed'] and compared['after']['evidence_count']==6
        assert compared['after']['missing_aspect']
        old_messages=row['trace']['generation'][0]['messages']
        new_messages=after.build_messages(row['query'],sources,'kb',[])
        report={'scope':'Recorded dev retrieval and supplied six-reference partial-response claim; no new model answer',
            'network_calls':0,'llm_calls':0,'embedding_calls':0,'source_trace_sha256':hashlib.sha256(TRACE.read_bytes()).hexdigest(),
            'usage_sha256':hashlib.sha256(USAGE.read_bytes()).hexdigest(),
            'code_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                ('app/rag/support_pipeline.py','app/rag/evidence.py')},
            'retrieval_unchanged':True,'selected_sources':len(sources),'visible_sources':len(scoped),
            'crop_scope_changes':changes,'six_reference_fixture':compared,
            'before_message_characters':sum(len(m['content']) for m in old_messages),
            'after_message_characters':sum(len(m['content']) for m in new_messages)}
        with target.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps({'removed_rows':sum(len(c['removed_original_lines']) for c in changes),
        'changed_sources':len(changes),'six_reference_fixture_before':False,'six_reference_fixture_after':True,
        'warning_present':True,'api_calls':0,'output':str(target)}))


if __name__=='__main__':main()
