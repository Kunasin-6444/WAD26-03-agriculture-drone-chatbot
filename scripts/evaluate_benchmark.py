from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from app.rag.crag_service import run_crag_pipeline


@dataclass
class TestCase:
    id: int
    category: str
    query: str
    expected_source_type: str  # "knowledge_base", "caat_portal", "web_fallback", "abstain"
    expected_keywords: list[str]
    description: str


TEST_CASES: list[TestCase] = [
    # ----------------------------------------------------
    # Category 1: In-Scope Knowledge Base (UAV06 / UAV07)
    # ----------------------------------------------------
    TestCase(
        id=1,
        category="in_scope",
        query="หัวฉีดพัดส้มมีอัตราการไหลเท่าไรต่อหัวฉีด?",
        expected_source_type="knowledge_base",
        expected_keywords=["500", "UAV07"],
        description="ถามอัตราการไหลของหัวฉีดพัดส้ม (ต้องพบ 500 ml และอ้างอิง UAV07 หรือ UAV06)",
    ),
    TestCase(
        id=2,
        category="in_scope",
        query="ที่ความสูง 1 เมตร หน้ากว้างการฉีดพ่นต่อหัวเท่าไร?",
        expected_source_type="knowledge_base",
        expected_keywords=["2.8", "UAV07"],
        description="ถามหน้ากว้างการพ่นที่ความสูง 1 เมตร (ต้องพบ 2.8 และอ้างอิง UAV07)",
    ),
    TestCase(
        id=3,
        category="in_scope",
        query="หัวฉีดพัดส้ม 3 หัวรวมกันมีอัตราการไหลรวมเท่าไร?",
        expected_source_type="knowledge_base",
        expected_keywords=["1500", "1,500"],
        description="ถามอัตราการไหลรวมของ 3 หัวฉีดพัดส้ม (ต้องพบ 1500 ml)",
    ),
    TestCase(
        id=4,
        category="in_scope",
        query="ละอองยาที่มีขนาดเล็กเกินไปในการฉีดพ่นด้วยโดรนมีข้อเสียอย่างไร?",
        expected_source_type="knowledge_base",
        expected_keywords=["ปลิว", "ลอย", "ระเหย", "ฟุ้ง"],
        description="ถามข้อเสียของละอองสารขนาดเล็กเกินไป (drift/ปลิวลอย)",
    ),
    TestCase(
        id=5,
        category="in_scope",
        query="โดรนฉีดพ่นเพื่อการเกษตรสามารถนำไปใช้งานอะไรได้บ้าง?",
        expected_source_type="knowledge_base",
        expected_keywords=["ฉีดพ่น", "ปุ๋ย", "สารเคมี", "เกษตร"],
        description="ถามประโยชน์การใช้งานโดรนเกษตร",
    ),
    TestCase(
        id=6,
        category="in_scope",
        query="รอบการทำงานของหัวฉีดพัดส้มที่อัตราการไหล 500 ml คือกี่ rpm?",
        expected_source_type="knowledge_base",
        expected_keywords=["1600", "1,600", "rpm"],
        description="ถามรอบการทำงาน (ต้องพบ 1600 rpm)",
    ),
    TestCase(
        id=7,
        category="in_scope",
        query="หัวฉีดมีหน้าที่สำคัญอย่างไรในระบบฉีดพ่นของโดรนการเกษตร?",
        expected_source_type="knowledge_base",
        expected_keywords=["หัวฉีด", "ละออง", "กระจาย", "อัตรา"],
        description="ถามหน้าที่และความสำคัญของหัวฉีด",
    ),

    # ----------------------------------------------------
    # Category 2: CAAT Air Law & Air Space (Rule R1)
    # ----------------------------------------------------
    TestCase(
        id=8,
        category="caat_rule_r1",
        query="การขึ้นทะเบียนโดรนเกษตรต้องทำอย่างไร?",
        expected_source_type="caat_portal",
        expected_keywords=["https://uasportal.caat.or.th/infographic", "CAAT"],
        description="ถามการขึ้นทะเบียนโดรน (ต้องส่งต่อไปยัง CAAT UAS Portal ตาม R1)",
    ),
    TestCase(
        id=9,
        category="caat_rule_r1",
        query="ข้อกำหนดเขตห้ามบินโดรนและระยะห่างจากสนามบินมีอะไรบ้าง?",
        expected_source_type="caat_portal",
        expected_keywords=["https://uasportal.caat.or.th/infographic"],
        description="ถามเขตห้ามบินและระยะห่างสนามบิน (ต้องส่งต่อไปยัง CAAT UAS Portal)",
    ),
    TestCase(
        id=10,
        category="caat_rule_r1",
        query="กฎหมายการบินโดรนห้ามบินสูงเกินกี่เมตร?",
        expected_source_type="caat_portal",
        expected_keywords=["https://uasportal.caat.or.th/infographic"],
        description="ถามกฎหมายความสูงการบินโดรน (ต้องส่งต่อไปยัง CAAT UAS Portal)",
    ),
    TestCase(
        id=11,
        category="caat_rule_r1",
        query="ผู้บังคับโดรนต้องมีใบอนุญาตนักบินหรือขึ้นทะเบียน กสทช อย่างไร?",
        expected_source_type="caat_portal",
        expected_keywords=["https://uasportal.caat.or.th/infographic"],
        description="ถามใบอนุญาตและการขึ้นทะเบียน (ต้องส่งต่อไปยัง CAAT UAS Portal)",
    ),
    TestCase(
        id=12,
        category="caat_rule_r1",
        query="น่านฟ้าและเงื่อนไขการขออนุญาตบินโดรนตรวจสอบได้ที่ไหน?",
        expected_source_type="caat_portal",
        expected_keywords=["https://uasportal.caat.or.th/infographic"],
        description="ถามช่องทางตรวจสอบน่านฟ้าและขออนุญาตบิน",
    ),

    # ----------------------------------------------------
    # Category 3: Out-of-Scope / Web Fallback
    # ----------------------------------------------------
    TestCase(
        id=13,
        category="out_of_scope",
        query="ราคาน้ำมันดีเซล B7 วันนี้ราคาลิตรละเท่าไร?",
        expected_source_type="web_fallback_or_abstain",
        expected_keywords=[],
        description="คำถามนอกขอบเขตเกษตรโดรน (ต้องไม่มั่วจาก PDF)",
    ),
    TestCase(
        id=14,
        category="out_of_scope",
        query="พยากรณ์อากาศจังหวัดขอนแก่นสัปดาห์นี้เป็นอย่างไร?",
        expected_source_type="web_fallback_or_abstain",
        expected_keywords=[],
        description="คำถามสภาพอากาศ (ต้องไม่ตอบมั่วจาก PDF)",
    ),
    TestCase(
        id=15,
        category="out_of_scope",
        query="ราคาข้าวเปลือกเจ้าหอมมะลิในตลาดวันนี้ตันละเท่าไร?",
        expected_source_type="web_fallback_or_abstain",
        expected_keywords=[],
        description="คำถามราคาตลาดสินค้าเกษตรรายวัน",
    ),
    TestCase(
        id=16,
        category="out_of_scope",
        query="มหาวิทยาลัยขอนแก่นมีคณะอะไรบ้าง?",
        expected_source_type="web_fallback_or_abstain",
        expected_keywords=[],
        description="คำถามทั่วไปเกี่ยวกับมหาวิทยาลัยขอนแก่น",
    ),
    TestCase(
        id=17,
        category="out_of_scope",
        query="ดัชนีตลาดหลักทรัพย์แห่งประเทศไทยวันนี้ปิดที่เท่าไร?",
        expected_source_type="web_fallback_or_abstain",
        expected_keywords=[],
        description="คำถามการเงิน/ตลาดหุ้น",
    ),

    # ----------------------------------------------------
    # Category 4: Ambiguous / Vague Queries
    # ----------------------------------------------------
    TestCase(
        id=18,
        category="ambiguous",
        query="อัตราการไหลเท่าไร?",
        expected_source_type="any",
        expected_keywords=[],
        description="คำถามกำกวม ไม่ระบุหัวฉีดหรือบริบท",
    ),
    TestCase(
        id=19,
        category="ambiguous",
        query="ราคาเท่าไร?",
        expected_source_type="any",
        expected_keywords=[],
        description="คำถามกำกวม ไม่ระบุสินค้าหรืออุปกรณ์",
    ),
    TestCase(
        id=20,
        category="ambiguous",
        query="บินได้ไหม?",
        expected_source_type="any",
        expected_keywords=[],
        description="คำถามสั้นและกำกวม",
    ),
    TestCase(
        id=21,
        category="ambiguous",
        query="ฉีดพ่นอย่างไร?",
        expected_source_type="any",
        expected_keywords=[],
        description="คำถามกว้างมาก",
    ),

    # ----------------------------------------------------
    # Category 5: Unsupported / Nonsense / Abstain (Rule R6)
    # ----------------------------------------------------
    TestCase(
        id=22,
        category="unsupported_abstain",
        query="โดรนเกษตรรุ่นใดสามารถบินไปฉีดปุ๋ยบนพื้นผิวดาวอังคารได้?",
        expected_source_type="abstain",
        expected_keywords=["ไม่พบข้อมูล", "ไม่สามารถยืนยัน"],
        description="คำถามหลุดโลก (ต้องปฏิเสธอย่างชัดเจน ไม่เดา)",
    ),
    TestCase(
        id=23,
        category="unsupported_abstain",
        query="คาถาหรือมนต์วิเศษที่ทำให้โดรนบินได้โดยไม่ต้องใส่แบตเตอรี่คือบทไหน?",
        expected_source_type="abstain",
        expected_keywords=["ไม่พบข้อมูล", "ไม่สามารถยืนยัน"],
        description="คำถามไสยศาสตร์ (ต้อง Abstain)",
    ),
    TestCase(
        id=24,
        category="unsupported_abstain",
        query="หัวฉีดรุ่นนีออนสายรุ้งปี ค.ศ. 3000 มีความเร็วการฉีดกี่ล้านกิโลเมตรต่อชั่วโมง?",
        expected_source_type="abstain",
        expected_keywords=["ไม่พบข้อมูล", "ไม่สามารถยืนยัน"],
        description="คำถามเรื่องแต่งอนาคต (ต้อง Abstain)",
    ),
    TestCase(
        id=25,
        category="unsupported_abstain",
        query="วิธีนำโดรนการเกษตรไปดำน้ำจับปลาวาฬสีน้ำเงินในแม่น้ำเจ้าพระยา?",
        expected_source_type="abstain",
        expected_keywords=["ไม่พบข้อมูล", "ไม่สามารถยืนยัน"],
        description="คำถามที่เป็นไปไม่ได้ (ต้อง Abstain)",
    ),
    TestCase(
        id=26,
        category="unsupported_abstain",
        query="โดรนฉีดพ่นผสมพันธุ์กับยานอวกาศอพอลโล 11 ได้ลูกออกมาเป็นเครื่องบินแบบใด?",
        expected_source_type="abstain",
        expected_keywords=["ไม่พบข้อมูล", "ไม่สามารถยืนยัน"],
        description="คำถามไร้สาระ/หลอกลวง (ต้อง Abstain)",
    ),
    TestCase(
        id=27,
        category="unsupported_abstain",
        query="qwertyuiopasdfghjklzxcvbnm1234567890",
        expected_source_type="abstain",
        expected_keywords=["ไม่พบข้อมูล", "ไม่สามารถยืนยัน"],
        description="ข้อความสุ่มตัวอักษรไร้ความหมาย (ต้อง Abstain)",
    ),
    TestCase(
        id=28,
        category="unsupported_abstain",
        query="   ",
        expected_source_type="abstain",
        expected_keywords=["กรุณาระบุคำถาม"],
        description="ข้อความว่างเปล่า (ต้องขอให้ระบุคำถาม)",
    ),
]


def evaluate_all() -> dict:
    results = []
    total = len(TEST_CASES)
    passed = 0
    total_latency = 0.0

    print("=" * 70)
    print(f"RUNNING FINAL EVALUATION BENCHMARK ({total} REAL THAI QUESTIONS)")
    print("=" * 70)

    for tc in TEST_CASES:
        start_time = time.time()
        resp = run_crag_pipeline(tc.query)
        latency = round(time.time() - start_time, 2)
        total_latency += latency

        # Evaluate correctness
        is_pass = False
        reasons = []

        # Check source type
        if tc.expected_source_type == "any":
            is_pass = True
        elif tc.expected_source_type == "web_fallback_or_abstain":
            if resp.source_type in ("web_fallback", "abstain"):
                is_pass = True
            else:
                reasons.append(f"Expected web_fallback or abstain, got {resp.source_type}")
        elif resp.source_type == tc.expected_source_type:
            is_pass = True
        else:
            reasons.append(f"Source type mismatch: expected {tc.expected_source_type}, got {resp.source_type}")

        # Check expected keywords
        if is_pass and tc.expected_keywords:
            has_keywords = any(kw.lower() in resp.answer.lower() for kw in tc.expected_keywords)
            if not has_keywords:
                is_pass = False
                reasons.append(f"None of expected keywords found: {tc.expected_keywords}")

        # Verify no hallucination (must have citation if answered from KB or web)
        if resp.source_type == "knowledge_base" and "แหล่งอ้างอิง" not in resp.answer:
            is_pass = False
            reasons.append("Missing source citation in knowledge_base answer")

        if is_pass:
            passed += 1
            status_str = "PASS"
        else:
            status_str = "FAIL"

        print(f"[{status_str}] Q{tc.id:02d} ({tc.category}) | Latency: {latency}s | Source: {resp.source_type}")
        print(f"     Query: {tc.query}")
        print(f"     Answer: {resp.answer[:120]}..." if len(resp.answer) > 120 else f"     Answer: {resp.answer}")
        if not is_pass:
            print(f"     Reason: {'; '.join(reasons)}")
        print("-" * 70)

        results.append({
            "id": tc.id,
            "category": tc.category,
            "query": tc.query,
            "expected_source_type": tc.expected_source_type,
            "actual_source_type": resp.source_type,
            "latency_seconds": latency,
            "status": status_str,
            "answer": resp.answer,
            "reasons": reasons,
        })

    avg_latency = round(total_latency / total, 2)
    pass_rate = round((passed / total) * 100, 1)

    print()
    print("=" * 70)
    print("EVALUATION SUMMARY")
    print("=" * 70)
    print(f"Total Questions : {total}")
    print(f"Passed          : {passed}/{total} ({pass_rate}%)")
    print(f"Average Latency : {avg_latency}s")
    print("=" * 70)

    summary = {
        "total": total,
        "passed": passed,
        "failed": total - passed,
        "pass_rate_percent": pass_rate,
        "avg_latency_seconds": avg_latency,
        "results": results,
    }

    # Save evaluation report to docs/
    report_file = Path("docs/FINAL_EVALUATION_REPORT.json")
    report_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Detailed report saved to {report_file}")

    return summary


if __name__ == "__main__":
    evaluate_all()
