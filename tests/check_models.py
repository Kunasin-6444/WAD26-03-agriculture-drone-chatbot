import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("API_KEY")
base_url = "https://gen.ai.kku.ac.th/api/v1"

if not api_key:
    raise RuntimeError("API_KEY is not set.")

client = OpenAI(
    api_key=api_key,
    base_url=base_url
)

models = client.models.list()

for model in models.data:
    print(model.id)