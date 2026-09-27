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
API_KEY = get_required_env("API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")