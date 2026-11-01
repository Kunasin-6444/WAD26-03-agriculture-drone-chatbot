"""Release blockers: source identity, mixture components and conflicting dose units."""
from app.rag.evidence import Evidence
from app.rag.natural_answer import render
from tests.test_natural_mixture_context import SOURCE, HEADING
from pathlib import Path


def test_english_name_must_be_in_cited_source():
    source = Evidence('D1', 'ไตรไซคลาโซล Tricyclazole 75% WP', 'guide.pdf', '1')
    assert render('ไตรไซคลาโซล (Tricyclazole) 75% WP [D1]', [source]).text
    assert not render('ไตรไซคลาโซล (Glyphosate) 75% WP [D1]', [source]).text


def test_uncited_page_cannot_supply_model_name():
    sources = [Evidence('D1', 'Falcon-A ถังพ่นจุ 20 ลิตร', 'guide.pdf', '1'),
               Evidence('D2', 'Falcon-X ถังพ่นจุ 40 ลิตร', 'guide.pdf', '2')]
    assert not render('Falcon-X ถังพ่นจุ 20 ลิตร [D1]', sources).text
    assert render('Falcon-A ถังพ่นจุ 20 ลิตร [D1]', sources).text


def test_mixture_component_in_separate_paragraph_is_checked_against_its_row():
    prefix = HEADING + '\n\n'
    correct = '• สารเอ: 120-160 กรัมสารออกฤทธิ์/ไร่\n• สารบี: 12 กรัมสารออกฤทธิ์/ไร่ [D1]'
    assert not render(prefix + correct, [SOURCE]).dropped
    for wrong in [correct.replace('120-160', '320-480'), correct.replace('120-160', '12'),
                  correct.replace('กรัมสารออกฤทธิ์/ไร่', 'มิลลิลิตร/ไร่')]:
        assert render(prefix + wrong, [SOURCE]).dropped


def test_conflicting_units_for_same_formulation_are_not_both_recommended():
    sources = [Evidence('D1', 'ไตรไซคลาโซล 75% WP อัตรา 10-15 กรัมต่อน้ำ 20 ลิตร', 'a.pdf', '1'),
               Evidence('D2', 'ไตรไซคลาโซล 75% WP อัตรา 15-20 ซีซีต่อน้ำ 20 ลิตร', 'b.pdf', '2')]
    raw = ('โรคใบไหม้ [D1]\n• ไตรไซคลาโซล สูตร 75% WP อัตรา 10-15 กรัมต่อน้ำ 20 ลิตร [D1]\n'
           '• ไตรไซคลาโซล สูตร 75% WP อัตรา 15-20 ซีซีต่อน้ำ 20 ลิตร [D2]')
    result = render(raw, sources)
    assert 'ต่างกัน' in result.gap
    assert '10-15 กรัม' not in result.text and '15-20 ซีซี' not in result.text


def test_different_formulations_can_have_different_units():
    source = Evidence('D1', 'ไตรไซคลาโซล 75% WP อัตรา 10 กรัม และไตรไซคลาโซล 40% EC อัตรา 20 ซีซี', 'a.pdf', '1')
    raw = ('ไตรไซคลาโซล 75% WP อัตรา 10 กรัม [D1]\n'
           'ไตรไซคลาโซล 40% EC อัตรา 20 ซีซี [D1]')
    assert 'ต่างกัน' not in render(raw, [source]).gap


def test_updated_menu_guidance_has_a_source_and_renders():
    url = 'https://www.fao.org/4/x1531e/x1531e04.htm'
    source = Evidence('W1', 'Empty pesticide containers should not be burned or buried. '
                      'Return them to the distributor or take them to an approved collection scheme. '
                      'Read the product label. Keep pesticides in original containers in a secure place.', url=url)
    claims = [
        'ภาชนะสารที่ใช้หมดแล้ว ไม่ควรฝังหรือเผา ให้สอบถามผู้จำหน่ายหรือหน่วยงานท้องถิ่นเกี่ยวกับจุดรับกำจัดที่เหมาะสม [W1]',
        'อ่านฉลากและปฏิบัติตามคำแนะนำก่อนใช้สาร [W1]',
        'อ่านฉลากและปฏิบัติตามคำแนะนำก่อนใช้สาร เก็บสารในภาชนะเดิมในที่ปลอดภัย [W1]',
    ]
    for claim in claims:
        result = render(claim, [source])
        assert result.text and not result.dropped and url in result.text
    for number in (5, 6):
        menu = Path(f'data/rich_menu_answers/{number}.txt').read_text(encoding='utf-8')
        assert url in menu and 'แล้วฝังดิน' not in menu
