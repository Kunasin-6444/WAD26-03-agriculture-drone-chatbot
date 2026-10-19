import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import pymupdf

from app.ingestion.pipeline import _run_vision
from app.ingestion.layout import needs_vision
from app.ingestion.vision_extractor import (
    TableRow, VisionPageResult, VisualElement, load_vision_cache,
    parse_vision_response, save_vision_cache, validate_vision_result,
)


def looping_result():
    return VisionPageResult(has_meaningful_visual_content=True, elements=[
        VisualElement(type="table", extracted_text="standard " * 1600, status="clear")])


def test_schema_valid_generation_loop_is_rejected_before_cache_or_publish():
    bad = looping_result()
    with pytest.raises(ValueError, match="generation loop"):
        parse_vision_response(SimpleNamespace(parsed=bad))
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "page_6.json"
        with pytest.raises(ValueError):
            save_vision_cache(path, bad)
        assert not path.exists()
        path.write_text(bad.model_dump_json(), encoding="utf-8")
        assert load_vision_cache(path) is None


def test_repeated_values_in_separate_real_table_cells_are_allowed():
    result = VisionPageResult(elements=[VisualElement(type="table", columns=["Model", "Mode"],
        rows=[TableRow(cells=[f"M{i}", "standard"]) for i in range(80)])])
    assert validate_vision_result(result) is result


def test_truncated_vision_response_is_rejected_even_if_json_was_parseable():
    response = SimpleNamespace(parsed=VisionPageResult(),
                               candidates=[SimpleNamespace(finish_reason="MAX_TOKENS")])
    with pytest.raises(RuntimeError, match="finish normally"):
        parse_vision_response(response)


def test_pipeline_marks_looping_vision_page_degraded_instead_of_publishing_it():
    deps = SimpleNamespace(vision=Mock(return_value=looping_result()))
    result = _run_vision(Path("example.pdf"), "sha", [6], deps, 1)[6]
    assert result.summary.startswith("[VISION_EXTRACTION_FAILED]")
    assert result.elements == []


def test_native_table_border_paint_just_outside_cells_does_not_trigger_vision():
    page = Mock()
    page.rect = pymupdf.Rect(0, 0, 600, 800)
    page.get_image_info.return_value = []
    page.get_images.return_value = []
    page.get_text.return_value = "Complete native table text"
    page.get_drawings.return_value = [
        {"rect": pymupdf.Rect(49.5, y, 50, y + 1), "type": "f", "items": [("re", y)]}
        for y in range(100, 200)]
    assert needs_vision(page, [pymupdf.Rect(50, 90, 500, 300)], 200) == (False, "text_layer_sufficient")


def test_overpainted_strokes_count_once_but_distinct_diagram_paths_still_need_vision():
    page = Mock()
    page.rect = pymupdf.Rect(0, 0, 600, 800)
    page.get_image_info.return_value = []
    page.get_images.return_value = []
    page.get_text.return_value = "Normal prose with graphics"
    drawing = {"rect": pymupdf.Rect(50, 50, 500, 300), "type": "s", "items": [("l", 1)]}
    page.get_drawings.return_value = [drawing] * 100
    assert needs_vision(page, [], 200)[0] is False
    page.get_drawings.return_value = [{**drawing, "items": [("l", i)]} for i in range(30)]
    assert needs_vision(page, [], 200)[0] is True
