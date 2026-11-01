"""One parameterized query executor for typed source tables.

The model supplies a validated plan, never executable SQL. Numeric comparisons
use Decimal collation; returned values/units/conditions keep their original rows.
"""
from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal
import json
import re
import sqlite3

from app.rag.candidate.models import CandidateResponse
from app.rag.evidence import ABSTAIN_MESSAGE, parse_grounded_result, render_grounded_answer
from app.rag.structured_tables import canonical_unit, decimal_value, quantity_bounds
from app.rag.claim_consistency import emergence_states, _crops, _flat


class QueryError(ValueError):
    pass


def quantity_compare(raw, op, requested):
    bounds=quantity_bounds(raw) if raw else None
    if bounds is None:
        return None
    low,high=bounds; value=Decimal(requested)
    if op in {'eq','ne'}:
        answer=True if low==high==value else False if value<low or value>high else None
        return not answer if op=='ne' and answer is not None else answer
    if op=='lt':return True if high<value else False if low>=value else None
    if op=='lte':return True if high<=value else False if low>value else None
    if op=='gt':return True if low>value else False if high<=value else None
    if op=='gte':return True if low>=value else False if high<value else None
    raise QueryError('Unsupported quantity operator')


def execute(catalog, plan):
    allowed = {'action','table_id','operation','column','order','limit','select','filters','unsupported_aspects'}
    if not isinstance(plan, dict) or set(plan) - allowed:
        raise QueryError('Unknown query fields')
    if not isinstance(plan.get('unsupported_aspects',[]),list) or plan.get('unsupported_aspects'):
        raise QueryError('Question contains an unsupported condition')
    table = next((t for t in catalog.tables if t.id == plan.get('table_id')), None)
    if table is None:
        raise QueryError('Unknown source table')
    columns = {c.id: (i, c) for i, c in enumerate(table.columns)}
    operation = plan.get('operation')
    if not isinstance(operation,str) or operation not in {'min','max','rank','select'}:
        raise QueryError('Unsupported operation')
    if operation != 'select' and not table.complete:
        raise QueryError('A global comparison requires a complete table')
    measure = plan.get('column')
    if measure is not None and not isinstance(measure,str):
        raise QueryError('Invalid comparison column')
    if measure is not None and measure not in columns:
        raise QueryError('Unknown comparison column')
    if operation != 'select' and (measure not in columns or columns[measure][1].kind not in {'decimal','quantity'}):
        raise QueryError('Comparison requires an unambiguous numeric column')
    if operation == 'select' and measure is not None and columns[measure][1].kind != 'decimal':
        raise QueryError('Ordered lookup requires an exact numeric column')
    limit = plan.get('limit', 20 if operation == 'select' else 1)
    if type(limit) is not int or not 1 <= limit <= 20:
        raise QueryError('Result limit must be an integer between1and20')
    if operation in {'min','max'} and limit != 1:
        raise QueryError('Use rank for multiple ordered results')
    order = plan.get('order', 'asc')
    if not isinstance(order,str) or order not in {'asc','desc'}:
        raise QueryError('Invalid order')
    selected = plan.get('select', [])
    if not isinstance(selected, list) or any(not isinstance(c,str) or c not in columns for c in selected):
        raise QueryError('Unknown projection column')
    if operation == 'select' and not selected:
        raise QueryError('Row lookup needs explicit requested fields')
    primary = next((c.id for c in table.columns if re.search(r'รุ่น|model',c.name,re.I)),
                   next((c.id for c in table.columns if c.identity),table.columns[0].id))
    identity_columns=[c.id for c in table.columns if re.search(r'บริษัท|ยี่ห้อ|company|brand',c.name,re.I)] + [primary]
    projection = list(dict.fromkeys(identity_columns + selected
        + ([measure] if measure in columns else []) + [c.id for c in table.columns if c.condition]))
    filters = plan.get('filters', [])
    if not isinstance(filters, list) or len(filters) > 8:
        raise QueryError('Invalid filters')
    clauses, parameters, bound_filters = [], [], []
    for predicate in filters:
        if not isinstance(predicate, dict) or set(predicate) - {'column','op','value','unit'}:
            raise QueryError('Invalid filter structure')
        column, op, value = predicate.get('column'), predicate.get('op'), predicate.get('value')
        if (not isinstance(column,str) or column not in columns or not isinstance(op,str)
                or op not in {'eq','ne','lt','lte','gt','gte','contains'} or not isinstance(value, str) or len(value)>500):
            raise QueryError('Unknown filter column/operator/value')
        _, spec = columns[column]
        if not isinstance(predicate.get('unit',''),str):
            raise QueryError('Invalid filter unit')
        if spec.kind in {'decimal','quantity'}:
            if canonical_unit(predicate.get('unit', '')) != canonical_unit(spec.unit):
                raise QueryError('Filter unit does not match source column; no implicit conversion')
            number = decimal_value(value)
            if number is None or op == 'contains':
                raise QueryError('Numeric filter needs a single explicit number')
            value = str(number)
        elif op not in {'eq','ne','contains'} or predicate.get('unit'):
            raise QueryError('Text column cannot be compared as a quantity')
        bound_filters.append((columns[column][0],spec,op,value))
        if spec.kind=='quantity':
            clauses.append(f'quantity_cmp({column}, ?, ?) = 1')
            parameters.extend([op,value])
            continue
        if op == 'contains':
            clauses.append(f'literal_contains({column}, ?)')
        else:
            symbol = {'eq':'=','ne':'!=','lt':'<','lte':'<=','gt':'>','gte':'>='}[op]
            collation = 'DECIMAL' if spec.kind == 'decimal' else 'CASEFOLD'
            clauses.append(f'{column} COLLATE {collation} {symbol} ?')
        parameters.append(value)
    projection=list(dict.fromkeys(projection+[table.columns[i].id for i,_,_,_ in bound_filters]))
    for row in table.rows:
        outcomes=[]
        for index,spec,op,value in bound_filters:
            raw=row.cells[index]
            if spec.kind in {'decimal','quantity'}:
                outcomes.append(quantity_compare(raw,op,value))
            elif not raw.strip():
                outcomes.append(None)
            else:
                match=value.casefold() in raw.casefold() if op=='contains' else value.casefold()==raw.casefold()
                outcomes.append(not match if op=='ne' else match)
        if False not in outcomes and None in outcomes:
            raise QueryError('Source interval or missing value leaves the requested filter ambiguous')
    with sqlite3.connect(':memory:') as db:
        db.create_collation('DECIMAL', lambda a, b: (Decimal(a) > Decimal(b)) - (Decimal(a) < Decimal(b)))
        db.create_collation('CASEFOLD', lambda a, b: (a.casefold() > b.casefold()) - (a.casefold() < b.casefold()))
        db.create_function('literal_contains', 2, lambda a, b: a is not None and b.casefold() in a.casefold())
        db.create_function('quantity_cmp',3,quantity_compare)
        db.execute('CREATE TABLE source_rows (row_id INTEGER PRIMARY KEY, '+', '.join(c.id+' TEXT' for c in table.columns)+')')
        for i, row in enumerate(table.rows):
            values = [str(decimal_value(v)) if c.kind == 'decimal' and v.strip() else None if c.kind == 'decimal' else v
                      for c, v in zip(table.columns, row.cells)]
            db.execute('INSERT INTO source_rows VALUES ('+','.join('?' for _ in range(len(values)+1))+')', [i]+values)
        where = ' WHERE '+' AND '.join(clauses) if clauses else ''
        eligible = [r[0] for r in db.execute('SELECT row_id FROM source_rows'+where, parameters)]
        if operation != 'select':
            i = columns[measure][0]
            if any(not table.rows[r].cells[i].strip() for r in eligible):
                raise QueryError('Missing comparison values in eligible rows')
            if any(decimal_value(table.rows[r].cells[i]) is None for r in eligible):
                raise QueryError('An interval cannot be ranked as one exact value')
            identities = {}
            for r in eligible:
                cells = table.rows[r].cells
                # A model/brand remains the same entity even if another spec was
                # changed between source rows. Other specs cannot hide a price conflict.
                key = tuple(cells[columns[c][0]].casefold() for c in identity_columns)
                number = decimal_value(cells[i])
                if key in identities and identities[key] != number:
                    raise QueryError('Conflicting values for the same source entity')
                identities[key] = number
        direction = 'ASC' if operation == 'min' else 'DESC' if operation == 'max' else order.upper()
        if operation == 'select' and measure is not None and any(
                not table.rows[r].cells[columns[measure][0]].strip() for r in eligible):
            raise QueryError('Missing ordering values in eligible rows')
        sort = f' ORDER BY {measure} COLLATE DECIMAL {direction}, row_id' if measure is not None else ' ORDER BY row_id'
        sql = 'SELECT row_id FROM source_rows'+where+sort
        ordered = [r[0] for r in db.execute(sql, parameters)]
    chosen = ordered[:limit]
    if operation != 'select' and chosen:
        index = columns[measure][0]
        boundary = decimal_value(table.rows[chosen[-1]].cells[index])
        chosen.extend(r for r in ordered[limit:] if decimal_value(table.rows[r].cells[index]) == boundary)
    if len(chosen) > 20:
        raise QueryError('Too many tied rows for one bounded answer')
    return table, [table.rows[i] for i in chosen], projection, {
        'stage':'table_query','operation':operation,'table_id':table.id,'source_table_id':table.source_table_id,
        'source_file':table.source_file,'scope_complete':table.complete,'source_rows':len(table.rows),
        'eligible_rows':len(eligible),'result_rows':len(chosen),'truncated':len(chosen)<len(ordered),
        'sql':sql,'parameters':parameters,'llm_answer_calls':0}


def render_result(question, catalog, plan, evidence):
    try:
        table, rows, projection, event = execute(catalog, plan)
        if not rows:
            raise QueryError('No source row satisfies all requested filters')
        claims, missing = [], []
        requested_crop = _crops(_flat(question))
        for row in rows:
            if requested_crop and _crops(_flat(row.quote)) and not requested_crop & _crops(_flat(row.quote)):
                raise QueryError('Returned row is for another crop')
            fields = []
            for column, value in zip(table.columns, row.cells):
                if column.id not in projection:
                    continue
                if not value.strip():
                    raise QueryError('A requested field has no verified value')
                label = re.sub(r'\s*\([^)]*\)\s*$', '', column.name).strip() if column.unit else column.name
                rendered = value+(' '+column.unit if column.unit else '')
                # Printed component lists stay aligned; no rate is calculated.
                names = row.cells[next((i for i,c in enumerate(table.columns) if c.identity), 0)].split('+')
                amounts = value.split('+')
                if column.unit and len(names) == len(amounts) > 1 and all(re.fullmatch(r'\d+(?:[-–]\d+)?', a.strip()) for a in amounts):
                    rendered += ' ('+'; '.join(n.strip()+' '+v.strip()+' '+column.unit for n,v in zip(names,amounts))+')'
                field = label+': '+rendered
                if column.condition and re.search(r'ห้าม|prohibit', value, re.I):
                    fields.insert(0, field)
                else:
                    fields.append(field)
            text = '; '.join(fields)
            if len(text) > 390 or len(row.quote)>800 or len(row.header_quote)>800:
                raise QueryError('Requested row fields exceed one grounded answer')
            claims.append({'text':text,'evidence':[{'source_id':row.source.id,'quote':row.header_quote},
                {'source_id':row.source.id,'quote':row.quote}]})
            phase = emergence_states(row.quote)
            missing.extend(f'แถวนี้ยังไม่ยืนยันการใช้{p}{s}งอก' for p,s in emergence_states(question)-phase)
        if not table.complete:
            missing.append('ข้อมูลนี้มาจากส่วนตารางที่ค้นได้ ยังไม่ยืนยันว่าครบทั้งตาราง')
        if event['operation']=='select' and event['truncated']:
            missing.append('ยังแสดงไม่ครบทุกแถวที่ตรงเงื่อนไข')
        raw = json.dumps({'status':'partial' if missing else 'sufficient','intro':'','reason':'Validated structured table query',
            'claims':claims,'missing_aspects':list(dict.fromkeys(missing))},ensure_ascii=False)
        checked = parse_grounded_result(raw,evidence,max_claims=32,allow_weed_subset=True,max_body_chars=3200)
        if len(checked.claims)!=len(claims) or checked.status=='insufficient':
            raise QueryError('Computed source rows failed grounding: '+checked.reason)
        heading={'min':'ค่าต่ำสุดจากตาราง','max':'ค่าสูงสุดจากตาราง',
                 'rank':'รายการเรียงจากค่าน้อยไปมาก' if plan.get('order','asc')=='asc' else 'รายการเรียงจากค่ามากไปน้อย',
                 'select':'ข้อมูลที่ตรงเงื่อนไข'}[event['operation']]
        rendered = render_grounded_answer(checked,evidence)
        if rendered == ABSTAIN_MESSAGE:
            raise QueryError('Rendered source rows exceed bounded delivery size')
        result = CandidateResponse(heading+'\n'+rendered,'knowledge_base','EXPERIMENTAL',
            'Structured query over original source rows',citation_checks_passed=True,diagnostics=[event])
        by_id={e.id:e for e in evidence}
        result.evidence_trace=[{'text':c.text,'evidence':[{'source_id':sid,'quote':q,'citation':by_id[sid].citation,
            'source_file':by_id[sid].source_file,'page_number':by_id[sid].page_number} for sid,q in c.quotes]} for c in checked.claims]
        result.missing_aspect='; '.join(dict.fromkeys(missing))
        return result
    except (QueryError,ValueError) as exc:
        return CandidateResponse('ยังยืนยันผลจากตารางตามเงื่อนไขที่ถามไม่ได้ครับ เพราะข้อมูล ขอบเขต หรือหน่วยที่ใช้เปรียบเทียบยังไม่ชัดเจน',
            'abstain','EXPERIMENTAL',str(exc),diagnostics=[{'stage':'table_query','status':'not_verified','reason':str(exc)}])
