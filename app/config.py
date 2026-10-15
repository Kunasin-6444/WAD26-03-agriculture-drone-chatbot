import os

from dotenv import load_dotenv

load_dotenv()


def get_required_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(f"{name} is not set.")

    return value


LINE_CHANNEL_SECRET = get_required_env("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = get_required_env("LINE_CHANNEL_ACCESS_TOKEN")
# LLM_API_KEY is provider-neutral (OpenAI, KKU gateway, ...); API_KEY is the legacy KKU name.
LLM_API_KEY = os.getenv("LLM_API_KEY") or get_required_env("API_KEY")
API_KEY = LLM_API_KEY
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://gen.ai.kku.ac.th/api/v1")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")