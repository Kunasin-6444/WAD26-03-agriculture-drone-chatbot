import unittest
from unittest.mock import MagicMock, patch

from app.rag.source_policy import CAAT_DESIGNATED_URLS
from app.rag.web_fallback import MAX_WEB_TIMEOUT_SECONDS, WebSearchResult, get_tavily_client, is_trusted_domain, search_web_fallback, web_evidence
import threading


class WebSourceContractTests(unittest.TestCase):
    def test_official_hosts_and_subdomains_trusted(self):
        for url in ["https://caat.or.th/a", "https://uasportal.caat.or.th/a", "https://doa.go.th/a", "https://kku.ac.th/a", "https://pttor.com/a"]:
            with self.subTest(url=url):
                self.assertTrue(is_trusted_domain(url))

    def test_spoofed_domains_and_arbitrary_organizations_not_trusted(self):
        for url in ["https://fake.example/caat.or.th", "https://caat.or.th.attacker.example", "https://caat.or.th@attacker.example", "https://random.or.th", "javascript:caat.or.th", "https://[broken"]:
            with self.subTest(url=url):
                self.assertFalse(is_trusted_domain(url))

    def test_search_rejects_untrusted_but_keeps_distinct_official_pages(self):
        client = MagicMock()
        client.search.return_value = {"results": [
            {"url": "https://unknown.example", "content": "คำตอบ", "score": 1},
            {"url": "https://doa.go.th/a", "content": "ข้อมูลแรก", "score": 0.8},
            {"url": "https://doa.go.th/b", "content": "ข้อมูลที่สอง", "score": 0.7},
        ]}
        results = search_web_fallback("หัวฉีด", tavily_client=client, max_results=3)
        self.assertEqual([r.url for r in results], ["https://doa.go.th/a", "https://doa.go.th/b"])
        self.assertEqual(client.search.call_args.kwargs["max_results"], 3)
        self.assertLessEqual(client.search.call_args.kwargs["timeout"], MAX_WEB_TIMEOUT_SECONDS)

    def test_invalid_empty_and_duplicate_urls_removed(self):
        client = MagicMock()
        client.search.return_value = {"results": [
            {"url": "javascript:bad", "content": "bad"},
            {"url": "https://doa.go.th/empty", "content": ""},
            {"url": "https://doa.go.th/a", "content": "ข้อมูล", "score": 0.8},
            {"url": "https://doa.go.th/a/", "content": "ข้อมูลซ้ำ", "score": 0.8},
        ]}
        self.assertEqual(len(search_web_fallback("ข้อมูล", tavily_client=client)), 1)

    def test_caat_fetches_actual_designated_page_and_restricts_search(self):
        client = MagicMock()
        client.extract.return_value = {"results": [{"url": CAAT_DESIGNATED_URLS[0], "raw_content": "ข้อกำหนดที่อ่านได้จริง"}]}
        client.search.return_value = {"results": [{"url": "https://attacker.example/caat.or.th", "content": "ข้อมูลปลอม"}]}
        results = search_web_fallback("ขึ้นทะเบียนโดรน", True, tavily_client=client)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, "ข้อกำหนดที่อ่านได้จริง")
        self.assertEqual(client.extract.call_args.kwargs["urls"], CAAT_DESIGNATED_URLS)
        self.assertEqual(client.search.call_args.kwargs["include_domains_mode"], "restrict")
        # the passages that match the question, not a short page summary
        self.assertEqual((client.search.call_args.kwargs["search_depth"], client.search.call_args.kwargs["chunks_per_source"]),
                         ("advanced", 3))

    def test_caat_extraction_error_can_use_official_search(self):
        client = MagicMock()
        client.extract.side_effect = TimeoutError()
        client.search.return_value = {"results": [{"url": "https://uasportal.caat.or.th/guide", "content": "คู่มือทางการ"}]}
        self.assertEqual(search_web_fallback("กฎหมาย", True, tavily_client=client)[0].content, "คู่มือทางการ")

    def test_caat_no_key_never_injects_static_facts(self):
        with patch("app.rag.web_fallback.get_tavily_client", return_value=None):
            self.assertEqual(search_web_fallback("กฎหมาย", True), [])

    def test_provider_failure_and_expired_deadline_are_clean(self):
        client = MagicMock()
        client.search.side_effect = TimeoutError()
        self.assertEqual(search_web_fallback("หัวฉีด", tavily_client=client), [])
        client.reset_mock()
        self.assertEqual(search_web_fallback("หัวฉีด", tavily_client=client, deadline=-1), [])
        client.search.assert_not_called()

    def test_evidence_retains_long_content_and_complete_rows(self):
        content = "\n".join(["แถวตาราง " + "ก" * 200 for _ in range(25)])
        evidence = web_evidence([WebSearchResult("ตาราง", "https://doa.go.th/table", content)])
        self.assertGreater(len(evidence), 1)
        self.assertEqual("\n".join(e.content for e in evidence), content)
        self.assertTrue(all(e.url == "https://doa.go.th/table" for e in evidence))

    def test_search_timeout_cannot_overrun_remaining_request_budget(self):
        client = MagicMock()
        client.search.return_value = {"results": []}
        with patch("app.rag.web_fallback.time.monotonic", return_value=100):
            search_web_fallback("หัวฉีด", tavily_client=client, deadline=100.9)
        self.assertLessEqual(client.search.call_args.kwargs["timeout"], .900001)

    def test_transport_reuse_does_not_reuse_credentials_after_key_change(self):
        with patch("app.rag.web_fallback._client_local", threading.local()), \
             patch("app.rag.web_fallback.TavilyClient", side_effect=[MagicMock(), MagicMock()]) as create:
            first = get_tavily_client(api_key="test-key-a")
            self.assertIs(first, get_tavily_client(api_key="test-key-a"))
            self.assertIsNot(first, get_tavily_client(api_key="test-key-b"))
            first.close.assert_called_once()
            self.assertEqual(create.call_count, 2)


class DesignatedCaatDocument(unittest.TestCase):
    def test_the_designated_document_survives_a_full_page_of_search_results(self):
        client = MagicMock()
        client.extract.return_value = {"results": [{"url": CAAT_DESIGNATED_URLS[0], "raw_content": "คู่มือผู้ขอรับบริการ"}]}
        client.search.return_value = {"results": [{"url": f"https://www.caat.or.th/{n}", "content": f"หน้า {n}", "score": 1}
                                                  for n in range(4)]}
        results = search_web_fallback("ประกันโดรน", True, tavily_client=client, max_results=4)
        self.assertEqual(results[0].url, CAAT_DESIGNATED_URLS[0])
        self.assertEqual(len(results), 4)
        self.assertEqual(results[0].title, "เอกสารทางการ CAAT")   # extract results carry no title

    def test_only_caat_urls_may_be_configured(self):
        from app.rag.web_fallback import designated_caat_urls
        with patch.dict("os.environ", {"CAAT_DESIGNATED_URLS": "https://evil.example/a.pdf, https://www.caat.or.th/b.pdf"}):
            self.assertEqual(designated_caat_urls(), ["https://www.caat.or.th/b.pdf"])
