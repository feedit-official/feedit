import { JSDOM } from 'jsdom';
const dom = new JSDOM('<!doctype html><div id="cpThread"></div>', {url:'https://feedit.test/'});
global.window=dom.window; global.document=dom.window.document;
global.location=dom.window.location;
global.HTMLElement=dom.window.HTMLElement; global.fetch=async()=>({ok:false});
const api=await import(new URL('./home/static/js/chat_api.js', `file://${process.cwd()}/`).href);

const html=api.reportHTML({blocks:[{type:'rank',slot:'full',title:'트렌드 TOP 10',
  rows:[{k:'자켓',v:'86',up:true},{k:'셔츠',v:'80',up:true}]}]});
console.log('legacy rpTools :', /data-rp-share/.test(html) && /data-rp-save/.test(html));

const gen=api.reportHTML({blocks:[{type:'generative_report',slot:'full',title:'T',accent:'coral',
  surface:'paper',density:'balanced',fingerprint:'x',
  modules:[{kind:'ranking',presentation:'hero',span:12,emphasis:'strong',
    block:{type:'rank',title:'TOP',rows:[{k:'자켓',v:'86',up:true}]}}]}]});
console.log('generative rpTools :', /data-rp-share/.test(gen) && /data-rp-save/.test(gen));
console.log('head order ok :', gen.indexOf('SIGNALS') < gen.indexOf('rpTools'));
