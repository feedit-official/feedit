import { defineConfig } from 'vite';
import { fileURLToPath } from 'node:url';

/* FEEDiT — 여러 장의 정적 페이지를 한 프로젝트로 묶는다.
   여기 등록된 html 만 빌드 결과물(dist)에 들어간다.
   새 시안 페이지를 만들면 이 목록에 한 줄 추가할 것. */
const page = (name) => fileURLToPath(new URL(`./${name}`, import.meta.url));

export default defineConfig({
  server: {
    port: 5173,
    open: true,          // npm run dev 하면 브라우저가 알아서 열린다
    /* 챗봇 서버(feedit-chat)로 넘기는 길.
       chat_api.js 는 5173/4173 에서 돌 때 API_BASE 를 '/api' 로 잡는다.
       이 프록시가 없으면 /api/v1/health 가 404 라서 isUp() 이 false 가 되고,
       화면은 조용히 목업 답변으로 떨어진다 — 서버가 떠 있어도 그렇다.

       ★ 챗봇 서버를 따로 켜야 한다:
           cd ../Final/feedit-chat && python3 server.py
       안 켜져 있으면 여기 프록시가 ECONNREFUSED 를 내고, 역시 목업으로 떨어진다. */
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8770',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
    },
  },
  build: {
    outDir: 'dist',
    /* 번들 결과물은 _build/ 로 뺀다.
       public/assets/ (사진) 가 dist/assets/ 로 그대로 복사되기 때문에,
       기본값(assets)을 쓰면 두 종류가 같은 폴더에서 섞인다. */
    assetsDir: '_build',
    rollupOptions: {
      input: {
        main:   page('index.html'),   // 메인 목업 (덱 + 앱)
      },
    },
  },
});
