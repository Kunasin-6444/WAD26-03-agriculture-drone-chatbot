"""Typed, immutable read model of source tables with row-level provenance.

Built from retrieved evidence, never by re-ingesting or modifying the KB. A table
is complete only when its declared members all survived context selection.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
import hashlib
import json
import re
import sqlite3

from app.rag.claim_consistency import _units
from app.rag.table_grounding import parse_tables

NUMBER = re.compile(r'-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?')
ENTITY = re.compile(r'บริษัท|ยี่ห้อ|รุ่น|ชื่อ|รายการ|company|brand|model|name|item|สาร', re.I)
CONDITION = re.compile(r'เงื่อนไข|ช่วง|กำหนด|การใช้|พืช|สถานะ|สถานนะ|คำแนะนำ|สภาพ|ภาษี|condition|crop|state|status|tax', re.I)


def canonical_unit(value):
    value = re.sub(r'\s+', '', value.casefold())
    for canonical, aliases in {'THB': {'บาท','thb','฿'}, 'USD': {'usd','$','dollar','dollars'},
            'L': {'ลิตร','l','liter','litre','liters','litres'}, 'ml': {'มิลลิลิตร','มล.','ml'},
            'kg': {'กิโลกรัม','กก.','kg'}, 'g': {'กรัม','g'}, 'm': {'เมตร','m'},
            'm/s': {'เมตร/วินาที','m/s'}}.items():
        if value in aliases:
            return canonical
    return value


def header_unit(header):
    match = re.search(r'\(([^()]*)\)\s*$', header)
    if match and (_units(match[1]) or re.search(r'บาท|THB|USD|฿|\$', match[1], re.I)):
        return match[1].strip()
    match = re.search(r'(บาท(?:/[^\s]+)?|THB|USD|฿|\$)\s*$', header, re.I)
    return match[1] if match else ''


def decimal_value(value):
    return Decimal(value.replace(',', '')) if NUMBER.fullmatch(value.strip()) else None


def quantity_bounds(value):
    scalar = decimal_value(value)
    if scalar is not None:
        return scalar, scalar
    match = re.fullmatch(r'\s*(-?\d+(?:\.\d+)?)\s*[-–]\s*(-?\d+(?:\.\d+)?)\s*', value)
    if match:
        low, high = map(Decimal, match.groups())
        return (low, high) if low <= high else None
    return None


def source_key(source):
    return source.source_file, str(source.page_number), source.content.strip()


@dataclass(frozen=True)
class Column:
    id: str
    name: str
    kind: str
    unit: str
    identity: bool
    condition: bool


@dataclass(frozen=True)
class Row:
    cells: tuple[str, ...]
    source: object
    quote: str
    header_quote: str


@dataclass(frozen=True)
class DataTable:
    id: str
    source_file: str
    source_table_id: str
    columns: tuple[Column, ...]
    rows: tuple[Row, ...]
    complete: bool

    def schema(self):
        return {'id': self.id, 'source_file': self.source_file, 'complete': self.complete,
            'pages':list(dict.fromkeys(str(r.source.page_number) for r in self.rows)),
            'columns': [{'id': c.id, 'name': c.name, 'type': c.kind, 'unit': c.unit,
                'examples': list(dict.fromkeys(r.cells[i] for r in self.rows if r.cells[i]))[:8]
                            if c.kind == 'text' else []} for i, c in enumerate(self.columns)]}


@dataclass(frozen=True)
class TableCatalog:
    tables: tuple[DataTable, ...]
    text_evidence: tuple
    source_evidence: tuple = ()

    def answer_evidence(self, *, calculation=False):
        """Calculation plans see schemas; narrative answers see unchanged sources.

        A procedure's numbers are facts (step order), not quantities to hide.
        Separate source chunks keep their own page and citation even when a
        table continues across pages. No header-only inferred joins are needed.
        """
        return self.text_evidence if calculation else self.source_evidence or self.text_evidence

    @classmethod
    def build(cls, evidence, diagnostics):
        evidence = tuple(evidence)
        available = {source_key(e): e for e in evidence}
        declarations = {}
        for diagnostic in diagnostics:
            for item in diagnostic.get('tables', []):
                key = (item.get('source_file'), item.get('table_id'))
                members = frozenset(tuple(v) for v in item.get('included_chunks', []))
                complete = bool(members and key[1] and item.get('coverage') == 'complete'
                    and item.get('total_chunks') == len(members) and members <= available.keys()
                    and not item.get('missing_pages') and not item.get('missing_chunks')
                    and not item.get('extraction_incomplete_chunks')
                    and not item.get('post_selection_dropped_chunks'))
                old = declarations.get(key)
                if old and old[0] != members:
                    complete = False
                declarations[key] = (members, complete and (old is None or old[1]))
        groups, visible = {}, []
        for source in evidence:
            parsed = parse_tables(source.content) if source.source_file and not source.url else ()
            if not parsed:
                prose='\n'.join(line for line in source.content.splitlines() if '|' not in line).strip()
                if prose:
                    visible.append(replace(source,content=prose))
                continue
            bindings = [(key, proof) for key, proof in declarations.items() if source_key(source) in proof[0]]
            for table in parsed:
                key, proof = bindings[0] if len(bindings) == 1 else (
                    (source.source_file, f'partial:{source.page_number}:{table.id}'), (frozenset(), False))
                group = groups.setdefault((key, table.headers), {'rows': [], 'complete': proof[1], 'seen': set()})
                group['complete'] &= proof[1]
                for row in table.rows:
                    if row.cells not in group['seen']:
                        group['seen'].add(row.cells)
                        group['rows'].append(Row(row.cells, source, row.raw, ' | '.join(table.headers)))
            # The model gets schema, not table facts it could re-rank itself.
            prose = '\n'.join(line for line in source.content.splitlines() if '|' not in line).strip()
            if prose:
                visible.append(replace(source, content=prose))
        result = []
        for (key, headers), group in groups.items():
            complete = group['complete'] and sum(k[0] == key for k in groups) == 1
            members = declarations.get(key, (frozenset(), False))[0]
            if any('|' in available[m].content and not parse_tables(available[m].content) for m in members if m in available):
                complete = False
            columns = []
            for i, name in enumerate(headers):
                values = [r.cells[i] for r in group['rows'] if r.cells[i].strip()]
                identity = bool(ENTITY.search(name)) and not header_unit(name)
                numeric = bool(values) and not identity and all(quantity_bounds(v) is not None for v in values)
                kind = ('decimal' if all(decimal_value(v) is not None for v in values) else 'quantity') if numeric else 'text'
                columns.append(Column(f'c{i}', name, kind, header_unit(name), identity, bool(CONDITION.search(name))))
            table_id = 'table_'+hashlib.sha256(json.dumps([key, headers], ensure_ascii=False).encode()).hexdigest()[:16]
            result.append(DataTable(table_id, key[0], key[1], tuple(columns), tuple(group['rows']), complete))
        return cls(tuple(result), tuple(visible), tuple(evidence))

    def export_sqlite(self, path):
        """Explicit, reversible read-model export. Never opens the source KB for writes."""
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb'):
            pass  # fail rather than overwrite an existing catalog
        with sqlite3.connect(path) as db:
            db.executescript('''
                CREATE TABLE source_tables (id TEXT PRIMARY KEY, source_file TEXT, source_table_id TEXT, complete INTEGER);
                CREATE TABLE source_columns (table_id TEXT, id TEXT, ordinal INTEGER, name TEXT, kind TEXT, unit TEXT);
                CREATE TABLE source_rows (table_id TEXT, row_id INTEGER, source_id TEXT, page TEXT, quote TEXT, header_quote TEXT, content_sha256 TEXT);
                CREATE TABLE source_cells (table_id TEXT, row_id INTEGER, column_id TEXT, raw_value TEXT, decimal_value TEXT, lower_bound TEXT, upper_bound TEXT);
            ''')
            for table in self.tables:
                db.execute('INSERT INTO source_tables VALUES (?,?,?,?)',(table.id,table.source_file,table.source_table_id,table.complete))
                for i,column in enumerate(table.columns):
                    db.execute('INSERT INTO source_columns VALUES (?,?,?,?,?,?)',(table.id,column.id,i,column.name,column.kind,column.unit))
                for row_id,row in enumerate(table.rows):
                    db.execute('INSERT INTO source_rows VALUES (?,?,?,?,?,?,?)',(table.id,row_id,row.source.id,str(row.source.page_number),row.quote,row.header_quote,
                        hashlib.sha256(row.source.content.encode()).hexdigest()))
                    for column,value in zip(table.columns,row.cells):
                        bounds=quantity_bounds(value) if column.kind in {'decimal','quantity'} else None
                        scalar=decimal_value(value) if bounds else None
                        db.execute('INSERT INTO source_cells VALUES (?,?,?,?,?,?,?)',(table.id,row_id,column.id,value,
                            str(scalar) if scalar is not None else None,str(bounds[0]) if bounds else None,str(bounds[1]) if bounds else None))
