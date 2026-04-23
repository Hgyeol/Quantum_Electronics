import dart_fss as dart
import os
from dotenv import load_dotenv

load_dotenv()
CRTFC_KEY= os.getenv('DISCLOSURE_CRTFC_KEY')

dart.set_api_key(CRTFC_KEY)



corp_code = "00126380"
bgn_de = "20260101"
end_de = "20260423"
page_no: int = 1
page_count: int = 10

data = dart.api.filings.search_filings(corp_code=corp_code,bgn_de=bgn_de, end_de=end_de,page_no=page_no, page_count=page_count)

res = []
for i in data['list']:
    full_path = dart.api.filings.download_document(
        path="files",
        rcept_no=i['rcept_no']
    )
    res.append(full_path)

print(res)