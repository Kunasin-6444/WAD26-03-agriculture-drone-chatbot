import sys
from pathlib import Path

import pymupdf

from app.ingestion.page_analyzer import analyze_page


def analyze_pdf(pdf_path: str) -> None:

    path = Path(pdf_path)

    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    doc = pymupdf.open(path)

    print(f"\nPDF: {path.name}")
    print(f"Pages: {len(doc)}")
    print("-" * 110)

    for page in doc:

        result = analyze_page(page)

        print(
            f"Page {result.page_number:2d} | "
            f"text={result.text_chars:4d} | "
            f"tables={result.native_table_count:1d} | "
            f"images={result.image_instance_count:2d}"
            f"/{result.unique_image_count:2d} | "
            f"coverage={result.image_area_ratio * 100:6.2f}% | "
            f"full_page={str(result.full_page_image):5s} | "
            f"vision={str(result.vision_candidate):5s}"
        )

    doc.close()


if __name__ == "__main__":

    if len(sys.argv) != 2:
        print("Usage:")
        print("python -m scripts.analyze_pdf <pdf_path>")
        sys.exit(1)

    analyze_pdf(sys.argv[1])