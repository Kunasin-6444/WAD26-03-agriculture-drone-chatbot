from app.rag.vector_store import collection


TEST_IDS = [
    "uav07-test-1",
    "uav07-test-2",
    "uav07-test-3",
]


collection.delete(
    ids=TEST_IDS
)

print("Test data removed.")

print(
    "Remaining documents:",
    collection.count()
)