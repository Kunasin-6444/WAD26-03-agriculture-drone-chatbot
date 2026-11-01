"""Conservative document focus for an already retrieved KB subset.

RRF ranks do not express the gap in relevance between chunks. Only narrow the
subset when one document has a clear lexical anchor; ambiguous questions keep
the original evidence. Whole chunks and provenance are never rewritten.
This is a local relevance heuristic, not a semantic correctness check.
"""
from __future__ import annotations

from collections import Counter
import math
import re


def _features(text):
    text = re.sub(r'\s+', ' ', text.casefold().replace('ํา', 'ำ')).strip()
    return {text[i:i + size] for size in (3, 4, 5)
            for i in range(len(text) - size + 1) if text[i:i + size].strip()}


def focus_documents(query, evidence, diagnostics, *, preserve_scope=False):
    """Retain a clear document winner and its already retrieved companion chunks.

Use character TF-IDF cosine so Thai need not be segmented by a domain word list.
The winner must reach 0.1 similarity and twice the next document's best match.
All chunks of the winning document survive, including weaker conditions/units.
Multi-aspect requests joined by 'and' keep the original cross-document scope.
Exhaustive, comparative and procedural requests must pass preserve_scope=True.
"""
    groups = {e.source_file for e in evidence}
    diagnostic = {'stage': 'context_focus', 'method': 'character_tfidf_document_margin',
                  'input_chunks': len(evidence), 'output_chunks': len(evidence),
                  'minimum_similarity': 0.1, 'minimum_margin': 2.0,
                  'scope': 'retrieved_subset_not_semantic_assessment'}
    diagnostics.append(diagnostic)
    if preserve_scope or re.search(r'และ|พร้อม(?:ทั้ง|กับ)?|รวมทั้ง|\band\b', query, re.I):
        diagnostic['reason'] = 'preserve_comparative_procedure_or_multi_aspect_scope'
        return list(evidence)
    if len(groups) < 2 or '' in groups or any(e.url for e in evidence):
        diagnostic['reason'] = 'no_separate_kb_documents'
        return list(evidence)

    bags = [_features(e.content) for e in evidence]
    frequency = Counter(term for bag in bags for term in bag)

    def vector(bag):
        weights = {term: math.log(1 + (len(bags) + 1) / (frequency[term] + 1)) for term in bag}
        norm = math.sqrt(sum(value * value for value in weights.values()))
        return {term: value / norm for term, value in weights.items()} if norm else {}

    query_vector = vector(_features(query))
    scores, best = [], {}
    for item, bag in zip(evidence, bags):
        score = sum(value * query_vector.get(term, 0) for term, value in vector(bag).items())
        best[item.source_file] = max(best.get(item.source_file, 0.0), score)
        scores.append({'source_id': item.id, 'similarity': round(score, 6)})
    ranking = sorted(best, key=lambda source: (-best[source], source))
    winner, runner_up = ranking[:2]
    diagnostic['scores'] = scores
    diagnostic['document_scores'] = {source: round(best[source], 6) for source in ranking}
    if best[winner] < 0.1 or best[winner] < 2 * best[runner_up]:
        diagnostic['reason'] = 'no_clear_lexical_anchor'
        return list(evidence)
    selected = [item for item in evidence if item.source_file == winner]
    diagnostic.update(reason='clear_document_anchor', selected_document=winner,
                      output_chunks=len(selected),
                      dropped_source_ids=[item.id for item in evidence if item.source_file != winner])
    return selected
