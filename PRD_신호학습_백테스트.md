# PRD: 퀀트+LLM 신호 학습 및 백테스트 시스템

**프로젝트**: Quantum Electronics  
**작성일**: 2026-05-12  
**버전**: 0.1  
**상태**: 목표 정의

---

## 1. 목적

현재 서비스는 특정 종목에 대해 퀀트 신호, 재무 신호, LLM 신호를 생성하고 단순 합산 점수로 전망을 반환한다.

최종 목표는 과거 데이터를 기준으로 다음 구조를 검증하고 개선하는 것이다.

```text
과거 특정일의 정보
→ 퀀트 신호 생성
→ 뉴스/공시/재무 evidence 수집
→ LLM 신호 생성
→ 퀀트+LLM+재무 신호를 feature로 변환
→ 다음 거래일 주가 변동을 label로 사용
→ 예측 모델/스코어링 모델 학습
→ 백테스트로 실제 성능 검증
```

이 시스템의 목적은 LLM 자체를 바로 강화학습시키는 것이 아니라, 먼저 **퀀트+LLM 신호가 다음날 주가 방향 예측에 실제로 유효한지 검증하고, 최종 전망 점수 산출 방식을 데이터 기반으로 개선**하는 것이다.

---

## 2. 핵심 질문

이 PRD가 답해야 하는 질문은 다음과 같다.

1. 현재 `quant_score + ai_score + financial_score` 단순 합산은 다음날 주가 방향 예측에 유효한가?
2. 어떤 개별 신호가 실제 수익률과 가장 관련이 있는가?
3. LLM 신호를 추가했을 때 퀀트/재무만 썼을 때보다 성능이 좋아지는가?
4. 다음날 수익률 기준으로 학습한 모델이 기존 rule score보다 나은가?
5. 장기적으로 사용자 피드백 또는 실제 수익률을 보상으로 한 강화학습/RFT/DPO로 확장할 가치가 있는가?

---

## 3. 범위

### 3.1 포함 범위

- 과거 날짜별 신호 feature dataset 생성
- 다음 거래일 수익률 label 생성
- 기존 rule score baseline 평가
- 지도학습 기반 예측 모델 학습
- 시간순 train/validation/test 분리
- 백테스트 평가 지표 산출
- FastAPI 결과에 ML 예측 결과를 추가할 수 있는 구조 설계

### 3.2 제외 범위

- 실거래 주문 실행
- 자동 매매
- 사용자 계좌 기반 포지션 관리
- 처음부터 PPO/RLHF/RFT 적용
- LLM이 직접 가격을 예측하도록 학습
- 랜덤 split 기반 성능 평가

---

## 4. 데이터 정의

### 4.1 Feature Row 단위

한 row는 특정 종목의 특정 거래일 기준 전망 상태를 의미한다.

```text
(date, stock_code) = 1 row
```

예:

```text
2026-05-11, 005930
```

### 4.2 필수 컬럼

```text
date
stock_code
stock_name

quant_score
ai_score
financial_score
total_rule_score

golden_cross_score
disparity_score
momentum_score
foreign_investor_score
volume_score

llm_direction
llm_score
llm_confidence

financial_revenue_growth_score
financial_margin_score
financial_debt_score

news_count
disclosure_count
financial_evidence_count

next_day_return
target_up
```

### 4.3 Label

초기 label은 다음 거래일 종가 기준으로 정의한다.

```text
next_day_return = (close[t+1] - close[t]) / close[t]
target_up = 1 if next_day_return > 0 else 0
```

추후 확장 label:

```text
next_3d_return
next_5d_return
target_up_3d
target_up_5d
excess_return_vs_kospi
```

---

## 5. 데이터 누수 방지 원칙

백테스트 신뢰도를 위해 다음 규칙을 반드시 지킨다.

1. `date=t` row에는 `t` 시점에 알 수 있는 정보만 포함한다.
2. `t+1` 가격, 이후 뉴스, 이후 공시는 feature에 포함하지 않는다.
3. 재무제표는 실제 공시일 이후에만 feature로 사용할 수 있다.
4. 뉴스/공시는 발행 시간이 `t` 장 마감 이후라면 다음 거래일 feature로 넘긴다.
5. train/test는 랜덤 분리하지 않고 반드시 시간순으로 분리한다.
6. 같은 날짜의 같은 종목이 중복 생성되면 안 된다.

---

## 6. 모델 전략

### 6.1 Baseline

가장 먼저 기존 rule score를 평가한다.

```text
predict_up = total_rule_score > 0
```

이 baseline보다 개선되지 않으면 ML 모델을 붙일 이유가 약하다.

### 6.2 1차 지도학습 모델

초기 모델은 해석 가능성과 구현 난도를 우선한다.

우선순위:

1. Logistic Regression
2. RandomForest
3. XGBoost 또는 LightGBM

초기 목표는 고급 모델이 아니라, **어떤 feature가 실제로 유효한지 확인하는 것**이다.

### 6.3 강화학습 확장

강화학습은 1차 목표가 아니다.

강화학습이 적합해지는 조건:

- 충분한 과거 feature/label dataset 확보
- baseline 대비 지도학습 모델 성능 개선 확인
- reward 정의가 명확함
- 거래비용/슬리피지/포지션 관리가 모델에 포함됨

강화학습 형태:

```text
state: 오늘의 퀀트+LLM+재무+가격 상태
action: buy / hold / sell
reward: 다음날 또는 보유기간 수익률 - 거래비용
```

OpenAI RFT/DPO는 “분석 문장 품질 개선”에는 사용할 수 있지만, 주가 수익률 최적화의 1차 수단으로 보지 않는다.

---

## 7. 평가 지표

### 7.1 분류 성능

```text
accuracy
precision
recall
ROC-AUC
```

### 7.2 투자 성능

```text
mean_return_when_pred_up
cumulative_return
max_drawdown
win_rate
trade_count
turnover
```

### 7.3 비교 기준

모든 모델은 다음 baseline과 비교한다.

```text
Baseline A: 항상 상승 예측
Baseline B: total_rule_score > 0
Baseline C: quant_score > 0
Baseline D: ai_score > 0
```

---

## 8. 시스템 구조

```text
ml/
  dataset.py        # feature + price → labeled dataset
  labels.py         # return/target label 생성
  evaluation.py     # baseline/model 평가
  training.py       # 모델 학습
  backtest.py       # 수익률 기반 백테스트
  artifacts/        # 학습된 모델 저장

scripts/
  build_ml_dataset.py
  train_outlook_model.py
  evaluate_ml_dataset.py
```

---

## 9. 단계별 구현 계획

### Phase 1: Dataset 기반 만들기

- feature CSV 입력
- price CSV 입력
- `next_day_return`, `target_up` 생성
- baseline `total_score > 0` 평가

완료 기준:

```text
data/ml_dataset.csv 생성 가능
baseline 평가 JSON 출력 가능
```

### Phase 2: 과거 feature 생성기

- `as_of_date` 기준 퀀트 신호 생성
- `as_of_date` 기준 뉴스/공시/evidence 수집
- LLM 신호 캐싱
- 날짜별 feature row 저장

완료 기준:

```text
특정 종목/기간에 대해 daily feature CSV 생성 가능
```

### Phase 3: 모델 학습

- Logistic Regression 학습
- 시간순 train/validation/test split
- 모델 artifact 저장
- feature importance 또는 coefficient 출력

완료 기준:

```text
기존 total_score baseline 대비 validation 성능 비교 가능
```

### Phase 4: 서비스 반영

FastAPI 응답에 ML 예측 결과를 추가한다.

```json
{
  "ml_prediction": {
    "target": "next_day_up",
    "probability": 0.57,
    "model": "logistic_regression_v1",
    "features_version": "v1"
  }
}
```

기존 rule score는 제거하지 않고 함께 노출한다.

### Phase 5: 강화학습/선호학습 검토

- 사용자 피드백 수집
- 좋은 분석/나쁜 분석 pair 생성
- DPO 또는 RFT 적용 가능성 검토
- 수익률 reward 기반 trading policy는 별도 연구 과제로 분리

---

## 10. 성공 기준

### 10.1 기술 성공 기준

- 최소 3개월 이상의 과거 dataset 생성
- 최소 3개 이상 종목에 대해 백테스트 가능
- feature/label 생성 과정 재현 가능
- LLM 호출 결과 캐싱 가능

### 10.2 모델 성공 기준

- validation/test에서 baseline보다 높은 precision 또는 mean return
- trade_count가 너무 적지 않음
- 특정 종목 하나에만 과최적화되지 않음

### 10.3 서비스 성공 기준

- 기존 전망 API에 ML 예측을 추가해도 응답 구조가 깨지지 않음
- rule score와 ML prediction의 차이를 사용자에게 설명 가능
- 모델 버전과 feature 버전을 추적 가능

---

## 11. 주요 리스크

| 리스크 | 설명 | 대응 |
|--------|------|------|
| 데이터 누수 | 미래 정보를 feature에 포함 | as_of_date 강제 |
| 과최적화 | 특정 기간/종목에만 맞음 | 시간순 test, 종목 분산 |
| LLM 비용 | 과거 전체 뉴스 분석 비용 큼 | 캐싱, 샘플링, 중요 뉴스만 사용 |
| 하루 수익률 노이즈 | LLM 분석이 맞아도 다음날 주가 반대 가능 | 3일/5일 label 추가 |
| 설명력 부족 | ML 결과를 사용자가 이해하기 어려움 | rule score와 feature contribution 병행 |

---

## 12. 최종 방향

최종 서비스는 세 가지 판단을 함께 제공한다.

```text
1. Rule Score
   현재 정의된 퀀트+LLM+재무 단순 합산 점수

2. ML Prediction
   과거 데이터로 학습한 다음날 상승 확률

3. Evidence Explanation
   뉴스/공시/재무/퀀트 근거 설명
```

즉, 목표는 “LLM이 주가를 맞히게 만드는 것”이 아니라,

```text
LLM은 비정형 정보를 구조화하고,
퀀트는 가격/수급 흐름을 수치화하고,
ML은 과거 성과를 기준으로 이 신호들의 가중치를 학습한다.
```

이 구조가 Quantum Electronics의 장기 목표다.
