import math
import os
from google.genai import types
from dotenv import load_dotenv
from google import genai


load_dotenv()

api_key = os.getenv("GOOGLE_API_KEY")

if not api_key:
    raise RuntimeError("GOOGLE_API_KEY is not set.")

client = genai.Client(
        api_key=api_key,
)

def cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        raise RuntimeError("Vectors must have the same dimensions.")

    dot_product = sum(x*y for x,y in zip(a,b))
    norm_a = math.sqrt(sum(x**2 for x in a))
    norm_b = math.sqrt(sum(y**2 for y in b))

    if norm_a == 0 or norm_b == 0:
        raise ZeroDivisionError("Can't divide with 0.")
    
    return dot_product / (norm_a * norm_b)

texts = [
    "task: sentence similarity | query: โดรนเกษตรใช้สำหรับฉีดพ่นสารในนาข้าว",
    "task: sentence similarity | query: การใช้ UAV เพื่อพ่นสารในแปลงเกษตร",
    "task: sentence similarity | query: วิธีปลูกข้าวให้ได้ผลผลิตสูง",
]

contents = [
    types.Content(
        parts=[
            types.Part.from_text(text=text)
        ]
    )
    for text in texts
]

result = client.models.embed_content(
    model= "gemini-embedding-2",
    contents= contents
)

embeddings = [e.values for e in result.embeddings]

for i in range(len(embeddings)):
    for j in range(i+1, len(embeddings)):
        similarity = cosine_similarity(embeddings[i],embeddings[j])
        print(f"Similarity {i+1} -> {j+1} = {similarity:.4f}")


