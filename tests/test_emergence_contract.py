from app.rag.claim_consistency import claim_inconsistency
from app.rag.evidence import Evidence, parse_grounded_result
from tests.helpers import result_json
import pytest


def test_weed_emergence_cannot_be_relabelled_as_crop_emergence():
    source = "อาลาคลอร์ | พ่นก่อนวัชพืชงอก | ใบแคบ"
    assert claim_inconsistency("ใช้อาลาคลอร์ก่อนอ้อยงอก", [source], source)
    assert not claim_inconsistency("ใช้อาลาคลอร์ก่อนวัชพืชงอก", [source], source)
    assert claim_inconsistency("ใช้อาลาคลอร์หลังวัชพืชงอก", [source], source)


def test_cited_source_keeps_emergence_subject_and_timing_at_answer_boundary():
    quote = "พ่นก่อนวัชพืชงอก"
    evidence = [Evidence("D1", quote, "UAV06.pdf", "18")]
    bad = result_json(claims=[("พ่นก่อนอ้อยงอก", "D1", quote)])
    good = result_json(claims=[(quote, "D1", quote)])
    assert parse_grounded_result(bad, evidence).claims == []
    assert parse_grounded_result(good, evidence).status == "sufficient"


@pytest.mark.parametrize('joiner', ['หรือ', 'และ'])
def test_coordinated_subject_does_not_smuggle_crop_emergence_into_weed_timing(joiner):
    source = 'พ่นสารคลุมดินก่อนวัชพืชงอกหลังปลูกอ้อยหรือหลังแต่งตอ'
    claim = f'พ่นก่อนอ้อย{joiner}วัชพืชงอก'
    assert claim_inconsistency(claim, [source], source)
    assert not claim_inconsistency('พ่นก่อนวัชพืชงอกหลังปลูกอ้อย', [source], source)
    evidence = [Evidence('D1', source, 'synthetic.pdf', '2')]
    assert not parse_grounded_result(result_json(claims=[(claim, 'D1', source)]), evidence).claims


@pytest.mark.parametrize('phase', ['ก่อน', 'หลัง'])
def test_both_declared_phases_support_an_individual_phase(phase):
    source = 'ใช้ได้ทั้งก่อนและหลังวัชพืชงอก'
    assert not claim_inconsistency(f'ใช้{phase}วัชพืชงอก', [source], source)
    assert claim_inconsistency(f'ใช้{phase}อ้อยงอก', [source], source)


def test_explicit_coordinated_crop_subjects_remain_distinct_and_long_names_are_not_shortened():
    from app.rag.claim_consistency import emergence_states
    assert emergence_states('ก่อนข้าวโพดหรือวัชพืชงอก') == {('ก่อน', 'ข้าวโพด'), ('ก่อน', 'วัชพืช')}
    assert emergence_states('ก่อนและหลังอ้อยหรือวัชพืชงอก') == {
        ('ก่อน', 'อ้อย'), ('หลัง', 'อ้อย'), ('ก่อน', 'วัชพืช'), ('หลัง', 'วัชพืช')}
    assert emergence_states('หลังปลูกอ้อย ก่อนวัชพืชงอก') == {('ก่อน', 'วัชพืช')}


def test_per_quote_scope_does_not_borrow_an_unquoted_crop_phase():
    quote = 'ก่อนวัชพืชงอก'
    page = quote + '\nอีกวิธีหนึ่งใช้หลังอ้อยงอก'
    assert claim_inconsistency('ก่อนอ้อยหรือวัชพืชงอก', [quote], page)


def test_subject_first_table_category_is_about_weeds_not_crop_emergence():
    source = 'กลุ่มสารคุมและฆ่าวัชพืชก่อนงอก (Pre-emergence)'
    assert claim_inconsistency('ใช้ก่อนอ้อยงอก', [source], source)
    assert not claim_inconsistency('ใช้ก่อนวัชพืชงอก', [source], source)
