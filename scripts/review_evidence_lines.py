"""Replay saved development answers as server-resolved line references, offline."""
from __future__ import annotations

from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'cache/eval/support_v19_evidence_references_20261027'
TRACE=ROOT/'cache/eval/support_v17_claude_measurement_20261027/kb.json'


def references_for(quote, source, canonical):
    lines=source.content.splitlines()
    one=[i for i,line in enumerate(lines,1) if quote in line and len(line.strip())<=800]
    if len(one)==1:return one
    target=canonical(quote); matches=[]
    for start in range(len(lines)):
        fragment=''
        for end in range(start,min(start+4,len(lines))):
            if not 3<=len(lines[end].strip())<=800:break
            fragment+=canonical(lines[end])
            if fragment==target:matches.append(list(range(start+1,end+2)))
            if not target.startswith(fragment):break
    return matches[0] if len(matches)==1 else []


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-stem',default='replay')
    args=parser.parse_args()
    if Path(args.output_stem).name!=args.output_stem or any(c in args.output_stem for c in '/\\:'):
        parser.error('output-stem must be a filename stem')
    output=OUT/(args.output_stem+'.json')
    if output.exists():raise FileExistsError(output)
    def no_network(*args,**kwargs):raise AssertionError('Offline replay cannot contact a provider')
    with patch.object(socket.socket,'connect',no_network):
        from app.rag import support_pipeline as support
        from app.rag.evidence import Evidence,_canonical
        saved=json.loads(TRACE.read_text(encoding='utf-8'))
        if saved['config']['split']!='dev':raise ValueError('Only saved dev cases are permitted')
        results=[]
        for case_id in ('mix02','my01','my04'):
            case=next(r for r in saved['rows'] if r['id']==case_id)
            sources=[Evidence(**e) for e in case['pipeline_result']['post_selection_evidence']]
            by_id={e.id:e for e in sources}
            actual=case['trace']['generation'][0]['raw_answer']; data=deepcopy(json.loads(actual))
            data.pop('reason',None);data.pop('intro',None)
            converted=legacy=0
            for claim in data.get('claims',[]):
                citations=[]
                for ref in claim['evidence']:
                    numbers=references_for(ref['quote'],by_id[ref['source_id']],_canonical)
                    if numbers:
                        citations.extend({'source_id':ref['source_id'],'line':n} for n in numbers)
                        converted+=1
                    else:
                        citations.append(ref);legacy+=1
                if len(citations)>4:raise ValueError('Cannot replace one claim with more than four references')
                claim['evidence']=citations
            raw=json.dumps(data,ensure_ascii=False,separators=(',',':'))
            with patch.object(support,'call_llm',return_value=raw):
                result=support.run_support_pipeline(case['query'],source='kb',evidence_override=sources,context_chars=16000)
            if not result.citation_checks_passed or result.answer!=case['answer']:
                raise ValueError('Saved answer did not survive: '+case_id+' '+result.grade_reason)
            new_messages=support.build_messages(case['query'],sources,'kb',[])
            results.append({'id':case_id,'original_response_chars':len(actual),'line_reference_response_chars':len(raw),
                'original_message_chars':sum(len(m['content']) for m in case['trace']['generation'][0]['messages']),
                'numbered_message_chars':sum(len(m['content']) for m in new_messages),
                'converted_original_quotes':converted,'legacy_quotes_retained':legacy,
                'answer_identical':True,'citation_checks_passed':True,'simulated_line_response':data,
                'scope':'Line references produced offline from saved source excerpts, not by a model'})
        query_path=ROOT/'cache/eval/support_v15_claude_measurement_20261027/kb.json'
        queries=json.loads(query_path.read_text(encoding='utf-8'))
        query_replays=[]
        for case_id in ('inv07','u03'):
            case=next(r for r in queries['rows'] if r['id']==case_id)
            sources=[Evidence(**e) for e in case['pipeline_result']['post_selection_evidence']]
            coverage=[t for d in case['diagnostics'] for t in d.get('tables',[])]
            raw=case['trace']['generation'][0]['raw_answer']
            with patch.object(support,'call_llm',return_value=raw):
                result=support.run_support_pipeline(case['query'],source='kb',evidence_override=sources,
                    table_coverage_override=coverage,context_chars=16000)
            if not result.citation_checks_passed or result.answer!=case['answer']:
                raise ValueError('Saved table query changed: '+case_id+' '+result.grade_reason)
            query_replays.append({'id':case_id,'answer_identical':True,'citation_checks_passed':True})
        partial_path=ROOT/'cache/eval/support_v18_claude_measurement_20261027/kb.json'
        partial_case=json.loads(partial_path.read_text(encoding='utf-8'))['rows'][0]
        partial_sources=[Evidence(**e) for e in partial_case['pipeline_result']['post_selection_evidence']]
        partial_raw=partial_case['pipeline_result'].get('raw_answer') or partial_case['trace']['generation'][0].get('partial_response')
        if not partial_raw:
            usage_path=partial_path.with_name('usage.json')
            partial_raw=json.loads(usage_path.read_text(encoding='utf-8'))['calls'][-1]['choices'][0]['content']
        with patch.object(support,'call_llm',return_value=partial_raw):
            rejected=support.run_support_pipeline(partial_case['query'],source='kb',
                evidence_override=partial_sources,context_chars=16000)
        if rejected.source_type!='abstain' or rejected.error_code!='invalid_response':
            raise ValueError('The recorded incomplete XML was not rejected')
        # A supplied claim references an actual printed row. It demonstrates
        # the question-condition guard, not a new model answer or gold score.
        source=next(e for e in partial_sources if e.id=='D4')
        row=source.content.splitlines()[1]
        cells=[c.strip() for c in row.split('|')]
        unit=source.content.splitlines()[0].split('|')[1].split('(')[1].split(')')[0]
        supplied={'action':'answer','status':'sufficient','missing_aspects':[],
            'claims':[{'text':f'{cells[0]} {cells[1]} {unit} {cells[2]} {cells[3]}',
                       'evidence':[{'source_id':source.id,'line':2}]}]}
        with patch.object(support,'call_llm',return_value=json.dumps(supplied,ensure_ascii=False)):
            guarded=support.run_support_pipeline(partial_case['query'],source='kb',
                evidence_override=partial_sources,context_chars=16000)
        if not guarded.citation_checks_passed or not guarded.missing_aspect:
            raise ValueError('Missing requested crop phase was not surfaced')
        report={'scope':'Three saved real model replies transformed offline into exact source-line references and two saved query plans replayed; no new generation',
            'profile':support.PROFILE,'llm_calls':0,'embedding_calls':0,'search_calls':0,
            'trace_sha256':hashlib.sha256(TRACE.read_bytes()).hexdigest(),
            'query_trace_sha256':hashlib.sha256(query_path.read_bytes()).hexdigest(),
            'partial_trace_sha256':hashlib.sha256(partial_path.read_bytes()).hexdigest(),
            'code_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                ('app/rag/support_pipeline.py','app/rag/table_query.py','app/rag/evidence.py')},
            'rows':results,'saved_table_queries':query_replays,
            'recorded_incomplete_xml_rejected':True,
            'supplied_row_fixture':{'missing_question_condition':guarded.missing_aspect,
                                    'citation_checks_passed':guarded.citation_checks_passed,
                                    'scope':'Supplied from a real source row; not a model answer'}}
        with output.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps({'cases':len(results),'converted_quotes':sum(r['converted_original_quotes'] for r in results),
        'legacy_quotes':sum(r['legacy_quotes_retained'] for r in results),'saved_table_queries':len(query_replays),
        'recorded_incomplete_xml_rejected':True,'supplied_row_phase_warning':True,
        'api_calls':0,'output':str(output)}))


if __name__=='__main__':main()
