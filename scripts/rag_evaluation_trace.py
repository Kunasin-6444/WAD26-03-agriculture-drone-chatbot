"""Evaluation-only tracing and review fields; no provider calls of its own.

Page coverage is a retrieval diagnostic, never semantic answer correctness.
Unknown human-review fields stay unknown, including when legacy judge passed.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
from copy import deepcopy
from dataclasses import asdict
import json
import os
from unittest.mock import patch


REVIEW_FIELDS = ('retrieval_relevant', 'answer_relevant', 'grounded', 'correct', 'complete', 'harmful')


def blank_review() -> dict:
    return {'rubric': 'rag-review-v1', **dict.fromkeys(REVIEW_FIELDS), 'reviewer': '', 'reason': ''}


def review_passed(review: dict) -> bool | None:
    """A completed semantic review is required; missing values never mean pass."""
    values = [review.get(key) for key in REVIEW_FIELDS]
    if any(value is not None and type(value) is not bool for value in values):
        raise ValueError('Review values must be boolean or null')
    if any(value is None for value in values) or not review.get('reviewer') or not review.get('reason'):
        return None
    return all(review[key] for key in REVIEW_FIELDS if key != 'harmful') and not review['harmful']


def summarize_reviews(rows: list[dict]) -> dict:
    available = [row for row in rows if row.get('outcome') not in ('not_run', 'unavailable')]
    verdicts = [review_passed(row.get('quality_review', {})) for row in available]
    reviewed = [value for value in verdicts if value is not None]
    return {'eligible': len(available), 'reviewed': len(reviewed), 'pending': len(verdicts) - len(reviewed),
            'pass_rate': sum(reviewed) / len(reviewed) if reviewed else None}


def _pages(sources: list[dict]) -> set[tuple[str, str]]:
    pages = set()
    for source in sources:
        if source.get('url') or not source.get('source_file'):
            continue
        first = str(source.get('page_from') or source.get('page_number') or '')
        last = str(source.get('page_end') or first)
        if first.isdigit() and last.isdigit() and 0 < int(first) <= int(last):
            pages.update((source['source_file'], str(page)) for page in range(int(first), int(last) + 1))
    return pages


def retrieval_diagnostics(case: dict, trace: dict) -> dict:
    groups = case.get('evidence_groups', [])
    expected = [{(p['source_file'], str(p['page_number'])) for p in group['pages']} for group in groups]
    retrieved = _pages([source for stage in trace['retrieval'] for source in stage.get('sources', [])])
    # Keep each generation separate: unioning two incomplete prompts could falsely
    # imply that one model call received all necessary evidence.
    def coverage(pages):
        return sum(bool(group & pages) for group in expected) / len(expected) if expected else None

    generation = []
    for call in trace['generation']:
        sources = None
        schema_pages = set()
        for message in reversed(call['messages']):
            if message.get('role') != 'user':
                continue
            try:
                payload = json.loads(message['content'])
            except (TypeError, ValueError):
                continue
            if isinstance(payload, dict) and isinstance(payload.get('sources'), list):
                sources = payload['sources']
                schema_pages = {(table['source_file'],str(page)) for table in payload.get('table_schemas',[])
                                for page in table.get('pages',[]) if table.get('source_file')}
                break
        pages = _pages(sources) if sources is not None else set()
        generation.append({'source_payload_observed': sources is not None, 'kb_pages': sorted(pages),
                           'gold_group_coverage': coverage(pages) if sources is not None else None,
                           'schema_only_table_pages':sorted(schema_pages),
                           'schema_only_gold_group_coverage':coverage(schema_pages) if schema_pages else None})
    return {'scope': 'annotated KB page groups only; not semantic relevance or answer accuracy',
            'gold_groups': len(expected), 'retrieved_kb_pages': sorted(retrieved),
            'retrieved_gold_group_coverage': coverage(retrieved), 'generation': generation}


@contextmanager
def capture_pipeline(pipeline_name: str = 'baseline'):
    """Single-process evaluator hook. Does not modify prompts, raw replies or routing.

    Persist only the evidence/messages/response, never client objects or request
    credentials. Hooks restore on success and exceptions. Not for concurrent use.
    """
    if pipeline_name in ('baseline', 'exclusive'):
        from app.rag import crag_service, rag_service
        entry_module = crag_service
        generation_modules = (crag_service, rag_service)
    elif pipeline_name == 'candidate':
        from app.rag.candidate import pipeline as entry_module
        generation_modules = (entry_module,)
    elif pipeline_name == 'support':
        from app.rag import support_pipeline as entry_module
        generation_modules = (entry_module,)
    else:
        raise ValueError(f'Unknown evaluation pipeline: {pipeline_name}')
    trace = {'retrieval': [], 'web': [], 'generation': []}
    query = getattr(entry_module,'render_table_query',None)
    retrieve = entry_module.retrieve_evidence
    web = getattr(entry_module, 'web_evidence', None)

    def record_retrieval(query, *args, **kwargs):
        entry = {'query': query, 'sources': []}
        trace['retrieval'].append(entry)
        try:
            result = retrieve(query, *args, **kwargs)
            entry['sources'] = [asdict(source) for source in result]
            return result
        except Exception as exc:
            entry['error_type'] = type(exc).__name__
            raise

    def record_web(*args, **kwargs):
        result = web(*args, **kwargs)
        trace['web'].append({'sources': [asdict(source) for source in result]})
        return result

    def recorder(original):
        def call(messages, *args, **kwargs):
            entry = {'messages': deepcopy(messages)}
            trace['generation'].append(entry)
            try:
                result = original(messages, *args, **kwargs)
                entry['raw_answer'] = result
                return result
            except Exception as exc:
                entry['error_type'] = type(exc).__name__
                if getattr(exc, 'finish_reason', ''):
                    entry['finish_reason'] = exc.finish_reason
                    entry['partial_response'] = exc.partial_response
                raise
        return call

    def record_query(question,catalog,plan,evidence):
        entry={'plan':deepcopy(plan)}
        trace.setdefault('table_queries',[]).append(entry)
        result=query(question,catalog,plan,evidence)
        entry.update(diagnostics=deepcopy(result.diagnostics),source_type=result.source_type,
                     evidence_trace=deepcopy(result.evidence_trace))
        return result

    with ExitStack() as stack:
        stack.enter_context(patch.object(entry_module, 'retrieve_evidence', record_retrieval))
        if pipeline_name == 'exclusive':
            if os.getenv('RAG_WEB_RETRIEVER', 'legacy').strip().lower() == 'read':
                from app.rag import web_retrieval
                stack.enter_context(patch.object(web_retrieval, 'call_llm', recorder(web_retrieval.call_llm)))
        if web is not None:
            stack.enter_context(patch.object(entry_module, 'web_evidence', record_web))
        if query is not None:
            stack.enter_context(patch.object(entry_module,'render_table_query',record_query))
        # Natural calls the crag alias; legacy structured generation calls rag_service.
        for module in generation_modules:
            stack.enter_context(patch.object(module, 'call_llm', recorder(module.call_llm)))
        yield trace
