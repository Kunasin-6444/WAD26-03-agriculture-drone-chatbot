from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from openai import OpenAI
from tavily import TavilyClient

from urllib.parse import urlparse

from app.config import TAVILY_API_KEY
from app.rag.rag_service import call_llm, get_llm_client

logger = logging.getLogger(__name__)

CAAT_PORTAL_INFOGRAPHIC_URL = "https://uasportal.caat.or.th/infographic"


def get_domain(url: str) -> str:
    """Extract lowercase network location/domain from URL."""
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""

# Trusted official government, educational, official energy/agri providers, and reputable sources
TRUSTED_DOMAINS = [
    # Government & Regulations (.go.th, .or.th, .ac.th)
    ".go.th",
    ".or.th",
    ".ac.th",
    # Official Agriculture & Research
    "doa.go.th",
    "moac.go.th",
    "doae.go.th",
    "oae.go.th",
    "dit.go.th",
    "nstda.or.th",
    "caat.or.th",
    "nbtc.go.th",
    # Official Energy & Fuel Providers
    "eppo.go.th",
    "doeb.go.th",
    "pttor.com",
    "bangchak.co.th",
    # Established Thai Media & News
    "thaipbs.or.th",
    "bangkokbiznews.com",
    "thairath.co.th",
    "matichon.co.th",
    "prachachat.net",
]


def is_trusted_domain(url: str) -> bool:
    """Check if the URL belongs to a trusted government, educational, or recognized domain."""
    url_lower = url.lower()
    return any(domain in url_lower for domain in TRUSTED_DOMAINS)


@dataclass
class WebSearchResult:
    title: str
    url: str
    content: str
    score: float = 0.0
    is_trusted: bool = False


def get_tavily_client(api_key: str | None = None) -> TavilyClient | None:
    key = api_key or TAVILY_API_KEY
    if not key:
        logger.warning("TAVILY_API_KEY is not set. Web fallback search will be skipped.")
        return None
    try:
        return TavilyClient(api_key=key)
    except Exception as e:
        logger.error(f"Failed to initialize TavilyClient: {e}")
        return None


def search_web_fallback(
    query: str,
    is_caat_topic: bool = False,
    max_results: int = 5,
    tavily_client: TavilyClient | None = None,
) -> list[WebSearchResult]:
    """
    Search the web using Tavily with preference for official sources.
    If is_caat_topic is True, prioritize CAAT domains and include the CAAT portal.
    Applies credibility domain filtering and ranking to avoid SEO spam / AI scrapers.
    """
    client = tavily_client or get_tavily_client()

    results: list[WebSearchResult] = []

    # If CAAT law/airspace topic, always ensure CAAT UAS portal is in references
    if is_caat_topic:
        caat_content = (
            "ศูนย์บริการข้อมูลการบินอากาศยานไร้คนขับ สำนักงานการบินพลเรือนแห่งประเทศไทย (CAAT): "
            "ข้อกำหนดและขั้นตอนการบินโดรนเกษตรและการบินในพื้นที่ตนเอง (อ้างอิงจาก UAS Portal Infographic):\n"
            "1. การขึ้นทะเบียนก่อนทำการบิน:\n"
            "   - ผู้บังคับโดรนต้องขึ้นทะเบียนผู้บังคับอากาศยานไร้คนขับกับ CAAT ผ่านระบบ UAS Portal (uasportal.caat.or.th)\n"
            "   - ต้องขึ้นทะเบียนเครื่องวิทยุคมนาคม/โดรนกับ กสทช.\n"
            "   - ต้องจัดทำประกันภัยความรับผิดต่อบุคคลภายนอกสำหรับโดรน\n"
            "2. การปฏิบัติการบินโดรนเกษตรเพื่อตนเอง:\n"
            "   - ผู้ที่ต้องการบินโดรนเพื่อฉีดพ่นหรือสำรวจในพื้นที่การเกษตร/ที่นาของตนเอง ต้องยื่นขออนุญาตปฏิบัติการบินโดรนเกษตรเพื่อตนเองผ่านระบบ UAS Portal\n"
            "   - ทำการปักหมุด/ระบุพิกัดแปลงเกษตรของตนเองในระบบ และแนบเอกสารผู้บังคับและโดรนที่ขึ้นทะเบียนถูกต้อง\n"
            "3. เงื่อนไขและกฎความปลอดภัยในการบิน:\n"
            "   - ทำการบินเฉพาะในเวลากลางวัน (พระอาทิตย์ขึ้นถึงพระอาทิตย์ตก)\n"
            "   - ทำการบินในแนวสายตา (VLOS: Visual Line of Sight) มองเห็นโดรนได้ตลอดเวลา\n"
            "   - บินสูงไม่เกิน 90 เมตร (300 ฟุต) เหนือพื้นดิน\n"
            "   - ห้ามบินเข้าใกล้สนามบินหรือเขตขึ้นลงชั่วคราวในระยะ 9 กิโลเมตร (5 ไมล์ทะเล) เว้นแต่ได้รับอนุญาต\n"
            "   - ห้ามบินในเขตห้ามบิน (No-Fly Zone) และรักษาระยะห่างที่ปลอดภัยจากบุคคลและชุมชน\n"
            "สามารถศึกษารายละเอียดและอินโฟกราฟิกทางการได้ที่ https://uasportal.caat.or.th/infographic"
        )
        caat_entry = WebSearchResult(
            title="CAAT UAS Portal - สื่อประชาสัมพันธ์และอินโฟกราฟิกกฎหมายการบินโดรน",
            url=CAAT_PORTAL_INFOGRAPHIC_URL,
            content=caat_content,
            score=1.0,
            is_trusted=True,
        )
        results.append(caat_entry)

    if not client:
        return results

    search_query = query
    if is_caat_topic and "caat" not in query.lower():
        search_query = f"{query} CAAT กฎหมายโดรน"

    try:
        response: dict[str, Any] = client.search(
            query=search_query,
            search_depth="basic",
            max_results=max_results * 2,  # Fetch more to allow credibility filtering
        )

        raw_items = response.get("results", [])
        trusted_items: list[WebSearchResult] = []
        other_items: list[WebSearchResult] = []
        seen_domains = {get_domain(r.url) for r in results}

        for item in raw_items:
            url = item.get("url", "").strip()
            if not url:
                continue
            domain = get_domain(url)
            # Avoid duplicate domains (e.g. multiple links from the same site) and identical URLs
            if domain in seen_domains:
                continue
            if any(r.url.rstrip("/") == url.rstrip("/") for r in results):
                continue

            seen_domains.add(domain)
            trusted = is_trusted_domain(url)
            entry = WebSearchResult(
                title=item.get("title", ""),
                url=url,
                content=item.get("content", ""),
                score=float(item.get("score", 0.0)),
                is_trusted=trusted,
            )
            if trusted:
                trusted_items.append(entry)
            else:
                other_items.append(entry)

        # Prioritize trusted official and established sources first
        combined = trusted_items + other_items
        for entry in combined[:max_results]:
            results.append(entry)

    except Exception as e:
        logger.warning(f"Tavily search encountered error: {e}")

    return results


def format_web_context(results: list[WebSearchResult]) -> str:
    """
    Format web search results into a structured context string for the LLM.
    """
    if not results:
        return ""

    context_parts: list[str] = []
    for idx, r in enumerate(results, 1):
        trust_status = (
            "แหล่งข้อมูลทางการ/น่าเชื่อถือ (Official/Trusted)"
            if r.is_trusted
            else "แหล่งข้อมูลทั่วไป (Unverified Web)"
        )
        context_parts.append(
            f"[เว็บแหล่งข้อมูล {idx}]\n"
            f"ระดับความน่าเชื่อถือ: {trust_status}\n"
            f"หัวข้อ: {r.title}\n"
            f"URL: {r.url}\n"
            f"เนื้อหา: {r.content}"
        )
    return "\n\n".join(context_parts)


def generate_web_grounded_answer(
    query: str,
    web_results: list[WebSearchResult],
    is_caat_topic: bool = False,
    client: OpenAI | None = None,
    model: str = "gpt-5.6-luna",
) -> str:
    """
    Generate an answer grounded in web search results, citing URLs.
    Abstains if no relevant reliable answer can be formed.
    """
    if not web_results:
        if is_caat_topic:
            return (
                "สำหรับข้อมูลด้านกฎหมายอากาศยานและการใช้น่านฟ้าโดรนการเกษตร "
                f"สามารถตรวจสอบข้อมูลทางการได้ที่ CAAT UAS Portal: {CAAT_PORTAL_INFOGRAPHIC_URL}"
            )
        return "ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้และไม่พบข้อมูลที่น่าเชื่อถือจากแหล่งข้อมูลภายนอก"

    context = format_web_context(web_results)
    ai_client = client or get_llm_client()

    caat_note = (
        f"คำถามนี้เป็นเรื่องเกี่ยวกับกฎหมายอากาศยาน/น่านฟ้า ให้ระบุ URL แหล่งอ้างอิงทางการหลักเป็น "
        f"{CAAT_PORTAL_INFOGRAPHIC_URL} เพียงแห่งเดียวเป็นหลัก (ห้ามระบุลิงก์อื่นจาก uasportal ซ้ำซ้อน)\n\n"
        if is_caat_topic
        else ""
    )

    system_prompt = (
        "คุณคือผู้ช่วยผู้เชี่ยวชาญด้านโดรนการเกษตร หน้าที่ของคุณคือตอบคำถามโดยอิงจาก 'ข้อมูลจากเว็บไซต์' (Web Search Context) ที่ให้มาเท่านั้น\n\n"
        f"{caat_note}"
        "กฎการตอบ:\n"
        "1. ตอบเป็นภาษาไทยอย่างชัดเจน สุภาพ และกระชับ\n"
        "2. ห้ามคิดค้นหรือเดาข้อมูลเอง ใช้เฉพาะข้อมูลที่มีอยู่ในบริบทเว็บเท่านั้น\n"
        "3. ต้องระบุ URL แหล่งอ้างอิงท้ายคำตอบเฉพาะแหล่งข้อมูลทางการที่ตรงประเด็นที่สุด 1-2 แหล่งเท่านั้น (ห้ามใส่ URL ซ้ำ และห้ามใส่ลิงก์จากโดเมนเดียวกันซ้ำกัน) เช่น (แหล่งอ้างอิง: [URL])\n"
        "4. ตรวจสอบความน่าเชื่อถือของแหล่งที่มา: หากเป็นข้อมูลตัวเลขสำคัญ กฎหมาย หรือราคาสินค้า/น้ำมัน "
        "ต้องให้ความสำคัญกับ 'แหล่งข้อมูลทางการ/น่าเชื่อถือ' เป็นหลัก ห้ามนำข้อมูลจากเว็บบล็อกทั่วไป เว็บขายของ หรือเว็บที่ใช้ AI สร้างเนื้อหามาเป็นข้อเท็จจริง\n"
        "5. หากข้อมูลในบริบทเว็บไม่มีคำตอบที่ตรงประเด็น มาจากเว็บที่ไม่น่าเชื่อถือ หรือมีเฉพาะเว็บสแปม "
        "ให้ตอบว่า 'ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้และไม่พบข้อมูลที่น่าเชื่อถือจากแหล่งข้อมูลภายนอก'"
    )

    user_prompt = (
        f"ข้อมูลจากเว็บไซต์:\n"
        f"{context}\n\n"
        f"คำถาม:\n"
        f"{query}\n\n"
        f"คำตอบ:"
    )

    try:
        return call_llm(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            client=client,
            preferred_model=model,
            temperature=0.0,
        )
    except Exception as e:
        logger.error(f"Error generating web grounded answer: {e}")
        if is_caat_topic:
            return (
                "สำหรับข้อมูลด้านกฎหมายอากาศยานและการใช้น่านฟ้าโดรนการเกษตร "
                f"สามารถตรวจสอบข้อมูลทางการได้ที่ CAAT UAS Portal: {CAAT_PORTAL_INFOGRAPHIC_URL}"
            )
        return "ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้และไม่พบข้อมูลที่น่าเชื่อถือจากแหล่งข้อมูลภายนอก"
