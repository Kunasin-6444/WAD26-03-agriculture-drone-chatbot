"""Offline regression and coverage tests for candidate multi-page table continuation retrieval.

Zero network/API calls. Uses synthetic fixtures, authentic recorded snapshots, and optional real DB checks:
1. Multi-page tables spanning across pages reach context selection and model messages.
2. Multiple row chunks on the same continuation page survive assembly and selection.
3. Unit and condition conflicts (USD vs THB, new vs used, with vs without battery) prevent improper merging.
4. Missing/empty lookups do not certify complete scope.
5. Post-selection coverage tracks evidence that actually reaches the simulated model.
6. Mutation check verifies that disabling continuation strictly FAILS the positive reach assertion.
7. Recorded snapshot replay of authentic Table 4 records from ฟีเจอร์การลงทุน.pdf (verified by SHA256).
8. Real local Chroma DB test (explicitly skipped if DB not present; no silent fallbacks).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.rag.candidate.context_filter import scope_and_filter_context, score_evidence
from app.rag.candidate import pipeline
from app.rag.candidate.prompt import build_candidate_messages
from app.rag.candidate.table_continuation import (
    _chroma_table_lookup,
    are_tables_compatible,
    assemble_candidate_table_evidence,
    extract_table_headers,
    is_comparative_or_table_query,
    is_ui_template_content,
    parse_table_metadata,
)
from app.rag.evidence import Evidence


def _make_table_chunk(
    doc_id: str,
    file: str,
    page: str,
    rows: list[list[str]],
    headers: list[str],
    caption: str = "",
    table_id: str = "",
    row_start: int | None = None,
    row_end: int | None = None,
) -> tuple[Evidence, dict]:
    header_line = " | ".join(headers)
    separator = " | ".join(["---"] * len(headers))
    row_lines = [" | ".join(r) for r in rows]
    content_lines = [header_line, separator] + row_lines
    if caption:
        content_lines.append(f"\n{caption}")

    ev = Evidence(
        id=doc_id,
        content="\n".join(content_lines),
        source_file=file,
        page_number=page,
    )
    meta = {
        "source_file": file,
        "page_number": page,
        "table_id": table_id,
        "row_start": row_start,
        "row_end": row_end,
    }
    return ev, meta


# -----------------------------------------------------------------------------
# Tier 1: Synthetic Fixture Acceptance & Edge Probes
# -----------------------------------------------------------------------------
def test_synthetic_table_continuation_reaches_model_messages():
    """Verify that when the cheapest item is on a continuation page not in initial retrieval,
    table continuation retrieves it and delivers it to the model prompt messages."""
    headers = ["ผู้ผลิต", "รุ่นโดรน", "ความจุ (L)", "ราคา RTF (บาท)"]

    page1_ev, page1_meta = _make_table_chunk(
        "D1", "drone_spec_doc.pdf", "5",
        [["AlphaCorp", "Alpha-X1", "10", "450,000"], ["AlphaCorp", "Alpha-X2", "20", "520,000"]],
        headers=headers, caption="ตารางที่ 1 เปรียบเทียบข้อมูลโดรนและราคา",
        table_id="spec-t1", row_start=1, row_end=2
    )
    page2_ev, page2_meta = _make_table_chunk(
        "D_cont_6", "drone_spec_doc.pdf", "6",
        [["BetaTech", "Beta-Standard", "16", "299,000"], ["BetaTech", "Beta-Pro", "25", "380,000"]],
        headers=headers, caption="ตารางที่ 1 เปรียบเทียบข้อมูลโดรนและราคา (ต่อ)",
        table_id="spec-t1", row_start=3, row_end=4
    )
    page3_ev, page3_meta = _make_table_chunk(
        "D_cont_7", "drone_spec_doc.pdf", "7",
        [["GammaDrone", "Gamma-EcoMini", "8", "85,000"]],
        headers=headers, caption="ตารางที่ 1 เปรียบเทียบข้อมูลโดรนและราคา (ต่อ)",
        table_id="spec-t1", row_start=5, row_end=5
    )

    mock_store = {
        "drone_spec_doc.pdf": [
            (page1_ev, page1_meta),
            (page2_ev, page2_meta),
            (page3_ev, page3_meta),
        ]
    }

    query = "โดรนรุ่นไหนในตารางราคาถูกที่สุด"
    assembled, diag = assemble_candidate_table_evidence(
        [page1_ev], query, lookup_fn=lambda f, t: mock_store.get(f, [])
    )

    assert diag["table_continuation_applied"] is True
    assert diag["tables"][0]["coverage"] == "complete"
    assert diag["tables"][0]["total_pages"] == 3

    assembled_pages = [e.page_number for e in assembled]
    assert assembled_pages == ["5", "6", "7"]

    selected, pre, post, drops = scope_and_filter_context(query, assembled, max_chunks=8)
    selected_pages = [e.page_number for e in selected]
    assert "7" in selected_pages, "Continuation page 7 with cheapest model must survive selection"

    messages = build_candidate_messages(query, selected)
    user_payload = json.loads(messages[1]["content"])
    sources_text = " ".join(s["content"] for s in user_payload["sources"])
    assert "Gamma-EcoMini" in sources_text
    assert "85,000" in sources_text


def test_synthetic_all_row_chunks_on_same_continuation_page_survive():
    """Verify that multiple distinct row chunks on the same continuation page do NOT collide."""
    def chunk(page, row, caption="ตารางที่ 1 ราคาขาย", header="รุ่น | ราคา (บาท)"):
        return Evidence("D" + str(page), caption + "\n" + header + "\n" + row, "catalog.pdf", str(page))

    anchor = chunk(1, "Alpha | 900")
    first = chunk(2, "Beta | 800")
    second = chunk(2, "Gamma | 100")
    query = "รุ่นไหนในตารางราคาถูกที่สุด"

    out, diag = assemble_candidate_table_evidence(
        [anchor], query, lookup_fn=lambda *a: [(anchor, {}), (first, {}), (second, {})]
    )
    all_content = "\n".join(e.content for e in out)
    assert "Beta | 800" in all_content
    assert "Gamma | 100" in all_content

    # Also confirm both survive context selection
    selected, _, _, _ = scope_and_filter_context(query, out, max_chunks=8)
    selected_content = "\n".join(e.content for e in selected)
    assert "Beta | 800" in selected_content
    assert "Gamma | 100" in selected_content


def test_synthetic_same_id_cannot_override_incompatible_units():
    """Verify that having the same table_id does not permit merging when currency/units conflict."""
    def chunk(page, row, caption="ตารางที่ 1 ราคาขาย", header="รุ่น | ราคา (บาท)"):
        return Evidence("D" + str(page), caption + "\n" + header + "\n" + row, "catalog.pdf", str(page))

    a = parse_table_metadata(chunk(1, "Alpha | 900"), {"table_id": "t1"})
    b = parse_table_metadata(chunk(2, "Beta | 20", header="รุ่น | ราคา (USD)"), {"table_id": "t1"})
    assert not are_tables_compatible(a, b)


def test_synthetic_identical_headers_do_not_join_distinct_conditions():
    """Verify that identical headers across distant pages with incompatible conditions are not joined."""
    def chunk(page, row, caption="ตารางที่ 1 ราคาขาย", header="รุ่น | ราคา (บาท)"):
        return Evidence("D" + str(page), caption + "\n" + header + "\n" + row, "catalog.pdf", str(page))

    anchor = chunk(1, "Alpha | 900", caption="ราคาขายเครื่องใหม่ รวมแบตเตอรี่")
    used = chunk(8, "Beta | 100", caption="ราคาขายมือสอง ไม่รวมแบตเตอรี่")
    query = "รุ่นไหนในตารางราคาถูกที่สุด"

    out, diag = assemble_candidate_table_evidence(
        [anchor], query, lookup_fn=lambda *a: [(anchor, {}), (used, {})]
    )
    all_content = "\n".join(e.content for e in out)
    assert "Beta | 100" not in all_content


def test_synthetic_missing_lookup_does_not_certify_complete_scope():
    """Verify that when document lookup returns empty or fails, coverage is NOT marked complete."""
    def chunk(page, row, caption="ตารางที่ 1 ราคาขาย", header="รุ่น | ราคา (บาท)"):
        return Evidence("D" + str(page), caption + "\n" + header + "\n" + row, "catalog.pdf", str(page))

    query = "รุ่นไหนในตารางราคาถูกที่สุด"
    _, diag = assemble_candidate_table_evidence([chunk(1, "Alpha | 900")], query, lookup_fn=lambda *a: [])
    assert diag["tables"][0]["coverage"] != "complete"
    assert diag["tables"][0]["coverage"] == "unknown"

    # Also verify exception during lookup records error rather than complete
    def failing_lookup(*a):
        raise RuntimeError("Lookup timeout")

    _, err_diag = assemble_candidate_table_evidence([chunk(1, "Alpha | 900")], query, lookup_fn=failing_lookup)
    assert err_diag["tables"][0]["coverage"] == "unknown"
    assert err_diag["tables"][0]["status"] == "lookup_error"


def test_synthetic_coverage_tracks_sources_that_actually_reach_model():
    """Verify that if post-selection context drops any table pages, coverage is downgraded to incomplete."""
    def chunk(page, row, caption="ตารางที่ 1 ราคาขาย", header="รุ่น | ราคา (บาท)"):
        return Evidence("D" + str(page), caption + "\n" + header + "\n" + row, "catalog.pdf", str(page))

    query = "รุ่นไหนในตารางราคาถูกที่สุด"
    pages = [chunk(i, f"Model-{i} | {1000-i}") for i in range(1, 10)]
    captured = []

    def reply(messages, **kw):
        captured.append(json.loads(messages[-1]["content"]))
        return "Model-1 ราคา 999 บาท [D1]"

    with patch.object(pipeline, "llm_pool_error", return_value=""), \
         patch.object(pipeline, "retrieve_evidence", return_value=[pages[0]]), \
         patch.object(pipeline, "call_llm", side_effect=reply):
        response = pipeline.run_candidate_pipeline(
            query, mode="kb_only", lookup_fn=lambda *a: [(e, {}) for e in pages]
        )

    sent = {s["page_number"] for s in captured[0]["sources"]}
    complete = [
        t for d in response.diagnostics if d.get("stage") == "table_continuation"
        for t in d.get("tables", []) if t.get("coverage") == "complete"
    ]
    assert len(sent) == 9 or not complete, f"Only {len(sent)} of 9 pages reached the model but coverage stayed complete"


@pytest.mark.parametrize("cheapest_page, cheapest_model, cheapest_price", [
    ("1", "Omega-Base", "72,000"),
    ("2", "Zeta-Compact", "65,000"),
    ("3", "Delta-Lite", "58,000"),
])
def test_synthetic_swapped_positions_and_arbitrary_values_preserve_table_continuity(
    cheapest_page: str, cheapest_model: str, cheapest_price: str
):
    """Verify that table continuation operates independently of where the minimum row is located."""
    headers = ["ผู้ผลิต", "รุ่น", "ราคา"]
    all_pages = {}
    for p in ["1", "2", "3"]:
        price = cheapest_price if p == cheapest_page else f"{int(p) * 200000}"
        model = cheapest_model if p == cheapest_page else f"Model-P{p}"
        ev, meta = _make_table_chunk(
            f"D_{p}", "custom_inventory.pdf", p,
            [["Brand", model, price]],
            headers=headers,
            table_id="inv-tbl",
            row_start=int(p), row_end=int(p)
        )
        all_pages[p] = (ev, meta)

    def mock_lookup(file: str, t_id: str | None):
        return [all_pages["1"], all_pages["2"], all_pages["3"]]

    assembled, diag = assemble_candidate_table_evidence(
        [all_pages["1"][0]], "อุปกรณ์รุ่นไหนราคาต่ำที่สุดในตาราง", lookup_fn=mock_lookup
    )
    assert diag["table_continuation_applied"] is True
    assert len(assembled) == 3

    selected, _, _, _ = scope_and_filter_context("อุปกรณ์รุ่นไหนราคาต่ำที่สุดในตาราง", assembled, max_chunks=8)
    all_content = " ".join(e.content for e in selected)
    assert cheapest_model in all_content
    assert cheapest_price in all_content


def test_synthetic_disparate_tables_with_different_headers_do_not_merge():
    """Two tables on adjacent pages with different headers/units must not be merged."""
    t1_ev, t1_meta = _make_table_chunk(
        "D1", "uav_guide.pdf", "10",
        [["พัดส้ม", "1600", "500"]],
        headers=["หัวฉีด", "รอบ (rpm)", "ปริมาณ (ml/min)"],
        table_id="nozzle-t1", row_start=1, row_end=1
    )
    t2_ev, t2_meta = _make_table_chunk(
        "D2", "uav_guide.pdf", "11",
        [["0.5", "1.428", "3.128"]],
        headers=["Height (m)", "Width (m)/nozzle", "Width (m)/3 nozzle"],
        table_id="width-t2", row_start=1, row_end=1
    )

    t1_parsed = parse_table_metadata(t1_ev, t1_meta)
    t2_parsed = parse_table_metadata(t2_ev, t2_meta)

    assert not are_tables_compatible(t1_parsed, t2_parsed)

    t1_parsed.table_id = ""
    t2_parsed.table_id = ""
    assert not are_tables_compatible(t1_parsed, t2_parsed)


def test_synthetic_ui_templates_and_mockups_excluded_and_penalized_in_table_comparison():
    """Verify that UI mockups and JS code templates are not treated as data tables and
    are penalized during table comparison queries."""
    ui_ev = Evidence(
        id="D1",
        content="ภาพที่ 6 แสดงราคาโดรนและข้อมูลโดรนหลังจากเลือกโดรนแล้ว\n"
                "เปรียบเทียบโดรน DJI AGRAS T2P TigerDrone TGD2 NACdrone EASY 30 Plus "
                "ราคาพร้อมบิน 320,000 บาท 305,700 บาท 289,000 บาท",
        source_file="invest.pdf",
        page_number="18",
    )
    code_ev = Evidence(
        id="D2",
        content="- เงินลงทุนรวม: ${formatNumber(data.drone_1_investment)} บาท\n"
                "- ราคา Ready to Fly: ${formatNumber(data.drone_2_price)} บาท",
        source_file="invest.pdf",
        page_number="26",
    )
    data_table_ev, data_table_meta = _make_table_chunk(
        "D3", "invest.pdf", "10",
        [["MakerA", "Model1", "200,000"], ["MakerB", "Model2", "150,000"]],
        headers=["บริษัท", "รุ่น", "ราคา RTF โดยประมาณ (บาท)"],
        table_id="inv-t4", row_start=1, row_end=2
    )

    assert is_ui_template_content(ui_ev.content) is True
    assert is_ui_template_content(code_ev.content) is True
    assert is_ui_template_content(data_table_ev.content) is False

    query = "โดรนรุ่นไหนในตารางราคาถูกที่สุด"
    ui_score, ui_notes = score_evidence(query, ui_ev)
    data_score, data_notes = score_evidence(query, data_table_ev)

    assert "penalized_ui_mockup_in_table_comparison" in ui_notes
    assert "matches_table_comparison_scope" in data_notes
    assert data_score > ui_score, "Data table must strongly outrank UI mockup"


def test_synthetic_non_comparative_query_does_not_expand_table_continuations():
    """Verify that a simple non-comparative question does not perform unnecessary continuation expansion."""
    table_ev, table_meta = _make_table_chunk(
        "D1", "chemical.pdf", "4",
        [["อะลาคลอร์", "หญ้าใบแคบ", "400-500 มล./ไร่"]],
        headers=["ชื่อสามัญ", "วัชพืชที่ควบคุม", "อัตราการใช้"],
        table_id="chem-t1", row_start=1, row_end=1
    )

    query = "แนะนำยาคุมหญ้าในไร่อ้อย"
    assert is_comparative_or_table_query(query) is False

    mock_lookup = MagicMock()
    assembled, diag = assemble_candidate_table_evidence([table_ev], query, lookup_fn=mock_lookup)

    assert diag["table_continuation_applied"] is False
    assert mock_lookup.call_count == 0
    assert len(assembled) == 1


def test_synthetic_budget_constraints_record_incomplete_coverage_accurately():
    """Verify that when table continuation pages exceed the chunk budget, incomplete
    coverage and missing pages are tracked in diagnostics rather than silently dropped."""
    headers = ["ColA", "ColB"]
    pages = []
    for i in range(1, 6):
        ev, meta = _make_table_chunk(
            f"D_{i}", "long_table.pdf", str(i),
            [[f"val_{i}_1", f"val_{i}_2"]],
            headers=headers,
            table_id="long-t",
            row_start=i, row_end=i,
        )
        pages.append((ev, meta))

    query = "รายการทั้งหมดในตารางมีอะไรบ้าง"
    assembled, diag = assemble_candidate_table_evidence(
        [pages[0][0]], query, max_table_chunks=3, lookup_fn=lambda *a: pages
    )

    assert diag["table_continuation_applied"] is True
    table_diag = diag["tables"][0]
    assert table_diag["coverage"] == "incomplete"
    assert table_diag["total_pages"] == 5
    assert table_diag["included_pages"] == ["1", "2", "3"]
    assert table_diag["missing_pages"] == ["4", "5"]


# -----------------------------------------------------------------------------
# Tier 2: Mutation Test Integrity
# -----------------------------------------------------------------------------
def test_mutation_check_disabling_table_continuation_fails_positive_target_assertion():
    """Mutation proof: the positive assertion that the target continuation page reaches
    context selection succeeds when enabled, and strictly FAILS when disabled."""
    headers = ["ผู้ผลิต", "รุ่น", "ราคา (บาท)"]
    page1, meta1 = _make_table_chunk("D1", "drone.pdf", "1", [["Alpha", "900"]], headers=headers, table_id="t1")
    page2, meta2 = _make_table_chunk("D2", "drone.pdf", "2", [["Beta", "100"]], headers=headers, table_id="t1")

    def mock_lookup(file: str, t_id: str | None):
        return [(page1, meta1), (page2, meta2)]

    query = "รุ่นไหนราคาถูกที่สุดในตาราง"

    # POSITIVE PATH: enabled=True -> Page 2 is retrieved, survives selection, reaches context
    assembled_enabled, diag_enabled = assemble_candidate_table_evidence(
        [page1], query, lookup_fn=mock_lookup, enabled=True
    )
    selected_enabled, _, _, _ = scope_and_filter_context(query, assembled_enabled, max_chunks=8)
    # The positive assertion holds:
    assert "2" in [e.page_number for e in selected_enabled]
    assert any("Beta" in e.content for e in selected_enabled)

    # MUTATION PATH: enabled=False -> Table continuation is disabled
    assembled_disabled, diag_disabled = assemble_candidate_table_evidence(
        [page1], query, lookup_fn=mock_lookup, enabled=False
    )
    selected_disabled, _, _, _ = scope_and_filter_context(query, assembled_disabled, max_chunks=8)

    # Prove that the exact same positive assertion FAILS:
    assert "2" not in [e.page_number for e in selected_disabled]
    with pytest.raises(AssertionError):
        assert "2" in [e.page_number for e in selected_disabled]
    with pytest.raises(AssertionError):
        assert any("Beta" in e.content for e in selected_disabled)


# -----------------------------------------------------------------------------
# Tier 3: Recorded Snapshot Replay for inv07 Table 4 (Verifiable Hash)
# -----------------------------------------------------------------------------
def test_recorded_snapshot_inv07_reaches_page_13():
    """Verify against authentic recorded snapshot of Table 4 from ฟีเจอร์การลงทุน.pdf
    (with SHA256 integrity verification, zero network calls, zero live provider calls)."""
    snapshot_path = Path("tests/fixtures/inv07_table4_snapshot.json")
    if not snapshot_path.exists():
        snapshot_path = Path("scratch/inv07_table4_snapshot.json")
    assert snapshot_path.exists(), "Snapshot file must exist for recorded replay"

    raw_json = snapshot_path.read_text(encoding="utf-8")
    actual_hash = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
    expected_hash = "536bee139e1bf55c39f0583442ad465f31e99b6aac202245d6d0a6c30f04cdef"
    assert actual_hash == expected_hash, f"Snapshot checksum mismatch: {actual_hash} != {expected_hash}"

    items_data = json.loads(raw_json)
    snapshot_items: list[tuple[Evidence, dict]] = []
    for item in items_data:
        m = item["meta"]
        p = str(m.get("page_number", ""))
        ev = Evidence(
            id=item["id"],
            content=item["doc"],
            source_file=m.get("source_file", "ฟีเจอร์การลงทุน.pdf"),
            page_number=p,
            page_from=str(m.get("page_from", "")),
            page_end=str(m.get("page_end", "")),
        )
        snapshot_items.append((ev, m))

    query = "โดรนรุ่นไหนในตารางราคาถูกที่สุด"

    # Initial retrieval has page 10 (table header/initial rows) and page 18 (UI mockup)
    page10_ev = snapshot_items[1][0]
    ui_ev = Evidence(
        id="D1",
        content="ภาพที่ 6 แสดงราคาโดรนและข้อมูลโดรนหลังจากเลือกโดรนแล้ว\n"
                "เปรียบเทียบโดรน DJI AGRAS T2P TigerDrone TGD2 NACdrone EASY 30 Plus "
                "ราคาพร้อมบิน 320,000 บาท 305,700 บาท 289,000 บาท",
        source_file="ฟีเจอร์การลงทุน.pdf",
        page_number="18",
    )
    initial_evidence = [ui_ev, page10_ev]

    # Explicit snapshot lookup (no fallback, no hidden switches)
    def recorded_snapshot_lookup(file: str, t_id: str | None):
        if file == "ฟีเจอร์การลงทุน.pdf":
            return snapshot_items
        return []

    assembled, diag = assemble_candidate_table_evidence(
        initial_evidence, query, lookup_fn=recorded_snapshot_lookup
    )

    assert diag["table_continuation_applied"] is True
    table_diag = diag["tables"][0]
    assert table_diag["coverage"] == "complete"
    assert "13" in table_diag["included_pages"]
    assert table_diag["total_pages"] >= 5

    # Run through context scoping & selection
    selected, pre, post, drops = scope_and_filter_context(query, assembled, max_chunks=12)
    selected_pages = [e.page_number for e in selected if e.source_file == "ฟีเจอร์การลงทุน.pdf"]

    assert "13" in selected_pages, "Page 13 with Segumo 5 Pro Lite must be selected into model context"
    assert "18" not in selected_pages or selected_pages.index("13") < selected_pages.index("18")

    page13_ev = next(e for e in selected if e.page_number == "13")
    assert "5 Pro Lite" in page13_ev.content
    assert "99,000" in page13_ev.content


# -----------------------------------------------------------------------------
# Tier 4: Real Local Chroma DB (Explicit, No Silent Fallback)
# -----------------------------------------------------------------------------
def test_real_chroma_db_inv07_when_available():
    """Direct query against the actual local chroma_db on disk if present.
    Opt-in via ENABLE_REAL_CHROMA_TEST=1 for unisolated environments."""
    if not os.environ.get("ENABLE_REAL_CHROMA_TEST"):
        pytest.skip("Real Chroma DB test is opt-in (set ENABLE_REAL_CHROMA_TEST=1)")

    chroma_dir = Path("chroma_db")
    if not chroma_dir.exists():
        pytest.skip("Local chroma_db folder not present on test runner")

    try:
        import chromadb
        client = chromadb.PersistentClient(path="chroma_db")
        col = client.get_collection("drone_knowledge")
        if col.count() == 0:
            pytest.skip("Local chroma_db is empty")
    except Exception as exc:
        pytest.skip(f"Chroma DB cannot be opened: {exc}")

    # Query directly from real local Chroma without any fallback
    res = col.get(where={"source_file": "ฟีเจอร์การลงทุน.pdf"}, include=["metadatas", "documents"])
    docs = res.get("documents") or []
    metas = res.get("metadatas") or []

    assert len(docs) > 0, "Real Chroma DB must have chunks for ฟีเจอร์การลงทุน.pdf"

    table4_items = []
    for m, d in zip(metas, docs):
        p = str(m.get("page_number", ""))
        ev = Evidence(
            id=f"D_cont_{p}",
            content=d,
            source_file="ฟีเจอร์การลงทุน.pdf",
            page_number=p,
        )
        table4_items.append((ev, m))

    def real_chroma_lookup(f: str, t: str | None):
        return table4_items

    query = "โดรนรุ่นไหนในตารางราคาถูกที่สุด"
    page10_candidate = next(
        e for e, m in table4_items
        if e.page_number == "10" and m.get("source_type") == "table"
    )

    assembled, diag = assemble_candidate_table_evidence(
        [page10_candidate], query, lookup_fn=real_chroma_lookup
    )

    assert diag["table_continuation_applied"] is True
    assert "13" in diag["tables"][0]["included_pages"]

    selected, _, _, _ = scope_and_filter_context(query, assembled, max_chunks=12)
    selected_pages = [e.page_number for e in selected]
    assert "13" in selected_pages


# -----------------------------------------------------------------------------
# Tier 4: Round 3 Contract Regressions (Codex Review Round 3)
# -----------------------------------------------------------------------------
def test_explicit_different_table_ids_do_not_fall_through_to_headers():
    """Explicit different table_ids must never fall through to identical headers."""
    a = parse_table_metadata(Evidence("D1", "รุ่น | ราคา (บาท)\nAlpha | 100", "a.pdf", "1"), {"table_id": "retail_t1"})
    b = parse_table_metadata(Evidence("D2", "รุ่น | ราคา (บาท)\nBeta | 80", "a.pdf", "2"), {"table_id": "wholesale_t1"})
    assert are_tables_compatible(a, b) is False


def test_adjacent_conflicting_conditions_are_not_a_continuation():
    """Adjacent pages with conflicting conditions (new vs used, battery) must not merge."""
    a = Evidence("D1", "ราคาขายเครื่องใหม่ รวมแบตเตอรี่\nรุ่น | ราคา (บาท)\nAlpha | 100", "a.pdf", "1")
    b = Evidence("D2", "ราคาขายมือสอง ไม่รวมแบตเตอรี่\nรุ่น | ราคา (บาท)\nBeta | 80", "a.pdf", "2")
    query = "รุ่นไหนในตารางราคาถูกที่สุด"
    assembled, _ = assemble_candidate_table_evidence([a], query, lookup_fn=lambda *args: [(a, {}), (b, {})])
    assert "Beta | 80" not in "\n".join(x.content for x in assembled)


def test_unknown_scope_reaches_generation_as_not_proven_complete():
    """Empty or unverified lookup must propagate unknown/incomplete to generation payload."""
    query = "รุ่นไหนในตารางราคาถูกที่สุด"
    initial = [Evidence("D1", "รุ่น | ราคา (บาท)\nAlpha | 100", "a.pdf", "1")]
    captured = []

    def reply(messages, **kwargs):
        captured.append(json.loads(messages[-1]["content"]))
        return "NOT_FOUND"

    with patch.object(pipeline, "llm_pool_error", return_value=""), \
         patch.object(pipeline, "retrieve_evidence", return_value=initial), \
         patch.object(pipeline, "call_llm", side_effect=reply):
        response = pipeline.run_candidate_pipeline(query, mode="kb_only", lookup_fn=lambda *args: [])

    assert any(t["coverage"] == "unknown" for d in response.diagnostics for t in d.get("tables", []))
    assert captured[0].get("table_coverage") in ("unknown", "incomplete")


def test_missing_chunks_on_surviving_pages_invalidate_complete():
    """Dropping row chunks during selection invalidates complete status even if page survives."""
    query = "รุ่นไหนในตารางราคาถูกที่สุด"

    def make_ev(doc, page, row, caption=""):
        return Evidence("D1", f"{caption}\nรุ่น | ราคา (บาท)\n{row}", doc, str(page))

    pools = {
        doc: [make_ev(doc, 1, f"Model-{i} | {100+i}", "ตารางที่ 1 ราคา") for i in range(8)]
        for doc in ["a.pdf", "b.pdf"]
    }
    captured = []

    def reply(messages, **kwargs):
        captured.append(json.loads(messages[-1]["content"]))
        return "NOT_FOUND"

    with patch.object(pipeline, "llm_pool_error", return_value=""), \
         patch.object(pipeline, "retrieve_evidence", return_value=[pools["a.pdf"][0], pools["b.pdf"][0]]), \
         patch.object(pipeline, "call_llm", side_effect=reply):
        response = pipeline.run_candidate_pipeline(query, mode="kb_only", lookup_fn=lambda doc, _: [(e, {}) for e in pools[doc]])

    tables = [t for d in response.diagnostics for t in d.get("tables", [])]
    payload = captured[0]
    assert len(payload["sources"]) == 16 or any(t["coverage"] != "complete" for t in tables)
