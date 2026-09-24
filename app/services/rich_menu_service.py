from __future__ import annotations

import os
from pathlib import Path
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
    URIAction,
)

from app.config import LINE_CHANNEL_ACCESS_TOKEN


def build_rich_menu_request() -> RichMenuRequest:
    """
    Build the RichMenuRequest structure based on the project requirements:
    - Grid: 2500 x 1686 (3 columns x 2 rows = 6 buttons)
    - Priority 1 (Top Row): Laws & Registration (CAAT Link + Self-registration PDF query)
    - Priority 2 (Middle Row): Spraying Drones & Weed Control (UAV06/07 & UAV08/09)
    - Priority 3 (Bottom Row): Survey Mapping & AI Assistant Help (UAV10/11/12 & Prompt Guide)
    """
    return RichMenuRequest(
        size=RichMenuSize(width=2500, height=1686),
        selected=True,
        name="Agriculture Drone Main Menu",
        chat_bar_text="เมนูหลัก",
        areas=[
            # --- Top Row (Priority 1: Laws & Registration) ---
            # Button 1: Air Law & Airspace (Direct link to CAAT Infographics)
            RichMenuArea(
                bounds=RichMenuBounds(x=0, y=0, width=1250, height=562),
                action=URIAction(
                    label="กฎหมายน่านฟ้า CAAT",
                    uri="https://uasportal.caat.or.th/infographic",
                ),
            ),
            # Button 2: Drone Registration Workflow
            RichMenuArea(
                bounds=RichMenuBounds(x=1250, y=0, width=1250, height=562),
                action=MessageAction(
                    label="ขั้นตอนลงทะเบียนโดรน",
                    text="ขั้นตอนการยื่นขออนุญาตปฏิบัติการบินโดรนเกษตรเพื่อตนเองต้องทำอย่างไร?",
                ),
            ),
            # --- Middle Row (Priority 2: Spraying & Weed Control) ---
            # Button 3: Nozzle Selection & Spraying Operation
            RichMenuArea(
                bounds=RichMenuBounds(x=0, y=562, width=1250, height=562),
                action=MessageAction(
                    label="เลือกใช้หัวฉีดโดรน",
                    text="แนะนำการเลือกใช้หัวฉีดโดรนเกษตรและอัตราการไหล",
                ),
            ),
            # Button 4: Chemical Spraying & Weed Control
            RichMenuArea(
                bounds=RichMenuBounds(x=1250, y=562, width=1250, height=562),
                action=MessageAction(
                    label="การพ่นยากำจัดวัชพืช",
                    text="วิธีการใช้สารกำจัดวัชพืชและควบคุมการพ่นด้วยโดรน",
                ),
            ),
            # --- Bottom Row (Priority 3: Survey & AI Guidance) ---
            # Button 5: Aerial Mapping & Survey
            RichMenuArea(
                bounds=RichMenuBounds(x=0, y=1124, width=1250, height=562),
                action=MessageAction(
                    label="โดรนสำรวจแปลง",
                    text="หลักการตั้งค่าโดรนสำรวจแปลงและถ่ายภาพทางอากาศ",
                ),
            ),
            # Button 6: How to ask AI / Help Guide
            RichMenuArea(
                bounds=RichMenuBounds(x=1250, y=1124, width=1250, height=562),
                action=MessageAction(
                    label="วิธีใช้งานผู้ช่วย AI",
                    text="แนะนำวิธีพิมพ์คำถามเพื่อขอข้อมูลโดรนเกษตร",
                ),
            ),
        ],
    )


def generate_default_rich_menu_image(output_path: str | Path) -> str:
    """
    Generates a high-quality 2500x1686 PNG background image with 6 color-coded button cards
    when no custom image file is provided.
    """
    width, height = 2500, 1686
    img = Image.new("RGB", (width, height), color=(245, 247, 250))
    draw = ImageDraw.Draw(img)

    # Grid specifications: 2 columns x 3 rows
    card_margin = 20
    cols, rows = 2, 3
    col_w = width // cols
    row_h = height // rows

    # 6 Color-coded themes (Laws/Registration highlighted in deep forest green)
    cards = [
        # Row 1 (Laws & Registration - Priority 1)
        {"title": "1. กฎหมายและน่านฟ้า CAAT", "subtitle": "Air Law & Airspace Regulations", "color": (34, 112, 62)},
        {"title": "2. ขั้นตอนลงทะเบียนโดรน", "subtitle": "CAAT & NBTC Registration Guide", "color": (16, 92, 48)},
        # Row 2 (Spraying & Chemical - Priority 2)
        {"title": "3. การเลือกใช้หัวฉีดโดรน", "subtitle": "Nozzle Selection & Spraying Rate", "color": (41, 128, 185)},
        {"title": "4. การพ่นยากำจัดวัชพืช", "subtitle": "Herbicides & Chemical Control", "color": (39, 174, 96)},
        # Row 3 (Mapping & Help - Priority 3)
        {"title": "5. โดรนสำรวจแปลงเกษตร", "subtitle": "Aerial Mapping & Survey Setup", "color": (142, 68, 173)},
        {"title": "6. วิธีใช้งานผู้ช่วย AI", "subtitle": "Chatbot Guide & Help", "color": (44, 62, 80)},
    ]

    font_large = ImageFont.load_default()
    font_small = ImageFont.load_default()

    for idx, card in enumerate(cards):
        r = idx // cols
        c = idx % cols

        x1 = c * col_w + card_margin
        y1 = r * row_h + card_margin
        x2 = (c + 1) * col_w - card_margin
        y2 = (r + 1) * row_h - card_margin

        # Draw rounded rectangle background card
        draw.rounded_rectangle([x1, y1, x2, y2], radius=30, fill=card["color"])

        # Text position
        tx = x1 + 50
        ty = y1 + 180
        draw.text((tx, ty), card["title"], fill=(255, 255, 255), font=font_large)
        draw.text((tx, ty + 100), card["subtitle"], fill=(220, 240, 230), font=font_small)

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_file, format="PNG")
    print(f"[RichMenu] Default background image generated at: {out_file.resolve()}")
    return str(out_file.resolve())


def get_or_create_rich_menu_image(image_path: str | Path) -> bytes:
    """
    Retrieves rich menu image bytes. If the image file does not exist,
    triggers default fallback image generation automatically.
    """
    file_path = Path(image_path)
    if not file_path.exists():
        print(f"[RichMenu] Image not found at {file_path}. Generating default fallback image...")
        generate_default_rich_menu_image(file_path)

    with open(file_path, "rb") as f:
        return f.read()


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

        # 2. Retrieve or Generate Image Bytes
        image_bytes = get_or_create_rich_menu_image(image_path)

        # 3. Upload Image to LINE
        messaging_api_blob.set_rich_menu_image(
            rich_menu_id=rich_menu_id,
            body=bytearray(image_bytes),
            _headers={"Content-Type": "image/png"},
        )
        print("[RichMenu] Uploaded background image to LINE.")

        # 4. Set as Default Rich Menu for all users
        messaging_api.set_default_rich_menu(rich_menu_id=rich_menu_id)
        print(f"[RichMenu] Successfully set {rich_menu_id} as default Rich Menu!")

        return rich_menu_id
