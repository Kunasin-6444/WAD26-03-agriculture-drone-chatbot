import json
import os
import unittest
from unittest.mock import patch

from app.rag import crag_service as crag
from app.rag.evidence import Evidence
from scripts.rag_evaluation_trace import (blank_review, capture_pipeline, retrieval_diagnostics,
                                         review_passed, summarize_reviews)


def generation(*pages):
    return {'messages': [{'role': 'user', 'content': json.dumps({'sources': [
        {'source_file': 'manual.pdf', 'page_number': page} for page in pages]})}]}


class EvaluationTrace(unittest.TestCase):
    def test_raw_rejected_answer_and_actual_sources_survive_for_review(self):
        evidence = Evidence('D1', 'ปั๊มมีปริมาณ 250 ml', 'manual.pdf', '3')
        raw = 'ปั๊มมีปริมาณ 999 ml [D1]'
        with patch.dict(os.environ, {'ANSWER_MODE': 'natural'}), \
             patch.object(crag, 'llm_pool_error', return_value=''), \
             patch.object(crag, 'retrieve_evidence', return_value=[evidence]) as retrieve, \
             patch.object(crag, 'call_llm', return_value=raw) as model, \
             patch.object(crag, 'search_web_fallback', return_value=[]):
            with capture_pipeline() as trace:
                answer = crag.run_crag_pipeline('ปั๊มมีปริมาณเท่าไร')
            self.assertIs(crag.call_llm, model)
        self.assertEqual(retrieve.call_count, 1)
        self.assertEqual(model.call_count, 1)  # tracing cannot create more provider calls
        self.assertEqual(trace['generation'][0]['raw_answer'], raw)
        self.assertEqual(trace['retrieval'][0]['sources'][0]['content'], evidence.content)
        payload = json.loads(trace['generation'][0]['messages'][-1]['content'])
        self.assertEqual(payload['sources'][0]['content'], evidence.content)
        self.assertNotIn('999', answer.answer)
        self.assertTrue(answer.diagnostics[0]['dropped'])

    def test_page_coverage_separates_retrieval_from_each_generation(self):
        case = {'evidence_groups': [
            {'pages': [{'source_file': 'manual.pdf', 'page_number': 3}]},
            {'pages': [{'source_file': 'manual.pdf', 'page_number': 4},
                       {'source_file': 'manual.pdf', 'page_number': 5}]},
        ]}
        trace = {'retrieval': [{'sources': [{'source_file': 'manual.pdf', 'page_from': '3', 'page_end': '5'}]}],
                 'generation': [generation(3), generation(4)]}
        result = retrieval_diagnostics(case, trace)
        self.assertEqual(result['retrieved_gold_group_coverage'], 1)
        self.assertEqual([g['gold_group_coverage'] for g in result['generation']], [.5, .5])
        # Two incomplete generations must never be reported as one complete prompt.
        self.assertEqual(result['gold_groups'], 2)

    def test_unannotated_web_case_has_unknown_page_coverage(self):
        result = retrieval_diagnostics({}, {'retrieval': [], 'generation': [generation(3)]})
        self.assertIsNone(result['retrieved_gold_group_coverage'])
        self.assertIsNone(result['generation'][0]['gold_group_coverage'])

    def test_failed_call_retains_sources_and_hooks_restore_after_exception(self):
        messages = [{'role': 'user', 'content': 'question'}]
        with patch.object(crag, 'call_llm', side_effect=TimeoutError('do not log credentials')) as call:
            with self.assertRaises(TimeoutError):
                with capture_pipeline() as trace:
                    crag.call_llm(messages, client=object())
            self.assertIs(crag.call_llm, call)
        self.assertEqual(trace['generation'], [{'messages': messages, 'error_type': 'TimeoutError'}])

    def test_legacy_judge_pass_does_not_fill_semantic_review(self):
        summary = summarize_reviews([{'outcome': 'answered', 'judge': {'passed': True},
                                      'quality_review': blank_review()}])
        self.assertEqual(summary, {'eligible': 1, 'reviewed': 0, 'pending': 1, 'pass_rate': None})

    def test_complete_review_requires_relevance_grounding_and_no_harm(self):
        review = {**blank_review(), 'reviewer': 'owner', 'reason': 'checked reference and source',
                  'retrieval_relevant': True, 'answer_relevant': True, 'grounded': True,
                  'correct': True, 'complete': True, 'harmful': False}
        self.assertTrue(review_passed(review))
        for key in ('answer_relevant', 'grounded', 'complete'):
            self.assertFalse(review_passed({**review, key: False}))
        self.assertFalse(review_passed({**review, 'harmful': True}))
        self.assertIsNone(review_passed({**review, 'grounded': None}))
        with self.assertRaises(ValueError):
            review_passed({**review, 'grounded': 'yes'})

    def test_unavailable_and_unrun_are_not_counted_as_reviewed_success(self):
        self.assertEqual(summarize_reviews([{'outcome': 'not_run'}, {'outcome': 'unavailable'}]),
                         {'eligible': 0, 'reviewed': 0, 'pending': 0, 'pass_rate': None})
