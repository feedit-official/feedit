# FEEDiT — 서비스 소개 페이지 (Showcase)

AI Championship 2026 (Wanted × KRAFTON Cofa) 예선 제출용.
본 프론트(`../frontend`)와 완전히 분리된 독립 정적 페이지이며,
프론트의 이미지 에셋을 하나도 쓰지 않는다 — 인체·데님·지퍼·신발끈·도식이
전부 절차적으로 생성된다.

## 구성

```
showcase/
├── index.html
├── css/showcase.css
├── js/
│   ├── main.js       씬 오케스트레이션 (스크롤·타임라인·지퍼·신발끈·도식)
│   ├── figures.js    3D 파티클 인체 — 골격에서 캡슐을 세우고 부피를 점으로 채운다
│   └── textmorph.js  텍스트 파티클 모핑 — 앞머리 'A' 를 유지한 채 나머지만 분해·재조합
├── audio/theme.m4a   (+ .mp3 폴백)
└── vercel.json
```

## 시퀀스

| 구간 | 내용 |
|---|---|
| S0 | 스크롤 잠금 상태로 대기. IMPACT · THINK · BUILD 세 파티클 인체 |
| S1 | 첫 제스처 → THINK·BUILD 가 가루가 되어 바닥에 쌓이고, IMPACT 만 남아 회전 |
| S2 | AI Championship 2026 → Are you ready? → Already. (A 유지·중앙정렬 유지) |
|    | 동시에 하단 락업이 F 마크 + FEEDiT 로 조립되고 음악이 시작된다 |
| S3 | 스크롤 = 지퍼가 잠기며 데님이 드러남. 바닥의 가루가 THINK 로 재조립되어 회전 |
| S4 | S자 신발끈을 따라 내려가는 WHY — 수명주기·신호 다변화·이탈 통계·포지셔닝 맵·4원 교집합 |
| S5 | 백지. 가루가 BUILD 로 다시 뭉쳐 회전 → LET'S BUILD → BUILD FEEDiT |

## 로컬 실행

```bash
npx serve .          # 또는  python3 -m http.server 5500
```

## 배포 (별도 Vercel 프로젝트)

Root Directory 를 `feedit/showcase`, 프레임워크 프리셋은 `Other`.

## 손볼 곳

- `js/main.js` 최상단 `PLATFORM_URL` — 진입 대상
- `js/figures.js` 의 `POSES` — 인체 포즈(관절 좌표)
- `js/figures.js` 의 `FIGURES` — 인체별 색 그라디언트
- `index.html` 의 `.beat` — WHY 카피와 수치

## 오디오

브라우저 정책상 자동재생이 불가하므로 **첫 제스처(스크롤·클릭)** 가
시퀀스와 오디오를 함께 깨운다. 우상단 이퀄라이저 버튼으로 켜고 끌 수 있다.

## 접근성

`prefers-reduced-motion` 을 켠 사용자에게는 스크롤 잠금·붕괴·모핑을 모두 건너뛰고
완성된 장면과 수치를 정적으로 보여준다.
