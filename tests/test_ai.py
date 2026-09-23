import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

api_key = os.getenv("API_KEY")
base_url = "https://gen.ai.kku.ac.th/api/v1"

if not api_key:
    raise RuntimeError("API_KEY is not set.")

client = OpenAI(
    api_key=api_key,
    base_url=base_url
)

def ask_ai(user_message: str) -> str:
    response = client.chat.completions.create(
        model="gemini-3.5-flash-lite",
        messages=[
            {"role": "system","content": "You are helpful assistant"},
            {"role": "user","content": {user_message}}
        ],
        stream=False
    )

    return(response.choices[0].message.content)

