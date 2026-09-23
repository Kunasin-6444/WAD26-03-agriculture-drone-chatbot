import json

from app.ingestion.knowledge_builder import (
    build_page_knowledge_units,
)
from app.ingestion.vision_extractor import (
    analyze_pdf_page,
)


pdf_path = (
    "data/"
    "UAV07 หัวฉีดกับคุณภาพการฉีดพ่นของโดรนเกษตร.pdf"
)

page_number = 12

vision_result = analyze_pdf_page(
    pdf_path=pdf_path,
    page_number=page_number,
)

units = build_page_knowledge_units(
    pdf_path=pdf_path,
    document_id="uav07",
    page_number=page_number,
    vision_result=vision_result,
)

print(
    json.dumps(
        [
            unit.model_dump()
            for unit in units
        ],
        ensure_ascii=False,
        indent=2,
    )
)