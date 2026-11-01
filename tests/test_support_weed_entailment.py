"""Opt-in positive subset entailment retains strict row/value/unit checks."""
import json
from unittest.mock import patch

import pytest

from app.rag import support_pipeline as support
from app.rag.evidence import Evidence, parse_grounded_result
from app.rag.structured_tables import TableCatalog

TABLE = ('สาร | อัตรา (กรัมสารออกฤทธิ์/ไร่) | ช่วงใช้ | วัชพืช\n'
         'เบตาซีน | 35-45 | ก่อนวัชพืชงอก | ใบแคบและกว้าง\n'
         'แกมมาซีน | 70-80 | ก่อนวัชพืชงอก | ใบกว้าง\n'
         'เดลตาซีน | 90-100 | หลังวัชพืชงอก | ใบแคบ')
SOURCES = [Evidence('D1', TABLE, 'synthetic.pdf', '4')]
QUOTE = TABLE.splitlines()[1]


def raw(claim, quote=QUOTE):
    return json.dumps({'status': 'sufficient', 'intro': '', 'claims': [{'text': claim,
        'evidence': [{'source_id': 'D1', 'quote': quote}]}]}, ensure_ascii=False)


def test_positive_coverage_subset_needs_opt_in_and_works_through_support_rendering():
    reply = raw('เบตาซีน 35–45 กรัมสารออกฤทธิ์/ไร่ ใช้ก่อนวัชพืชงอก ควบคุมวัชพืชใบแคบได้')
    # Disabling the new policy rejects exactly the same claim/evidence.
    assert not parse_grounded_result(reply, SOURCES).claims
    assert parse_grounded_result(reply, SOURCES, allow_weed_subset=True).status == 'sufficient'
    catalog=TableCatalog.build(SOURCES,[])
    query={'action':'table_query','table_id':catalog.tables[0].id,'operation':'select',
        'select':['c1','c2','c3'],'filters':[{'column':'c0','op':'eq','value':'เบตาซีน'}],
        'limit':1,'unsupported_aspects':[]}
    with patch.object(support, 'call_llm', return_value=json.dumps(query,ensure_ascii=False)):
        result = support.run_support_pipeline('ใช้สารอะไรคุมใบแคบ', source='kb', evidence_override=SOURCES)
    assert result.citation_checks_passed and '35-45' in result.answer


@pytest.mark.parametrize('claim,quote', [
    ('เบตาซีน 35-45 กรัมสารออกฤทธิ์/ไร่ คุมเฉพาะใบแคบ', QUOTE),
    ('เบตาซีน 35-45 กรัมสารออกฤทธิ์/ไร่ คุมใบแคบเท่านั้น', QUOTE),
    ('เบตาซีน 35-45 กรัมสารออกฤทธิ์/ไร่ ไม่คุมใบแคบ', QUOTE),
    ('เบตาซีน 70-80 กรัมสารออกฤทธิ์/ไร่ คุมใบแคบได้', QUOTE),
    ('เบตาซีน 35-45 ลิตร/ไร่ คุมใบแคบได้', QUOTE),
    ('เบตาซีน 35-45 กรัมสารออกฤทธิ์/ไร่ คุมใบแคบได้หลังวัชพืชงอก', QUOTE),
    ('แกมมาซีน 70-80 กรัมสารออกฤทธิ์/ไร่ คุมใบแคบได้', TABLE.splitlines()[2]),
    ('คุมใบแคบได้ ได้แก่ เบตาซีน 35-45 และแกมมาซีน 70-80 กรัมสารออกฤทธิ์/ไร่',
     '\n'.join(TABLE.splitlines()[1:3])),
    ('เดลตาซีน 90-100 กรัมสารออกฤทธิ์/ไร่ คุมใบแคบและกว้างได้', TABLE.splitlines()[3]),
])
def test_false_exclusive_negative_wrong_row_rate_unit_or_timing_remains_rejected(claim, quote):
    assert not parse_grounded_result(raw(claim, quote), SOURCES, allow_weed_subset=True).claims
