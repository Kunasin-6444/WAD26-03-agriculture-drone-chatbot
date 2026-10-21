from __future__ import annotations

import io
import os
import re
from pathlib import Path
from typing import Any
from PIL import Image, ImageDraw, ImageFont

from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessagingApi,
    MessagingApiBlob,
    MessageAction,
    RichMenuArea,
    RichMenuBounds,
    RichMenuRequest,
    RichMenuSize,
)

from app.config import LINE_CHANNEL_ACCESS_TOKEN


def get_preanswers_dir() -> Path:
    """Return the absolute or working directory path to rich menu pre-answer text files."""
    candidates = [
        Path("data/rich_menu_answers"),
        Path(__file__).resolve().parent.parent.parent / "data" / "rich_menu_answers",
    ]
    for p in candidates:
        if p.exists() and p.is_dir():
            return p
    return candidates[0]


RICH_MENU_ITEMS: list[dict[str, Any]] = [
    {
        "index": 1,
        "title": "ขึ้นทะเบียนโดรน",
        "subtitle": "Drone Registration",
        "label": "ขึ้นทะเบียนโดรน",
        "text": "ขึ้นทะเบียนโดรน",
        "file": "1.txt",
        "color": (34, 112, 62),
        "aliases": [
            "ขึ้นทะเบียนโดรน",
            "คู่มือการขึ้นทะเบียนโดรน",
            "1. ขึ้นทะเบียนโดรน",
            "richmenu_1",
            "richmenu:1",
            "action=richmenu&item=1",
        ],
    },
    {
        "index": 2,
        "title": "ขึ้นทะเบียนนักบินโดรน",
        "subtitle": "Pilot Registration",
        "label": "ขึ้นทะเบียนนักบินโดรน",
        "text": "ขึ้นทะเบียนนักบินโดรน",
        "file": "2.txt",
        "color": (16, 92, 48),
        "aliases": [
            "ขึ้นทะเบียนนักบินโดรน",
            "ขึ้นทะเบียนผู้บังคับโดรน",
            "คู่มือการขึ้นทะเบียนผู้บังคับโดรน",
            "2. ขึ้นทะเบียนนักบินโดรน",
            "richmenu_2",
            "richmenu:2",
            "action=richmenu&item=2",
        ],
    },
    {
        "index": 3,
        "title": "ขออนุญาตบินโดรน",
        "subtitle": "Flight Permission",
        "label": "ขออนุญาตบินโดรน",
        "text": "ขออนุญาตบินโดรน",
        "file": "3.txt",
        "color": (41, 128, 185),
        "aliases": [
            "ขออนุญาตบินโดรน",
            "คู่มือการขออนุญาตทำการบินโดรน",
            "ขั้นตอนการยื่นขออนุญาตปฏิบัติการบินโดรนเกษตรเพื่อตนเองต้องทำอย่างไร?",
            "ขั้นตอนลงทะเบียนโดรน",
            "3. ขออนุญาตบินโดรน",
            "richmenu_3",
            "richmenu:3",
            "action=richmenu&item=3",
        ],
    },
    {
        "index": 4,
        "title": "กฎหมายการบินโดรน",
        "subtitle": "CAAT Laws",
        "label": "กฎหมายการบินโดรน",
        "text": "กฎหมายการบินโดรน",
        "file": "4.txt",
        "color": (39, 174, 96),
        "aliases": [
            "กฎหมายการบินโดรน",
            "คู่มือกฎหมายและข้อกำหนดการบินโดรนในประเทศไทย",
            "กฎหมายและน่านฟ้า CAAT",
            "4. กฎหมายการบินโดรน",
            "richmenu_4",
            "richmenu:4",
            "action=richmenu&item=4",
        ],
    },
    {
        "index": 5,
        "title": "โดรนฉีดพ่นและหัวฉีด",
        "subtitle": "Spraying & Nozzles",
        "label": "โดรนฉีดพ่นและหัวฉีด",
        "text": "โดรนฉีดพ่นและหัวฉีด",
        "file": "5.txt",
        "color": (142, 68, 173),
        "aliases": [
            "โดรนฉีดพ่นและหัวฉีด",
            "แนะนำการเลือกใช้หัวฉีดโดรนเกษตรและอัตราการไหล",
            "คู่มือโดรนฉีดพ่นทางการเกษตร",
            "5. โดรนฉีดพ่นและหัวฉีด",
            "richmenu_5",
            "richmenu:5",
            "action=richmenu&item=5",
        ],
    },
    {
        "index": 6,
        "title": "การใช้สารกำจัดวัชพืช",
        "subtitle": "Herbicides",
        "label": "การใช้สารกำจัดวัชพืช",
        "text": "การใช้สารกำจัดวัชพืช",
        "file": "6.txt",
        "color": (44, 62, 80),
        "aliases": [
            "การใช้สารกำจัดวัชพืช",
            "วิธีการใช้สารกำจัดวัชพืชและควบคุมการพ่นด้วยโดรน",
            "คู่มือการใช้สารกำจัดวัชพืชอย่างปลอดภัย",
            "6. การใช้สารกำจัดวัชพืช",
            "richmenu_6",
            "richmenu:6",
            "action=richmenu&item=6",
        ],
    },
]

_preanswers_cache: dict[int, str] | None = None


def load_rich_menu_preanswers(reload: bool = False) -> dict[int, str]:
    """
    Load pre-answer texts from files in data/rich_menu_answers/ (1.txt to 6.txt).
    Caches content in memory for instant O(1) response.
    """
    global _preanswers_cache
    if _preanswers_cache is not None and not reload:
        return _preanswers_cache

    answers: dict[int, str] = {}
    answers_dir = get_preanswers_dir()
    for item in RICH_MENU_ITEMS:
        idx = item["index"]
        file_path = answers_dir / item["file"]
        if file_path.exists():
            answers[idx] = file_path.read_text(encoding="utf-8").strip()
        else:
            answers[idx] = ""

    _preanswers_cache = answers
    return _preanswers_cache


def get_rich_menu_preanswer(key: str | None) -> str | None:
    """
    Match incoming user message text or postback data against registered Rich Menu triggers.
    If matched, returns the corresponding pre-answer text directly, bypassing CRAG.
    Returns None if not matched.
    """
    if not key:
        return None

    normalized = re.sub(r"\s+", " ", key).strip().casefold()
    preanswers = load_rich_menu_preanswers()

    for item in RICH_MENU_ITEMS:
        for alias in item["aliases"]:
            if normalized == re.sub(r"\s+", " ", alias).strip().casefold():
                answer = preanswers.get(item["index"])
                if answer:
                    return answer

    return None


def build_rich_menu_request() -> RichMenuRequest:
    """
    Build the RichMenuRequest structure based on the 6 pre-answer buttons:
    - Image layout: 2500 x 1686 px (3 columns x 2 rows = 6 buttons)
    - Row 1 (y: 0 to 843, h: 843):
        * Col 1 (x: 0, w: 833): ขึ้นทะเบียนโดรน (1.txt)
        * Col 2 (x: 833, w: 834): ขึ้นทะเบียนนักบินโดรน (2.txt)
        * Col 3 (x: 1667, w: 833): ขออนุญาตบินโดรน (3.txt)
    - Row 2 (y: 843 to 1686, h: 843):
        * Col 1 (x: 0, w: 833): กฎหมายการบินโดรน (4.txt)
        * Col 2 (x: 833, w: 834): โดรนฉีดพ่นและหัวฉีด (5.txt)
        * Col 3 (x: 1667, w: 833): การใช้สารกำจัดวัชพืช (6.txt)
    """
    bounds_map = [
        # Row 1
        RichMenuBounds(x=0, y=0, width=833, height=843),
        RichMenuBounds(x=833, y=0, width=834, height=843),
        RichMenuBounds(x=1667, y=0, width=833, height=843),
        # Row 2
        RichMenuBounds(x=0, y=843, width=833, height=843),
        RichMenuBounds(x=833, y=843, width=834, height=843),
        RichMenuBounds(x=1667, y=843, width=833, height=843),
    ]

    areas: list[RichMenuArea] = []
    for item, bounds in zip(RICH_MENU_ITEMS, bounds_map):
        areas.append(
            RichMenuArea(
                bounds=bounds,
                action=MessageAction(
                    label=item["label"],
                    text=item["text"],
                ),
            )
        )

    return RichMenuRequest(
        size=RichMenuSize(width=2500, height=1686),
        selected=True,
        name="Agriculture Drone Main Menu (3x2)",
        chat_bar_text="เมนูหลัก",
        areas=areas,
    )


def generate_default_rich_menu_image(output_path: str | Path) -> str:
    """
    Generates a 2500x1686 PNG background image with 3 columns x 2 rows
    matching the 6 Rich Menu items.
    """
    width, height = 2500, 1686
    img = Image.new("RGB", (width, height), color=(245, 247, 250))
    draw = ImageDraw.Draw(img)

    card_margin = 20
    cols, rows = 3, 2
    col_w = width // cols
    row_h = height // rows

    font_large = ImageFont.load_default()
    font_small = ImageFont.load_default()

    for idx, item in enumerate(RICH_MENU_ITEMS):
        r = idx // cols
        c = idx % cols

        x1 = c * col_w + card_margin
        y1 = r * row_h + card_margin
        x2 = (c + 1) * col_w - card_margin
        y2 = (r + 1) * row_h - card_margin

        draw.rounded_rectangle([x1, y1, x2, y2], radius=30, fill=item["color"])

        tx = x1 + 30
        ty = y1 + 300
        draw.text((tx, ty), f"{item['index']}. {item['title']}", fill=(255, 255, 255), font=font_large)
        draw.text((tx, ty + 100), item["subtitle"], fill=(220, 240, 230), font=font_small)

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_file, format="PNG")
    print(f"[RichMenu] Default background image generated at: {out_file.resolve()}")
    return str(out_file.resolve())


def get_or_create_rich_menu_image(image_path: str | Path) -> tuple[bytes, str]:
    """
    Retrieves rich menu image bytes and content-type. If the image file does not exist,
    triggers default fallback image generation automatically.
    Guarantees that image size is strictly under LINE's 1 MB limit (1,048,576 bytes) to prevent HTTP 413.
    """
    file_path = Path(image_path)
    if not file_path.exists():
        print(f"[RichMenu] Image not found at {file_path}. Generating default fallback image...")
        generate_default_rich_menu_image(file_path)

    raw_data = file_path.read_bytes()
    if len(raw_data) <= 1_000_000:
        content_type = "image/png" if raw_data.startswith(b"\x89PNG") else "image/jpeg"
        return raw_data, content_type

    print(f"[RichMenu] Image size ({len(raw_data)} bytes) exceeds LINE 1MB limit. Compressing to JPEG...")
    img = Image.open(io.BytesIO(raw_data))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=88, optimize=True)
    compressed_bytes = buf.getvalue()
    print(f"[RichMenu] Optimized image size: {len(compressed_bytes)} bytes.")
    return compressed_bytes, "image/jpeg"


def setup_rich_menu(
    access_token: str | None = None,
    image_path: str | Path = "assets/rich_menu/rich_menu_bg.png",
) -> str:
    """
    Creates the Rich Menu structure, uploads the image (or fallback default),
    and sets it as default for all subscriber users on LINE.
    """
    token = access_token or LINE_CHANNEL_ACCESS_TOKEN
    if not token:
        raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN is required to setup Rich Menu.")

    config = Configuration(access_token=token)

    with ApiClient(config) as api_client:
        messaging_api = MessagingApi(api_client)
        messaging_api_blob = MessagingApiBlob(api_client)

        # 1. Build & Create Rich Menu
        rich_menu_req = build_rich_menu_request()
        res = messaging_api.create_rich_menu(rich_menu_request=rich_menu_req)
        rich_menu_id = res.rich_menu_id
        print(f"[RichMenu] Created Rich Menu ID: {rich_menu_id}")

        # 2. Retrieve or Generate Image Bytes (strictly <= 1 MB)
        image_bytes, content_type = get_or_create_rich_menu_image(image_path)

        # 3. Upload Image to LINE
        messaging_api_blob.set_rich_menu_image(
            rich_menu_id=rich_menu_id,
            body=bytearray(image_bytes),
            _headers={"Content-Type": content_type},
        )
        print(f"[RichMenu] Uploaded background image to LINE ({len(image_bytes)} bytes, {content_type}).")

        # 4. Set as Default Rich Menu for all users
        messaging_api.set_default_rich_menu(rich_menu_id=rich_menu_id)
        print(f"[RichMenu] Successfully set {rich_menu_id} as default Rich Menu!")

        return rich_menu_id
