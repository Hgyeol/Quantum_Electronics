"""
quant 패키지: 퀀트 엔진 + 5개 신호 모듈.

임포트 시 프로젝트 루트와 tools/strategy 경로를 sys.path 에 추가한다.
"""

import sys
import os

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_STRATEGY_ROOT = os.path.join(_PROJECT_ROOT, "tools", "strategy")

for _p in [_PROJECT_ROOT, _STRATEGY_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from quant.models import QuantSignal
from quant.engine import QuantEngine

__all__ = ["QuantSignal", "QuantEngine"]
