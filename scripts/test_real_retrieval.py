from app.rag.vector_store import search


queries = [
    "หัวฉีดพัดส้มมีอัตราการไหลเท่าไรต่อหัวฉีด?",
    "ที่ความสูง 1 เมตร หน้ากว้างการฉีดพ่นต่อหัวเท่าไร?",
    "หัวฉีดแบบใดมีอัตราการไหลสูงที่สุด?",
]


for query in queries:

    print("\n" + "=" * 70)
    print(f"QUERY: {query}")
    print("=" * 70)

    results = search(
        query=query,
        n_results=10,
    )

    ids = results["ids"][0]
    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    for i, (
        chunk_id,
        document,
        metadata,
        distance,
    ) in enumerate(
        zip(
            ids,
            documents,
            metadatas,
            distances,
        ),
        start=1,
    ):

        print(f"\n--- Result {i} ---")
        print(f"ID       : {chunk_id}")
        print(f"Distance : {distance}")
        print(
            f"Source   : "
            f"{metadata.get('source_file')}"
        )
        print(
            f"Page     : "
            f"{metadata.get('page_number')}"
        )
        print(
            f"Type     : "
            f"{metadata.get('source_type')}"
        )
        print("Content:")
        print(document)