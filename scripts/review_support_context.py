"""Replay recorded dense hits and compare context selection without any API calls.

Reads SQLite in read-only mode. Requires the unfocused replay to reproduce the
recorded context exactly, then compares focus with the same candidates/corpus.
No answers are generated or scored here. Owner holdout is never loaded.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import socket
import sqlite3
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def identity(item):
    return item.source_file, str(item.page_number), item.content


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace', type=Path, default=ROOT/'cache/eval/support_v12_claude_measurement_20261026/kb.json')
    parser.add_argument('--database', type=Path, default=ROOT/'chroma_db/chroma.sqlite3')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output exists; choose a new path')

    def no_network(*a, **kw):
        raise AssertionError('Offline context replay must not call a provider or open a network connection')

    with patch.object(socket.socket, 'connect', no_network):
        from langchain_core.documents import Document
        from app.rag import support_pipeline as support
        from app.rag.evidence import Evidence
        from app.rag.standard.hybrid_retriever import document_key

        old = json.loads(args.trace.read_text(encoding='utf-8'))
        if old['config']['split'] != 'dev':
            raise ValueError('Only saved development traces may be replayed')
        metadata = defaultdict(dict)
        with sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro', uri=True) as db:
            db.row_factory = sqlite3.Row
            for row in db.execute("SELECT m.* FROM embedding_metadata m JOIN embeddings e ON m.id=e.id "
                    "JOIN segments s ON e.segment_id=s.id JOIN collections c ON s.collection=c.id "
                    "WHERE c.name='drone_knowledge'"):
                metadata[row['id']][row['key']] = next((row[k] for k in
                    ('string_value', 'int_value', 'float_value', 'bool_value')
                    if k in row.keys() and row[k] is not None), None)
        corpus = []
        for meta in metadata.values():
            text = meta.pop('chroma:document', '')
            if text:
                corpus.append(Document(page_content=text, metadata=meta))
        by_key = {document_key(doc): doc for doc in corpus}
        rows = []
        with patch.object(support, 'call_llm', no_network):
            for case in old['rows']:
                audit = next(d for d in case['diagnostics'] if d.get('stage') == 'retrieval')
                ranked = sorted((r for r in audit['rankings'] if r['branch_ranks'].get('dense')),
                                key=lambda r: r['branch_ranks']['dense'])
                dense = [by_key[r['chunk_key']] for r in ranked]

                def get(where=None, **kw):
                    docs = [d for d in corpus if not where or all(d.metadata.get(k) == v for k, v in where.items())]
                    return {'documents': [d.page_content for d in docs], 'metadatas': [d.metadata for d in docs]}

                store = SimpleNamespace(get=get, as_retriever=lambda **kw:
                                        SimpleNamespace(invoke=lambda query: dense))

                def collect():
                    diagnostics = []
                    evidence = support.retrieve_evidence(case['query'], store=store, diagnostics=diagnostics)
                    packed = support.pack_context(evidence, 'kb', diagnostics, 16000)
                    messages = support.build_messages(case['query'], packed, 'kb', diagnostics)
                    return packed, diagnostics, sum(len(m['content']) for m in messages)

                with patch.object(support, 'focus_documents', lambda query, evidence, *a, **kw: evidence):
                    before, _, before_chars = collect()
                recorded = [Evidence(**e) for e in case['pipeline_result']['post_selection_evidence']]
                if [identity(e) for e in before] != [identity(e) for e in recorded]:
                    raise ValueError('Unfocused replay differs from the frozen trace: '+case['id'])
                after, diagnostics, after_chars = collect()
                kept = {identity(e) for e in after}
                previous_by_id = {e.id: e for e in recorded}
                cited = set()
                for generation in case['trace']['generation']:
                    if generation.get('raw_answer'):
                        raw = json.loads(generation['raw_answer'])
                        for claim in raw.get('claims', []):
                            for citation in claim.get('evidence', []):
                                cited.add(identity(previous_by_id[citation['source_id']]))
                pages = {(e.source_file, str(e.page_number)) for e in after}
                focus = next(d for d in diagnostics if d.get('stage') == 'context_focus')
                rows.append({'id': case['id'], 'query': case['query'],
                    'unfocused_matches_frozen_trace': True,
                    'before_chunks': len(before), 'after_chunks': len(after),
                    'before_message_characters': before_chars, 'after_message_characters': after_chars,
                    'annotated_gold_page_present': bool(pages & {tuple(p) for p in case['gold_pages']}),
                    'all_previously_cited_chunks_retained': cited <= kept,
                    'previously_cited_chunks': len(cited), 'focus': focus,
                    'selected_sources': [asdict(e) for e in after],
                    'table_coverage': [t for d in diagnostics for t in d.get('tables', [])]})
    report = {'scope': 'Offline recorded dense hits + read-only corpus lexical replay; no new answers or accuracy score',
              'profile': support.PROFILE, 'network_calls': 0, 'llm_calls': 0, 'embedding_calls': 0,
              'corpus_chunks': len(corpus), 'source_trace_sha256': hashlib.sha256(args.trace.read_bytes()).hexdigest(),
              'code_sha256': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in (
                  'app/rag/context_focus.py', 'app/rag/support_pipeline.py',
                  'app/rag/standard/hybrid_retriever.py', 'scripts/review_support_context.py')},
              'source_trace': str(args.trace), 'rows': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps({'cases': len(rows), 'before_chunks': sum(r['before_chunks'] for r in rows),
        'after_chunks': sum(r['after_chunks'] for r in rows),
        'gold_page_present': sum(r['annotated_gold_page_present'] for r in rows),
        'all_previously_cited_chunks_retained': all(r['all_previously_cited_chunks_retained'] for r in rows),
        'network_calls': 0, 'output': str(args.output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
