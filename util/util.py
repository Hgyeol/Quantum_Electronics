import dart_fss as dart
import os
from dotenv import load_dotenv

load_dotenv()
CRTFC_KEY= os.getenv('DISCLOSURE_CRTFC_KEY')

dart.set_api_key(CRTFC_KEY)