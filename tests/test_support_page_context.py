"""Grounded same-page context from the existing index; no provider calls."""
import json
import re
from types import SimpleNamespace

from app.rag import support_pipeline as support
from app.rag.evidence import Evidence


def doc(content, *, file='guide.pdf', page='4', kind='text', source='pdf_text',
        section='Chapter', sha='v1'):
    return SimpleNamespace(page_content=content, metadata={'source_file':file,'page_number':page,
        'source_type':kind,'source':source,'section':section,'source_sha256':sha})


def test_table_parent_is_added_as_separate_original_evidence_with_page_and_section():
    table=doc('Name | Dose\nAlpha | 30',kind='table',source='pdf_native_table',section='Chapter › 1')
    heading=doc('Recommendations for orchard crops\nUse according to the label.')
    distractors=[doc('Other page',page='5'),doc('Other file',file='other.pdf'),
                 doc('Other section',section='Another chapter'),doc('Different revision',sha='v2'),
                 doc('Unknown revision',sha=''),
                 doc('Image interpretation',kind='image',source='vision')]
    evidence=[Evidence('D1',table.page_content,'guide.pdf','4')]
    result=support.add_table_page_context(evidence,[table,heading,*distractors],[])
    assert [(e.content,e.source_file,e.page_number) for e in result]==[
        (heading.page_content,'guide.pdf','4'),(table.page_content,'guide.pdf','4')]


def test_ambiguous_or_absent_section_does_not_invent_a_table_parent():
    table=doc('Name | Dose\nAlpha | 30',kind='table',source='pdf_native_table',section='')
    evidence=[Evidence('D1',table.page_content,'guide.pdf','4')]
    assert support.add_table_page_context(evidence,[table,doc('Some title')],[])==evidence
    changed=doc('Name | Dose\nAlpha | 99',kind='table',source='pdf_native_table')
    assert support.add_table_page_context(evidence,[changed,doc('Some title')],[])==evidence


def test_existing_page_text_is_not_duplicated_and_actual_source_quote_remains_checkable():
    table=doc('Name | Dose\nAlpha | 30',kind='table',source='pdf_native_table')
    heading=doc('Dose table for orchard crops')
    evidence=[Evidence('D1',heading.page_content,'guide.pdf','4'),
              Evidence('D2',table.page_content,'guide.pdf','4')]
    result=support.add_table_page_context(evidence,[table,heading],[])
    assert result==evidence
    payload=json.loads(support.build_messages('What is the dose?',result,'kb',[])[1]['content'])
    assert ['\n'.join(re.sub(r'^L[1-9]\d*: ', '', line) for line in s['content'].splitlines())
            for s in payload['sources']]==[heading.page_content,table.page_content]
    assert 'reason' not in payload['response_contract']['answer']
    assert 'intro' not in payload['response_contract']['answer']
