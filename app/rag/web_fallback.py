from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from openai import OpenAI
from tavily import TavilyClient

from urllib.parse import urlparse

from app.config import TAVILY_API_KEY
from app.rag.format_utils import format_response_layout
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
    max_results: int = 3,
    tavily_client: TavilyClient | None = None,
) -> list[WebSearchResult]:
    """
    Search the web using Tavily with preference for official sources.
    If is_caat_topic is True, Rule R1 mandates using the designated CAAT UAS Portal
    Infographic source directly, bypassing external search for speed and precision.
    Applies credibility domain filtering and ranking to avoid SEO spam / AI scrapers.
    """
    client = tavily_client or get_tavily_client()

    results: list[WebSearchResult] = []

    # If CAAT law/airspace topic, use designated CAAT UAS portal infographic directly (Rule R1)
    if is_caat_topic:
        caat_content = (
            "ศูนย์บริการข้อมูลการบินอากาศยานไร้คนขับ สำนักงานการบินพลเรือนแห่งประเทศไทย (CAAT): "
            "ข้อกำหนดและขั้นตอนการขึ้นทะเบียนและการบินโดรนเกษตร (อ้างอิงจาก CAAT UAS Portal Infographic):\n"
            "1. 3 เสาหลักของการขึ้นทะเบียนก่อนทำการบิน (กฎหมายบังคับ):\n"
            "   • ขึ้นทะเบียนเครื่องวิทยุคมนาคม/ตัวเครื่องโดรนกับ กสทช. (ต้องยื่นภายใน 30 วันนับแต่วันที่ครอบครองโดรน ผ่านระบบ AnyRegistration หรือสำนักงาน กสทช.)\n"
            "   • จัดทำประกันภัยความรับผิดต่อบุคคลภายนอกสำหรับโดรน (วงเงินคุ้มครองไม่ต่ำกว่า 1,000,000 บาท ต่อครั้งตามที่กฎหมายกำหนด)\n"
            "   • ขึ้นทะเบียนผู้บังคับอากาศยานไร้คนขับกับ CAAT ผ่านระบบ UAS Portal (uasportal.caat.or.th) โดยใบรับรองการขึ้นทะเบียนมีอายุ 2 ปี\n"
            "2. เอกสารสำคัญที่ต้องเตรียมในการยื่นขึ้นทะเบียน:\n"
            "   • บัตรประจำตัวประชาชนและทะเบียนบ้านของผู้ขอขึ้นทะเบียน (อายุไม่ต่ำกว่า 18 ปีบริบูรณ์ หรือมีหนังสือยินยอมจากผู้แทนโดยชอบธรรม)\n"
            "   • รูปถ่ายตัวโดรนและรูปถ่ายหมายเลขประจำเครื่อง (Serial Number) ที่ชัดเจน\n"
            "   • กรมธรรม์ประกันภัยบุคคลภายนอกที่ยังไม่หมดอายุ\n"
            "   • หลักฐานการซื้อขายหรือการครอบครองโดรน\n"
            "3. ขั้นตอนการปฏิบัติการบินโดรนเกษตรเพื่อตนเอง (หลังขึ้นทะเบียนเสร็จสิ้น):\n"
            "   • ผู้ที่ต้องการบินโดรนเพื่อฉีดพ่นหรือสำรวจในพื้นที่การเกษตร/ที่นาของตนเอง ต้องยื่นขออนุญาตปฏิบัติการบินโดรนเกษตรเพื่อตนเองผ่านระบบ UAS Portal\n"
            "   • ทำการปักหมุดระบุพิกัดแปลงเกษตรของตนเองในระบบ และแนบเอกสารผู้บังคับและโดรนที่ขึ้นทะเบียนถูกต้อง\n"
            "4. เงื่อนไขและกฎความปลอดภัยในการบิน:\n"
            "   • ทำการบินเฉพาะในเวลากลางวัน (พระอาทิตย์ขึ้นถึงพระอาทิตย์ตก)\n"
            "   • ทำการบินในแนวสายตา (VLOS: Visual Line of Sight) มองเห็นโดรนได้ตลอดเวลา\n"
            "   • บินสูงไม่เกิน 90 เมตร (300 ฟุต) เหนือพื้นดิน\n"
            "   • ห้ามบินเข้าใกล้สนามบินหรือเขตขึ้นลงชั่วคราวในระยะ 9 กิโลเมตร (5 ไมล์ทะเล) เว้นแต่ได้รับอนุญาต\n"
            "   • ห้ามบินในเขตห้ามบิน (No-Fly Zone) และรักษาระยะห่างที่ปลอดภัยจากบุคคลและชุมชน\n"
            "5. บทลงโทษตามกฎหมายการบินโดรน (พ.ร.บ. การเดินอากาศ):\n"
            "   • ทำการบินโดยไม่ได้รับอนุญาต มีโทษจำคุกไม่เกิน 1 ปี หรือปรับไม่เกิน 40,000 บาท หรือทั้งจำทั้งปรับ\n"
            "   • ฝ่าฝืนเงื่อนไขความปลอดภัยหรือบินในเขตห้ามบิน มีโทษปรับทางอาญาตามที่กฎหมายกำหนด\n"
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
            max_results=4,  # Fetch 4 focused results for fast scraping and lower latency
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
        context_parts.append(
            f"[ข้อมูลจากเว็บไซต์ {idx}]\n"
            f"หัวข้อ: {r.title}\n"
            f"URL: {r.url}\n"
            f"เนื้อหา: {r.content[:700].strip()}"
        )
    return "\n\n".join(context_parts)


def generate_web_grounded_answer(
    query: str,
    web_results: list[WebSearchResult],
    is_caat_topic: bool = False,
    client: OpenAI | None = None,
    model: str = "gemini-3.5-flash-lite",
    max_tokens: int = 420,
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
        f"คำถามนี้เป็นเรื่องเกี่ยวกับกฎหมายอากาศยาน การขึ้นทะเบียนโดรน และเงื่อนไขการขออนุญาตบินโดรน: "
        f"ให้ใช้ข้อมูลหลักเกณฑ์การขึ้นทะเบียน 3 เสาหลัก ขั้นตอนการยื่น และเงื่อนไขความปลอดภัยในการบินตามกฎหมาย CAAT จากบริบทมาตอบและอธิบายขั้นตอนให้ผู้ถามอย่างชัดเจนและมีประโยชน์ "
        f"(แม้ผู้ถามจะระบุชื่อสถานที่แปลงเกษตร เช่น สวนเกษตร มข. แปลงเกษตร มหาวิทยาลัย หรือแปลงนา ให้แนะนำข้อกำหนดกฎหมายการบินและการขึ้นทะเบียนของ CAAT ได้เลย) "
        f"และให้ระบุ URL แหล่งอ้างอิงทางการหลักเป็น {CAAT_PORTAL_INFOGRAPHIC_URL} เพียงแห่งเดียวเป็นหลัก (ห้ามระบุลิงก์อื่นจาก uasportal ซ้ำซ้อน)\n\n"
        if is_caat_topic
        else ""
    )

    system_prompt = (
        "คุณคือผู้ช่วยผู้เชี่ยวชาญด้านโดรนการเกษตร หน้าที่ของคุณคือตอบคำถามโดยอิงจาก 'ข้อมูลจากเว็บไซต์' (Web Search Context) ที่ให้มาเท่านั้น สำหรับอ่านใน LINE ให้มีระเบียบ สวยงาม ครบถ้วน ได้ใจความ ตรงประเด็น และเป็นประโยชน์แก่ผู้อ่าน โดยอธิบายรายละเอียดสำคัญให้ครบถ้วน ไม่ตอบสั้นห้วนจนขาดสาระสำคัญ\n\n"
        f"{caat_note}"
        "หลักการจัดโครงสร้างคำตอบให้อ่านง่ายบน LINE (Adaptive Layout Principles):\n"
        "1. ห้ามใช้เครื่องหมาย Markdown ทุกชนิด โดยเด็ดขาด (ห้ามใส่ ** ตัวหนา, * ตัวเอียง, หรือ # หัวข้อ)\n"
        "2. ลำดับชั้นสายตาและการจัดกลุ่ม (Visual Hierarchy):\n"
        "   - เริ่มต้นตอบประเด็นสำคัญทันที ไม่ต้องเกริ่นอารัมภบทหรือพูดทวนคำถามยืดยาว\n"
        "   - หากมีหัวข้อหลักและรายละเอียด ให้ตั้งหัวข้อหลักให้ชัดเจน แล้วขึ้นบรรทัดใหม่ใช้ขีดย่อย (- ) หรือรายการย่อย เพื่อแยกแยะหัวข้อกับเนื้อหาให้ชัดเจน\n"
        "   - หลีกเลี่ยงการทำ bullet แบนราบที่กลืนกันไปหมด\n"
        "3. ปรับสไตล์คำตอบให้สอดคล้องกับลักษณะคำถาม (Context-Aware):\n"
        "   - ถ้าเป็นขั้นตอน / เงื่อนไขกฎหมาย: ใช้ลำดับตัวเลข 1. 2. 3. เพื่อให้อ่านตามและปฏิบัติตามได้ง่าย\n"
        "   - ถ้าเป็นมาตรการ / ข้อมูลหลายด้าน: สรุป 3-5 ประเด็นสำคัญที่ตรงคำถาม โดยขึ้นบรรทัดใหม่และอธิบายสาระสำคัญอย่างชัดเจนและมีประโยชน์\n"
        "4. การใช้ Emoji อย่างเป็นธรรมชาติ (Contextual Emojis):\n"
        "   - สามารถเลือกใช้ emoji ประกอบหัวข้อหรือเน้นประเด็นสำคัญได้ตามความเหมาะสมของบริบท เพื่อความสบายตาในการอ่านบนมือถือ แต่ไม่จำเป็นต้องใส่ทุกจุด และห้ามใส่มากเกินไปจนรกสายตา\n"
        "5. ตำแหน่งแหล่งอ้างอิง (Bottom Isolated Citation):\n"
        "   - ต้องเว้นบรรทัดว่าง 1 บรรทัด ก่อนใส่แหล่งอ้างอิงเสมอ\n"
        "   - ต้องวางแหล่งอ้างอิงไว้ที่ 'บรรทัดล่างสุดเพียงที่เดียว' ในรูปแบบ: (แหล่งอ้างอิง: [URL]) โดยเลือกเฉพาะแหล่งข้อมูลทางการที่ตรงประเด็นที่สุด 1-2 แหล่งเท่านั้น (ห้ามใส่ URL ซ้ำ)\n"
        "   - ห้ามใส่แหล่งอ้างอิงติดกับประโยคเนื้อหาในบรรทัดเดียวกันโดยเด็ดขาด\n\n"
        "6. การตอบจากข้อมูลเว็บ (Web Grounding):\n"
        "   - ใช้ข้อเท็จจริงจากเนื้อหาเว็บไซต์ที่ค้นหาได้มาตอบคำถามและให้ข้อมูลที่เป็นประโยชน์แก่ผู้ใช้ พร้อมระบุ URL แหล่งอ้างอิงท้ายคำตอบ\n"
        "7. การตอบปฏิเสธอย่างเคร่งครัดเมื่อไม่มีข้อมูลยืนยัน (Strict Abstain & Anti-Hallucination):\n"
        "   - หากคำถามถามถึงสิ่งที่เป็นไปไม่ได้ ไม่มีอยู่จริง หรือไม่มีการยืนยันว่าเป็นภารกิจของโดรนเกษตรในแหล่งข้อมูล (เช่น โดรนเกษตรดำน้ำฉีดปุ๋ยใต้ทะเลลึก, โดรนบินไปอวกาศ, หรือสิ่งที่ไม่มีข้อเท็จจริงรองรับ)\n"
        "   - ห้ามเดา ห้ามนำข้อมูลโดรนประเภทอื่น (เช่น โดรนสำรวจใต้น้ำ) มาผสมโรงหรือพยายามอธิบาย\n"
        "   - ในกรณีดังกล่าว ให้ตอบเพียงประโยคนี้เท่านั้น: 'ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้และไม่พบข้อมูลที่น่าเชื่อถือจากแหล่งข้อมูลภายนอก'"
    )

    user_prompt = (
        f"ข้อมูลจากเว็บไซต์:\n"
        f"{context}\n\n"
        f"คำถาม:\n"
        f"{query}\n\n"
        f"คำตอบ:"
    )

    try:
        raw_answer = call_llm(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            client=client,
            preferred_model=model,
            temperature=0.0,
            max_tokens=max_tokens,
        )

        default_cite = ""
        if is_caat_topic:
            default_cite = f"(แหล่งอ้างอิง: {CAAT_PORTAL_INFOGRAPHIC_URL})"
        elif web_results:
            trusted = [r for r in web_results if r.is_trusted]
            target = trusted[0] if trusted else web_results[0]
            if target.url:
                default_cite = f"(แหล่งอ้างอิง: {target.url})"

        return format_response_layout(raw_answer, default_citation=default_cite)
    except Exception as e:
        logger.error(f"Error generating web grounded answer: {e}")
        if is_caat_topic:
            return (
                "สำหรับข้อมูลด้านกฎหมายอากาศยานและการใช้น่านฟ้าโดรนการเกษตร\n\n"
                f"(แหล่งอ้างอิง: {CAAT_PORTAL_INFOGRAPHIC_URL})"
            )
        return "ไม่พบข้อมูลดังกล่าวในเอกสารฐานความรู้และไม่พบข้อมูลที่น่าเชื่อถือจากแหล่งข้อมูลภายนอก"
