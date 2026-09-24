from __future__ import annotations

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.services.rich_menu_service import setup_rich_menu


def main():
    print("=" * 60)
    print("[RichMenu] Agricultural Drone LINE Chatbot - Rich Menu Builder")
    print("=" * 60)

    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    if not token or token.strip() == "":
        print("[ERROR] LINE_CHANNEL_ACCESS_TOKEN is not set in environment or .env file.")
        print("Please set LINE_CHANNEL_ACCESS_TOKEN before running this script.")
        sys.exit(1)

    image_path = Path("assets/rich_menu/rich_menu_bg.png")

    try:
        rich_menu_id = setup_rich_menu(access_token=token, image_path=image_path)
        print("=" * 60)
        print("[SUCCESS] Rich Menu deployed and activated!")
        print(f"Rich Menu ID: {rich_menu_id}")
        print(f"Image Asset : {image_path.resolve()}")
        print("=" * 60)
    except Exception as exc:
        print(f"[ERROR] Failed to setup Rich Menu: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
