from copy import deepcopy
from datetime import date
import json
from unittest.mock import Mock, patch

import pytest

from app.rag import official_fuel as fuel, support_pipeline as support

TODAY=date(2026,2,15)
PAGE='<table><th>ชนิดน้ำมัน</th><th>บาท/ลิตร</th></table><script>$.get("/apioilprice2/th")</script>'


def payload():
    return [{'OilDateNow':'15/02/2569','OilRemark':'ราคาขายปลีก กทม. ที่ยังไม่รวมภาษีบำรุงท้องถิ่น กทม.',
        'OilRemark2':'ราคามีผล ณ วันที่ 14 ก.พ. 69 เวลา 05.00 น.',
        'OilList':json.dumps([{'OilName':'ดีเซล B20','PriceToday':32.17,'PriceTomorrow':99.99},
                             {'OilName':'ดีเซลพรีเมียม','PriceToday':41.25},
                             {'OilName':'แก๊สโซฮอล์ E20','PriceToday':25.50}],ensure_ascii=False)}]


def test_exact_price_grade_display_date_effective_date_and_tax_scope_survive_grounding():
    data=fuel.parse_prices(PAGE,payload(),'ราคาน้ำมันดีเซลล่าสุด',today=TODAY)
    response=fuel.render_prices(data)
    assert response.citation_checks_passed and not response.generation_succeeded
    assert all(v in response.answer for v in ['ดีเซล B20','32.17','41.25','บาท/ลิตร','15/02/2569','14 ก.พ. 69','ไม่รวมภาษี'])
    assert '99.99' not in response.answer and '25.50' not in response.answer
    assert fuel.FEED_URL in response.answer and fuel.WIDGET_URL in response.answer


def test_no_inferred_grade_or_retailer_substitution():
    with pytest.raises(fuel.SourceDataError):
        fuel.parse_prices(PAGE,payload(),'ราคาดีเซล B7',today=TODAY)
    data=fuel.parse_prices(PAGE,payload(),'ราคาดีเซล B20',today=TODAY)
    assert data['prices']==[('ดีเซล B20','32.17')]
    assert not fuel.matches('ราคาดีเซลของ PTT')
    assert not fuel.matches('ราคาน้ำมันเชลล์ล่าสุด')
    assert fuel.matches('ราคาน้ำมันดีเซลล่าสุดจากแหล่งทางการ')


@pytest.mark.parametrize('question',['ราคาดีเซลเมื่อวาน','ราคาน้ำมันเดือนที่แล้ว','ราคาเฉลี่ยดีเซลทั่วประเทศ',
                                   'ราคาน้ำมันเครื่องล่าสุด','ราคาดีเซลวันที่ 12/02/2569','ราคาดีเซลในจังหวัดเชียงใหม่'])
def test_current_bangkok_feed_is_not_substituted_for_other_date_product_or_region(question):
    assert not fuel.matches(question)


@pytest.mark.parametrize('mutation', ['stale','future','no_scope','no_effective','negative','bool','overprecise'])
def test_incomplete_stale_or_invalid_data_cannot_be_claimed_current(mutation):
    data=deepcopy(payload())
    if mutation=='stale':data[0]['OilDateNow']='14/02/2569'
    elif mutation=='future':data[0]['OilDateNow']='16/02/2569'
    elif mutation=='no_scope':data[0]['OilRemark']=''
    elif mutation=='no_effective':data[0]['OilRemark2']=''
    else:
        items=json.loads(data[0]['OilList'])
        items[0]['PriceToday']={'negative':-1,'bool':True,'overprecise':32.175}[mutation]
        data[0]['OilList']=json.dumps(items)
    with pytest.raises(fuel.SourceDataError):fuel.parse_prices(PAGE,data,'ราคาดีเซลล่าสุด',today=TODAY)


def test_missing_widget_unit_or_feed_contract_is_not_assumed():
    with pytest.raises(fuel.SourceDataError):fuel.parse_prices('page changed',payload(),'ราคาดีเซล',today=TODAY)


def test_price_answer_bypasses_search_embedding_and_model_without_bypassing_source_validation():
    data=fuel.parse_prices(PAGE,payload(),'ราคาดีเซล',today=TODAY)
    with patch.object(fuel,'read_prices',return_value=data),patch.object(support,'call_llm') as model, \
         patch.object(support,'search_web_fallback') as search,patch.object(support,'retrieve_evidence') as kb:
        result=support.run_support_pipeline('ราคาน้ำมันดีเซลล่าสุด',source='web')
    assert result.citation_checks_passed and '32.17' in result.answer
    model.assert_not_called();search.assert_not_called();kb.assert_not_called()


def test_first_http_timeout_stops_without_a_second_request_or_fallback():
    get=Mock(side_effect=TimeoutError('synthetic'))
    with pytest.raises(TimeoutError):fuel.read_prices('ราคาดีเซล',http_get=get)
    assert get.call_count==1
    with patch.object(fuel,'read_prices',side_effect=TimeoutError('synthetic')), \
         patch.object(support,'call_llm') as model,patch.object(support,'search_web_fallback') as search:
        result=support.run_support_pipeline('ราคาดีเซลล่าสุด',source='web')
    assert result.error_code=='timeout'
    model.assert_not_called();search.assert_not_called()
