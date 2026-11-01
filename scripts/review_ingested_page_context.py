"""Replay four saved development traces against the read-only index; no API calls."""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import sqlite3
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'cache/eval/support_v18_ingestion_context_20261027'
TRACE=ROOT/'cache/eval/support_v17_claude_measurement_20261027/kb.json'


def key(e):
    return e.source_file,str(e.page_number),e.content


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-stem',default='replay')
    args=parser.parse_args()
    if Path(args.output_stem).name!=args.output_stem or any(c in args.output_stem for c in '/\\:'):
        parser.error('output-stem must be a filename stem')
    target=OUT/(args.output_stem+'.json')
    if target.exists():raise FileExistsError(target)
    def no_network(*args,**kwargs):raise AssertionError('Offline replay cannot contact a provider')
    with patch.object(socket.socket,'connect',no_network):
        from langchain_core.documents import Document
        from app.rag import support_pipeline as after
        from app.rag.evidence import Evidence
        from app.rag.standard.hybrid_retriever import document_key
        spec=importlib.util.spec_from_file_location('v17_support',OUT/'before/app/rag/support_pipeline.py')
        before=importlib.util.module_from_spec(spec);spec.loader.exec_module(before)
        metadata=defaultdict(dict)
        dbpath=ROOT/'chroma_db/chroma.sqlite3'
        with sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True) as db:
            db.row_factory=sqlite3.Row
            for row in db.execute("SELECT m.* FROM embedding_metadata m JOIN embeddings e ON m.id=e.id "
                    "JOIN segments s ON e.segment_id=s.id JOIN collections c ON s.collection=c.id "
                    "WHERE c.name='drone_knowledge'"):
                metadata[row['id']][row['key']]=next((row[k] for k in ('string_value','int_value','float_value','bool_value')
                                                       if row[k] is not None),None)
        corpus=[]
        for meta in metadata.values():
            content=meta.pop('chroma:document','')
            if content:corpus.append(Document(page_content=content,metadata=meta))
        by_key={document_key(d):d for d in corpus}
        saved=json.loads(TRACE.read_text(encoding='utf-8'))
        if saved['config']['split']!='dev':raise ValueError('Only saved dev traces are permitted')
        results=[]
        for case in saved['rows']:
            if case['outcome']=='not_run':continue
            ranking=next(d for d in case['diagnostics'] if d.get('stage')=='retrieval')['rankings']
            dense=[by_key[r['chunk_key']] for r in sorted(
                (r for r in ranking if r['branch_ranks'].get('dense')),key=lambda r:r['branch_ranks']['dense'])]
            def get(where=None,**kwargs):
                found=[d for d in corpus if not where or all(d.metadata.get(k)==v for k,v in where.items())]
                return {'documents':[d.page_content for d in found],'metadatas':[d.metadata for d in found]}
            store=SimpleNamespace(get=get,as_retriever=lambda **kw:SimpleNamespace(invoke=lambda q:dense))
            def collect(module):
                diag=[]
                sources=module.retrieve_evidence(case['query'],store=store,diagnostics=diag)
                packed=module.pack_context(sources,'kb',diag,16000)
                messages=module.build_messages(case['query'],packed,'kb',diag)
                return packed,diag,messages
            old,_,old_messages=collect(before)
            recorded=[Evidence(**e) for e in case['pipeline_result']['post_selection_evidence']]
            if [key(e) for e in old]!=[key(e) for e in recorded]:
                raise ValueError('Before replay differs from measured trace: '+case['id'])
            new,diag,new_messages=collect(after)
            new_lookup={key(e):e for e in new}
            retained=all(key(e) in new_lookup for e in old)
            check={'id':case['id'],'before_matches_recorded':True,'before_chunks':len(old),'after_chunks':len(new),
                'previous_evidence_retained':retained,
                'before_message_chars':sum(len(m['content']) for m in old_messages),
                'after_message_chars':sum(len(m['content']) for m in new_messages),
                'added_page_context':[d for d in diag if d.get('stage')=='table_page_context'],
                'after_sources':[asdict(e) for e in new]}
            generation=case['trace']['generation'][0]
            if generation.get('raw_answer'):
                parsed=json.loads(generation['raw_answer'])
                old_by_id={e.id:e for e in old}
                for claim in parsed.get('claims',[]):
                    for citation in claim.get('evidence',[]):
                        identity=key(old_by_id[citation['source_id']])
                        if identity not in new_lookup:raise ValueError('Cited source lost: '+case['id'])
                        citation['source_id']=new_lookup[identity].id
                with patch.object(after,'call_llm',return_value=json.dumps(parsed,ensure_ascii=False)):
                    result=after.run_support_pipeline(case['query'],source='kb',evidence_override=new,context_chars=16000)
                check.update(saved_answer_replay_identical=result.answer==case['answer'],
                             saved_answer_citation_check=result.citation_checks_passed)
                if result.answer!=case['answer'] or not result.citation_checks_passed:
                    raise ValueError('Saved answer did not survive: '+case['id'])
            results.append(check)
        affected=next(r for r in results if r['id']=='u01')
        title='ชนิดและประเภทของสารกำจัดวัชพืชในไร่อ้อย'
        assert any(title in e['content'] and e['page_number']=='18' for e in affected['after_sources'])
        report={'scope':'Recorded dev dense hits plus read-only SQLite corpus; saved replies remapped by exact source identity; no new model answers',
            'network_calls':0,'llm_calls':0,'embedding_calls':0,'kb_writes':0,'corpus_chunks':len(corpus),
            'trace_sha256':hashlib.sha256(TRACE.read_bytes()).hexdigest(),
            'code_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                ('app/rag/support_pipeline.py','app/rag/standard/pipeline.py','app/rag/standard/hybrid_retriever.py')},
            'rows':results}
        with target.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
    print(json.dumps({'cases':len(results),'corpus_chunks':len(corpus),'u01_title_restored':True,
        'saved_answers_replayed':sum(bool(r.get('saved_answer_replay_identical')) for r in results),
        'provider_calls':0,'output':str(target)}))


if __name__=='__main__':main()
