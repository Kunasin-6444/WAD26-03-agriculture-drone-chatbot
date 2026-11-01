"""Empty source cells must preserve coordinates; never repair unknown values."""
from app.rag.table_grounding import parse_tables


def test_empty_final_cells_do_not_drop_other_rows_or_shift_columns():
    text=('Step | Type | Example | Note\n'
          '3 | Oil | Sample | After water\n'
          '4 | Nutrient | Sample | Near end\n'
          '5 | Other |  | \n'
          '6 | Adjuvant | Label | Add last')
    tables=parse_tables(text)
    assert len(tables)==1
    assert len(tables[0].headers)==4 and len(tables[0].rows)==4
    assert tables[0].rows[2].cells==('5','Other','','')
    assert tables[0].rows[3].cells==('6','Adjuvant','Label','Add last')
    assert tables[0].rows[2].raw=='5 | Other |  |'


def test_empty_leading_row_label_stays_aligned_with_the_header():
    table=parse_tables('System | Interval | Action\nMotor | 10 | Inspect\n | 20 | Clean')[0]
    assert table.rows[1].cells==('','20','Clean')


def test_markdown_outer_pipes_do_not_remove_a_genuine_inner_empty_cell():
    table=parse_tables('| Step | Type | Note |\n| 1 | Powder | |\n| 2 | Liquid | After powder |')[0]
    assert table.headers==('Step','Type','Note')
    assert table.rows[0].cells==('1','Powder','')


def test_genuine_extra_cell_still_cannot_be_assigned_to_a_different_header():
    assert parse_tables('Model | Amount\nAlpha | 250 | Unexplained extra cell')==()
