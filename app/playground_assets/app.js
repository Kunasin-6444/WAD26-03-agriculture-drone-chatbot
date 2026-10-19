"use strict";

const byId = (id) => document.getElementById(id);
const form = byId("question-form");
const question = byId("question");
const modeFieldset = byId("mode-fieldset");
const scenario = byId("scenario");
const submitButton = byId("submit-button");
const copyButton = byId("copy-button");
const answerPanel = document.querySelector(".answer-panel");
const screenStatus = byId("screen-status");
let busy = false;
let lastAnswer = "";

function selectedMode() {
  return form.querySelector('input[name="mode"]:checked').value;
}

function updateMode() {
  const live = selectedMode() === "live";
  byId("demo-options").hidden = live;
  byId("mode-note").textContent = live
    ? "ใช้ API และ quota จริงเมื่อกดส่งเท่านั้น หาก quota ยังหมด ให้ใช้โหมดจำลองต่อก่อน"
    : "คำตอบและแหล่งอ้างอิงเป็นตัวอย่าง ยังไม่ได้ค้นเอกสารหรือเว็บจริง";
  byId("mode-note").classList.toggle("live", live);
  submitButton.classList.toggle("live", live);
  byId("submit-label").textContent = live ? "ส่งคำถามจริง · ใช้ quota" : "ดูคำตอบจำลอง";
}

// Build DOM nodes from text; never interpret model/source text as HTML.
// Keep source URL paths, query strings and fragments exactly as received.
function appendLinkedText(element, text) {
  const pattern = /https?:\/\/[^\s<>"\u0000-\u001f]+/g;
  let start = 0;
  for (const match of text.matchAll(pattern)) {
    element.append(document.createTextNode(text.slice(start, match.index)));
    const link = document.createElement("a");
    link.setAttribute("href", match[0]);
    link.textContent = match[0];
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.referrerPolicy = "no-referrer";
    element.append(link);
    start = match.index + match[0].length;
  }
  element.append(document.createTextNode(text.slice(start)));
}

function displayResult(data, submittedQuestion) {
  lastAnswer = data.notice ? data.notice + "\n\n" + data.answer : data.answer;
  byId("result").hidden = false;
  byId("answered-question").textContent = "คำถาม: " + submittedQuestion;
  const demo = data.mode === "demo";
  byId("result-mode").textContent = demo ? "ตัวอย่างจำลอง · ไม่ได้เรียก AI" : "คำตอบจากระบบจริง";
  byId("result-mode").classList.toggle("live", !demo);
  byId("elapsed-time").textContent = (demo ? "เวลาโหมดจำลอง " : "เวลาระบบ ")
    + (data.elapsed_ms / 1000).toLocaleString("th-TH", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " วินาที";
  byId("demo-notice").textContent = data.notice || "";
  byId("demo-notice").hidden = !data.notice;
  const marker = "\n\nแหล่งอ้างอิง:\n";
  const split = data.answer.indexOf(marker);
  const body = split === -1 ? data.answer : data.answer.slice(0, split);
  const references = split === -1 ? "" : data.answer.slice(split + marker.length);
  byId("answer-body").replaceChildren();
  appendLinkedText(byId("answer-body"), body);
  byId("answer-body").classList.toggle("error", data.status === "unavailable" || data.status === "error");
  byId("sources-list").replaceChildren();
  byId("sources-section").hidden = !references;
  if (references) {
    for (const source of references.split(/\n(?=\[\d+\])/)) {
      const item = document.createElement("p");
      item.className = "source-item";
      appendLinkedText(item, source);
      byId("sources-list").append(item);
    }
  }
  copyButton.hidden = false;
  copyButton.textContent = "คัดลอก";
  screenStatus.textContent = demo ? "แสดงผลจำลองแล้ว ไม่ได้เรียก AI" : "ประมวลผลคำถามเสร็จแล้ว";
}

form.addEventListener("change", (event) => {
  if (event.target.name === "mode") updateMode();
});
question.addEventListener("input", () => {
  byId("character-count").textContent = question.value.length.toLocaleString("th-TH") + " / 2,000";
  question.setCustomValidity("");
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (busy) return;
  const text = question.value.trim();
  if (!text) {
    question.setCustomValidity("กรุณาพิมพ์คำถามก่อนส่ง");
    question.reportValidity();
    return;
  }
  const mode = selectedMode();
  const chosenScenario = scenario.value;
  busy = true;
  submitButton.disabled = true;
  modeFieldset.disabled = true;
  scenario.disabled = true;
  question.readOnly = true;
  copyButton.hidden = true;
  byId("empty-state").hidden = true;
  byId("result").hidden = true;
  byId("loading-state").hidden = false;
  byId("loading-state").querySelector("small").textContent = mode === "demo"
    ? "กำลังแสดงตัวอย่างหน้าจอ ไม่ได้เรียก AI"
    : "กำลังใช้ระบบจริง ครั้งแรกอาจใช้เวลาโหลดเพิ่มเติม";
  answerPanel.setAttribute("aria-busy", "true");
  screenStatus.textContent = "กำลังประมวลผลคำถาม";
  const started = performance.now();
  byId("waiting-time").textContent = "0 วินาที";
  const ticker = setInterval(() => {
    byId("waiting-time").textContent = Math.floor((performance.now() - started) / 1000) + " วินาที";
  }, 1000);
  try {
    const response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: text, mode, scenario: chosenScenario }),
      credentials: "same-origin",
    });
    const data = await response.json();
    if (typeof data.answer !== "string" || typeof data.elapsed_ms !== "number") {
      throw new Error("Unexpected response");
    }
    displayResult(data, text);
  } catch {
    displayResult({
      answer: "เชื่อมต่อหน้าทดลองไม่สำเร็จ กรุณาตรวจว่าเซิร์ฟเวอร์ยังเปิดอยู่ ระบบไม่ได้ส่งคำถามซ้ำอัตโนมัติครับ",
      mode, status: "error", notice: mode === "demo" ? "โหมดจำลอง ไม่ได้เรียก AI" : "",
      elapsed_ms: performance.now() - started,
    }, text);
  } finally {
    clearInterval(ticker);
    busy = false;
    submitButton.disabled = false;
    modeFieldset.disabled = false;
    scenario.disabled = false;
    question.readOnly = false;
    byId("loading-state").hidden = true;
    answerPanel.setAttribute("aria-busy", "false");
    updateMode();
  }
});

copyButton.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(lastAnswer);
    copyButton.textContent = "คัดลอกแล้ว";
    screenStatus.textContent = "คัดลอกคำตอบและอ้างอิงแล้ว";
  } catch {
    screenStatus.textContent = "คัดลอกอัตโนมัติไม่ได้ กรุณาเลือกข้อความคำตอบเพื่อคัดลอก";
    copyButton.textContent = "เลือกข้อความเพื่อคัดลอก";
  }
});

updateMode();
