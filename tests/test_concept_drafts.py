"""Draft provenance and pedagogical examples; no publication or embeddings."""
from decimal import Decimal,ROUND_HALF_UP
import hashlib
import json
import pytest
from scripts import new_bank_documents as docs

FOLDER=docs.ROOT/'docs/drafts/new-bank-concepts'
INDEX=json.loads((FOLDER/'sources.json').read_text(encoding='utf-8'))


@pytest.mark.parametrize('draft',INDEX['documents'],ids=lambda d:d['file'])
def test_draft_sources_are_preserved(draft):
    catalog=docs.load_catalog()
    assert hashlib.sha256(docs.catalog.CATALOG_PATH.read_bytes()).hexdigest()==INDEX['catalog_sha256']
    text=(FOLDER/draft['file']).read_text(encoding='utf-8')
    assert 'No publicado en RAG' in text and draft['status']=='draft_not_published'
    expected=[claim for key in draft['source_entries'] for claim in catalog['entries'][key]['claims']]
    assert draft['claims']==expected
    assert all(key in text for key in draft['source_entries'])
    for claim in draft['claims']:
        for source in claim['source_refs']:
            assert hashlib.sha256((docs.ROOT/source['path']).read_bytes()).hexdigest()==source['sha256']


@pytest.mark.parametrize('example',INDEX['examples'],ids=lambda e:e['product'])
def test_financial_examples_are_exact(example):
    prior=Decimal(example['prior']);rate=Decimal(example['rate'])
    target=(prior*(1+rate)).quantize(Decimal('0.01'),rounding=ROUND_HALF_UP)
    closing=prior+sum(map(Decimal,example['positive']))-sum(map(Decimal,example['negative']))
    assert closing==target==Decimal(example['closing'])


def test_join_example_doubles_count_not_money_units():
    movements=[Decimal('10'),Decimal('20')]
    assert sum(movements)==30
    assert sum(amount for amount in movements for duplicate in range(2))==60
