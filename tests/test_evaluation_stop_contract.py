"""No false answers or extra calls after an evaluation controller stops."""
import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.rag.candidate.models import CandidateResponse
from app.rag import support_pipeline as support
from scripts import evaluate_answers as ev


@pytest.mark.parametrize('error_code,stop_controller,expected_outcome',[
    ('provider_unavailable',True,'unavailable'),
    ('timeout',False,'unavailable'),
    ('',True,'abstain'),
])
def test_response_metadata_and_controller_stop_override_arbitrary_answer_text(
        tmp_path,error_code,stop_controller,expected_outcome):
    args=SimpleNamespace(pipeline='support',source='kb',model='pinned',prompt='full',judge_model='unused',
        skip_judge=True,split='dev',no_answer_only=True,limit=2,ids=None,gold=ev.GOLD,
        attempt_timeout=25,kb_budget=None,request_timeout=None,output='stop-test',reasoning_effort='low')
    cases=[{'id':str(i),'query':f'question{i}','expected_answer':'reference'} for i in range(2)]
    stopped=False

    def run(question, **kwargs):
        nonlocal stopped
        stopped=stop_controller
        return CandidateResponse('Arbitrary stopped or abstained text','abstain','ERROR','not answered',error_code=error_code)

    with patch.dict(os.environ), patch.object(ev,'OUT_DIR',tmp_path), \
         patch.object(ev,'load_cases',return_value=cases), \
         patch.object(support,'run_support_pipeline',side_effect=run) as pipeline, \
         patch('app.rag.rag_service.FALLBACK_MODELS',[]), \
         patch('app.rag.rag_service.secondary_enabled',return_value=False):
        ev.run(args,stop_requested=lambda:stopped)
    report=json.loads((tmp_path/'stop-test.json').read_text(encoding='utf-8'))
    assert pipeline.call_count==1
    assert [r['outcome'] for r in report['rows']]==[expected_outcome,'not_run']
    assert report['summary']['quality_review']['pass_rate'] is None
    assert report['summary']['ran']==1
