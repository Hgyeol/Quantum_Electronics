"""
quant 패키지: 퀀트 엔진 + 5개 신호 모듈.

임포트 시 프로젝트 루트와 tools/strategy 경로를 sys.path 에 추가한다.
QuantEngine은 KIS 샘플 모듈을 참조하므로 패키지 import 단계에서 eager import하지 않는다.
"""

import sys
import os

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_STRATEGY_ROOT = os.path.join(_PROJECT_ROOT, "tools", "strategy")

for _p in [_PROJECT_ROOT, _STRATEGY_ROOT]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from quant.models import QuantSignal

__all__ = ["QuantSignal"]
