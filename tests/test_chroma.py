import os
import chromadb
from dotenv import load_dotenv
from google import genai

load_dotenv()

google_api_key = os.getenv("GOOGLE_API_KEY")

if not google_api_key:
    raise RuntimeError("GOOGLE_API_KEY is not set.")

embedding_client = genai.Client(
    api_key=google_api_key,
)

def embed_text(text: str) -> list[float]:
    result = embedding_client.models.embed_content(
        model="gemini-embedding-2",
        contents=text
    )
    return result.embeddings[0].values

chroma_client = chromadb.PersistentClient(
    path="./chroma_db"
)

collection = chroma_client.get_or_create_collection(
    name="drone_knowledge"
)

documents = [
    "โดรนเกษตรใช้สำหรับฉีดพ่นสารในนาข้าว",
    "การใช้ UAV เพื่อพ่นสารในแปลงเกษตร",
    "วิธีปลูกข้าวให้ได้ผลผลิตสูง",
]

ids = [
    "doc_1",
    "doc_2",
    "doc_3",
]

embeddings = [embed_text(document) for document in documents]

collection.upsert(
    ids=ids,
    documents=documents,
    embeddings=embeddings
)

question = "โดรนใช้พ่นสารในนาได้ไหม?"

query_embedding = embed_text(question)

results = collection.query([query_embedding], n_results=2)


print("\nQuestion:")
print(question)

print("\nRetrieved documents:")

for i, document in enumerate(results["documents"][0]):
    print(f"\n{i + 1}. {document}")

print("\nDistances:")
print(results["distances"][0])