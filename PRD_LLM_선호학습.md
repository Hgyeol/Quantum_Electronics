# PRD: LLM 선호학습 (DPO)

**프로젝트**: Quantum Electronics
**작성일**: 2026-05-13
**버전**: 0.1
**상태**: 목표 정의

---

## 1. 목적

현재 outlook 서비스의 `ai_signals`는 OpenAI gpt-5.2를 호출해 얻는다.
모델 자체는 학습되지 않은 일반 모델이라, 한국 주식 도메인 판단이 한쪽으로 쏠리거나
다음 거래일 실제 결과와 자주 어긋난다.

`PRD_신호학습_백테스트.md §6.3 / §9 Phase 5`가 보류 항목으로 정의한
*"LLM 자체를 결과와 더 정렬되도록 학습"*에 대한 첫 번째 구체적 단계로,
**DPO (Direct Preference Optimization)** 를 적용한다.

---

## 2. 비목표 (Non-Goals)

- 수익률 기반 PPO·GRPO (`PRD_신호학습_백테스트.md §6.3` 그대로 보류)
- OpenAI 폐쇄 모델 파인튜닝 (예산상)
- LLM이 직접 가격을 출력하도록 학습
- 거래 비용·슬리피지·포지션 관리

DPO는 *"같은 evidence 묶음에 대해, 결과와 일치한 판단 vs 일치하지 않은 판단 중 어느 쪽을 선호하는가"* 만 학습한다.

---

## 3. 핵심 아이디어

```text
prompt    : build_evidence_prompt(evidence)  ← 기존 코드 재사용
chosen    : 다음 거래일 실제 방향과 일치하는 판단 응답
rejected  : 일치하지 않는 판단 응답
```

기존 데이터셋(`features.csv` 303행 + `outlook_reports.jsonl` 303건 + `ml_dataset.csv`의 `next_day_return`)에서 직접 (prompt, chosen, rejected) 트리플을 추출한다.

---

## 4. 데이터 정의

### 4.1 misaligned 판단 정의

```text
actual_direction = "positive" if next_day_return > 0
                   "negative" if next_day_return < 0
                   "neutral"  if |next_day_return| < ε  (default ε = 0.005)

misaligned ↔ llm_direction ≠ actual_direction
```

### 4.2 pair 구성

각 misaligned 행에 대해:

| 필드 | 값 |
|------|------|
| `prompt` | `build_evidence_prompt(evidence_for_(date, stock))` 그대로 (인퍼런스와 100% 동일) |
| `rejected` | 그 (date, stock)의 실제 LLM 응답 JSON 문자열 |
| `chosen` | `actual_direction`을 따르는 합성 응답 JSON (label·summary 템플릿 + 동일 `evidence_ids` + `confidence=0.5`) |

aligned 행은 DPO pair에 포함하지 않는다. 같은 prompt에 대해 둘 다 LLM이 생성한 게 아니므로 *"학습 대상 = 결과 불일치 사례만 교정"* 으로 한정.

### 4.3 합성 chosen 응답 형식

```json
{
  "label": "다음 거래일 [상승/하락] 방향성 정렬",
  "direction": "positive",
  "score": 2,
  "summary": "evidence 점검 결과, 다음 거래일은 상승 방향으로 정렬되는 신호가 우세함.",
  "evidence_ids": ["disclosure-...", "financial-statements", ...],
  "confidence": 0.5
}
```

- 직접 매수·매도 권유 어휘는 사용하지 않는다 (`PRD_의사결정보조.md §5.4`와 동일 가이드).
- `evidence_ids`는 rejected와 동일 (실제 evidence 풀에서만 추출).

---

## 5. 학습 위치·도구

| 항목 | 선택 |
|------|------|
| Base 모델 | `Qwen/Qwen2.5-3B-Instruct` (멀티링구얼·한국어 양호) |
| 양자화 | 4-bit (bitsandbytes 또는 MLX) |
| 어댑터 | LoRA (`r=16`, `alpha=32`, target: `q_proj`, `k_proj`, `v_proj`, `o_proj`) |
| 학습 라이브러리 | `trl.DPOTrainer` (Hugging Face) |
| 학습 장소 | Google Colab 무료 T4 (로컬 Mac 8 GB RAM 부적합) |
| 에폭 | 2~3 (overfitting 방지) |
| Beta (DPO 강도) | 0.1 |

로컬 저장소가 다루는 산출물은 **LoRA 어댑터 (~100 MB)** 뿐. Base 모델 가중치는 인퍼런스 시점에 Hugging Face에서 자동 다운로드.

---

## 6. 인퍼런스 통합

`llm/local_qwen_analyzer.py`로 `EvidenceAnalyzer` 프로토콜을 구현한 어댑터를 추가한다.
환경 변수 `OUTLOOK_LOCAL_LLM_ADAPTER_PATH`가 설정돼 있고 모델 가중치 로드에 성공하면
`services.outlook.OutlookService`가 OpenAI 대신 로컬 어댑터를 사용한다.

설정되지 않거나 가중치 로드 실패 시 자동으로 기존 OpenAI 경로로 fallback.

---

## 7. 평가 (졸업 발표용)

같은 holdout set (예: `ml_dataset.csv`의 test split)에서:

| 지표 | 측정 |
|------|------|
| `direction_match_rate` | LLM 판단이 실제 다음날 방향과 일치하는 비율 |
| `confidence_calibration` | `llm_confidence`와 실제 정확도의 상관 |
| `mean_return_when_positive` | LLM이 positive로 판단한 날의 평균 다음날 수익률 |

기준선 (`gpt-5.2` 원본) vs DPO 학습된 `Qwen2.5-3B + LoRA` 두 모델 결과를 동일 evidence 풀에 대해 비교.

---

## 8. 성공 기준

### 8.1 기술 성공

- DPO pair JSONL이 misaligned 행 수만큼 생성된다.
- LoRA 어댑터 학습이 OOM 없이 완주한다 (Colab T4 기준).
- 로컬 인퍼런스 어댑터가 OpenAI 어댑터와 동일한 `AISignal` 스키마를 반환한다.

### 8.2 모델 성공

- holdout direction_match_rate ≥ baseline + 5pp (절대값)
- 또는 mean_return_when_positive 가 baseline 보다 큼

목표 미달이어도 졸업 발표용으로 "시도했고 이 정도 효과/한계가 있었다" 라는 분석은 학술적으로 유효함을 명시.

### 8.3 운영 성공

- 로컬 인퍼런스 fallback이 깨지지 않음 (어댑터 없으면 OpenAI 경로 그대로).
- DPO 데이터·어댑터 모두 `git` 추적 외 (`data/`, `ml/artifacts/` 디렉토리 규칙 준수).

---

## 9. 단계별 진행

| Phase | 항목 | 위치 |
|-------|------|------|
| 9.1 | DPO pair 생성기 `scripts/build_dpo_pairs.py` | 로컬 |
| 9.2 | Colab 노트북에서 학습, LoRA 어댑터 다운로드 | Colab |
| 9.3 | 로컬 인퍼런스 어댑터 `llm/local_qwen_analyzer.py` | 로컬 |
| 9.4 | A/B 비교 평가 스크립트 `scripts/evaluate_llm_alignment.py` | 로컬 (별도 추가) |

본 PR는 9.1 + 9.3 + 노트북 골격까지를 다룬다. 9.2 (실 학습) 와 9.4 (비교 평가) 는 후속 작업.

---

## 10. 리스크

| 리스크 | 대응 |
|--------|------|
| Colab T4 세션 시간 제한 | LoRA 4-bit로 학습 시간 < 2시간 유지, 중간 체크포인트 저장 |
| 합성 chosen 응답이 단조로워 모델이 템플릿만 외움 | summary 어휘를 5~10종 랜덤 샘플, 평가 시 정성 점검 |
| 데이터 부족 (300행 미만 misaligned) | epoch 늘리거나 holdout 비율 축소 |
| 평가에서 baseline보다 낮게 나옴 | 발표에서 "왜 그랬는지" 분석 자체를 학술 결과로 사용 |
