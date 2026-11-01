"""Citations retain the exact source page all the way to the LINE message."""
import re

from app.rag.natural_answer import render
from app.rag.web_fallback import _results, web_evidence
from app.services.line_service import _messages


def test_caat_answer_contains_only_the_cited_document_url_not_a_homepage():
    url = 'https://uasportal.caat.or.th/documents/flight-guide.pdf?lang=th&version=2#page=6'
    sources = web_evidence(_results([{
        'url': url, 'title': 'คู่มือการบิน', 'content': 'บินได้เฉพาะเวลา 06.00-18.00 น.'
    }], is_caat=True))
    answer = render('บินได้เฉพาะเวลา 06.00-18.00 น. [W1]', sources)
    assert not answer.dropped
    message = _messages(answer.text)[0].to_dict()
    assert message['type'] == 'text'
    assert re.findall(r'https?://\S+', message['text']) == [url]


def test_only_used_sources_are_cited_and_full_article_links_are_preserved():
    url = 'https://ag.dji.com/maintenance/battery?model=T50&lang=th#inspection'
    sources = web_evidence(_results([
        {'url': url, 'title': 'Battery inspection', 'content': 'ตรวจว่าแบตเตอรี่ไม่บวมก่อนบิน'},
        {'url': 'https://ag.dji.com/', 'title': 'หน้าหลัก', 'content': 'ผลิตภัณฑ์โดรน'}
    ], is_caat=False))
    answer = render('ตรวจว่าแบตเตอรี่ไม่บวมก่อนบิน [W1]', sources)
    assert not answer.dropped
    assert re.findall(r'https?://\S+', _messages(answer.text)[0].text) == [url]
