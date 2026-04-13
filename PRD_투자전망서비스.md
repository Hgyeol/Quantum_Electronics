# PRD: AI 투자 전망 서비스 (Investment Outlook Service)

**프로젝트**: Quantum Electronics
**작성일**: 2026-04-09
**버전**: 2.0

---

## 1. 개요 (Overview)

### 1.1 서비스 한 줄 요약
사용자가 정의한 퀀트 규칙(기술적 지표)과 AI의 뉴스·공시 분석을 결합해, 코스피 종목에 대한 투자 전망 리포트를 제공하는 서비스.

### 1.2 핵심 철학

```
퀀트 신호 (규칙 기반, 사용자 정의)
        +
AI 뉴스·공시 분석 (LLM)
        =
투자 전망 리포트
```

- **퀀트 규칙**: 사용자가 직접 정의. 이동평균, RSI, 이격도 등 수치 기반 시그널
- **AI 역할**: 뉴스·공시 텍스트 분석에만 집중. 퀀트 판단에는 개입하지 않음
- **전망 생성**: 두 신호를 합산해 최종 전망 산출

### 1.3 해결하려는 문제
- 퀀트 규칙만으로는 갑작스러운 공시·뉴스 이벤트를 반영하지 못함
- 뉴스·공시만으로는 기술적 흐름(추세, 과매수/과매도)을 놓침
- 두 정보를 사람이 직접 취합하는 데 시간이 걸림

---

## 2. 사용자 스토리 (User Stories)

| ID | 요청 | 기대 결과 |
|----|------|-----------|
| U1 | "삼성전자 전망 알려줘" | 퀀트 신호(이동평균·RSI·이격도) + AI 뉴스/공시 분석 → 종합 전망 |
| U2 | "오늘 코스피 시장 분위기 어때?" | 지수·업종별 퀀트 신호 + 주요 시장 뉴스 AI 요약 |
| U3 | "거래량 급증 종목 주목할 게 있어?" | 거래량 급증 퀀트 필터 + 해당 종목 최근 공시 AI 분석 |
| U4 | "배당주 추천해줘" | 배당률·신용잔고 퀀트 필터 + 관련 공시 AI 검토 |

---

## 3. 시스템 구조

```
┌─────────────────────────────────────────┐
│              사용자 질의                  │
└──────────────────┬──────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────┐
│              FastAPI (WAS)               │
└──────┬──────────────────────┬───────────┘
       │                      │
       ▼                      ▼
┌─────────────┐      ┌────────────────────┐
│  퀀트 엔진   │      │    AI 분석 엔진      │
│  (규칙 기반) │      │  (LangChain + LLM)  │
│             │      │                    │
│ KIS API로   │      │ KIS 뉴스·공시 API로  │
│ 시세 수집    │      │ 텍스트 수집 후 분석  │
│             │      │                    │
│ → 퀀트 신호  │      │ → 뉴스/공시 신호    │
└──────┬──────┘      └─────────┬──────────┘
       │                       │
       └──────────┬────────────┘
                  ▼
       ┌──────────────────────┐
       │    전망 합산 모듈      │
       │  퀀트 신호 + AI 신호  │
       │  → OutlookReport     │
       └──────────────────────┘
                  │
                  ▼
       PostgreSQL (저장) / React 대시보드
```

---

## 4. 퀀트 엔진 (사용자 정의 규칙)

### 4.1 개념
- 사용자가 규칙을 직접 정의하고, 코드로 관리
- AI는 이 판단에 개입하지 않음
- KIS API에서 수치 데이터를 수집해 규칙에 대입 → `QuantSignal` 생성

### 4.2 퀀트 신호 구성 (확정)

기술적 지표 3개 + 수급 지표 2개로 구성. 최대 quant_score 범위: **-8 ~ +8**

| # | 알고리즘 | 분류 | KIS API | score |
|---|---------|------|---------|-------|
| 1 | 골든크로스 (MA5/MA20) | 기술 | `inquire_daily_itemchartprice` | +2 / -2 / 0 |
| 2 | 이격도 (MA20 대비 현재가 %) | 기술 | `inquire_daily_itemchartprice` | +2 / -2 / 0 |
| 3 | 모멘텀 (60일 수익률) | 기술 | `inquire_daily_itemchartprice` | +1 / -1 / 0 |
| 4 | 외인 순매수 (최근 3일 누적) | 수급 | `inquire_investor` | +2 / -2 / 0 |
| 5 | 거래량 급증 (평균 대비 당일 비율) | 수급 | `volume_rank` | +1 / -1 / 0 |

### 4.3 구현 구조

기존 전략(#1~#3)은 `StrategyResult`를 반환하는 구조를 유지하고, 퀀트 엔진 레이어에서 `QuantSignal`로 변환한다. 수급 신호(#4~#5)는 `QuantSignal`을 직접 반환하도록 신규 구현한다.

```
strategy_01 (골든크로스) ──→ StrategyResult ──┐
strategy_02 (모멘텀)     ──→ StrategyResult ──┤  퀀트 엔진 레이어  ──→ QuantSignal 리스트
strategy_05 (이격도)     ──→ StrategyResult ──┘  (변환 + 신규 수집)
inquire_investor (외인)  ──────────────────────→ QuantSignal (신규)
volume_rank (거래량)     ──────────────────────→ QuantSignal (신규)
```

### 4.4 QuantSignal 스키마

```python
class QuantSignal(BaseModel):
    label: str                                        # 규칙 이름
    direction: Literal["positive", "negative", "neutral"]
    score: int                                        # 가중치 (-3 ~ +3, 사용자 정의)
    value: float | None                               # 실제 수치 (e.g. RSI=28.5)
    api_used: str                                     # 사용한 KIS API
```

---

## 5. AI 분석 엔진 (뉴스·공시)

### 5.1 개념
- LangChain + LLM이 뉴스·공시 텍스트만 분석
- 수치 데이터·퀀트 판단에는 관여하지 않음
- 분석 결과를 `AISignal`로 구조화하여 반환

### 5.2 활용 KIS API

| 데이터 | KIS API |
|--------|---------|
| 국내 종목 뉴스 | `news_title` (국내주식 업종/기타) |
| 시장 전체 뉴스 | `exp_index_trend` 연관 뉴스 |

> **공시**: KIS API에서 공시 원문 미지원 → DART Open API 연동으로 보완 (v1.1)

### 5.3 AI 분석 프롬프트 구조

```
[시스템]
너는 주식 뉴스·공시를 분석해 투자 영향도를 판단하는 전문가야.
수치 데이터나 기술적 지표 판단은 하지 마.
뉴스·공시 텍스트만 보고 해당 종목에 긍정/부정/중립 영향인지 판단해.

[입력]
종목: {종목명}
뉴스/공시 목록: {texts}

[출력]
AISignal 리스트 (JSON)
```

### 5.4 AISignal 스키마

```python
class AISignal(BaseModel):
    source: Literal["뉴스", "공시"]
    title: str                                        # 뉴스/공시 제목
    summary: str                                      # AI 요약 (1~2문장)
    direction: Literal["positive", "negative", "neutral"]
    score: int                                        # -2 ~ +2
    reason: str                                       # 판단 근거
```

---

## 6. 전망 합산 모듈

### 6.1 합산 방식

```python
def combine_signals(
    quant_signals: list[QuantSignal],
    ai_signals: list[AISignal],
    quant_weight: float = 0.6,   # 퀀트 비중 (사용자 조정 가능)
    ai_weight: float = 0.4,      # AI 비중 (사용자 조정 가능)
) -> OutlookReport:
    quant_score = sum(s.score for s in quant_signals) * quant_weight
    ai_score    = sum(s.score for s in ai_signals)    * ai_weight
    total_score = quant_score + ai_score
    ...
```

### 6.2 OutlookReport 스키마

```python
class OutlookReport(BaseModel):
    subject: str                          # 종목명 or 시장
    summary: str                          # 전망 한 줄 요약
    outlook: Literal["긍정", "중립", "부정"]
    total_score: float                    # 최종 합산 점수
    quant_score: float                    # 퀀트 점수
    ai_score: float                       # AI 점수
    quant_signals: list[QuantSignal]      # 퀀트 시그널 상세
    ai_signals: list[AISignal]            # 뉴스/공시 시그널 상세
    generated_at: datetime
```

---

## 7. API 엔드포인트 (FastAPI)

| Method | Path | 설명 |
|--------|------|------|
| POST | `/outlook/query` | 자연어 질의 → 전망 리포트 반환 |
| GET | `/outlook/market` | 오늘의 코스피 시장 개요 |
| GET | `/outlook/stock/{code}` | 특정 종목 전망 리포트 |
| GET | `/outlook/history` | 과거 전망 리포트 조회 |
| GET/PUT | `/rules` | 퀀트 규칙 조회·수정 |

---

## 8. 데이터 흐름 예시

**질의**: "삼성전자 전망 알려줘"

```
1. 퀀트 엔진
   - inquire_daily_itemchartprice("005930") → OHLCV 수집
   - 규칙 적용:
     · MA 골든크로스   → positive  +1
     · RSI 45 (중립)   → neutral    0
     · 이격도 103 (약 과매수) → negative -1
     · 외인 3일 순매수  → positive  +2
   - quant_score = +2

2. AI 분석 엔진
   - news_title("005930") → 뉴스 3건 수집
   - LLM 분석:
     · "삼성전자, HBM4 양산 확정" → positive +2
     · "반도체 수출 규제 우려 확산" → negative -1
   - ai_score = +1

3. 합산
   - total_score = 2×0.6 + 1×0.4 = 1.6 → "긍정"

4. OutlookReport 반환
   - summary: "외인 매수 지속·HBM4 호재로 긍정적. 이격도 과매수 구간 주의."
   - outlook: "긍정"
   - quant_signals: [MA골든크로스(+), 외인순매수(+), 이격도과매수(-)]
   - ai_signals: [HBM4 양산 확정(+), 수출 규제 우려(-)]
```

---

## 9. 비기능 요구사항

| 항목 | 목표 |
|------|------|
| 응답 시간 | 15초 이내 |
| KIS API 캐시 | Redis TTL 60초 |
| 리포트 저장 | PostgreSQL, 30일 보관 |
| 투명성 | 퀀트·AI 신호를 항상 분리해서 노출 |
| 면책 고지 | 투자 판단 보조 도구. 투자 손실 책임은 사용자에게 있음 |

---

## 10. 개발 단계 (Roadmap)

| 단계 | 기간 | 내용 |
|------|------|------|
| 1. 퀀트 엔진 | 1주 | KIS API 수집 + 사용자 정의 규칙 프레임워크 구현 |
| 2. AI 분석 엔진 | 1주 | 뉴스 수집 + LLM 분석 + AISignal 구조화 |
| 3. 합산 모듈 + FastAPI | 1주 | 두 신호 합산, 엔드포인트, Redis 캐시 |
| 4. 대시보드 | 1주 | React: 퀀트/AI 신호 분리 시각화 |
| 5. 테스트·배포 | 1주 | 모의투자 연동 검증, Docker 배포 |

---

## 11. 제외 범위 (Out of Scope)

- 해외주식·선물·옵션
- 실제 주문 실행 (자율매매는 별도 모듈)
- 공시 원문 파싱 (v1.1에서 DART API 연동으로 추가)
- 사용자 포트폴리오 연동 (v2)
