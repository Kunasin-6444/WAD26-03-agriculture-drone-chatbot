"""Prepare the bounded Nov 1 development review from existing references, offline.

No app imports, providers, gold edits or holdout selection. Web references are
historical and explicitly await source review. This command prepares no live run.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from scripts.rag_evaluation_trace import blank_review

ROOT = Path(__file__).resolve().parents[1]
KB_IDS = ('my04', 'my01', 'u01', 'u03', 'mix02', 'inv07')


def prepare() -> dict:
    gold_path = ROOT / 'tests/data/source_gold_2026-10-18.json'
    hybrid_path = ROOT / 'tests/data/hybrid_acceptance.json'
    gold = json.loads(gold_path.read_text(encoding='utf-8'))
    hybrid = json.loads(hybrid_path.read_text(encoding='utf-8'))
    known = {case['id']: case for case in gold['cases'] + gold['answer_only_cases']}
    rows = []
    for case_id in (*KB_IDS, 'a01'):
        case = known[case_id]
        if case.get('split', 'dev') != 'dev' or case['review']['decision'] not in ('ok', 'fix'):
            raise ValueError(f'Reference is not reviewed development data: {case_id}')
        rows.append({'id': case_id, 'mode': 'web' if case_id == 'a01' else 'kb',
                     'query': case['query'], 'reference_file': str(gold_path.relative_to(ROOT)),
                     'reference_review': case['review'], 'expected_answer': case['expected_answer'],
                     'evidence_groups': case.get('evidence_groups', []),
                     'reference_status': 'web_recheck_required' if case_id == 'a01' else 'owner_reviewed_reference',
                     'quality_review': blank_review(), 'run_status': 'not_run'})
    # Reuse existing acceptance questions; these are weaker contracts, not a
    # substitute for a full source-backed expected answer (especially registration).
    for index, case in enumerate(hybrid['cases'], 1):
        mode = 'mixed' if case['sources'] == ['hybrid'] else 'web'
        rows.append({'id': f'acceptance{index:02}', 'mode': mode, 'query': case['query'],
                     'reference_file': str(hybrid_path.relative_to(ROOT)),
                     'reference_checked_at': hybrid['reviewed_at'], 'reference_note': hybrid['note'],
                     'existing_acceptance_contract': case,
                     'reference_status': 'web_recheck_and_complete_reference_required',
                     'expected_answer': None, 'quality_review': blank_review(), 'run_status': 'not_run'})
    return {'version': 1, 'deadline': '2026-11-01', 'kind': 'development_review_not_live_authorization',
            'source_sha256': {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in (gold_path, hybrid_path)},
            'counts': {mode: sum(row['mode'] == mode for row in rows) for mode in ('kb', 'web', 'mixed')},
            'owner_trial': 'Owner chooses six new questions, two per mode; not used for tuning.',
            'diagnostic_backlog': ['a05 has pending owner reference; do not silently treat it as approved gold',
                                  'Soil-nozzle and crop-age owner traces still need full source-backed expected answers'],
            'cases': rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'cache/eval/release_20261101')
    args = parser.parse_args()
    payload = prepare()
    # A new directory protects any filled-in owner review or earlier baseline.
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'review.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    with (args.output / 'review.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['id', 'โหมด', 'คำถาม', 'สถานะคำตอบอ้างอิง', 'คำตอบอ้างอิงเดิม', 'หลักฐาน KB',
                         'คำตอบจริง', 'ค้นตรงเรื่อง', 'ตอบตรงคำถาม', 'ความหมายตรงหลักฐาน', 'ถูก', 'ครบ', 'ผิดอันตราย', 'ผู้ตรวจ', 'เหตุผล'])
        for case in payload['cases']:
            writer.writerow([case['id'], case['mode'], case['query'], case['reference_status'],
                             case['expected_answer'] or 'ต้องตรวจแหล่งเว็บและจัดทำคำตอบอ้างอิงให้ครบก่อนวัด',
                             json.dumps(case.get('evidence_groups', []), ensure_ascii=False),
                             '', '', '', '', '', '', '', '', ''])
    print(json.dumps({'prepared': len(payload['cases']), 'counts': payload['counts'],
                      'needs_web_reference_review': sum(c['mode'] != 'kb' for c in payload['cases']),
                      'api_calls': 0, 'output': str(args.output)}, indent=2))


if __name__ == '__main__':
    main()
