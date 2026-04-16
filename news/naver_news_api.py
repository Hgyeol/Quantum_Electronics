import requests
import os
from dotenv import load_dotenv

load_dotenv()
CLIENT = os.getenv("NAVER_NEWS_API_CLIENT")
SECRET = os.getenv("NAVER_NEWS_API_SECRET")
print(CLIENT)
api = 'https://openapi.naver.com/v1/search/news.json'

headers = {
    "X-Naver-Client-Id" : CLIENT,
    "X-Naver-Client-Secret" : SECRET
}

params = {
    "query" : """“매출 2배 많은데 주가 왜 이래” 삼성전자 시총, TSMC 절반이라니…여전히 저평가, 왜? [투자360]""",
    "display" : 1,
    "sort" : "sim"
}

res = requests.get(api, headers=headers, params=params)
print(res.json())