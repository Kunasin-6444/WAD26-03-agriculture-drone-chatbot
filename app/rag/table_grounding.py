"""Deterministic row/cell constraints for rectangular tables in retrieved evidence.

The source content is unchanged. Coordinates identify its existing cells; values are
never repaired, rounded or inferred from model memory. This complements quote checks,
and is not a general natural-language entailment or PDF/OCR correctness guarantee.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from app.rag.claim_consistency import _ALIAS_TO_UNIT, _ALTERNATION, _NOZZLE, _WEED_CLASS, _nozzles, _units, rate_units, time_denominator

_NUMBER = r"\d+(?:,\d{3})*(?:\.\d+)?"
_QUANTITY = re.compile(rf"(?P<value>{_NUMBER})\s*(?P<unit>{_ALTERNATION})(?![a-z])", re.IGNORECASE)
_RANGE_JOINER = re.compile(r"\s*(?:-|–|~|ถึง|\+|/)\s*")


def _flat(text: str) -> str:
    text = re.sub(r"[\s|*`\u200b-\u200d\ufeff]+", "", text.replace("ํา", "ำ")).casefold()
    return re.sub(r"(?:เป็นเวลา|ระยะเวลา|นาน)(?=\d)", "", text)


def _numbers(text: str) -> set[Decimal]:
    return {Decimal(value.replace(",", "")) for value in re.findall(_NUMBER, text)}


@dataclass(frozen=True)
class TableRow:
    id: str
    cells: tuple[str, ...]
    raw: str


@dataclass(frozen=True)
class Table:
    id: str
    headers: tuple[str, ...]
    rows: tuple[TableRow, ...]


def parse_tables(content: str) -> tuple[Table, ...]:
    groups, group = [], []
    for line in content.splitlines() + [""]:
        if "|" in line:
            if re.fullmatch(r"[\s|:\-]+", line):
                continue
            cells = tuple(cell.strip() for cell in line.strip().strip("|").split("|"))
            if len(cells) >= 2:
                group.append((line.strip(), cells))
                continue
        if group:
            groups.append(group)
            group = []
    tables = []
    for group in groups:
        if len(group) < 2:
            continue
        if len({len(cells) for _, cells in group}) != 1:
            header = group[0][1]
            if not re.fullmatch(r"ลำดับ(?:ที่)?|no\.?|number|index|#", _flat(header[0])):
                continue
            aligned = [group[0]]
            for raw, cells in group[1:]:
                if (len(cells) == len(header) + 1 and not re.fullmatch(_NUMBER, _flat(cells[0]))
                        and re.fullmatch(r"\d+", cells[1])):
                    # A note outside the printed grid precedes the row number.
                    # Preserve the original raw row; align only its known cells.
                    cells = cells[1:]
                if len(cells) != len(header):
                    break
                aligned.append((raw, cells))
            if len(aligned) != len(group):
                continue  # Other ragged/multiline cells remain unstructured.
            group = aligned
        first = group[0][1]
        numeric_count = sum(bool(re.fullmatch(_NUMBER, cell)) for cell in first)
        has_header = numeric_count < len(first) / 2
        headers = first if has_header else tuple("" for _ in first)
        data = group[1:] if has_header else group
        if not data or not any(_numbers(" ".join(cells)) for _, cells in data):
            continue
        table_id = f"T{len(tables) + 1}"
        tables.append(Table(table_id, headers, tuple(TableRow(f"{table_id}:R{i}", cells, raw)
            for i, (raw, cells) in enumerate(data, 1))))
    return tuple(tables)


def _label_position(claim: str, label: str) -> int:
    key = _flat(label)
    if not key or re.fullmatch(_NUMBER, key):
        return -1
    if len(key) >= 3 and key in claim:
        return claim.index(key)
    # ISO colour translations use the same label families as the existing verifier.
    aliases = _nozzles(label)
    for match in _NOZZLE.finditer(claim):
        if _nozzles(match[0]) & aliases:
            return match.start()
    return -1


def _axis(text: str) -> str:
    text = _flat(text)
    if "ความสูง" in text or "height" in text:
        return "height"
    if any(word in text for word in ("หน้ากว้าง", "ความกว้าง", "width")):
        return "width"
    return ""


def _denominator(text: str) -> int | None:
    match = re.search(r"(?:ต่อ|/|สำหรับ|จำนวน)?(?P<count>\d+)?(?:หัวฉีด|หัว|nozzles?)", _flat(text))
    if match:
        return int(match["count"] or 1)
    return None


def _quantities(claim: str):
    matches = list(_QUANTITY.finditer(claim))
    previous_axis = ""
    for index, match in enumerate(matches):
        left = matches[index - 1].end() if index else 0
        right = matches[index + 1].start() if index + 1 < len(matches) else len(claim)
        prefix, suffix = claim[left:match.start()], claim[match.end():right]
        axis_markers = r"ความสูง|height|หน้ากว้าง|ความกว้าง|width"
        # A denominator before the NEXT measurement belongs to that measurement,
        # e.g. '2.8 m และหน้ากว้างรวม 3 หัว 4.5 m', never to the preceding 2.8.
        suffix_local = re.split(axis_markers, suffix, maxsplit=1)[0]
        prefix_local = re.split(axis_markers, prefix)[-1]
        before = list(re.finditer(r"(?:ต่อ|/|สำหรับ|รวม|per|for)(\d+)?(?:หัวฉีด|หัว|nozzles?)", prefix_local))
        denominator = _denominator(suffix_local)
        if denominator is None and before:
            denominator = int(before[-1][1] or 1)
        axis = _axis(prefix)
        if not axis and re.fullmatch(r"(?:[,;:–\-]|และ|หรือ|ถึง|กับ)*", prefix):
            axis = previous_axis  # e.g. heights 0.5 m, 1.0 m, 1.5 m
        previous_axis = axis
        yield (Decimal(match["value"].replace(",", "")), _ALIAS_TO_UNIT[match["unit"].lower()],
               axis, denominator, time_denominator(suffix_local))


def _column_aliases(header: str) -> set[str]:
    aliases = {_flat(header)}
    aliases.update(word.casefold() for word in re.findall(r"\b[A-Z][A-Z0-9]{1,}\b", header))
    core = _flat(re.sub(r"\([^)]*\)", "", header))
    if len(core) >= 4:
        aliases.add(core)
    return {alias for alias in aliases if len(alias) >= 2 and not _numbers(alias)}


def _check_columns(segment: str, table: Table, rows: list[TableRow]) -> str:
    table_numbers = _numbers(" ".join(cell for row in table.rows for cell in row.cells))
    for value, unit, axis, denominator, per_time in _quantities(segment):
        if value not in table_numbers:
            continue  # A claim can also contain facts from another table/prose block.
        columns = [index for index, header in enumerate(table.headers) if unit in _units(header)]
        if not columns:
            continue  # No declared unit means no justified column inference.
        if per_time:
            columns = [index for index in columns if (unit, per_time) in rate_units(table.headers[index])]
            if not columns:
                return f"table rate unit not supported in {table.id}"
        if axis:
            axes = [index for index in columns if _axis(table.headers[index]) == axis]
            if axes:
                columns = axes
        if denominator is not None:
            counted = [index for index in columns if _denominator(table.headers[index]) == denominator]
            if counted:
                columns = counted
            elif any(_denominator(table.headers[index]) is not None for index in columns):
                return f"table denominator not supported in {table.id}"
        if not any(value in _numbers(row.cells[index]) for row in rows for index in columns):
            return f"table value/unit/column mismatch in {table.id} ({','.join(row.id for row in rows)})"
    # Dimensionless measurements still need a column binding (MDR, RS, etc.).
    # A column name labels the number right after it (or the rest of its range "320-640"), not every
    # later number: in "อุณหภูมิ >=35°C ติดต่อกัน 3 วัน" the 3 is not a temperature (2026-10-20, dis11).
    typed_spans = [match.span("value") for match in _QUANTITY.finditer(segment)]
    previous_end, previous_columns = 0, set()
    for match in re.finditer(_NUMBER, segment):
        start, previous_end = previous_end, match.end()
        joined = previous_columns if _RANGE_JOINER.fullmatch(segment[start:match.start()]) else set()
        previous_columns = set()
        if match.span() in typed_spans or re.match(r"(?:หัวฉีด|หัว|nozzles?)", segment[match.end():]):
            continue
        value = Decimal(match[0].replace(",", ""))
        if value not in table_numbers:
            continue
        bindings = []
        for column, header in enumerate(table.headers):
            for alias in _column_aliases(header):
                found = segment.rfind(alias, start, match.start())
                if found >= 0:
                    bindings.append((found, len(alias), column))
        if bindings:
            latest = max((position, size) for position, size, _ in bindings)
            joined = {column for position, size, column in bindings if (position, size) == latest}
            # "ฝนทิ้งช่วง 1-2 สัปดาห์" copied from a text cell of the row is not the day-count column.
            quoted = _flat(segment[latest[0]:match.end()])
            if any(quoted in _flat(cell) for row in rows for cell in row.cells):
                joined = set()
        previous_columns = joined
        if joined and not any(value in _numbers(row.cells[index]) for row in rows for index in joined):
            return f"table dimensionless column mismatch in {table.id}"
    return ""


# Words people use for the "+" of a printed mixture name ("X+Y" -> "X ร่วมกับ Y"). "และ" is left
# out on purpose: it joins ordinary list items far more often than mixture components.
_MIXTURE_JOINER = r"(?:\+|ร่วมกับ|ผสมกับ|ผสม|กับ)"


def _key_pattern(flat_key: str) -> str:
    parts = [re.escape(part) for part in flat_key.split("+")]
    return _MIXTURE_JOINER.join(parts) if len(parts) > 1 and all(parts) else re.escape(flat_key)


def _row_mentions(claim: str, keyed_rows: list[tuple[str, TableRow]]) -> list[tuple[int, TableRow]]:
    """First position of each row key in the claim, ignoring hits that sit inside a longer
    row key: "เพนดิเมทาลิน" inside "เพนดิเมทาลิน+อิมาซาปิก" names the mixture row, not the
    single-substance row."""
    spans = {}
    for key, row in keyed_rows:
        flat = _flat(key)
        if len(flat) < 3:
            continue
        found = [(m.start(), m.end()) for m in re.finditer(_key_pattern(flat), claim)]
        if found:
            spans[row.id] = found
    every = [span for found in spans.values() for span in found]
    mentions = []
    for key, row in keyed_rows:
        if row.id not in spans:
            mentions.append((_label_position(claim, key), row))  # e.g. nozzle colour aliases
            continue
        free = [(start, stop) for start, stop in spans[row.id]
                if not any(o_start <= start and stop <= o_stop and o_stop - o_start > stop - start
                           for o_start, o_stop in every)]
        mentions.append((free[0][0] if free else -1, row))
    return mentions


def _without_component_explanations(claim: str, mentions: list[tuple[int, TableRow]],
                                    keys: dict[str, str]) -> list[tuple[int, TableRow]]:
    """'X+Y 120-160+12 หมายถึง X 120-160 ร่วมกับ Y 12' names X only to explain the mixture row:
    a later run of component mentions (X, and Y when Y is a row of its own) is that mixture row
    again, not the single-substance rows, when every component is named in the run's span and every
    number there belongs to the mixture — "(X 120-160 และ Y 240)" included (2026-10-20 live answer).
    'X เดี่ยว 120-160' (no Y) stays a claim about row X and is checked as one."""
    kept: list[tuple[int, TableRow]] = []
    index = 0
    while index < len(mentions):
        position, row = mentions[index]
        mixture = next((earlier for _, earlier in reversed(kept) if "+" in keys[earlier.id]), None)
        parts = [part for part in keys[mixture.id].split("+") if part] if mixture else []
        if len(parts) > 1 and keys[row.id] in parts:
            last = index
            while last + 1 < len(mentions) and keys[mentions[last + 1][1].id] in parts:
                last += 1
            end = mentions[last + 1][0] if last + 1 < len(mentions) else len(claim)
            span = claim[position:end]
            numbers = _numbers(span)
            if all(part in span for part in parts) and numbers and numbers <= _numbers(" ".join(mixture.cells)):
                index = last + 1
                continue
        kept.append((position, row))
        index += 1
    return kept


def _weed_group(flat_label: str) -> frozenset[str]:
    return frozenset(re.findall(r"แคบ|กว้าง", flat_label))


def _row_class_problem(row: TableRow, position: int, end: int, labels: list[tuple[int, frozenset[str]]]) -> str:
    """A class label must fit every row it is applied to, not just one row of the quote.

    A claim may label a list up front ("…สำหรับใบแคบ ได้แก่ A, B") or after each item
    ("A 320-640 ใบแคบ"); a row is consistent when either label equals its own class. A row
    printed as one combined class ("ใบแคบและกว้าง") is not a narrow-only row."""
    row_classes = {_weed_group(match[0]) for match in _WEED_CLASS.finditer(_flat(" ".join(row.cells)))}
    if not row_classes:
        return ""
    before = [group for label_end, group in labels if label_end <= position]
    own = [group for label_end, group in labels if position < label_end <= end]
    candidates = before[-1:] + own
    if candidates and not any(group in row_classes for group in candidates):
        return f"table weed class mismatch in {row.id}"
    return ""


_VALUE_AFTER_LABEL = re.compile(rf"(?::|=|คือ|เท่ากับ|อยู่ที่|ประมาณ)?{_NUMBER}")


def _mentions(claim: str, labels) -> list[bool]:
    """For each label named in the claim: is it directly followed by a value (an attribute name
    such as "MDR 1.2" / "อัตราส่วน 20") rather than used as the thing being described?"""
    flags = []
    for label in labels:
        position = _label_position(claim, label)
        if position >= 0:
            flags.append(bool(_VALUE_AFTER_LABEL.match(claim, position + len(_flat(label)))))
    return flags


def _entities_are_columns(claim: str, table: Table) -> bool:
    """Read the table column-wise only when the claim describes a column header ("พัดส้ม MDR 1.2")
    and does not describe a row. Naming an attribute header of a row-wise table
    ("หนอนกอลายจุด … อัตราส่วน 20 มล.") must not flip it (2026-10-20: a correct rate was rejected)."""
    if any(_units(header) for header in table.headers[1:]):
        return False
    columns = _mentions(claim, table.headers[1:])
    if not columns or all(columns):
        return False
    cells = Counter(_flat(cell) for row in table.rows for cell in row.cells)
    # A label has letters; "1.20-1.40" is a value even though it is not a single number.
    row_labels = {cell for row in table.rows for cell in row.cells
                  if len(_flat(cell)) >= 3 and re.search(r"[A-Za-zก-๙]", cell) and cells[_flat(cell)] == 1}
    rows = _mentions(claim, row_labels)
    return not rows or any(rows)


def table_inconsistency(claim: str, quotes: list[str], content: str) -> str:
    claim = _flat(claim)
    for table in parse_tables(content):
        # Some slides put entities in columns and measurements in rows. Use the
        # named entity axis, not the printed orientation, to preserve the same cells.
        if _entities_are_columns(claim, table):
            table = Table(table.id, (table.headers[0],) + tuple(row.cells[0] for row in table.rows),
                tuple(TableRow(f"{table.id}:C{i + 1}", (header,) + tuple(row.cells[i] for row in table.rows), "")
                      for i, header in enumerate(table.headers) if i > 0))
        # A stable text key identifies rows without a list of corpus-specific names: the first
        # text cell that no other row repeats in the same column, so a leading category column
        # ("แมลง/สัตว์ศัตรูพืช" on every row) does not hide the pest/disease name after it.
        column_counts = [Counter(_flat(row.cells[i]) for row in table.rows) for i in range(len(table.headers))]
        text_keys = [next((cell for i, cell in enumerate(row.cells) if len(_flat(cell)) >= 3
                           and not re.fullmatch(_NUMBER, _flat(cell)) and column_counts[i][_flat(cell)] == 1), "")
                     for row in table.rows]
        counts = Counter(_flat(key) for key in text_keys if key)
        unique = [(key, row) for key, row in zip(text_keys, table.rows) if key and counts[_flat(key)] == 1]
        mentions = sorted(((position, row) for position, row in _row_mentions(claim, unique) if position >= 0),
                          key=lambda pair: pair[0])
        mentions = _without_component_explanations(claim, mentions, dict((row.id, _flat(key)) for key, row in unique))
        if mentions:
            table_numbers = _numbers(" ".join(cell for row in table.rows for cell in row.cells))
            header_numbers = _numbers(" ".join(table.headers))
            labels = [(match.end(), _weed_group(match[0])) for match in _WEED_CLASS.finditer(claim)]
            for index, (position, row) in enumerate(mentions):
                start = position if index else 0
                end = mentions[index + 1][0] if index + 1 < len(mentions) else len(claim)
                segment = claim[start:end]
                problem = _row_class_problem(row, position, end, labels)
                if problem:
                    return problem
                allowed = _numbers(" ".join(row.cells)) | header_numbers
                if (_numbers(segment) & table_numbers) - allowed:
                    return f"table row mismatch in {row.id}"
                problem = _check_columns(segment, table, [row])
                if problem:
                    return problem
            continue

        # Numerical first-column keys are axes, e.g. height -> spray width.
        first_axis = _axis(table.headers[0])
        quantities = list(_quantities(claim))
        matches = list(_QUANTITY.finditer(claim))
        selectors = [(match.start(), value) for match, (value, _, axis, _, _) in zip(matches, quantities)
                     if first_axis and axis == first_axis]
        if selectors:
            if not {value for _, value in selectors} <= _numbers(" ".join(row.cells[0] for row in table.rows)):
                return f"table selector not present in {table.id}"
            for index, (position, value) in enumerate(selectors):
                rows = [row for row in table.rows if value in _numbers(row.cells[0])]
                start = position if index else 0
                end = selectors[index + 1][0] if index + 1 < len(selectors) else len(claim)
                segment = claim[start:end]
                allowed = _numbers(" ".join(cell for row in rows for cell in row.cells)) | _numbers(" ".join(table.headers))
                all_numbers = _numbers(" ".join(cell for row in table.rows for cell in row.cells))
                if (_numbers(segment) & all_numbers) - allowed:
                    return f"table numeric row mismatch in {table.id}"
                problem = _check_columns(segment, table, rows)
                if problem:
                    return problem
    return ""
