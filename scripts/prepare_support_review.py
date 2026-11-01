"""Prepare oracle inputs and replay actual dense32 hits offline; never calls providers."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sqlite3
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Choose a new output directory; historical reports cannot be overwritten')
    os.environ['ANONYMIZED_TELEMETRY'] = 'False'

    def deny_network(*a, **kw):
        raise AssertionError('Offline preparation attempted network access')

    with patch.object(socket.socket, 'connect', deny_network):
        from langchain_core.documents import Document
        from app.rag import support_pipeline as support
        from app.rag.evidence import Evidence
        from app.rag.standard.hybrid_retriever import document_key
        folder = ROOT/'cache/eval/standard_round3_comparison_20261026'
        source = json.loads((folder/'standard.json').read_text(encoding='utf-8'))
        branches = json.loads((folder/'retrieval_candidates.json').read_text(encoding='utf-8'))
        grouped = defaultdict(dict)
        with sqlite3.connect((ROOT/'chroma_db/chroma.sqlite3').as_uri()+'?mode=ro', uri=True) as db:
            db.row_factory = sqlite3.Row
            for row in db.execute("SELECT m.* FROM embedding_metadata m JOIN embeddings e ON m.id=e.id "
                "JOIN segments s ON e.segment_id=s.id JOIN collections c ON s.collection=c.id "
                "WHERE c.name='drone_knowledge'"):
                field = next((k for k in ('string_value', 'int_value', 'float_value', 'bool_value')
                              if k in row.keys() and row[k] is not None), None)
                if field:
                    grouped[row['id']][row['key']] = bool(row[field]) if field == 'bool_value' else row[field]
        corpus = []
        for meta in grouped.values():
            content = meta.pop('chroma:document', '')
            if content:
                corpus.append(Document(page_content=content, metadata=meta))
        by_key = {document_key(d): d for d in corpus}
        by_page_text = {(d.metadata.get('source_file'), str(d.metadata.get('page_number')), d.page_content): d for d in corpus}
        fixtures = json.loads((ROOT/'tests/fixtures/inv07_table4_snapshot.json').read_text(encoding='utf-8'))
        rows, oracles = [], []
        fake_answer = json.dumps({'status': 'insufficient', 'reason': 'offline mock', 'is_caat_topic': False,
                                  'intro': '', 'missing_aspects': [], 'claims': []})
        for original in source['rows']:
            recorded = next(r for r in branches['rows'] if r['id'] == original['id'])
            dense_entries = sorted((c for c in recorded['candidates'] if 'dense' in c['branch_ranks']),
                                   key=lambda c: c['branch_ranks']['dense'])
            dense = [by_key[c['chunk_key']] for c in dense_entries]

            def get_records(where=None, **kw):
                docs = [d for d in corpus if not where or d.metadata.get('source_file') == where.get('source_file')]
                return {'documents': [d.page_content for d in docs], 'metadatas': [d.metadata for d in docs]}

            store = SimpleNamespace(get=get_records,
                as_retriever=lambda **kw: SimpleNamespace(invoke=lambda query: dense))
            sent = []

            def mock_generate(messages, **kw):
                sent.extend(messages)
                return fake_answer

            with patch.object(support, 'call_llm', mock_generate):
                result = support.run_support_pipeline(original['query'], source='kb', store=store)
            if result.error_code or not sent:
                raise ValueError('Replay failed before mock generation: '+result.grade_reason)
            payload = json.loads(sent[-1]['content'])
            gold = {tuple(p) for p in original['gold_pages']}
            pages = {(s['source_file'], s['page_number']) for s in payload['sources']}
            oracle_docs = [d for d in corpus if (d.metadata.get('source_file'), str(d.metadata.get('page_number'))) in gold]
            if original['id'] == 'inv07':
                # Reviewed source-table fixture, not an expected-answer injection.
                oracle_docs = [by_page_text[(f['meta']['source_file'], str(f['meta']['page_number']), f['doc'])]
                               for f in fixtures]
            oracle_sources = [asdict(Evidence(f'D{i}', d.page_content, d.metadata['source_file'],
                str(d.metadata['page_number']))) for i, d in enumerate(oracle_docs, 1)]
            oracle_case = {'id': original['id'], 'question': original['query'], 'source_mode': 'kb',
                           'sources': oracle_sources, 'gold_pages': original['gold_pages']}
            if original['id'] == 'inv07':
                pages_in_table = sorted({e['page_number'] for e in oracle_sources}, key=int)
                identities = {f['meta'].get('table_id') for f in fixtures if f['meta'].get('table_id')}
                if len(identities) != 1:
                    raise ValueError('Reviewed table snapshot has ambiguous identity')
                oracle_case['table_coverage'] = [{'source_file': oracle_sources[0]['source_file'],
                    'table_id': next(iter(identities)), 'coverage': 'complete',
                    'total_pages': len(pages_in_table), 'total_chunks': len(oracle_sources),
                    'included_pages': pages_in_table, 'missing_pages': [],
                    'included_chunks': [(e['source_file'], e['page_number'], e['content'].strip()) for e in oracle_sources],
                    'reference_snapshot_sha256': hashlib.sha256((ROOT/'tests/fixtures/inv07_table4_snapshot.json').read_bytes()).hexdigest()}]
            oracles.append(oracle_case)
            rows.append({'id': original['id'], 'recorded_dense_count': len(dense),
                'previous_generation_gold_page_found': bool(original['retrieval_diagnostics']['retrieved_gold_group_coverage']),
                'replay_generation_gold_page_found': bool(gold & pages),
                'generation_payload': payload, 'diagnostics': result.diagnostics})
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'scope': 'Actual recorded dense32 + current lexical/table packing, mock generation; not answer accuracy',
              'network_calls': 0, 'corpus_chunks': len(corpus), 'rows': rows}
    for name, data in [('retrieval_replay.json', report), ('oracle_inputs.json', {
        'rubric': 'pilot-support-v2', 'prompt_profile': support.PROFILE,
        'scope': 'Reviewed source pages/table only; generation has not been called', 'cases': oracles,
        'source_report_sha256': hashlib.sha256((folder/'standard.json').read_bytes()).hexdigest()})]:
        with (args.output/name).open('x', encoding='utf-8') as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
    print(json.dumps({'cases': len(rows), 'previous_gold_page_found': sum(r['previous_generation_gold_page_found'] for r in rows),
        'replay_generation_gold_page_found': sum(r['replay_generation_gold_page_found'] for r in rows),
        'oracle_cases_prepared': len(oracles), 'network_calls': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
