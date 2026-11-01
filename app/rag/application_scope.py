"""Document applicability for the agricultural-pilot trial, before retrieval fusion.

Scope comes from document metadata/title, never from a gold page or numeric value.
Unclassified documents remain eligible. Survey material is available on request;
its device-specific procedures are not defaults for agricultural operations.
"""
from __future__ import annotations

from pathlib import Path
import re
from urllib.parse import urlparse

from app.rag.source_policy import canonical_document_id, requested_document_ids

SURVEY_REQUESTS = ('สำรวจ', 'ภาพถ่าย', 'ถ่ายภาพ', 'กล้อง', 'แผนที่', 'gsd',
                   'orthomosaic', 'overlap', 'camera', 'mapping', 'survey')
SURVEY_TITLES = ('สำรวจ', 'ภาพถ่าย', 'survey', 'mapping', 'photogrammetry')


def normalized(text):
    return re.sub(r'\s+', '', str(text).casefold().replace('ํา', 'ำ'))


class ApplicationScope:
    def __init__(self, query):
        self.document_ids = requested_document_ids(query)
        compact = normalized(query)
        self.survey_requested = any(term in compact for term in SURVEY_REQUESTS)
        self.excluded = {}

    def allows(self, document):
        meta = document.metadata
        filename = str(meta.get('source_file') or '')
        return self.allows_source(filename, str(meta.get('application_scope') or ''))

    def allows_source(self, filename, declared_scope=''):
        """Apply the same policy to retrieved evidence without a framework document wrapper."""
        filename = str(filename or '')
        if self.document_ids:
            reason = '' if canonical_document_id(filename) in self.document_ids else 'outside_named_documents'
        else:
            title = normalized(Path(filename).stem)
            declared = str(declared_scope or '').casefold()
            survey_only = declared == 'survey' or any(term in title for term in SURVEY_TITLES)
            reason = 'survey_document_not_requested' if survey_only and not self.survey_requested else ''
        if reason:
            self.excluded[filename] = reason
        return not reason

    def diagnostic(self):
        return {'stage': 'application_scope', 'default': 'agricultural_operations',
                'survey_requested': self.survey_requested,
                'requested_document_ids': sorted(self.document_ids),
                'excluded_documents': dict(sorted(self.excluded.items()))}


_AGRICULTURE = re.compile(r'เกษตร|ฉีดพ่น|agricultur|\bagras\b', re.I)
_DJI_CONSUMER = re.compile(r'\b(?:mavic|phantom|dji\s+mini|dji\s+air|dji\s+fpv)\b', re.I)


def web_source_applicable(question, result):
    """Do not silently generalize an explicitly consumer-family guide to agricultural DJI."""
    query = str(question or '')
    if not _AGRICULTURE.search(query) or _DJI_CONSUMER.search(query):
        return True
    url = getattr(result, 'url', '')
    host = (urlparse(url).hostname or '').lower().rstrip('.')
    if host != 'dji.com' and not host.endswith('.dji.com'):
        return True
    content = (str(getattr(result, 'title', '') or '') + '\n' + str(getattr(result, 'content', '') or '')[:3000])
    return not (_DJI_CONSUMER.search(content) and not _AGRICULTURE.search(content))
