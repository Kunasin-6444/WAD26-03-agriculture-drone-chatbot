"""Context relevance regression tests; no providers or production KB writes."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.rag.context_focus import focus_documents
from app.rag.evidence import Evidence
from app.rag import support_pipeline as support


def sample():
    return [
        Evidence('D1', 'ZX-847 dispensing volume is 250 ml per cycle.', 'pump.pdf', '7'),
        Evidence('D2', 'Do not operate with hot liquids. Use only a new seal.', 'pump.pdf', '8'),
        Evidence('D3', 'Inventory | Price\nZX-847 | 9000 dollars\nAB-16 | 1800 dollars', 'prices.pdf', '3'),
    ]


def test_clear_anchor_drops_price_document_but_keeps_same_manual_condition_and_ids():
    original = sample()
    diagnostic = []
    selected = focus_documents('ZX-847 dispensing volume per cycle', original, diagnostic)
    assert selected == original[:2]
    assert selected[0] is original[0] and selected[1] is original[1]
    assert selected[1].content == 'Do not operate with hot liquids. Use only a new seal.'
    assert diagnostic[-1]['reason'] == 'clear_document_anchor'
    assert diagnostic[-1]['dropped_source_ids'] == ['D3']
    assert len(original) == 3


def test_thai_focus_preserves_units_and_condition_in_another_chunk_of_the_manual():
    original = [
        Evidence('D1', 'ชุดกังหันมรกตมีปริมาตรถัง 18 ลิตร ใช้กับน้ำเย็นเท่านั้น', 'เครื่องมือ.pdf', '1'),
        Evidence('D2', 'ห้ามใช้เมื่อซีลชำรุด และต้องไม่เปิดฝาขณะทำงาน', 'เครื่องมือ.pdf', '2'),
        Evidence('D3', 'รายการ | ราคา\nกังหันมรกต | 900 บาท\nสายไฟ | 30 บาท', 'ราคา.pdf', '3')]
    diagnostic = []
    selected = focus_documents('ชุดกังหันมรกตมีปริมาตรถังกี่ลิตร', original, diagnostic)
    assert selected == original[:2]
    assert '18 ลิตร' in selected[0].content
    assert selected[1].content == original[1].content


def test_similar_relevance_keeps_both_documents_instead_of_picking_an_arbitrary_winner():
    original = [Evidence('D1', 'ZX-847 dispensing volume is 250 ml per cycle.', 'a.pdf', '1'),
                Evidence('D2', 'ZX-847 dispensing volume is 300 ml per cycle.', 'b.pdf', '1')]
    diagnostic = []
    assert focus_documents('ZX-847 dispensing volume per cycle', original, diagnostic) == original
    assert diagnostic[-1]['reason'] == 'no_clear_lexical_anchor'


def test_no_lexical_match_preserves_dense_synonym_results():
    original = [Evidence('D1', 'The rotor is fractured.', 'rotor.pdf', '4'),
                Evidence('D2', 'A damaged blade must be replaced.', 'maintenance.pdf', '5')]
    diagnostic = []
    assert focus_documents('ตรวจใบพัดแตก', original, diagnostic) == original
    assert diagnostic[-1]['reason'] == 'no_clear_lexical_anchor'


@pytest.mark.parametrize('query,preserve', [
    ('Compare all ZX-847 prices', True),
    ('List every mixing step and its conditions', True),
    ('ZX-847 dispensing volume and seal warranty', False),
    ('ปริมาตรถังและการรับประกันชุดกังหันมรกต', False),
])
def test_comparison_procedure_or_multi_aspect_request_preserves_cross_document_evidence(query, preserve):
    original = sample()
    diagnostic = []
    assert focus_documents(query, original, diagnostic, preserve_scope=preserve) == original
    assert diagnostic[-1]['reason'] == 'preserve_comparative_procedure_or_multi_aspect_scope'


@pytest.mark.parametrize('original', [[], [Evidence('D1', 'single source', 'a.pdf', '1')],
    [Evidence('W1', 'web', url='https://example.com/1'), Evidence('W2', 'web', url='https://example.com/2')]])
def test_empty_single_document_or_web_data_is_unchanged(original):
    assert focus_documents('arbitrary query', original, []) == original


def test_retrieval_uses_focus_before_source_ids_are_assigned():
    pytest.importorskip('langchain_core')
    from app.rag.standard import pipeline as standard
    evidence = sample()
    store = SimpleNamespace(get=lambda **kw: pytest.fail('No table lookup or other database work needed'))
    diagnostic = []
    with patch.object(standard, 'retrieve_evidence', return_value=evidence):
        actual = support.retrieve_evidence('ZX-847 dispensing volume per cycle', store=store, diagnostics=diagnostic)
    assert [(e.source_file, e.page_number, e.content) for e in actual] == [
        (e.source_file, e.page_number, e.content) for e in evidence[:2]]
    assert [e.id for e in actual] == ['D1', 'D2']
    assert diagnostic[-2]['stage'] == 'context_focus'


def test_explicitly_requested_multiple_manuals_cannot_be_narrowed_to_one():
    pytest.importorskip('langchain_core')
    from app.rag.standard import pipeline as standard
    evidence = [
        Evidence('D1', sample()[0].content, 'UAV01 pump.pdf', '7'),
        Evidence('D2', sample()[2].content, 'UAV02 prices.pdf', '3')]
    store = SimpleNamespace(get=lambda **kw: pytest.fail('No additional lookup needed'))
    with patch.object(standard, 'retrieve_evidence', return_value=evidence):
        actual = support.retrieve_evidence('UAV01 / UAV02 ZX-847 dispensing volume per cycle', store=store)
    assert [e.source_file for e in actual] == ['UAV01 pump.pdf', 'UAV02 prices.pdf']
