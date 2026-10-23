"""Exact coverage of immutable physical declarations, not a bank policy certification."""
import hashlib
import json
from pathlib import Path
from scripts.new_bank_catalog import ddl_tables, source_inventory, CATALOG_PATH


def test_classification_matches_all_physical_columns_and_types():
    proposal = json.loads(Path('docs/data-classification-proposal.json').read_text(encoding='utf-8'))
    declarations = ddl_tables(source_inventory())
    proposed = {table['table']: table for table in proposal['tables']}
    assert set(proposed) == set(declarations)
    assert len(proposed) == proposal['source_table_count'] == 5
    assert sum(len(t['columns']) for t in proposed.values()) == proposal['source_column_count'] == 42
    for name, table in declarations.items():
        cols = {c['column']: c for c in proposed[name]['columns']}
        assert len(cols) == len(proposed[name]['columns'])
        assert set(cols) == set(table['columns'])
        for col, physical in table['columns'].items():
            assert cols[col]['physical_type'] == physical['physical_type']
            assert cols[col]['source_ref'] == physical['source_ref']
            assert cols[col]['sensitivity'] in proposal['categories']
            assert cols[col]['sensitivity'] != 'aggregate_finance'
    assert proposal['catalog_sha256'] == hashlib.sha256(CATALOG_PATH.read_bytes()).hexdigest()
    assert proposal['status'] == 'reviewable_synthetic_proposal_not_official_bank_policy'


def test_identifiers_and_joined_finances_are_not_public_metadata():
    p = json.loads(Path('docs/data-classification-proposal.json').read_text(encoding='utf-8'))
    for table in p['tables']:
        for col in table['columns']:
            if col['column'] in ('num_cte', 'num_cta'):
                assert col['sensitivity'] == 'identifiers'
            if table['table'].startswith('cfg.'):
                assert col['sensitivity'] in ('identifiers', 'individual_movements')
        if table['table'] == 'dim.dim_cliente' or table['table'].startswith('cfg.'):
            assert table['row_sensitivity'] == 'restricted'
