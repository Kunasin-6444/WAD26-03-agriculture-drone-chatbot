"""Local input-budget calibration from receipts for the same pinned model.

Exact message matches can reuse the recorded input count with headroom. Other
requests use the worst observed tokenizer ratio plus a safety margin. This is an
estimate, not a provider token-count endpoint or a general tokenizer guarantee.
"""
from __future__ import annotations

import hashlib
import json
import math


def message_key(messages):
    return hashlib.sha256(json.dumps(messages, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


class ReceiptInputBudget:
    def __init__(self, model, report, receipts, encode):
        if report['config']['model'] != model or receipts['model'] != model:
            raise ValueError('Calibration must use the same pinned model')
        self.encode = encode
        self.known = {}
        ratios = []
        by_case = {c['phase']: c['usage']['prompt_tokens'] for c in receipts['calls']
                   if c.get('kind') == 'answer' and c.get('usage')}
        for row in report['rows']:
            if row['id'] not in by_case:
                continue
            generations = row['trace']['generation']
            if len(generations) != 1:
                raise ValueError('Calibration needs exactly one answer request per case')
            messages = generations[0]['messages']
            observed = by_case[row['id']]
            estimated = self.local_count(messages)
            if estimated <= 0 or observed <= 0:
                raise ValueError('Missing input-token count')
            self.known[message_key(messages)] = observed
            ratios.append(observed / estimated)
        if not ratios:
            raise ValueError('No usable calibration receipts')
        self.ratio = max(ratios) * 1.25

    def local_count(self, messages):
        return sum(len(self.encode(str(m.get('content', '')))) for m in messages)

    def reserve(self, messages):
        observed = self.known.get(message_key(messages))
        if observed is not None:
            return observed + 64, 'exact_prior_messages_plus64'
        return math.ceil(self.local_count(messages) * self.ratio) + 512, 'worst_observed_ratio_x1.25_plus512'
