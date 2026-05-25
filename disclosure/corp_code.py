from pathlib import Path

import pandas as pd

from util.util import dart

# 이 파일은 전자공시(DART) corp_code <-> stock_code 매핑 전용입니다.
# 프로젝트 루트의 kospi.csv (KRX 시스템데이터센터 상세 데이터)와 별개이므로
# 출력은 항상 이 스크립트와 같은 disclosure/ 디렉터리에 저장합니다.
OUT_DIR = Path(__file__).resolve().parent

corp_list = dart.get_corp_list()

listed = [c for c in corp_list.corps if c.stock_code]
df_listed = pd.DataFrame([c._info for c in listed])

# corp_cls: Y=코스피, K=코스닥, N=코넥스
columns = ['corp_code', 'corp_name', 'stock_code']

kospi = df_listed[df_listed['corp_cls'] == 'Y'][columns].reset_index(drop=True)
kosdaq = df_listed[df_listed['corp_cls'] == 'K'][columns].reset_index(drop=True)

print(f"코스피: {len(kospi)}개")
print(kospi)
print(f"코스닥: {len(kosdaq)}개")
print(kosdaq)

kospi.to_csv(OUT_DIR / 'kospi.csv', encoding='utf-8-sig')
kosdaq.to_csv(OUT_DIR / 'kosdaq.csv', encoding='utf-8-sig')