"""
QuantSignal: 퀀트 엔진이 생성하는 단일 신호의 데이터 구조.

PRD §4.4 스키마를 기준으로 정의.
score 는 각 알고리즘의 가중치이며 direction 과 일치해야 한다.
  positive → score > 0
  negative → score < 0
  neutral  → score = 0
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator


class QuantSignal(BaseModel):
    label: str
    direction: Literal["positive", "negative", "neutral"]
    score: int                  # PRD 기준: 알고리즘별 가중치 (-3 ~ +3)
    value: float | None         # 실제 수치 (e.g. 이격도=103.2, 수익률=0.32)
    api_used: str               # 사용한 KIS API 이름

    @model_validator(mode="after")
    def _check_score_direction_consistency(self) -> "QuantSignal":
        if self.direction == "positive" and self.score <= 0:
            raise ValueError("positive 방향이면 score > 0 이어야 합니다.")
        if self.direction == "negative" and self.score >= 0:
            raise ValueError("negative 방향이면 score < 0 이어야 합니다.")
        if self.direction == "neutral" and self.score != 0:
            raise ValueError("neutral 방향이면 score == 0 이어야 합니다.")
        return self
