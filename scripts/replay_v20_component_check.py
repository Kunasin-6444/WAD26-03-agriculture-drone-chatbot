"""Replay recorded model outputs against saved evidence; strictly no network."""
import hashlib
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUN = ROOT / 'cache/eval/support_v20_claude_measurement_20261029'
TARGET = RUN / 'component_and_header_replay.json'


def main():
    if TARGET.exists():
        raise FileExistsError(TARGET)
    report = json.loads((RUN / 'kb.json').read_text(encoding='utf-8'))
    usage = json.loads((RUN / 'usage.json').read_text(encoding='utf-8'))
    from app.rag import support_pipeline as support
    from app.rag.evidence import Evidence
    rows = []
    def deny(*args, **kwargs):
        raise AssertionError('Replay must stay offline')
    with patch.object(socket.socket, 'connect', deny):
        for row in report['rows']:
            if row['id'] == 'inv07':
                continue  # Query plans require catalog metadata; no answer replay.
            call = next(c for c in usage['calls'] if c['phase'] == row['id'] and c['kind'] == 'answer')
            saved = row['pipeline_result']['post_selection_evidence']
            sources = [Evidence(**source) for source in saved]
            with patch.object(support, 'call_llm', return_value=call['choices'][0]['content']):
                result = support.run_support_pipeline(row['query'], source='kb', evidence_override=sources)
            rows.append({'id': row['id'], 'old_answer': row.get('answer'), 'replayed_answer': result.answer,
                'old_citation_checks_passed': row['pipeline_result']['citation_checks_passed'],
                'replayed_citation_checks_passed': result.citation_checks_passed,
                'replayed_reason': result.grade_reason, 'missing_aspect': result.missing_aspect})
    u03 = next(row for row in rows if row['id'] == 'u03')
    if '120-160+12' not in u03['replayed_answer']:
        raise AssertionError('Saved u03 rate is still missing')
    result = {'scope': 'saved v20 response replay with saved evidence; not a new model response',
        'api_calls': 0, 'rows': rows, 'code_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ROOT / 'app/rag/table_grounding.py', ROOT / 'app/rag/evidence.py', ROOT / 'app/rag/support_pipeline.py')}}
    with TARGET.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(json.dumps({'rows': len(rows), 'u03_citations': u03['replayed_citation_checks_passed'],
                      'u03_reason': u03['replayed_reason'], 'output': str(TARGET)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
