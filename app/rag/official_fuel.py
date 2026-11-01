"""Public Bangchak widget data, with explicit retailer, date, units and scope.

The widget itself loads FEED_URL. No generated price, browser execution,
credentials, search credits or language-model calls are involved.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import json
import re
import time

import requests

from app.rag.candidate.models import CandidateResponse
from app.rag.evidence import Evidence, parse_grounded_result, render_grounded_answer

WIDGET_URL = 'https://oil-price.bangchak.co.th/BcpOilPrice1/th'
FEED_URL = 'https://oil-price.bangchak.co.th/apioilprice2/th'


class SourceDataError(ValueError):
    pass


def matches(question):
    q=question.casefold()
    if not ('ราคา' in q or 'price' in q):return False
    if not any(t in q for t in ('น้ำมัน','ดีเซล','แก๊สโซฮอล์','เบนซิน','diesel','fuel')):return False
    if any(t in q for t in ('ย้อนหลัง','เดือนที่แล้ว','ปีที่แล้ว','สัปดาห์ที่แล้ว','เมื่อวาน','พรุ่งนี้',
                            'historical','history','yesterday','tomorrow','last month','เฉลี่ย','average',
                            'ทั่วประเทศ','น้ำมันเครื่อง','น้ำมันเกียร์','น้ำมันไฮดรอลิก')):return False
    if re.search(r'\d{1,2}/\d{1,2}/\d{2,4}',q):return False
    if 'จังหวัด' in q and not any(t in q for t in ('กรุงเทพ','กทม')):return False
    # This source may not stand in for a specifically requested different retailer.
    return not any(t in q for t in ('ปตท','pttor','ptt','shell','เชลล์','esso','เอสโซ่','caltex','คาลเท็กซ์','susco','ซัสโก้'))


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.parts=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.skip+=1
    def handle_endtag(self,tag):
        if tag in ('script','style') and self.skip:self.skip-=1
    def handle_data(self,data):
        if not self.skip:self.parts.append(data)


def plain(value):
    parser=_Text();parser.feed(str(value or ''));return ' '.join(' '.join(parser.parts).split())


def parse_prices(page, payload, question, *, today=None):
    today=today or datetime.now(timezone(timedelta(hours=7))).date()
    if '/apioilprice2/th' not in page.lower() or 'บาท/ลิตร' not in plain(page):
        raise SourceDataError('Widget unit/feed contract changed')
    if not isinstance(payload,list) or len(payload)!=1 or not isinstance(payload[0],dict):
        raise SourceDataError('Ambiguous official price record')
    data=payload[0]
    try:
        day,month,year=map(int,data['OilDateNow'].split('/'))
        if year>=2400:year-=543
        shown=datetime(year,month,day).date()
    except (KeyError,ValueError,TypeError):
        raise SourceDataError('Official display date is missing or invalid') from None
    if shown!=today:
        raise SourceDataError('Official display date is not today; current price not verified')
    try:items=json.loads(data['OilList']) if isinstance(data.get('OilList'),str) else data['OilList']
    except (KeyError,ValueError,TypeError):raise SourceDataError('Invalid fuel list') from None
    if not isinstance(items,list):raise SourceDataError('Invalid fuel list')
    q=question.casefold()
    family='ดีเซล' if 'ดีเซล' in q or 'diesel' in q else 'แก๊สโซฮอล์' if 'แก๊สโซฮอล์' in q else 'เบนซิน' if 'เบนซิน' in q else ''
    grades=re.findall(r'(?<![a-z0-9])(?:b|e)\d+(?![a-z0-9])',q)
    result=[]
    for item in items:
        if not isinstance(item,dict):raise SourceDataError('Invalid fuel item')
        name=plain(item.get('OilName'))
        if family and family not in name:continue
        if grades and not any(g in name.casefold().replace(' ','') for g in grades):continue
        try:
            if isinstance(item.get('PriceToday'),bool):raise InvalidOperation
            price=Decimal(str(item['PriceToday']))
            if not price.is_finite() or price<=0 or price.as_tuple().exponent < -2:raise InvalidOperation
        except (KeyError,InvalidOperation):raise SourceDataError('Invalid or overprecise price') from None
        if not name or len(name)>100 or '|' in name:raise SourceDataError('Invalid fuel name')
        result.append((name,format(price,'.2f')))
    if not result:raise SourceDataError('Requested fuel grade is not explicitly listed')
    if len({name for name,_ in result})!=len(result):raise SourceDataError('Duplicate fuel grade')
    remark,effective=plain(data.get('OilRemark')),plain(data.get('OilRemark2'))
    if not remark or not effective:raise SourceDataError('Price applicability or effective date is missing')
    return {'date':data['OilDateNow'],'effective':effective,'scope':remark,'prices':result}


def read_prices(question, *, deadline=None, http_get=None, today=None):
    get=http_get or requests.get
    records=[]
    for url in (WIDGET_URL,FEED_URL):
        remaining=deadline-time.monotonic() if deadline else 6
        if remaining<=0.2:raise TimeoutError('Official price read budget exhausted')
        response=get(url,timeout=min(6,remaining),allow_redirects=False)
        response.raise_for_status()
        if response.status_code!=200 or len(response.content)>250000:
            raise SourceDataError('Unexpected official response')
        records.append(response)
    return parse_prices(records[0].text,records[1].json(),question,today=today)


def render_prices(data):
    units='หัวตารางราคาน้ำมันบางจาก: ชนิดน้ำมัน | บาท/ลิตร'
    date_line='OilDateNow: '+data['date']
    effective='OilRemark2: '+data['effective']
    scope='OilRemark: '+data['scope']
    price_lines=[name+' | '+price for name,price in data['prices']]
    evidence=[Evidence('W1',units,url=WIDGET_URL,title='ตารางราคาน้ำมันบางจาก'),
              Evidence('W2','\n'.join([date_line,effective,scope,'OilName | PriceToday',*price_lines]),
                       url=FEED_URL,title='ข้อมูลราคาน้ำมันบางจากจากต้นทาง')]
    claims=[]
    for (name,price),quote in zip(data['prices'],price_lines):
        claims.append({'text':f'{name} ราคา {price} บาท/ลิตร','evidence':[
            {'source_id':'W2','quote':quote},{'source_id':'W1','quote':units}]})
    claims.extend([
        {'text':'ข้อมูลบางจากแสดงวันที่ '+data['date'],'evidence':[{'source_id':'W2','quote':date_line}]},
        {'text':data['effective'],'evidence':[{'source_id':'W2','quote':effective}]},
        {'text':data['scope'],'evidence':[{'source_id':'W2','quote':scope}]},
    ])
    raw=json.dumps({'status':'sufficient','reason':'Official structured source; no LLM generation',
                    'intro':'','claims':claims},ensure_ascii=False)
    checked=parse_grounded_result(raw,evidence,max_claims=32)
    if checked.status!='sufficient' or len(checked.claims)!=len(claims):
        raise SourceDataError('Official price fields failed grounding')
    result=CandidateResponse('ราคาบางจาก\n'+render_grounded_answer(checked,evidence),'web_fallback','EXPERIMENTAL',
        'Official structured price data; no LLM',generation_succeeded=False,citation_checks_passed=True,
        pre_selection_evidence=[vars(e) for e in evidence],post_selection_evidence=[vars(e) for e in evidence],
        diagnostics=[{'stage':'official_fuel_source','retailer':'Bangchak','http_reads':2,'llm_calls':0}])
    by_id={e.id:e for e in evidence}
    result.evidence_trace=[{'text':c.text,'evidence':[{'source_id':sid,'quote':quote,
        'url':by_id[sid].url,'citation':by_id[sid].citation} for sid,quote in c.quotes]} for c in checked.claims]
    return result
