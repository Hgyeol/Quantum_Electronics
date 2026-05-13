# PRD: 의사결정 보조 서비스

**프로젝트**: Quantum Electronics
**작성일**: 2026-05-13
**버전**: 0.1
**상태**: 목표 정의

---

## 1. 목적

현재 outlook 서비스는 한 종목에 대해 *"긍정/중립/부정"* 라벨과 점수만 반환한다.
사용자 대화 로그(`타겟을 위한 정보.md`) 분석에서 드러난 실수요는
**"내 보유 종목·관심 종목들을 어디서 사고 어디서 팔지 결정할 보조 정보"** 이다.

이 PRD는 그 갭을 **결정론적 계산만으로** 메우는 것을 목표로 한다.
LLM도, AI Agent도, 자연어 후속 대화도 1차 범위에서 제외한다.

---

## 2. 비목표 (Non-Goals)

다음은 본 PRD의 범위가 **아니다**.

- AI Agent 또는 자율 매매
- 챗봇 / 자연어 후속 대화 / 세션 상태 보존
- 실시간 WebSocket 스트리밍
- 추천·권유 표현 ("지금 사세요", "손절하세요" 등)
- 미국 주식
- LLM 기반 시나리오 생성 (시나리오는 룰로만 산출)

---

## 3. 핵심 사용자 시나리오

```text
사용자: "녹십자엠에스를 12,660원에 2,200주 가지고 있는데"
시스템: → 평가손익 +X.X%, 본전 회복까지 +Y%, 52주 저점까지 -Z%
        → 1차 매수 후보 구간 (20일선), 2차 (60일선), 손절 후보 (52주 저점 또는 -10%)
        → 관찰 이벤트 (실적 발표 예정일, 공시 일정 등)
```

서비스는 *권유*하지 않고, *사용자가 직접 판단할 수 있는 사실*만 출력한다.

---

## 4. Phase 별 범위

| Phase | 항목 | 추가 외부 호출 | 비용 |
|-------|------|---------------|------|
| 1 | 포지션 인식 입력 (`?avg_price=&quantity=&held_since=`) | KIS `inquire_price` 1회 | 0 |
| 2 | OutlookReport에 `entry_zones`·`stop_loss_price`·`watch_events` | 추가 0 (가격은 이미 수집) | 0 |
| 3 | 다중 종목 비교 `POST /outlook/compare` | 종목 수만큼 outlook 호출 | 기존 outlook 비용 × N |
| 4 | 수급 신호 정밀화 (5d·20d 외인·기관 추세, 거래비중) | KIS daily investor 1회 | 0 |

각 Phase는 독립 배포 가능하며, 직전 Phase 완료를 전제로 한다.

---

## 5. Phase 1 상세

### 5.1 API 변경

```
GET /outlook/stock/{code}
    ?avg_price=12660           # optional, float, KRW
    ?quantity=2200             # optional, int
    ?held_since=2024-03-15     # optional, ISO date
```

`avg_price`·`quantity` 둘 다 제공돼야 손익을 계산한다. 둘 중 하나만 오면 무시.

### 5.2 응답 변경

`OutlookReport.position_context` 필드를 추가한다 (없으면 `null`).

```json
{
  "stock_code": "005930",
  "score": { ... },
  "quant_signals": [ ... ],
  "position_context": {
    "avg_price": 12660,
    "quantity": 2200,
    "held_since": "2024-03-15",
    "current_price": 13200,
    "holding_days": 791,
    "unrealized_pnl_amount": 1188000,
    "unrealized_pnl_pct": 4.27,
    "breakeven_required_pct": 0.0,
    "distance_to_52w_low_pct": 18.5,
    "distance_to_52w_high_pct": -12.1,
    "disclaimer": "정보 제공용 계산일 뿐 매수·매도 권유가 아님."
  }
}
```

### 5.3 계산 규칙 (전부 결정론적)

```
unrealized_pnl_amount   = (current_price - avg_price) * quantity
unrealized_pnl_pct      = (current_price - avg_price) / avg_price * 100
breakeven_required_pct  = max(0, (avg_price - current_price) / current_price * 100)
distance_to_52w_low_pct = (current_price - w52_low)  / current_price * 100
distance_to_52w_high_pct= (w52_high - current_price) / current_price * 100  # 양수면 고점 미달
holding_days            = (today - held_since).days  (held_since 제공 시)
```

음수/0 가격, 미래 held_since 같은 비정상 입력은 422 응답.

### 5.4 표현 규칙

`position_context`는 *사실 진술*만 포함한다. 다음 어휘는 사용하지 않는다.

- "매수하세요" / "사세요" / "추가매수"
- "팔아야 합니다" / "손절하세요"
- "추천", "권유", "기회"

`disclaimer` 필드는 모든 응답에 동일 문구가 들어간다.

---

## 6. 데이터 누수·정확성 원칙

`PRD_신호학습_백테스트.md §5`와 동일 원칙을 계승한다.

- 현재가는 라이브 시점에만 사용한다. 과거 backfill에는 position_context를 적용하지 않는다.
- 52주 고저점은 KIS `inquire_price` 응답을 그대로 사용한다.
- 계산 단위는 KRW, 정수 누적값은 반올림 없이 그대로 노출한다.

---

## 7. 성공 기준

### 7.1 기능

- `avg_price`·`quantity` 양쪽 제공 시 `position_context` 가 포함된 응답이 반환된다.
- 한쪽만 제공되거나 둘 다 없으면 `position_context = null`.
- 응답 스키마가 기존 클라이언트 (Phase 1 이전) 와 하위 호환된다.

### 7.2 안전

- 응답 본문 안에 매수/매도 권유 문구가 없다 (정적 grep 검사 가능).
- 비정상 입력(음수 가격, 미래 held_since) 시 422.

### 7.3 비용

- 추가 KIS 호출은 종목당 1회 (`inquire_price`).
- LLM·DART 호출 0 추가.

---

## 8. 평가 시연 시나리오

```bash
curl "http://127.0.0.1:8000/outlook/stock/005930?avg_price=80000&quantity=10&held_since=2024-01-15"
```

→ 응답의 `score`, `quant_signals`, `ai_signals` 옆에 `position_context` 한 블록이 추가로 보인다.
"수익률·본전·52주 저점 거리"라는 사용자 의사결정 변수가 단일 API 호출로 노출됨을 시연한다.

---

## 9. 향후 Phase 진입 조건

- **Phase 2**: Phase 1 안정 운영 + `entry_zones` 룰 후보 확정.
- **Phase 3**: Phase 1·2의 응답 구조 안정화 + 비교 정렬 룰 합의.
- **Phase 4**: `PRD_신호학습_백테스트.md` 외인 신호 정밀화와 합쳐서 단일 트랙으로 진행.
