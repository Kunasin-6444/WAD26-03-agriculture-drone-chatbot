from app.rag.claim_consistency import claim_inconsistency
from app.rag.evidence import Evidence, parse_grounded_result
from tests.helpers import result_json


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
