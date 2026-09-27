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
    Build the RichMenuRequest structure based on the project requirements and image:
    - Image layout: 2500 x 1686 px (3 columns x 2 rows = 6 buttons)
    - Row 1 (y: 0 to 843, h: 843):
        * Col 1 (x: 0, w: 833): กฎหมายและน่านฟ้า CAAT (Direct link to CAAT Infographics)
        * Col 2 (x: 833, w: 834): ขั้นตอนลงทะเบียนโดรน (Registration Workflow)
        * Col 3 (x: 1667, w: 833): โดรนฉีดพ่นและหัวฉีด (Spraying & Nozzles UAV06/07)
    - Row 2 (y: 843 to 1686, h: 843):
        * Col 1 (x: 0, w: 833): การใช้สารกำจัดวัชพืช (Herbicides & Weed Control UAV08/09)
        * Col 2 (x: 833, w: 834): โดรนสำรวจและภาพถ่ายแปลง (Aerial Mapping UAV10/11/12)
        * Col 3 (x: 1667, w: 833): สอบถามผู้ช่วย AI (AI Prompt Assistant Help)
    """
    return RichMenuRequest(
        size=RichMenuSize(width=2500, height=1686),
        selected=True,
        name="Agriculture Drone Main Menu (3x2)",
        chat_bar_text="เมนูหลัก",
        areas=[
            # --- Row 1 (y: 0 to 843) ---
            # Button 1 (Top Left): Air Law & Airspace (Direct link to CAAT Infographics)
            RichMenuArea(
                bounds=RichMenuBounds(x=0, y=0, width=833, height=843),
                action=URIAction(
                    label="กฎหมายน่านฟ้า CAAT",
                    uri="https://uasportal.caat.or.th/infographic",
                ),
            ),
            # Button 2 (Top Middle): Drone Registration Workflow
            RichMenuArea(
                bounds=RichMenuBounds(x=833, y=0, width=834, height=843),
                action=MessageAction(
                    label="ขั้นตอนลงทะเบียนโดรน",
                    text="ขั้นตอนการยื่นขออนุญาตปฏิบัติการบินโดรนเกษตรเพื่อตนเองต้องทำอย่างไร?",
                ),
            ),
            # Button 3 (Top Right): Spraying Drone & Nozzle Selection
            RichMenuArea(
                bounds=RichMenuBounds(x=1667, y=0, width=833, height=843),
                action=MessageAction(
                    label="โดรนฉีดพ่นและหัวฉีด",
                    text="แนะนำการเลือกใช้หัวฉีดโดรนเกษตรและอัตราการไหล",
                ),
            ),
            # --- Row 2 (y: 843 to 1686) ---
            # Button 4 (Bottom Left): Herbicides & Chemical Weed Control
            RichMenuArea(
                bounds=RichMenuBounds(x=0, y=843, width=833, height=843),
                action=MessageAction(
                    label="การใช้สารกำจัดวัชพืช",
                    text="วิธีการใช้สารกำจัดวัชพืชและควบคุมการพ่นด้วยโดรน",
                ),
            ),
            # Button 5 (Bottom Middle): Aerial Mapping & Crop Survey
            RichMenuArea(
                bounds=RichMenuBounds(x=833, y=843, width=834, height=843),
                action=MessageAction(
                    label="โดรนสำรวจภาพถ่ายแปลง",
                    text="หลักการตั้งค่าโดรนสำรวจแปลงและถ่ายภาพทางอากาศ",
                ),
            ),
            # Button 6 (Bottom Right): How to ask AI / Help Guide
            RichMenuArea(
                bounds=RichMenuBounds(x=1667, y=843, width=833, height=843),
                action=MessageAction(
                    label="สอบถามผู้ช่วย AI",
                    text="แนะนำวิธีพิมพ์คำถามเพื่อขอข้อมูลโดรนเกษตร",
                ),
            ),
        ],
    )


def generate_default_rich_menu_image(output_path: str | Path) -> str:
    """
    Generates a 2500x1686 PNG background image with 3 columns x 2 rows
    when no custom image file is provided.
    """
    width, height = 2500, 1686
    img = Image.new("RGB", (width, height), color=(245, 247, 250))
    draw = ImageDraw.Draw(img)

    # Grid specifications: 3 columns x 2 rows
    card_margin = 20
    cols, rows = 3, 2
    col_w = width // cols
    row_h = height // rows

    cards = [
        # Row 1
        {"title": "1. กฎหมายและน่านฟ้า CAAT", "subtitle": "Air Law & Airspace", "color": (34, 112, 62)},
        {"title": "2. ขั้นตอนลงทะเบียนโดรน", "subtitle": "Drone Registration", "color": (16, 92, 48)},
        {"title": "3. โดรนฉีดพ่นและหัวฉีด", "subtitle": "Spraying & Nozzles", "color": (41, 128, 185)},
        # Row 2
        {"title": "4. การใช้สารกำจัดวัชพืช", "subtitle": "Weed Control", "color": (39, 174, 96)},
        {"title": "5. โดรนสำรวจและภาพถ่ายแปลง", "subtitle": "Mapping & Survey", "color": (142, 68, 173)},
        {"title": "6. สอบถามผู้ช่วย AI", "subtitle": "AI Assistant Guide", "color": (44, 62, 80)},
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

        draw.rounded_rectangle([x1, y1, x2, y2], radius=30, fill=card["color"])

        tx = x1 + 30
        ty = y1 + 300
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
