"""New questions generate independently; stale cached answers must never return."""
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from app.rag.crag_service import CragResponse
from app.services.ai_service import ask_ai
from app.service_status import ERROR_MESSAGES


def response(text, source='knowledge_base', grade='CORRECT'):
    return CragResponse(text, source, grade, '')


def test_repeat_returns_new_answer_and_its_own_citation_even_with_old_cache_setting():
    first = 'ข้อมูลรุ่นแรก [1]\n[1] manual.pdf, หน้า 1'
    second = 'ข้อมูลรุ่นใหม่ [1]\n[1] manual.pdf, หน้า 2'
    with patch.dict('os.environ', {'ANSWER_CACHE_TTL_SECONDS': '3600'}), \
         patch('app.services.ai_service.run_crag_pipeline', side_effect=[response(first), response(second)]):
        assert ask_ai('ตรวจหัวฉีดอย่างไร', 'user-a') == first
        assert ask_ai('ตรวจหัวฉีดอย่างไร', 'user-a') == second


def test_identical_concurrent_questions_do_not_share_an_answer():
    barrier = threading.Barrier(2)
    lock = threading.Lock()
    counter = 0
    def generate(_):
        nonlocal counter
        with lock:
            counter += 1
            number = counter
        barrier.wait(timeout=3)
        return response(f'คำตอบ {number} [1]\n[1] manual.pdf, หน้า {number}')
    with patch('app.services.ai_service.run_crag_pipeline', side_effect=generate), ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(ask_ai, 'ตรวจหัวฉีดอย่างไร', 'user-a') for _ in range(2)]
        assert {f.result(timeout=5) for f in futures} == {
            'คำตอบ 1 [1]\n[1] manual.pdf, หน้า 1', 'คำตอบ 2 [1]\n[1] manual.pdf, หน้า 2'}


def test_repeated_question_reports_current_outage_instead_of_a_previous_success():
    with patch('app.services.ai_service.run_crag_pipeline', side_effect=[
        response('ข้อมูลเดิม'), response(ERROR_MESSAGES['quota_exhausted'], 'abstain', 'INCORRECT')]):
        assert ask_ai('ตรวจหัวฉีดอย่างไร') == 'ข้อมูลเดิม'
        assert ask_ai('ตรวจหัวฉีดอย่างไร') == ERROR_MESSAGES['quota_exhausted']


def test_failed_generation_does_not_block_the_next_question():
    with patch('app.services.ai_service.run_crag_pipeline', side_effect=[RuntimeError('unavailable'), response('คำตอบใหม่')]):
        with pytest.raises(RuntimeError):
            ask_ai('ตรวจหัวฉีดอย่างไร')
        assert ask_ai('ตรวจหัวฉีดอย่างไร') == 'คำตอบใหม่'
