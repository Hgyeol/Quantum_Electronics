# Quantum Electronics — 인수인계 / 재시작 가이드

**기준 시점**: 2026-05-14
**마지막 사용자 작업**: DPO LoRA 어댑터 로컬 인퍼런스 연결 완료 (MLX 4-bit Qwen2.5-3B + 변환 어댑터)

---

## 1. 한눈에 보는 상태

| 영역 | 상태 |
|------|------|
| 백엔드 (FastAPI) | ✅ 완성. CORS 포함. ml_prediction 노출 |
| 프론트엔드 (Next.js) | ✅ 완성. 다만 ML Prediction 카드는 임시 숨김 |
| `PRD_신호학습_백테스트.md` | ✅ 13/13 audit 통과 |
| `PRD_의사결정보조.md` Phase 1 | ✅ position_context 노출 |
| `PRD_LLM_선호학습.md` | ✅ 학습 + 로컬 인퍼런스 연결 완료 (MLX 4-bit + 변환 어댑터) |
| launchd 자동 수집 (매일 16:10) | ✅ 등록됨 — `com.quantum-electronics.signal-learning-daily` |

---

## 2. 재부팅 직후 재시작 절차

### 2.1 KIS 토큰 (필요시)

```bash
ls ~/KIS/config/KIS$(date +%Y%m%d)
# 오늘자 파일이 없으면 launchd가 다음 16:10에 새로 발급함.
# 즉시 필요하면:
cd /Users/gimhangyeol/졸작
.venv/bin/python -c "import kis_auth; kis_auth.auth(svr='prod')"
```

### 2.2 백엔드 (FastAPI)

```bash
cd /Users/gimhangyeol/졸작
.venv/bin/uvicorn web.main:app --reload
# → http://127.0.0.1:8000
# → http://127.0.0.1:8000/docs (Swagger)
```

### 2.3 프론트엔드 (Next.js)

```bash
cd /Users/gimhangyeol/졸작_프론트
npm run dev
# → http://localhost:3000  (또는 http://127.0.0.1:3000)
```

`npm run dev` 는 내부적으로 `next dev --webpack`. Turbopack은 한글 경로 패닉으로 비활성.

### 2.4 시연용 종목 후보

| 입력 | 기대 결과 |
|------|----------|
| `005930` 또는 `삼성전자` | Final Verdict negative, 외인 매도 -2, 이격도 -2 |
| `005380` 또는 `현대차` | Rule positive(+1), 다른 신호 다 양호 (학습 universe 밖) |
| `006840` 또는 `AK홀딩스` | 학습 universe 안. 모델·룰 정렬 |

---

## 3. 디렉토리 지도

```
/Users/gimhangyeol/
├── 졸작/                       ← 백엔드 + ML
│   ├── PRD_신호학습_백테스트.md  PRD #1 (audit 13/13 통과)
│   ├── PRD_의사결정보조.md       PRD #2 (Phase 1 완료, 2~4 TODO)
│   ├── PRD_LLM_선호학습.md       PRD #3 (학습 완료, 인퍼런스 TODO)
│   ├── HANDOFF.md               ← 이 문서
│   ├── README.md
│   ├── .env                     API 키 + OUTLOOK_* 변수 (gitignored)
│   ├── web/main.py              FastAPI 엔트리, CORS
│   ├── services/outlook.py      build_report(), position_context 통합
│   ├── services/position.py     PRD #2 결정론적 포지션 계산
│   ├── quant/                   퀀트 5개 신호 (라이브 경로)
│   ├── ml/
│   │   ├── historical.py        백필 경로 (라이브와 룰 동일)
│   │   ├── training.py          Logistic Regression
│   │   ├── runtime.py           OutlookMLPredictor
│   │   └── artifacts/
│   │       ├── signal_learning_v1/   학습된 LR 모델 + 메트릭
│   │       └── llm_dpo_v1/           ← DPO LoRA 어댑터 (Colab 산출)
│   ├── scripts/
│   │   ├── backfill_signal_features.py    PRD §9.2
│   │   ├── collect_daily_signal_learning_inputs.py  (launchd가 실행)
│   │   ├── run_signal_learning_workflow.py
│   │   ├── refresh_foreign_investor.py    외인 보강 (15:40 KST 이후)
│   │   └── build_dpo_pairs.py             DPO 학습 데이터 생성
│   ├── notebooks/dpo_qwen_colab.ipynb     Colab 학습 노트북
│   ├── data/                    (gitignored) features, prices, reports, llm_cache, dpo_pairs
│   └── runtime/                 (gitignored) launchd plist + 로그
└── 졸작_프론트/                ← 프론트엔드
    ├── src/app/page.tsx         메인 페이지
    ├── src/components/
    │   ├── OutlookForm.tsx
    │   ├── FinalVerdictCard.tsx  Final Verdict hero
    │   ├── QuantSignalsTable.tsx 신호 행 클릭→펼침
    │   ├── PositionContextCard.tsx
    │   ├── MLPredictionCard.tsx  현재 page.tsx에서 임시 비공개
    │   ├── EvidenceList.tsx
    │   └── ErrorsBanner.tsx
    ├── src/lib/api.ts           FastAPI 호출 클라이언트
    └── src/app/globals.css      Binance design tokens (@theme)
```

---

## 4. 데이터 자산 현황

| 파일 | 행 수 | 의미 |
|------|------|------|
| `data/features.csv` | 303 | 3종목 × 101 거래일 (2025-12-11 ~ 2026-05-13) |
| `data/outlook_reports.jsonl` | 303 | 각 (date, stock) 의 OutlookReport 원본 |
| `data/prices.csv` | 505 | 5종목 가격 (027410, 138930 포함, features엔 누락) |
| `data/llm_cache.json` | ~290 entries | gpt-5.2 응답 캐시 |
| `data/dpo_pairs.jsonl` | 204 | DPO 학습 페어 (misaligned 행만) |
| `data/stock_codes.csv` | 3 | 095570, 006840, 282330 |
| `ml/artifacts/signal_learning_v1/outlook_logistic_v1.json` | — | 학습된 Logistic Regression |
| `ml/artifacts/llm_dpo_v1/adapter_*.{json,safetensors}` | — | Qwen2.5-3B + LoRA (HF PEFT 포맷, 보관용 원본 14 MB) |
| `ml/artifacts/llm_dpo_v1_mlx/{adapter_config.json,adapters.safetensors}` | — | **MLX-LM 호환 변환본** — 실제 인퍼런스 경로 |
| `~/.cache/huggingface/hub/models--mlx-community--Qwen2.5-3B-Instruct-4bit/` | — | 4-bit MLX base (~1.8 GB, 첫 호출 시 자동 다운로드) |

---

## 5. 환경 변수 (`.env`)

| 키 | 용도 | 현재 |
|----|------|------|
| `NAVER_NEWS_API_CLIENT` / `_SECRET` | 라이브 뉴스 수집 | 설정됨 |
| `DISCLOSURE_CRTFC_KEY` | DART 공시·재무 | 설정됨 |
| `OPENAI_API_KEY` | gpt-5.2 LLM 호출 | 설정됨 |
| `OUTLOOK_ML_MODEL_PATH` | LR 모델 경로 | `ml/artifacts/signal_learning_v1/outlook_logistic_v1.json` |
| `OUTLOOK_LLM_CACHE_PATH` | LLM 캐시 | `data/llm_cache.json` |
| `OUTLOOK_LOCAL_LLM_ADAPTER_PATH` | DPO 어댑터 (MLX) | **활성**, `ml/artifacts/llm_dpo_v1_mlx` |
| `OUTLOOK_LOCAL_LLM_BASE` | MLX 4-bit base 모델 | 미설정 → 기본값 `mlx-community/Qwen2.5-3B-Instruct-4bit` |

---

## 6. 알려진 한계 / TODO

### 6.1 ML Prediction (LR) — 프론트에서 임시 숨김
- 학습 데이터가 **3종목 × 154일**로 매우 제한적
- 학습 universe 밖 종목(예: 현대차)에서 룰과 정반대 예측 발생
- `page.tsx`에서 `MLPredictionCard` import + 렌더 블록을 다시 살리면 복구됨

### 6.2 DPO LoRA 어댑터 — MLX 인퍼런스 운영 메모
- 8 GB RAM 제약: HF Transformers + bf16 base는 RAM 초과 → MLX 4-bit 경로로 우회
- 어댑터 포맷: PEFT(`adapter_model.safetensors`) ↔ MLX(`adapters.safetensors`) 키/shape 다름.
  `scripts/convert_peft_to_mlx_adapter.py`로 변환 (transpose + 키 매핑 + fp16 캐스팅)
- 새 어댑터 학습 후엔 반드시 변환 스크립트를 다시 실행해 `_mlx` 디렉토리를 갱신해야 함
- `web/main.py`의 `get_outlook_service`는 매 요청마다 `OutlookService`를 새로 만들어 모델을 재로딩한다 (~5초/요청 추가).
  성능이 문제면 `@functools.lru_cache`로 싱글톤화 가능 (다중 워커 환경에선 워커별 1회 로딩)

### 6.3 외인 순매수 신호 — 백필 99/303 행이 0
- KIS API의 15:40 KST 시간 제한 때문에 backfill 당시 0으로 들어감
- 보강 스크립트는 작성됨: `python scripts/refresh_foreign_investor.py` (15:40 KST 이후 1회 실행)
- launchd가 매일 16:10에 자동 수집하니 오늘 이후 신규 행은 정상

### 6.4 종목 수 — PRD §10.1을 5→3으로 낮춘 상태
- `data/stock_codes.csv` 3종목. OpenAI 크레딧 확보 후 027410, 138930 백필 재실행하면 5종목 복구
- 백필 명령: `python scripts/backfill_signal_features.py --kis-auth`

### 6.5 PRD #2 (의사결정보조) Phase 2~4 미구현
- Phase 2: `entry_zones`, `stop_loss_price`, `watch_events` 필드
- Phase 3: `POST /outlook/compare` 다종목 비교
- Phase 4: 외인 수급 5d/20d 추세 정밀화

---

## 7. 자주 쓰는 명령어 모음

```bash
# 백엔드 테스트
cd /Users/gimhangyeol/졸작
.venv/bin/python -m pytest -q          # 현재 99 passed

# PRD audit
.venv/bin/python scripts/audit_signal_learning_prd.py | jq .ok
# → true 이면 13/13 통과

# launchd 상태 확인
launchctl list | grep quantum

# 최근 launchd 실행 로그
tail -50 runtime/signal_learning_daily.out.log

# 라이브 API 한 번 호출
curl -sS "http://127.0.0.1:8000/outlook/stock/005930" | jq .score
curl -sS "http://127.0.0.1:8000/outlook/stock/$(python3 -c 'import urllib.parse;print(urllib.parse.quote("삼성전자"))')" | jq .stock_name

# 외인 보강 (15:40 KST 이후)
.venv/bin/python scripts/refresh_foreign_investor.py

# 워크플로 재실행 (베이스라인·모델 재학습)
.venv/bin/python scripts/run_signal_learning_workflow.py \
    --features data/features.csv --prices data/prices.csv \
    --output-dir ml/artifacts/signal_learning_v1 \
    --min-calendar-days 90 --min-stocks 3 --min-selected-stock-count 3

# 새 DPO 페어 만들기 (features 늘렸을 때)
.venv/bin/python scripts/build_dpo_pairs.py

# Colab에서 새 PEFT 어댑터 받으면 MLX 포맷으로 변환
.venv/bin/python scripts/convert_peft_to_mlx_adapter.py

# 로컬 Qwen 인퍼런스 스모크 (.env 그대로 사용, AISignal 출력)
.venv/bin/python scripts/smoke_local_qwen.py
```

---

## 8. 최근 git 히스토리 (백엔드)

```
ac31f42 fix: rebalance quant signals so sustained uptrends register positives
66ce1a3 feat: enable frontend CORS + document Next.js companion
d2da289 fix: clarify foreign-investor signal label as share-count units
dfd1ea3 docs: lower PRD §10.1 minimum from 5 stocks to 3
6cbfd0b feat: LLM preference-learning (DPO) scaffold — PRD + pair builder + Colab notebook
c3ec3e1 feat: add position_context query path for decision support (Phase 1)
8559a4b feat: wire trained signal-learning model into FastAPI (PRD Phase 4)
7af330f feat: add historical signal feature backfill for PRD Phase 2
```

프론트엔드는 `/Users/gimhangyeol/졸작_프론트` 별도 git, 마지막 커밋 `0d27539 feat: outlook visualization in Binance design language` + 그 이후 작업분 미커밋.

---

## 9. 다음 작업 우선순위 제안

1. **외인 보강 1회 실행** (5분, 비용 0)
2. **027410, 138930 backfill 재개** (1~2시간, OpenAI ~$5)
3. **PRD #2 Phase 2 (entry_zones / stop_loss)** — 룰 기반, LLM·KIS 추가 호출 0
4. **`OutlookService` 싱글톤화** — MLX 모델 매 요청 재로딩 제거
5. **프론트 미커밋분 정리·커밋**

---

## 10. 디자인 시스템 메모

프론트는 Binance 스타일 dark canvas 기반.
- Canvas: `#0b0e11`, Card: `#1e2329`
- Primary CTA: `#FCD535` (yellow) + 검은 글씨
- BinanceNova → Inter, BinancePlex → JetBrains Mono (숫자)
- Trading green/red는 텍스트 컬러로만, 카드 배경엔 사용 금지
- Radius: md 6 / lg 8 / xl 12 / pill 9999

자세한 토큰은 `/Users/gimhangyeol/졸작_프론트/src/app/globals.css` 의 `@theme` 블록 참고.
