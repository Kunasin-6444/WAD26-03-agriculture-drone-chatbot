from app.ingestion.models import KnowledgeUnit
from app.rag.chunking import chunk_knowledge_unit


unit = KnowledgeUnit(
    id="test-unit",
    document_id="uav07",
    source_file="UAV07.pdf",
    page_number=12,
    source_type="table",
    content="""
    ตารางแสดงความกว้างของพื้นที่ฉีดพ่นตามระดับความสูง

    ความสูง (เมตร) | หน้ากว้าง (เมตรต่อหัว) | หน้ากว้างรวม (เมตรต่อ 3 หัว)

    0.5 | 1.4 | 3.1
    1.0 | 2.8 | 4.5
    1.5 | 4.3 | 6.0
    2.0 | 5.7 | 7.4
    2.5 | 7.1 | 8.8
    """,
)

chunks = chunk_knowledge_unit(
    unit=unit,
    chunk_size=800,
    chunk_overlap=120,
)

print(f"Total chunks: {len(chunks)}")

for chunk in chunks:
    print("\n" + "=" * 60)
    print(f"ID: {chunk.id}")
    print(f"Page: {chunk.page_number}")
    print(f"Type: {chunk.source_type}")
    print(chunk.content)