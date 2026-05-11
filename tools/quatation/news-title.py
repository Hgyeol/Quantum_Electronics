"""
Created on 20260511
"""

import sys
import logging

import pandas as pd

sys.path.extend(['../..', '.'])
import kis_auth as ka
from langchain.tools import tool

logging.basicConfig(level=logging.INFO)

##############################################################################################
# [국내주식] 업종/기타 > 종합 시황/공시(제목)[국내주식-141]
##############################################################################################

API_URL = "/uapi/domestic-stock/v1/quotations/news-title"


@tool
def news_title(
    fid_news_ofer_entp_code: str = "",   # 뉴스제공업체코드
    fid_cond_mrkt_cls_code: str = "",    # 조건시장구분코드
    fid_input_iscd: str = "",            # 입력종목코드
    fid_titl_cntt: str = "",             # 제목내용
    fid_input_date_1: str = "",          # 입력일자
    fid_input_hour_1: str = "",          # 입력시간
    fid_rank_sort_cls_code: str = "",    # 순위정렬구분코드
    fid_input_srno: str = ""             # 입력일련번호
) -> pd.DataFrame:
    """
    종합 시황/공시(제목) API입니다.

    한국투자 Open API에서는 공시/시황의 제목 정보만 제공하며,
    본문 전문은 제공되지 않습니다.

    Args:
        fid_news_ofer_entp_code (str): 뉴스제공업체코드
        fid_cond_mrkt_cls_code (str): 조건시장구분코드
        fid_input_iscd (str): 입력종목코드
        fid_titl_cntt (str): 제목내용
        fid_input_date_1 (str): 입력일자, YYYYMMDD
        fid_input_hour_1 (str): 입력시간, HHMMSS
        fid_rank_sort_cls_code (str): 순위정렬구분코드
        fid_input_srno (str): 입력일련번호

    Returns:
        pd.DataFrame: 종합 시황/공시 제목 데이터

    Example:
        >>> df = news_title(fid_input_iscd="005930")
        >>> print(df)
    """

    tr_id = "FHKST01011800"

    params = {
        "FID_NEWS_OFER_ENTP_CODE": fid_news_ofer_entp_code,
        "FID_COND_MRKT_CLS_CODE": fid_cond_mrkt_cls_code,
        "FID_INPUT_ISCD": fid_input_iscd,
        "FID_TITL_CNTT": fid_titl_cntt,
        "FID_INPUT_DATE_1": fid_input_date_1,
        "FID_INPUT_HOUR_1": fid_input_hour_1,
        "FID_RANK_SORT_CLS_CODE": fid_rank_sort_cls_code,
        "FID_INPUT_SRNO": fid_input_srno
    }

    res = ka._url_fetch(API_URL, tr_id, "", params)

    if res.isOK():
        return pd.DataFrame(res.getBody().output)
    else:
        res.printError(url=API_URL)
        return pd.DataFrame()