import sys

from app.ingestion.vision_extractor import analyze_pdf_page


def main():
    if len(sys.argv) != 3:
        print(
            "Usage: "
            "python -m scripts.test_vision_page "
            "<pdf_path> <page_number>"
        )
        sys.exit(1)

    pdf_path = sys.argv[1]
    page_number = int(sys.argv[2])

    result = analyze_pdf_page(
        pdf_path=pdf_path,
        page_number=page_number,
    )

    print("\n=== Vision Result ===\n")
    print(result.model_dump_json(indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()