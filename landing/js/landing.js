const PLATFORM_URL='https://fee-di-t-frontend.vercel.app/';
const REDUCED=matchMedia('(prefers-reduced-motion: reduce)').matches;
const $=(selector,root=document)=>root.querySelector(selector);
const clamp=(n,a,b)=>Math.min(b,Math.max(a,n));

const impact=new GPUParticleBody($('#impactCanvas'),{group:true,count:78000});
const think=new GPUParticleBody($('#thinkCanvas'),{pose:'think',count:48000,cxRatio:.69,scale:.6});
const build=new GPUParticleBody($('#buildCanvas'),{pose:'build',count:48000,cxRatio:.73,scale:.64});
let introReady=false;

gsap.registerPlugin(ScrollTrigger);
if(window.Lenis&&!REDUCED){
  const lenis=new Lenis({duration:1.05,smoothWheel:true});
  lenis.on('scroll',ScrollTrigger.update);
  gsap.ticker.add(time=>lenis.raf(time*1000));
  gsap.ticker.lagSmoothing(0);
}

function morphTitle(text){
  const title=$('#heroTitle');
  gsap.to(title,{yPercent:-120,opacity:0,duration:.48,ease:'power3.in',onComplete:()=>{
    title.textContent=text;
    gsap.set(title,{yPercent:120});
    gsap.to(title,{yPercent:0,opacity:1,duration:.75,ease:'expo.out'});
  }});
}

function startExperience(){
window.FEEDiTParticleStats={hero:impact.particleCount,think:think.particleCount,build:build.particleCount,models:5,poses:['WANTED BUILD','WANTED THINK','WANTED IMPACT','WANTED THINK','WANTED BUILD'],interaction:'original 2400px loose cloud → cursor condensation + halo',renderer:'Wanted source coordinates → THREE.ShaderMaterial / GLSL',source:impact.catalogSource};
const introState={p:0};
gsap.timeline({delay:2.6})
  .to(introState,{p:.3,duration:1.25,ease:'power2.inOut',onUpdate:()=>impact.setProgress(introState.p)})
  .call(()=>morphTitle('Are you ready?'))
  .to(introState,{p:.52,duration:1.25,ease:'power2.inOut',onUpdate:()=>impact.setProgress(introState.p)},'+=.32')
  .call(()=>{introReady=true;morphTitle('Already.');audioOn()})
  .to(introState,{p:.70,duration:1.15,ease:'power2.inOut',onUpdate:()=>impact.setProgress(introState.p)},'<')
  .to('.sponsor-original',{autoAlpha:0,y:-18,duration:.45},'<.35')
  .to('.feedit-brand',{autoAlpha:1,y:0,duration:.6,ease:'expo.out'},'<')
  .to('.intro-bar',{autoAlpha:0,y:35,duration:.55},'<.1')
  .to('.scroll-cue',{autoAlpha:1,duration:.5},'-=.1');

ScrollTrigger.create({trigger:'.hero-scroll',start:'top top',end:'bottom bottom',onUpdate:self=>impact.setProgress(Math.max(introState.p,.70+self.progress*.06))});

const zipTL=gsap.timeline({scrollTrigger:{trigger:'.zip-scroll',start:'top top',end:'bottom bottom',scrub:.6,onUpdate:self=>{
  think.setProgress(clamp((self.progress-.22)/.58,0,1));
  think.alpha=clamp((self.progress-.24)*2.15,0,1);
}}});
zipTL.to('.zip-photo',{clipPath:'inset(0 0 0% 0)',ease:'none'},0).to('.zip-seam',{opacity:1,ease:'none'},0).to('#zipPull',{top:'96%',ease:'none'},0).to('.zip-copy',{xPercent:-120,opacity:0,duration:.28,ease:'power2.in'},.28).to('#thinkCanvas,.think-label',{opacity:1,duration:.34,ease:'power2.out'},.36);

const lacePath=$('#laceDraw');
const laceLength=lacePath.getTotalLength();
gsap.set(lacePath,{strokeDasharray:laceLength,strokeDashoffset:laceLength});
gsap.to(lacePath,{strokeDashoffset:0,ease:'none',scrollTrigger:{trigger:'.why',start:'top 72%',end:'bottom 82%',scrub:.45,onUpdate:self=>{
  const tip=$('.lace-tip');
  tip.style.opacity=String(Math.sin(self.progress*Math.PI)*.8);
  tip.style.top=`${8+self.progress*84}%`;
}}});
gsap.to('.lace-reveal',{scale:1.08,yPercent:-3,ease:'none',scrollTrigger:{trigger:'.why',start:'top bottom',end:'bottom top',scrub:true}});
gsap.utils.toArray('.why-intro,.story-card,.signal-cloud,.stats,.unify').forEach(element=>gsap.from(element,{y:90,opacity:0,scale:.97,duration:1.1,ease:'expo.out',scrollTrigger:{trigger:element,start:'top 78%',toggleActions:'play none none reverse'}}));
gsap.utils.toArray('.orbit').forEach((element,index)=>gsap.from(element,{scale:.72,opacity:0,duration:1,delay:index*.08,ease:'expo.out',scrollTrigger:{trigger:'.orbit-map',start:'top 70%'}}));

build.alpha=0;
const buildTL=gsap.timeline({scrollTrigger:{trigger:'.build-scroll',start:'top top',end:'bottom bottom',scrub:.7,onUpdate:self=>{
  build.alpha=clamp(self.progress*2.2,0,1);
  build.setProgress(self.progress);
}}});
buildTL.from('.build-copy',{opacity:0,y:80,ease:'power2.out'},.28).from('.build-copy h2',{clipPath:'inset(100% 0 0)',y:40,ease:'expo.out'},.38).from('.build-copy p,.build-button',{opacity:0,y:25,stagger:.08,ease:'power2.out'},.56);

ScrollTrigger.create({trigger:'.zip-scroll',start:'top 45%',endTrigger:'.build-scroll',end:'top 10%',onEnter:()=>$('.wanted-nav').classList.add('hidden'),onLeaveBack:()=>$('.wanted-nav').classList.remove('hidden')});
ScrollTrigger.create({start:0,end:'max',onUpdate:self=>$('.progress i').style.transform=`scaleX(${self.progress})`});

if(REDUCED){impact.setProgress(1);think.alpha=1;think.setProgress(1);build.alpha=1;build.setProgress(1);$('.scroll-cue').style.opacity=1;}
}

const audio=$('#themeAudio');
const sound=$('#soundToggle');
let audioPrimed=false;
async function audioOn(){
  try{
    audio.volume=.42;
    await audio.play();
    sound.classList.add('on');
    sound.querySelector('span').textContent='SOUND ON';
    removeUnlockers();
  }catch(error){}
}
function audioOff(){
  audio.pause();
  sound.classList.remove('on');
  sound.querySelector('span').textContent='SOUND OFF';
}
sound.addEventListener('click',()=>audio.paused?audioOn():audioOff());
async function unlockAudio(){
  if(introReady){audioOn();return}
  if(audioPrimed)return;
  try{
    const volume=audio.volume;
    audio.volume=0;
    await audio.play();
    audio.pause();audio.currentTime=0;audio.volume=volume||.42;audioPrimed=true;
  }catch(error){}
}
function removeUnlockers(){['pointerdown','wheel','touchstart','keydown'].forEach(type=>removeEventListener(type,unlockAudio))}
['pointerdown','wheel','touchstart','keydown'].forEach(type=>addEventListener(type,unlockAudio,{passive:true}));

document.querySelectorAll('[data-platform]').forEach(anchor=>anchor.addEventListener('click',event=>{
  if(event.metaKey||event.ctrlKey||REDUCED)return;
  event.preventDefault();
  const curtain=$('#curtain');
  gsap.timeline({onComplete:()=>location.href=PLATFORM_URL}).to(curtain,{y:0,duration:.8,ease:'expo.inOut'}).from('.curtain-mark',{scale:.4,rotate:-12,opacity:0,duration:.65,ease:'expo.out'},'-=.25').from('.transition-curtain span',{opacity:0,y:10,duration:.4},'-=.3');
}));

Promise.all([impact.ready,think.ready,build.ready]).then(startExperience).catch(error=>console.error('FEEDiT particle experience failed to initialize.',error));
