# FEEDiT — 서비스 소개 페이지

AI Championship 2026 (Wanted × KRAFTON) 예선 제출용 랜딩 페이지.
본 프론트(`../frontend`)와 **완전히 분리된 독립 정적 페이지**로, 브랜드 토큰만
계승하고 마지막에 플랫폼으로 자연스럽게 인계한다.

## 구조

```
landing/
├── index.html          # 마크업 (섹션 6개)
├── css/landing.css     # 전체 스타일
├── js/landing.js       # 인터랙션 · 데이터
├── assets/             # 화보 · 스냅 · 상품컷 (frontend/public/assets에서 선별 복사)
└── vercel.json
```

## 로컬 실행

```bash
npx serve .          # 또는  python3 -m http.server 5500
```

## 배포 (별도 Vercel 프로젝트)

```bash
cd landing && vercel --prod
```

Root Directory 를 `feedit/landing` 으로 지정하면 된다. 프레임워크 프리셋은 `Other`.

## 플랫폼 링크

`js/landing.js` 최상단 `PLATFORM_URL` 한 줄만 고치면 진입 대상이 바뀐다.

## 사용 기술

| 구간 | 기술 |
|---|---|
| 스크롤 오케스트레이션 | GSAP 3.13 + ScrollTrigger (pin · scrub · velocity) |
| 관성 스크롤 | Lenis 1.3 (ScrollTrigger 와 ticker 동기화) |
| 텍스트 리빌 | 커스텀 라인/어절 스플리터 (외부 의존 0) |
| 진행 게이지 | CSS `animation-timeline: scroll()` — JS 미사용 |
| 화면 전환 | View Transitions API + 커튼 폴백 |
| 타이포 | `text-wrap: balance` / `pretty` |
| 커서 | `mix-blend-mode: difference` + `gsap.quickTo` |
| 접근성 | `prefers-reduced-motion` 전 구간 대응 (가로 스크롤 → 네이티브 스크롤로 강등) |

## 데이터

`js/landing.js` 상단 `LOOKS` / `METRICS` / `ITEMS` 배열이 화면의 모든 수치를 만든다.
현재는 서비스 산출 방식을 따른 **예시 스냅샷**이며, 실 API 연동 시 이 배열만 교체하면 된다.
