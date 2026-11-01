"""Layout equivalence must not turn different names, rows or units into matches."""
import pytest

from app.rag.claim_consistency import claim_inconsistency
from app.rag.candidate.verifier import verify_and_render_candidate
from app.rag.evidence import Evidence


@pytest.mark.parametrize('printed', ['Q- novaline', 'Q -novaline', 'Q-\nnovaline', 'Q‑ novaline'])
def test_hyphen_layout_keeps_same_identifier(printed):
    assert claim_inconsistency('Q-novaline 50 ml', [], f'{printed} 50 ml') == ''
    evidence = [Evidence('D1', f'{printed} 50 ml', 'example.pdf', '2')]
    result = verify_and_render_candidate('Q-novaline 50 ml [D1]', evidence)
    assert 'Q-novaline' in result.rendered_text


@pytest.mark.parametrize('other', ['R-novaline', 'Q-novamide', 'novaline', 'Qnovaline', 'Q- | novaline'])
def test_distinct_or_cross_cell_identifiers_still_fail(other):
    assert claim_inconsistency('Q-novaline 50 ml', [], f'{other} 50 ml')


def test_layout_equivalence_cannot_hide_wrong_unit():
    assert 'unit conflicts' in claim_inconsistency('Q-novaline 50 l', [], 'Q- novaline 50 ml')


def test_layout_equivalence_cannot_move_value_from_other_row():
    evidence = [Evidence('D1', 'Model | Amount\nQ- novaline | 50 ml\nR- novaline | 90 ml', 'example.pdf', '2')]
    result = verify_and_render_candidate('Q-novaline 90 ml [D1]', evidence)
    assert '90 ml' not in result.rendered_text


def test_distinct_prefixes_and_unrelated_chemicals_are_rejected():
    assert claim_inconsistency('S-novaline 50 ml', [], 'R-novaline 50 ml')
    assert claim_inconsistency('novaline 50 ml', [], 'S-novaline 50 ml')
    assert claim_inconsistency('Q-novaline 50 ml', [], 'Q-glyphosate 50 ml')
