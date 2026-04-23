import requests
import xml.etree.ElementTree as ET                                                                                                                                                     
from datetime import datetime                                                                                                                                                        
import pandas as pd 
import os
from dotenv import load_dotenv

load_dotenv()
CRTFC_KEY= os.getenv('DISCLOSURE_CRTFC_KEY')

REPORT_CODES = {
    '11013': '1분기보고서',
    '11012': '반기보고서',
    '11014': '3분기보고서',
    '11011': '사업보고서',
}

ERROR_MESSAGES = {
    '010': '등록되지 않은 키입니다.',
    '011': '사용할 수 없는 키입니다. 오픈API에 등록되었으나, 일시적으로 사용 중지된 키를 통하여 검색하는 경우 발생합니다.',
    '012': '접근할 수 없는 IP입니다.',
    '013': '조회된 데이타가 없습니다.',
    '014': '파일이 존재하지 않습니다.',
    '020': '요청 제한을 초과하였습니다.',
    '021': '조회 가능한 회사 개수가 초과하였습니다.(최대 100건)',
    '100': '필드의 부적절한 값입니다.',
    '101': '부적절한 접근입니다.',
    '800': '시스템 점검으로 인한 서비스가 중지 중입니다.',
    '900': '정의되지 않은 오류가 발생하였습니다.',
    '901': '사용자 계정의 개인정보 보유기간이 만료되어 사용할 수 없는 키입니다. 관리자 이메일(opendart@fss.or.kr)로 문의하시기 바랍니다.',
}

def fetch_financial_statements(corp_code, bsns_year, reprt_code):
    
    url = "https://opendart.fss.or.kr/api/fnlttSinglAcnt.xml"
    params = {
        'crtfc_key': CRTFC_KEY,
        'corp_code': corp_code,
        'bsns_year': bsns_year,
        'reprt_code': reprt_code,
    }

    response = requests.get(url, params=params)
    if response.status_code != 200:
        raise Exception(f"[HTTP 오류] 상태 코드: {response.status_code}")

    root = ET.fromstring(response.content)

    status = root.findtext("status")
    message = root.findtext("message")
    if status != '000':
        error_desc = ERROR_MESSAGES.get(status, '알 수 없는 오류입니다.')
        # 조회 데이터 없음은 경고만 출력
        if status == '013':
            print(f"[정보] {bsns_year}년 {REPORT_CODES[reprt_code]}: 조회된 데이터 없음.")
            return []
        raise Exception(f"[API 오류] 상태 코드: {status} - {error_desc}\n→ DART 응답 메시지: {message}")

    results = []
    for item in root.findall("list"):
        data = {
            'bsns_year': bsns_year,
            'report_type': REPORT_CODES[reprt_code],
            'rcept_no': item.findtext('rcept_no'),
            'account_nm': item.findtext('account_nm'),
            'fs_div': item.findtext('fs_div'),
            'sj_div': item.findtext('sj_div'),
            'thstrm_nm': item.findtext('thstrm_nm'),
            'thstrm_dt': item.findtext('thstrm_dt'),
            'thstrm_amount': item.findtext('thstrm_amount'),
            'frmtrm_nm': item.findtext('frmtrm_nm'),
            'frmtrm_dt': item.findtext('frmtrm_dt'),
            'frmtrm_amount': item.findtext('frmtrm_amount'),
            'currency': item.findtext('currency'),
        }
        results.append(data)

    return results

def fetch_all_reports_last_n_years(corp_code):
    current_year = datetime.now().year
    years = [str(current_year - 1), str(current_year)]
    print(f"years: {years}")
    all_data = []

    for year in years:
        for code in REPORT_CODES.keys():
            print(f"수집 중: {year}년 {REPORT_CODES[code]}")
            try:
                result = fetch_financial_statements(corp_code, year, code)
                all_data.extend(result)
            except Exception as e:
                print(f"[오류] {year}년 {REPORT_CODES[code]} - {e}")

    df = pd.DataFrame(all_data)
    return df

kospi = pd.read_csv('./kospi.csv', dtype={'corp_code': str, 'stock_code': str})
samsung = kospi[kospi['corp_name'] == '삼성전자']
corp_code = samsung['corp_code'].iloc[0]
print(corp_code)
df = fetch_all_reports_last_n_years(corp_code)
print(df)