"""Adjacent referenced statements must preserve mixture components and their rates."""
from app.rag.evidence import Evidence
from app.rag.natural_answer import render


TABLE = (
    'สาร | อัตราสารที่ใช้ (กรัมสารออกฤทธิ์/ไร่) | กำหนดการใช้ | วัชพืชที่ควบคุมได้\n'
    'สารเอ | 320-480 | พ่นก่อนวัชพืชงอก | ใบแคบ\n'
    'สารเอ+สารบี | 120-160+12 | พ่นก่อนวัชพืชงอก | ใบแคบและกว้าง\n'
    'สารซี+สารดี | 100-150+30 | พ่นก่อนวัชพืชงอก | ใบแคบและกว้าง'
)
SOURCE = Evidence('D1', TABLE, 'table.pdf', '1')
OTHER = Evidence('D2', TABLE, 'other.pdf', '2')
HEADING = 'สารเอ+สารบี ควบคุมวัชพืชใบแคบและกว้าง [D1]'
CORRECT = ('อัตรา 120-160+12 กรัมสารออกฤทธิ์/ไร่ โดยเป็นสารเอ 120-160 '
           'กรัมสารออกฤทธิ์/ไร่ และสารบี 12 กรัมสารออกฤทธิ์/ไร่ '
           'พ่นก่อนวัชพืชงอก [D1]')


def test_multiline_mixture_keeps_correct_components_and_citation():
    result = render(HEADING + '\n' + CORRECT, [SOURCE])
    assert not result.dropped
    assert '120-160+12' in result.text and 'พ่นก่อนวัชพืชงอก' in result.text
    assert 'table.pdf, หน้า 1' in result.text


def test_multiline_swapped_components_are_not_shown():
    wrong = CORRECT.replace('สารเอ 120-160', 'สารเอ 12').replace('สารบี 12 กรัม', 'สารบี 120-160 กรัม')
    result = render(HEADING + '\n' + wrong, [SOURCE])
    assert result.dropped and 'สารเอ 12' not in result.text


def test_single_line_swapped_components_are_not_shown():
    correct = 'สารเอ+สารบี อัตรา 120-160+12 กรัมสารออกฤทธิ์/ไร่ คือสารเอ 120-160 กรัมสารออกฤทธิ์/ไร่ และสารบี 12 กรัมสารออกฤทธิ์/ไร่ [D1]'
    wrong = correct.replace('สารเอ 120-160', 'สารเอ 12').replace('สารบี 12 กรัม', 'สารบี 120-160 กรัม')
    assert not render(correct, [SOURCE]).dropped
    assert render(wrong, [SOURCE]).dropped


def test_mixture_context_cannot_cross_different_sources():
    wrong_citation = CORRECT.replace('[D1]', '[D2]')
    result = render(HEADING + '\n' + wrong_citation, [SOURCE, OTHER])
    assert result.dropped and '120-160+12' not in result.text


def test_single_component_wrong_unit_and_rate_remain_rejected():
    for line in [CORRECT.replace('กรัมสารออกฤทธิ์/ไร่', 'มิลลิลิตร/ไร่'),
                 CORRECT.replace('สารเอ 120-160', 'สารเอ 320-480'),
                 'สารเอเดี่ยวใช้อัตรา 120-160 กรัมสารออกฤทธิ์/ไร่ [D1]']:
        result = render(HEADING + '\n' + line, [SOURCE])
        assert result.dropped


def test_no_subject_or_ambiguous_subject_is_not_assumed():
    result = render('ข้อมูลสารกำจัดวัชพืช [D1]\n' + CORRECT, [SOURCE])
    assert result.dropped
    result = render(HEADING + ' สารซี+สารดี [D1]\n' + CORRECT, [SOURCE])
    assert result.dropped
