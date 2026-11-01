import unittest
from unittest.mock import MagicMock, patch

from app.rag import slide_retriever as sr
from app.rag.application_scope import ApplicationScope
from app.rag.evidence import Evidence, document_page_evidence, parse_grounded_result
from tests.helpers import result_json


class DocumentScopeTests(unittest.TestCase):
    def index(self):
        docs = ["พัดส้ม ปริมาณต่อหัว 500 ml", "พัดส้ม ปริมาณต่อหัว 500 ml"]
        metas = [{"source_file": "UAV06.pdf", "page_number": "5", "source_type": "text"},
                 {"source_file": "UAV07.pdf", "page_number": "12", "source_type": "text"}]
        tokens = [sr.tokenize_thai_terms(d) for d in docs]
        return {"docs": docs, "metas": metas, "tokens": tokens, "avgdl": len(tokens[0]),
                "idf": {t: 1 for token_list in tokens for t in token_list}}

    def test_named_document_constrains_dense_lexical_and_expanded_sources(self):
        index = self.index()
        collection = MagicMock()
        collection.query.return_value = {"documents": [index["docs"]], "metadatas": [index["metas"]], "distances": [[.1, .2]]}
        collection.get.return_value = {"documents": index["docs"], "metadatas": index["metas"]}
        with patch.object(sr, "collection", collection), patch.object(sr, "_bm25_index", return_value=index), \
             patch.object(sr, "embed_text", return_value=[1]), patch.object(sr, "RETRIEVER_BM25", "global"):
            result = sr.search_slides_pipeline("ตามเอกสารUAV07 พัดส้มมีปริมาณต่อหัวเท่าไร")
        self.assertEqual([p["source_file"] for p in result["top_pages"]], ["UAV07.pdf"])
        self.assertEqual(collection.query.call_args.kwargs["where"], {"source_file": {"$in": ["UAV07.pdf"]}})

    def test_application_scope_applies_before_dense_and_bm25_selection(self):
        index = self.index()
        index['metas'][0]['source_file'] = 'UAV06 การบินทั่วไป.pdf'
        index['metas'][1]['source_file'] = 'UAV07 โดรนสำรวจ.pdf'
        collection = MagicMock()
        collection.query.return_value = {'documents': [index['docs']], 'metadatas': [index['metas']], 'distances': [[.1, .2]]}
        collection.get.return_value = {'documents': index['docs'], 'metadatas': index['metas']}
        scope = ApplicationScope('ก่อนบินโดรนตรวจอะไร')
        with patch.object(sr, 'collection', collection), patch.object(sr, '_bm25_index', return_value=index), \
             patch.object(sr, 'embed_text', return_value=[1]), patch.object(sr, 'RETRIEVER_BM25', 'global'):
            result = sr.search_slides_pipeline('ก่อนบินโดรนตรวจอะไร', source_scope=scope)
        self.assertEqual(collection.query.call_args.kwargs['where'],
                         {'source_file': {'$in': ['UAV06 การบินทั่วไป.pdf']}})
        self.assertTrue(result['top_pages'])
        self.assertTrue(all(page['source_file'] == 'UAV06 การบินทั่วไป.pdf' for page in result['top_pages']))
        self.assertIn('UAV07 โดรนสำรวจ.pdf', scope.excluded)

    def test_no_eligible_document_stops_before_embedding(self):
        index = self.index()
        for m in index['metas']:
            m['source_file'] = 'UAV07 โดรนสำรวจ.pdf'
        with patch.object(sr, '_bm25_index', return_value=index), patch.object(sr, 'embed_text') as embed:
            result = sr.search_slides_pipeline('ก่อนบินโดรนตรวจอะไร', source_scope=ApplicationScope('ก่อนบินโดรนตรวจอะไร'))
        self.assertEqual(result['top_pages'], [])
        embed.assert_not_called()

    def test_missing_named_document_does_not_silently_broaden_scope(self):
        with patch.object(sr, "_bm25_index", return_value=self.index()), patch.object(sr, "embed_text") as embed:
            self.assertEqual(sr.search_slides_pipeline("ในเอกสารUAV99 พัดส้มมีปริมาณต่อหัวเท่าไร")["top_pages"], [])
        embed.assert_not_called()

    def test_true_document_name_is_metadata_not_an_unsupported_measurement(self):
        source = [Evidence("D1", "ปริมาณต่อหัว 500 ml", "UAV07.pdf", "12")]
        valid = result_json(claims=[("ตาม UAV07 ปริมาณต่อหัว 500 ml", "D1", "ปริมาณต่อหัว 500 ml")])
        self.assertEqual(parse_grounded_result(valid, source).status, "sufficient")
        invalid = valid.replace("ตาม UAV07", "ตาม UAV99")
        self.assertEqual(parse_grounded_result(invalid, source).claims, [])

    def test_stitched_table_citation_preserves_actual_page_span_from_metadata(self):
        pages = [{"source_file": "real.pdf", "page_number": "2", "page_from": "1", "page_end": "3",
                  "content": "หน้า: 999\nModel | Tank\nM1 | 50 L"}]
        (source,) = document_page_evidence(pages)
        self.assertEqual(source.page_number, "2")
        self.assertEqual(source.citation, "real.pdf, หน้า 1–3")
        pages[0]["page_end"] = "1"
        self.assertEqual(document_page_evidence(pages), [])

    def test_retrieval_passes_stitched_table_span_to_evidence(self):
        index = self.index()
        index["metas"][0].update(page_from="4", page_end="6")
        collection = MagicMock()
        collection.query.return_value = {"documents": [[index["docs"][0]]],
            "metadatas": [[index["metas"][0]]], "distances": [[.1]]}
        collection.get.return_value = {"documents": [index["docs"][0]], "metadatas": [index["metas"][0]]}
        with patch.object(sr, "collection", collection), patch.object(sr, "_bm25_index", return_value=index), \
             patch.object(sr, "embed_text", return_value=[1]), patch.object(sr, "RETRIEVER_BM25", "global"):
            pages = sr.search_slides_pipeline("ตาม UAV06 พัดส้ม")['top_pages']
        source = document_page_evidence(pages)[0]
        self.assertEqual(source.citation, "UAV06.pdf, หน้า 4–6")
