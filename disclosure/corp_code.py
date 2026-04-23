import pandas as pd

from util.util import dart

corp_list = dart.get_corp_list()

listed = [c for c in corp_list.corps if c.stock_code]
df_listed = pd.DataFrame([c._info for c in listed])

# corp_cls: Y=코스피, K=코스닥, N=코넥스
kospi = df_listed[df_listed['corp_cls'] == 'Y'][['corp_code', 'corp_name', 'stock_code']].reset_index(drop=True)

print(f"코스피: {len(kospi)}개")
print(kospi)

kospi.to_csv('kospi.csv', encoding='utf-8-sig')