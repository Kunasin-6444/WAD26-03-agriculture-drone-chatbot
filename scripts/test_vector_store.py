from app.rag.chunking import Chunk
from app.rag.vector_store import (
    add_chunks,
    search,
)


# --------------------------------------------------
# Test data
# --------------------------------------------------

chunks = [
    Chunk(
        id="uav07-test-1",
        content=(
            "หัวฉีดพัดส้มมีอัตราการไหล "
            "500 ml ต่อหัวฉีด ที่ความเร็วรอบ 1600 rpm "
            "และปริมาณ 3 หัวฉีดเท่ากับ 1500 ml"
        ),
        document_id="uav07",
        source_file="UAV07.pdf",
        page_number=12,
        source_type="table",
        metadata={
            "document_id": "uav07",
            "source_file": "UAV07.pdf",
            "page_number": "12",
            "source_type": "table",
        },
    ),

    Chunk(
        id="uav07-test-2",
        content=(
            "ที่ความสูง 1.0 เมตร "
            "หน้ากว้างการฉีดพ่นต่อหัวเท่ากับ 2.8 เมตร "
            "และหน้ากว้างรวมสำหรับ 3 หัวเท่ากับ 4.5 เมตร"
        ),
        document_id="uav07",
        source_file="UAV07.pdf",
        page_number=12,
        source_type="table",
        metadata={
            "document_id": "uav07",
            "source_file": "UAV07.pdf",
            "page_number": "12",
            "source_type": "table",
        },
    ),

    Chunk(
        id="uav07-test-3",
        content=(
            "เอกสารแสดงหัวฉีดหลายชนิด เช่น "
            "พัดส้ม พัดแดง พัดเหลือง พัดน้ำเงิน "
            "และหัวแบบเหวี่ยง"
        ),
        document_id="uav07",
        source_file="UAV07.pdf",
        page_number=12,
        source_type="image",
        metadata={
            "document_id": "uav07",
            "source_file": "UAV07.pdf",
            "page_number": "12",
            "source_type": "image",
        },
    ),
]


# --------------------------------------------------
# Insert
# --------------------------------------------------

add_chunks(chunks)

print("Chunks added to Chroma")


# --------------------------------------------------
# Search
# --------------------------------------------------

query = "หัวฉีดพัดส้มใช้น้ำกี่มิลลิลิตรต่อหัว"

results = search(
    query=query,
    n_results=3,
)


print("\n=== Search Result ===")

print(results)