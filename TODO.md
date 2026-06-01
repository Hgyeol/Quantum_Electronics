# TODO / 추가 작업 목록

---

## 후순위

### WebSocket 브로드캐스트 구조 개선
- **현황**: 유저 1명 접속 = KIS WebSocket 1개 생성 → N명 접속 시 KIS WebSocket N개 동시 연결
- **문제**: KIS API 동시 연결 수 제한으로 유저가 늘어나면 연결 거부될 수 있음
- **개선 방향**: KIS WebSocket 1개로 수신 → 접속한 모든 유저에게 브로드캐스트 (fan-out 구조)
- **관련 파일**: `services/realtime.py`, `web/main.py` (`ws_watchlist` 엔드포인트)
