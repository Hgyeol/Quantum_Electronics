"""CLI: 전종목 데이터 수집 → screener.db 저장.

사용법:
    python scripts/collect_screener_data.py

EC2 cron (평일 16:30, 장 마감 후):
    30 16 * * 1-5 cd /home/ubuntu/Quantum_Electronics && .venv/bin/python scripts/collect_screener_data.py >> logs/screener_collect.log 2>&1
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

from services.screener_collector import run

if __name__ == "__main__":
    run()
