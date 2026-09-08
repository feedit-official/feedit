/* 병합 뒤 링크 검사 — 모든 모듈을 실제로 불러 본다.
   Node 의 ESM 로더가 링크 단계에서 "export 되지 않은 이름" 을 잡아 준다.
   문자열 정규식으로는 못 잡는 것을 여기서 확실하게 본다. */
import { JSDOM } from 'jsdom';
import fs from 'node:fs';
import path from 'node:path';

const ROOT = process.argv[2];
const dom = new JSDOM('<!doctype html><body><div id="c"></div></body>', { url: 'http://localhost:5173/' });
for (const k of ['window','document','Element','SVGElement','HTMLElement','getComputedStyle','Node',
                 'CustomEvent','Event','MutationObserver','requestAnimationFrame','localStorage','navigator'])
  globalThis[k] = k === 'window' ? dom.window : dom.window[k];
globalThis.fetch = async () => ({ ok:true, status:200, text: async()=>'{}', json: async()=>({}) });
globalThis.IntersectionObserver = class { observe(){} unobserve(){} disconnect(){} };
globalThis.ResizeObserver = class { observe(){} unobserve(){} disconnect(){} };
globalThis.matchMedia = () => ({ matches:false, addEventListener(){}, removeEventListener(){}, addListener(){}, removeListener(){} });

const skip = new Set(['node_modules','_to_delete','tests','api','public','docs','.git']);
const files = [];
(function walk(d){
  for (const e of fs.readdirSync(d, {withFileTypes:true})) {
    if (skip.has(e.name)) continue;
    const p = path.join(d, e.name);
    if (e.isDirectory()) walk(p);
    else if (e.name.endsWith('.js')) files.push(p);
  }
})(ROOT);

let ok=0, link=0, runtime=0;
for (const f of files.sort()) {
  try { await import('file://' + path.resolve(f)); ok++; }
  catch (e) {
    const msg = String(e.message);
    if (/does not provide an export|Cannot find module|Cannot find package/.test(msg)) {
      console.log('✘ 링크 끊김 ', path.relative(ROOT,f), '\n     ', msg.split('\n')[0]); link++;
    } else {
      console.log('· 실행 중 예외(브라우저 밖이라 흔함)', path.relative(ROOT,f), '—', msg.split('\n')[0].slice(0,90)); runtime++;
    }
  }
}
console.log(`\n모듈 ${files.length}개 · 정상 ${ok} · ★링크 끊김 ${link} · 실행 예외 ${runtime}`);
process.exit(link ? 1 : 0);
