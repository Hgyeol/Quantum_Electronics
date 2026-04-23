import dart_fss as dart_fss
import pandas as pd 
import os
from dotenv import load_dotenv

load_dotenv()
CRTFC_KEY= os.getenv('DISCLOSURE_CRTFC_KEY')

dart_fss.set_api_key(api_key=CRTFC_KEY)

corp_list = dart_fss.get_corp_list()

listed = [c for c in corp_list.corps if c.stock_code]
df_listed = pd.DataFrame([c._info for c in listed])

# corp_cls: Y=코스피, K=코스닥, N=코넥스
kospi = df_listed[df_listed['corp_cls'] == 'Y'][['corp_code', 'corp_name', 'stock_code']].reset_index(drop=True)

print(f"코스피: {len(kospi)}개")
print(kospi)

kospi.to_csv('kospi.csv', encoding='utf-8-sig')