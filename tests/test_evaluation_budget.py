from copy import deepcopy

import pytest

from scripts.evaluation_budget import ReceiptInputBudget


def fixture_data():
    messages = [{'role': 'user', 'content': 'น้ำหนักถัง 18 ลิตร'}]
    report = {'config': {'model': 'same-model'}, 'rows': [
        {'id': 'one', 'trace': {'generation': [{'messages': messages}]}}]}
    receipts = {'model': 'same-model', 'calls': [
        {'kind': 'answer', 'phase': 'one', 'usage': {'prompt_tokens': 120}}]}
    return messages, report, receipts


def test_exact_message_uses_actual_receipt_without_counting_characters_as_provider_tokens():
    messages, report, receipts = fixture_data()
    calibration = ReceiptInputBudget('same-model', report, receipts, list)
    assert calibration.reserve(deepcopy(messages)) == (184, 'exact_prior_messages_plus64')
    changed = [{'role': 'user', 'content': 'different question'}]
    reserve, method = calibration.reserve(changed)
    assert method == 'worst_observed_ratio_x1.25_plus512'
    assert reserve > len(changed[0]['content'])


def test_calibration_refuses_another_model_and_missing_receipts():
    _, report, receipts = fixture_data()
    with pytest.raises(ValueError, match='same pinned model'):
        ReceiptInputBudget('other-model', report, receipts, list)
    receipts['calls'] = []
    with pytest.raises(ValueError, match='No usable'):
        ReceiptInputBudget('same-model', report, receipts, list)
