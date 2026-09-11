const PLATFORM_URL='https://fee-di-t-frontend.vercel.app/';
const REDUCED=matchMedia('(prefers-reduced-motion: reduce)').matches;
const $=(selector,root=document)=>root.querySelector(selector);
const clamp=(n,a,b)=>Math.min(b,Math.max(a,n));
const smoothRange=(value,start,end)=>{const t=clamp((value-start)/(end-start),0,1);return t*t*(3-2*t)};

const impact=new GPUParticleBody($('#impactCanvas'),{group:true,count:78000});
const build=new GPUParticleBody($('#buildCanvas'),{pose:'build',cxRatio:.68,cyRatio:.5,heightRatio:.92});
const storyFilm=$('#storyFilm');
const storyVideo=$('#storyFilmVideo');
const storyPhases=$('#storyPhases');
let introReady=false;
let storyVideoPrepared=false;
let storyVideoActive=false;

function prepareStoryVideo(){
  if(storyVideoPrepared||!storyVideo)return;
  const source=storyVideo.querySelector('source[data-src]');
  if(source){
    source.src=source.dataset.src;
    source.removeAttribute('data-src');
  }
  storyVideo.preload='auto';
  storyVideo.load();
  storyVideoPrepared=true;
}

function setStoryFilm(active){
  if(!storyFilm||!storyVideo)return;
  storyVideoActive=active;
  storyFilm.classList.toggle('is-active',active);
  document.body.classList.toggle('story-film-active',active);
  if(active){
    prepareStoryVideo();
    const playAttempt=storyVideo.play();
    if(playAttempt)playAttempt.catch(()=>{});
  }else{
    storyVideo.pause();
  }
}

function setStoryPhase(phase){
  if(!storyPhases)return;
  storyPhases.dataset.active=phase;
  storyPhases.querySelectorAll('[data-story-phase]').forEach(item=>item.classList.toggle('active',item.dataset.storyPhase===phase));
}

gsap.registerPlugin(ScrollTrigger);
let lenis=null;
if(window.Lenis&&!REDUCED){
  lenis=new Lenis({duration:1.05,smoothWheel:true});
  lenis.on('scroll',ScrollTrigger.update);
  gsap.ticker.add(time=>lenis.raf(time*1000));
  gsap.ticker.lagSmoothing(0);
  lenis.stop();
}

function morphTitle(text,onSwap){
  const title=$('#heroTitle');
  gsap.to(title,{yPercent:-120,opacity:0,duration:.48,ease:'power3.in',onComplete:()=>{
    title.textContent=text;
    if(onSwap)onSwap();
    gsap.set(title,{yPercent:120});
    gsap.to(title,{yPercent:0,opacity:1,duration:.75,ease:'expo.out'});
  }});
}

function enterAlreadyState(){
  document.body.classList.add('intro-complete');
  setStoryPhase('impact');
  morphTitle('Already.',()=>{
    introReady=true;
    audioOn(true);
  });
  gsap.to('.wanted-nav',{yPercent:-110,autoAlpha:0,duration:.7,ease:'expo.inOut',onComplete:()=>$('.wanted-nav').classList.add('hidden')});
  gsap.to('.entry-caption',{y:0,autoAlpha:1,duration:.72,ease:'expo.out',delay:.28});
}

function startExperience(){
window.FEEDiTParticleStats={hero:impact.particleCount,build:build.particleCount,models:6,poses:['WANTED BUILD','WANTED THINK','WANTED IMPACT','WANTED THINK','WANTED BUILD','WANTED BUILD SINGLE'],interaction:'32% ambient cohesion → original 2400px cursor condensation + shader halo + tracked backlights',renderer:'Wanted source coordinates → THREE.ShaderMaterial / GLSL',source:impact.catalogSource};
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

gsap.from('.zip-copy',{x:-72,opacity:0,duration:1.15,ease:'elastic.out(1,.78)',scrollTrigger:{trigger:'.zip-scroll',start:'top 80%',toggleActions:'play none none reverse'}});

gsap.utils.toArray('.why-intro,.story-card,.signal-cloud,.stats,.unify').forEach(element=>{
  const side=element.dataset.side;
  gsap.from(element,{x:side==='right'?92:side==='left'?-92:0,y:side?0:72,opacity:0,scale:.975,duration:1.24,ease:'elastic.out(1,.82)',scrollTrigger:{trigger:element,start:'top 82%',toggleActions:'play none none reverse'}});
});
gsap.from('.signal-chip',{opacity:0,scale:.55,duration:.72,stagger:{each:.055,from:'random'},ease:'back.out(2.2)',scrollTrigger:{trigger:'.signal-cloud',start:'top 72%',toggleActions:'play none none reverse'}});
gsap.from('.signal-core',{opacity:0,scale:.68,duration:1.05,ease:'elastic.out(1,.55)',scrollTrigger:{trigger:'.signal-cloud',start:'top 74%',toggleActions:'play none none reverse'}});
gsap.from('.why-stream>*',{opacity:0,x:-18,stagger:.075,duration:.7,ease:'power3.out',scrollTrigger:{trigger:'.why-stream',start:'top 84%',toggleActions:'play none none reverse'}});
gsap.from('.life-number>*',{opacity:0,y:34,rotateX:-28,stagger:.13,duration:.9,ease:'back.out(1.8)',scrollTrigger:{trigger:'.card-life',start:'top 72%',toggleActions:'play none none reverse'}});
gsap.from('.journey>*',{opacity:0,scaleX:0,transformOrigin:'left',stagger:.08,duration:.65,ease:'power3.out',scrollTrigger:{trigger:'.card-gap',start:'top 72%',toggleActions:'play none none reverse'}});
const signalPanel=$('.signal-cloud');
if(signalPanel&&!REDUCED&&matchMedia('(pointer:fine)').matches){
  signalPanel.addEventListener('pointermove',event=>{
    const bounds=signalPanel.getBoundingClientRect();
    signalPanel.style.setProperty('--radar-x',`${(((event.clientX-bounds.left)/bounds.width-.5)*22).toFixed(2)}px`);
    signalPanel.style.setProperty('--radar-y',`${(((event.clientY-bounds.top)/bounds.height-.5)*18).toFixed(2)}px`);
  });
  signalPanel.addEventListener('pointerleave',()=>{
    signalPanel.style.setProperty('--radar-x','0px');
    signalPanel.style.setProperty('--radar-y','0px');
  });
}
gsap.utils.toArray('.orbit').forEach((element,index)=>gsap.from(element,{scale:.72,opacity:0,duration:1,delay:index*.08,ease:'expo.out',scrollTrigger:{trigger:'.orbit-map',start:'top 70%'}}));

gsap.utils.toArray('.stats strong[data-count]').forEach(element=>{
  const end=Number(element.dataset.count);
  const decimals=(String(element.dataset.count).split('.')[1]||'').length;
  const suffix=element.dataset.suffix||'';
  const counter={value:0};
  ScrollTrigger.create({trigger:element,start:'top 84%',once:true,onEnter:()=>gsap.to(counter,{value:end,duration:1.45,ease:'power3.out',onUpdate:()=>{element.innerHTML=`${counter.value.toFixed(decimals)}<sup>${suffix}</sup>`}})});
});
const frictionCard=$('.card-gap');
if(frictionCard&&matchMedia('(pointer:fine)').matches){
  frictionCard.addEventListener('pointermove',event=>{
    const bounds=frictionCard.getBoundingClientRect();
    frictionCard.style.setProperty('--fx',`${((event.clientX-bounds.left)/bounds.width*100).toFixed(1)}%`);
    frictionCard.style.setProperty('--fy',`${((event.clientY-bounds.top)/bounds.height*100).toFixed(1)}%`);
  });
}

const solutionSection=$('.solution-scroll');
const solutionSticky=$('.solution-sticky');
const solutionScenes=gsap.utils.toArray('.solution-scene');
const solutionDots=gsap.utils.toArray('[data-solution-go]');
const solutionCounter=$('.solution-control-count strong');
const solutionPrev=$('[data-solution-prev]');
const solutionNext=$('[data-solution-next]');
let activeSolution=0;
let solutionTimer=null;
function setSolutionStep(index,animate=true){
  activeSolution=(index+solutionScenes.length)%solutionScenes.length;
  solutionDots.forEach((dot,dotIndex)=>{
    const selected=dotIndex===activeSolution;
    dot.classList.toggle('active',selected);
    dot.setAttribute('aria-pressed',String(selected));
  });
  if(solutionCounter)solutionCounter.textContent=String(activeSolution+1).padStart(2,'0');
  if(!animate)return;
  solutionScenes.forEach((scene,sceneIndex)=>{
    gsap.killTweensOf(scene);
    if(sceneIndex===activeSolution){
      scene.classList.add('active');
      gsap.fromTo(scene,{autoAlpha:0,yPercent:2.2,scale:.992},{autoAlpha:1,yPercent:0,scale:1,duration:.68,ease:'expo.out',overwrite:true,clearProps:'clipPath'});
      const chartLine=$('.chart-line',scene);
      if(chartLine)gsap.fromTo(chartLine,{strokeDasharray:900,strokeDashoffset:900},{strokeDashoffset:0,duration:.82,ease:'power2.out'});
      const editorial=$('.feed-editorial img',scene);
      if(editorial)gsap.fromTo(editorial,{scale:1.08},{scale:1.02,duration:1.1,ease:'power2.out'});
      const vote=$('.vote-meter span:first-child',scene);
      if(vote)gsap.fromTo(vote,{width:'18%'},{width:'72%',duration:.78,ease:'expo.out'});
    }else{
      scene.classList.remove('active');
      gsap.set(scene,{autoAlpha:0,yPercent:0,scale:1,clipPath:'none'});
    }
  });
}
if(solutionSection&&solutionScenes.length===3&&!REDUCED){
  gsap.set(solutionScenes,{autoAlpha:0,yPercent:3.5,scale:.987});
  gsap.set(solutionScenes[0],{autoAlpha:1,yPercent:0,scale:1});
  setSolutionStep(0,false);
  const startSolutionCycle=()=>{
    if(solutionTimer||document.hidden)return;
    solutionTimer=setInterval(()=>setSolutionStep(activeSolution+1),3000);
  };
  const stopSolutionCycle=()=>{
    if(!solutionTimer)return;
    clearInterval(solutionTimer);
    solutionTimer=null;
  };
  const selectSolution=index=>{
    stopSolutionCycle();
    setSolutionStep(index);
    startSolutionCycle();
  };
  solutionDots.forEach((dot,index)=>dot.addEventListener('click',()=>selectSolution(index)));
  if(solutionPrev)solutionPrev.addEventListener('click',()=>selectSolution(activeSolution-1));
  if(solutionNext)solutionNext.addEventListener('click',()=>selectSolution(activeSolution+1));
  const solutionObserver=new IntersectionObserver(entries=>entries.forEach(entry=>entry.isIntersecting&&entry.intersectionRatio>.28?startSolutionCycle():stopSolutionCycle()),{threshold:[0,.28,.55]});
  solutionObserver.observe(solutionSection);
  document.addEventListener('visibilitychange',()=>document.hidden?stopSolutionCycle():(solutionSection.getBoundingClientRect().top<innerHeight&&solutionSection.getBoundingClientRect().bottom>0&&startSolutionCycle()));

  if(matchMedia('(pointer:fine)').matches){
    solutionSticky.addEventListener('pointermove',event=>{
      const bounds=solutionSticky.getBoundingClientRect();
      const dx=(event.clientX-bounds.left)/bounds.width-.5;
      const dy=(event.clientY-bounds.top)/bounds.height-.5;
      solutionScenes.forEach((scene,index)=>{
        const windowElement=$('.product-window',scene);
        if(!windowElement)return;
        gsap.to(windowElement,{x:index===activeSolution?dx*13:0,y:index===activeSolution?dy*9:0,rotateY:index===activeSolution?dx*1.4:0,rotateX:index===activeSolution?-dy*.9:0,duration:.75,ease:'power3.out',overwrite:true});
      });
    });
    solutionSticky.addEventListener('pointerleave',()=>gsap.to('.solution-scroll .product-window',{x:0,y:0,rotateX:0,rotateY:0,duration:.8,ease:'power3.out',overwrite:true}));
  }
}

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
ScrollTrigger.create({
  trigger:'.zip-scroll',
  start:'top 92%',
  endTrigger:'.build-scroll',
  end:'top 5%',
  onEnter:()=>{setStoryFilm(true);setStoryPhase('think')},
  onEnterBack:()=>{setStoryFilm(true);setStoryPhase('think')},
  onLeave:()=>{setStoryFilm(false);setStoryPhase('build')},
  onLeaveBack:()=>{setStoryFilm(false);setStoryPhase('impact')}
});
ScrollTrigger.create({start:0,end:'max',onUpdate:self=>$('.progress i').style.transform=`scaleX(${self.progress})`});

if(REDUCED){impact.setProgress(1);build.alpha=1;build.setProgress(1);$('.scroll-cue').style.opacity=1;}
}

const audio=$('#themeAudio');
const sound=$('#soundToggle');
const experienceGate=$('#experienceGate');
const experienceEnter=$('#experienceEnter');
let audioWanted=true;
let audioUnlocked=false;
let audioUnlocking=false;
let introScrollReleased=false;
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
function releaseIntroScrollIfReady(){
  if(introScrollReleased||!introReady||audio.paused||audio.muted||audio.volume<=0)return;
  introScrollReleased=true;
  document.documentElement.classList.remove('experience-locked');
  document.body.classList.remove('experience-locked');
  if(lenis)lenis.start();
  requestAnimationFrame(()=>ScrollTrigger.refresh());
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
    releaseIntroScrollIfReady();
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
  prepareStoryVideo();
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

document.addEventListener('visibilitychange',()=>{
  if(document.hidden){
    storyVideo.pause();
  }else if(storyVideoActive){
    const playAttempt=storyVideo.play();
    if(playAttempt)playAttempt.catch(()=>{});
  }
});

document.querySelectorAll('[data-platform]').forEach(anchor=>anchor.addEventListener('click',event=>{
  if(event.metaKey||event.ctrlKey||REDUCED)return;
  event.preventDefault();
  const curtain=$('#curtain');
  gsap.timeline({onComplete:()=>location.href=PLATFORM_URL}).to(curtain,{y:0,duration:.8,ease:'expo.inOut'}).from('.curtain-mark',{scale:.4,rotate:-12,opacity:0,duration:.65,ease:'expo.out'},'-=.25').from('.transition-curtain span',{opacity:0,y:10,duration:.4},'-=.3');
}));

Promise.all([impact.ready,build.ready]).then(()=>{particlesReady=true;launchExperience()}).catch(error=>console.error('FEEDiT particle experience failed to initialize.',error));
