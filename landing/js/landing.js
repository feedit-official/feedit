const PLATFORM_URL='https://fee-di-t-frontend.vercel.app/';
const REDUCED=matchMedia('(prefers-reduced-motion: reduce)').matches;
const $=(selector,root=document)=>root.querySelector(selector);
const clamp=(n,a,b)=>Math.min(b,Math.max(a,n));

const impact=new GPUParticleBody($('#impactCanvas'),{group:true,count:78000});
const think=new GPUParticleBody($('#thinkCanvas'),{pose:'think',cxRatio:.69,cyRatio:.51,heightRatio:.84});
const build=new GPUParticleBody($('#buildCanvas'),{pose:'build',cxRatio:.68,cyRatio:.5,heightRatio:.92});
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

function enterAlreadyState(){
  introReady=true;
  document.body.classList.add('intro-complete');
  morphTitle('Already.');
  audioOn(true);
  gsap.to('.wanted-nav',{yPercent:-110,autoAlpha:0,duration:.7,ease:'expo.inOut',onComplete:()=>$('.wanted-nav').classList.add('hidden')});
  gsap.to('.entry-caption',{y:0,autoAlpha:1,duration:.72,ease:'expo.out',delay:.28});
}

function startExperience(){
window.FEEDiTParticleStats={hero:impact.particleCount,think:think.particleCount,build:build.particleCount,models:7,poses:['WANTED BUILD','WANTED THINK','WANTED IMPACT','WANTED THINK','WANTED BUILD','WANTED THINK SINGLE','WANTED BUILD SINGLE'],interaction:'32% ambient cohesion → original 2400px cursor condensation + shader halo + tracked backlights',renderer:'Wanted source coordinates → THREE.ShaderMaterial / GLSL',source:impact.catalogSource};
const introState={p:0};
gsap.timeline({delay:2.6})
  .to(introState,{p:.3,duration:1.25,ease:'power2.inOut',onUpdate:()=>impact.setProgress(introState.p)})
  .call(()=>morphTitle('Are you ready?'))
  .to(introState,{p:.52,duration:1.25,ease:'power2.inOut',onUpdate:()=>impact.setProgress(introState.p)},'+=.32')
  .call(enterAlreadyState)
  .to(introState,{p:.70,duration:1.15,ease:'power2.inOut',onUpdate:()=>impact.setProgress(introState.p)},'<')
  .to('.sponsor-original',{autoAlpha:0,y:-18,duration:.45},'<.35')
  .to('.feedit-brand',{autoAlpha:1,y:0,duration:.6,ease:'expo.out'},'<')
  .to('.intro-bar',{autoAlpha:0,y:35,duration:.55},'<.1')
  .to('.scroll-cue',{autoAlpha:1,duration:.5},'-=.1');

ScrollTrigger.create({trigger:'.hero-scroll',start:'top top',end:'bottom bottom',onUpdate:self=>impact.setProgress(Math.max(introState.p,.70+self.progress*.06))});

const thinkReveal={p:0,a:0};
gsap.set('#thinkCanvas',{opacity:0,xPercent:14,scale:.955,transformOrigin:'70% 50%'});
gsap.set('.think-label,.think-backlight',{opacity:0});
function revealThink(show){
  gsap.killTweensOf(thinkReveal);
  gsap.to(thinkReveal,{p:show?1:0,a:show?1:0,duration:show?1.2:.52,ease:show?'power3.out':'power2.inOut',onUpdate:()=>{
    think.setProgress(clamp(thinkReveal.p,0,1));
    think.alpha=clamp(thinkReveal.a,0,1);
  }});
  gsap.to('#thinkCanvas',{opacity:show?1:0,xPercent:show?0:14,scale:show?1:.955,duration:show?1.28:.5,ease:show?'elastic.out(1,.72)':'power2.inOut',overwrite:true});
  gsap.to('.think-label,.think-backlight',{opacity:show?1:0,y:show?0:24,duration:show?.82:.35,ease:show?'back.out(1.8)':'power2.in',overwrite:true});
}
ScrollTrigger.create({trigger:'.zip-scroll',start:'top 78%',onEnter:()=>revealThink(true),onEnterBack:()=>revealThink(true),onLeaveBack:()=>revealThink(false)});
gsap.from('.zip-copy',{x:-72,opacity:0,duration:1.15,ease:'elastic.out(1,.78)',scrollTrigger:{trigger:'.zip-scroll',start:'top 80%',toggleActions:'play none none reverse'}});

gsap.utils.toArray('.why-intro,.story-card,.signal-cloud,.stats,.unify').forEach(element=>{
  const side=element.dataset.side;
  gsap.from(element,{x:side==='right'?92:side==='left'?-92:0,y:side?0:72,opacity:0,scale:.975,duration:1.24,ease:'elastic.out(1,.82)',scrollTrigger:{trigger:element,start:'top 82%',toggleActions:'play none none reverse'}});
});
gsap.utils.toArray('.orbit').forEach((element,index)=>gsap.from(element,{scale:.72,opacity:0,duration:1,delay:index*.08,ease:'expo.out',scrollTrigger:{trigger:'.orbit-map',start:'top 70%'}}));

build.alpha=0;
const buildReveal={p:0,a:0};
gsap.set('#buildCanvas',{opacity:0,xPercent:14,scale:.955,transformOrigin:'70% 50%'});
gsap.set('.build-backlight',{opacity:0});
function revealBuild(show){
  gsap.killTweensOf(buildReveal);
  gsap.to(buildReveal,{p:show?1:0,a:show?1:0,duration:show?1.22:.52,ease:show?'power3.out':'power2.inOut',onUpdate:()=>{
    build.setProgress(clamp(buildReveal.p,0,1));
    build.alpha=clamp(buildReveal.a,0,1);
  }});
  gsap.to('#buildCanvas',{opacity:show?1:0,xPercent:show?0:14,scale:show?1:.955,duration:show?1.3:.5,ease:show?'elastic.out(1,.72)':'power2.inOut',overwrite:true});
  gsap.to('.build-backlight',{opacity:show?.42:0,duration:show?.9:.35,ease:'power2.out',overwrite:true});
}
ScrollTrigger.create({trigger:'.build-scroll',start:'top 78%',onEnter:()=>revealBuild(true),onEnterBack:()=>revealBuild(true),onLeaveBack:()=>revealBuild(false)});
gsap.from('.build-copy',{opacity:0,x:-82,duration:1.2,ease:'elastic.out(1,.8)',scrollTrigger:{trigger:'.build-scroll',start:'top 80%',toggleActions:'play none none reverse'}});
gsap.from('.build-copy h2,.build-copy p,.build-button',{opacity:0,y:34,stagger:.07,duration:.86,ease:'back.out(1.7)',scrollTrigger:{trigger:'.build-scroll',start:'top 72%',toggleActions:'play none none reverse'}});

ScrollTrigger.create({trigger:'.zip-scroll',start:'top 45%',endTrigger:'.build-scroll',end:'top 10%',onEnter:()=>$('.wanted-nav').classList.add('hidden'),onLeaveBack:()=>{if(!introReady)$('.wanted-nav').classList.remove('hidden')}});
ScrollTrigger.create({start:0,end:'max',onUpdate:self=>$('.progress i').style.transform=`scaleX(${self.progress})`});

if(REDUCED){impact.setProgress(1);think.alpha=1;think.setProgress(1);build.alpha=1;build.setProgress(1);$('.scroll-cue').style.opacity=1;}
}

const audio=$('#themeAudio');
const sound=$('#soundToggle');
const experienceGate=$('#experienceGate');
const experienceEnter=$('#experienceEnter');
let audioWanted=true;
let audioUnlocked=false;
let audioUnlocking=false;
const AUDIO_VOLUME=.42;
const AUDIO_PRIME_VOLUME=.001;
const AUDIO_UNLOCK_EVENTS=['pointerdown','pointerup','touchstart','touchend','keydown','wheel','scroll'];
function paintSoundState(state){
  const isOn=state==='on';
  sound.classList.toggle('on',isOn);
  sound.classList.toggle('off',state==='off');
  sound.classList.toggle('pending',state==='pending');
  sound.setAttribute('aria-pressed',String(isOn));
  sound.setAttribute('aria-label',isOn?'배경 음악 끄기':'배경 음악 켜기');
}
async function primeAudio(){
  try{
    audio.muted=true;
    audio.volume=0;
    await audio.play();
  }catch(error){}
}
async function audioOn(restart=false,fromUser=false){
  audioWanted=true;
  try{
    if(restart)audio.currentTime=0;
    audio.muted=false;
    audio.volume=AUDIO_VOLUME;
    await audio.play();
    if(fromUser)audioUnlocked=true;
    paintSoundState('on');
    if(introReady&&audioUnlocked)removeUnlockers();
  }catch(error){
    audio.muted=true;
    audio.volume=0;
    paintSoundState('pending');
  }
}
function audioOff(){
  audioWanted=false;
  audio.pause();
  paintSoundState('off');
}
sound.addEventListener('click',event=>{
  event.stopPropagation();
  audioWanted&&!audio.paused&&!audio.muted&&audio.volume>0?audioOff():audioOn(false,true);
});
async function unlockAudio(event){
  if(event.target===sound||sound.contains(event.target)||experienceGate.contains(event.target))return;
  if(!audioWanted||audioUnlocking)return;
  const isActivationEvent=['pointerdown','pointerup','touchstart','touchend','keydown'].includes(event.type);
  if(introReady){
    audioUnlocking=true;
    try{await audioOn(false,isActivationEvent)}finally{audioUnlocking=false}
    return;
  }
  if(!isActivationEvent)return;
  audioUnlocking=true;
  try{
    audio.muted=false;
    audio.volume=AUDIO_PRIME_VOLUME;
    await audio.play();
    audioUnlocked=true;
  }catch(error){
    audio.muted=true;
  }finally{
    audioUnlocking=false;
  }
}
function removeUnlockers(){AUDIO_UNLOCK_EVENTS.forEach(type=>removeEventListener(type,unlockAudio))}
AUDIO_UNLOCK_EVENTS.forEach(type=>addEventListener(type,unlockAudio,{passive:true}));
primeAudio();

let particlesReady=false;
let gateDismissed=false;
let experienceStarted=false;
function launchExperience(){
  if(experienceStarted||!particlesReady||!gateDismissed)return;
  experienceStarted=true;
  startExperience();
}
function acceptExperience(){
  if(experienceGate.classList.contains('is-leaving'))return;
  experienceGate.classList.add('is-leaving');
  audioWanted=true;
  try{
    audio.muted=false;
    audio.volume=AUDIO_PRIME_VOLUME;
    const playAttempt=audio.play();
    if(playAttempt)playAttempt.then(()=>{audioUnlocked=true}).catch(()=>{audio.muted=true;audio.volume=0});
  }catch(error){
    audio.muted=true;
    audio.volume=0;
  }
  gsap.timeline({onComplete:()=>{
    experienceGate.remove();
    requestAnimationFrame(()=>{
      document.body.classList.remove('experience-locked');
      gateDismissed=true;
      requestAnimationFrame(launchExperience);
    });
  }})
    .to('.experience-enter span',{letterSpacing:'.5em',opacity:0,y:-5,duration:.42,ease:'power2.in'},0)
    .to('.experience-enter i',{width:'42vw',opacity:.16,duration:.62,ease:'expo.inOut'},0)
    .to('.experience-enter i',{opacity:0,duration:.26,ease:'power1.out'},.46)
    .to(experienceGate,{opacity:0,duration:.82,ease:'power2.inOut'},.12);
}
experienceEnter.addEventListener('click',acceptExperience);

document.querySelectorAll('[data-platform]').forEach(anchor=>anchor.addEventListener('click',event=>{
  if(event.metaKey||event.ctrlKey||REDUCED)return;
  event.preventDefault();
  const curtain=$('#curtain');
  gsap.timeline({onComplete:()=>location.href=PLATFORM_URL}).to(curtain,{y:0,duration:.8,ease:'expo.inOut'}).from('.curtain-mark',{scale:.4,rotate:-12,opacity:0,duration:.65,ease:'expo.out'},'-=.25').from('.transition-curtain span',{opacity:0,y:10,duration:.4},'-=.3');
}));

Promise.all([impact.ready,think.ready,build.ready]).then(()=>{particlesReady=true;launchExperience()}).catch(error=>console.error('FEEDiT particle experience failed to initialize.',error));
