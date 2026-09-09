(function(){
  'use strict';
  if(!window.THREE||!window.THREE.GLTFLoader)throw new Error('Three.js and GLTFLoader are required.');

  const T=window.THREE;
  const TAU=Math.PI*2;
  const clamp=(n,a,b)=>Math.min(b,Math.max(a,n));
  const lerp=(a,b,t)=>a+(b-a)*t;
  const REDUCED=matchMedia('(prefers-reduced-motion: reduce)').matches;
  const MODEL_LOCAL='./assets/human-cc0.glb';
  const MODEL_REMOTE='https://cdn.jsdelivr.net/gh/UMRAM-Bilkent/supine-human-model@main/assets/human.glb';
  const MODEL_URL=location.protocol==='file:'?MODEL_REMOTE:MODEL_LOCAL;

  const POINTER={x:innerWidth*.5,y:innerHeight*.46,vx:0,vy:0,lastMove:performance.now(),inside:true};
  addEventListener('pointermove',event=>{
    const now=performance.now();
    if(POINTER.inside){
      const dt=Math.max(10,now-POINTER.lastMove);
      POINTER.vx=lerp(POINTER.vx,(event.clientX-POINTER.x)/dt,.62);
      POINTER.vy=lerp(POINTER.vy,(event.clientY-POINTER.y)/dt,.62);
    }
    POINTER.x=event.clientX;POINTER.y=event.clientY;POINTER.lastMove=now;POINTER.inside=true;
  },{passive:true});
  const keepEdgeResponse=()=>{
    const speed=Math.hypot(POINTER.vx,POINTER.vy);
    if(speed>.02){POINTER.x+=POINTER.vx/speed*140;POINTER.y+=POINTER.vy/speed*140}
    else{
      const edges=[POINTER.x,innerWidth-POINTER.x,POINTER.y,innerHeight-POINTER.y],edge=edges.indexOf(Math.min(...edges));
      if(edge===0)POINTER.x-=140;else if(edge===1)POINTER.x+=140;else if(edge===2)POINTER.y-=140;else POINTER.y+=140;
    }
    POINTER.inside=true;
  };
  document.addEventListener('pointerout',event=>{if(!event.relatedTarget)keepEdgeResponse()},{passive:true});
  document.addEventListener('mouseleave',keepEdgeResponse,{passive:true});

  // Exact Wanted 2026 fill pairs, remapped to visual left-to-right order.
  const HERO_PALETTES=[[[243,160,255],[0,173,255]],[[255,109,26],[242,203,119]],[[71,181,255],[149,238,128]],[[131,100,255],[126,188,255]],[[255,142,255],[255,140,142]]];
  const SINGLE_PALETTES={think:['#77e7ff','#7258ff'],build:['#ffad88','#ff4c36']};
  const POSE_SPECS={
    dancer:{clip:'Walk',phase:.08,lean:-.055,twist:-.12,profile:'leggy',editorial:'runwayOpen'},
    crouch:{clip:'Walk',phase:.25,lean:.06,twist:.14,profile:'androgynous',editorial:'runwayCross'},
    impact:{clip:'Walk',phase:.43,lean:-.025,twist:-.08,profile:'couture',editorial:'runwayPower'},
    think:{clip:'Walk',phase:.62,lean:.05,twist:.13,profile:'runway',editorial:'runwayTurn'},
    build:{clip:'Walk',phase:.82,lean:-.06,twist:-.15,profile:'athletic',editorial:'runwayExit'},
    thinkSingle:{clip:'Walk',phase:.62,lean:.055,twist:.15,profile:'runway',editorial:'runwayTurn'},
    buildSingle:{clip:'Walk',phase:.43,lean:-.04,twist:-.12,profile:'couture',editorial:'runwayPower'}
  };

  // Five editorial body profiles. The same licensed skin topology is retargeted
  // after animation, so each cloud keeps real joints and surface volume while
  // reading as a different high-fashion silhouette at particle distance.
  const FASHION_PROFILES={
    leggy:{leg:1.31,upper:.94,waist:.77,shoulder:1.02,hip:.98,head:.91,depth:.91,curve:-.025},
    androgynous:{leg:1.2,upper:.98,waist:.84,shoulder:1.1,hip:.92,head:.94,depth:.88,curve:.018},
    couture:{leg:1.27,upper:.96,waist:.73,shoulder:1.13,hip:1.04,head:.89,depth:.94,curve:-.014},
    runway:{leg:1.34,upper:.92,waist:.76,shoulder:.98,hip:1.01,head:.9,depth:.89,curve:.024},
    athletic:{leg:1.19,upper:1.0,waist:.81,shoulder:1.16,hip:.97,head:.92,depth:.97,curve:-.02}
  };

  const D=Math.PI/180;
  const EDITORIAL_POSES={
    runwayOpen:{
      Hips:[-2,8,-4],Spine:[2,-6,3],Spine1:[0,-4,2],Head:[-2,7,2],
      LeftShoulder:[0,-3,-4],LeftArm:[-6,4,-13],LeftForeArm:[-5,2,-8],
      RightShoulder:[0,3,3],RightArm:[5,-3,11],RightForeArm:[-3,0,7],
      LeftUpLeg:[-3,-2,5],RightUpLeg:[2,3,-5]
    },
    runwayCross:{
      Hips:[1,-8,5],Spine:[-2,8,-3],Spine2:[0,5,-2],Head:[-3,-7,-2],
      LeftShoulder:[0,-4,-5],LeftArm:[-8,5,-18],LeftForeArm:[-7,2,-11],
      RightShoulder:[0,4,4],RightArm:[7,-4,14],RightForeArm:[-4,0,8],
      LeftUpLeg:[4,6,9],LeftLeg:[5,0,-2],RightUpLeg:[-3,-5,-9],RightLeg:[-4,0,2]
    },
    runwayPower:{
      Hips:[-2,4,-3],Spine:[1,-4,2],Spine1:[-1,-3,1],Spine2:[1,5,-1],Head:[-2,-4,1],
      LeftShoulder:[0,-3,-5],LeftArm:[-6,3,-11],LeftForeArm:[-4,-1,-6],
      RightShoulder:[0,4,5],RightArm:[6,-4,13],RightForeArm:[-5,1,8],
      LeftUpLeg:[-4,-2,6],LeftLeg:[6,0,-2],RightUpLeg:[3,3,-6],RightLeg:[-3,0,2]
    },
    runwayTurn:{
      Hips:[1,-12,5],Spine:[-2,10,-3],Spine1:[0,8,-2],Spine2:[0,7,-1],Neck:[1,-7,1],Head:[-3,-11,-2],
      LeftShoulder:[0,-4,-5],LeftArm:[-7,4,-16],LeftForeArm:[-5,1,-9],
      RightShoulder:[0,5,4],RightArm:[8,-6,18],RightForeArm:[-8,2,12],RightHand:[2,-5,5],
      LeftUpLeg:[3,5,8],LeftLeg:[4,0,-2],RightUpLeg:[-2,-4,-8],RightLeg:[-3,0,2]
    },
    runwayExit:{
      Hips:[-1,10,-5],Spine:[2,-9,3],Spine1:[0,-7,2],Neck:[-1,5,-1],Head:[2,10,2],
      LeftShoulder:[0,-4,-4],LeftArm:[-9,5,-19],LeftForeArm:[-6,1,-10],
      RightShoulder:[0,4,5],RightArm:[8,-5,17],RightForeArm:[-6,-1,11],
      LeftUpLeg:[-3,-5,8],LeftLeg:[7,0,-3],RightUpLeg:[3,5,-8],RightLeg:[-5,0,3]
    }
  };

  function hexRgb(hex){const n=parseInt(hex.slice(1),16);return[(n>>16)/255,(n>>8&255)/255,(n&255)/255]}
  function byteRgb(rgb){return rgb.map(value=>value/255)}
  function mixRgb(a,b,t){return[lerp(a[0],b[0],t),lerp(a[1],b[1],t),lerp(a[2],b[2],t)]}
  function gaussian(){let u=0,v=0;while(!u)u=Math.random();while(!v)v=Math.random();return Math.sqrt(-2*Math.log(u))*Math.cos(TAU*v)}

  function loadGLTF(){
    return new Promise((resolve,reject)=>new T.GLTFLoader().load(MODEL_URL,resolve,undefined,reject));
  }

  function setAnimationPose(gltf,spec){
    const scene=gltf.scene;
    const clip=gltf.animations.find(item=>item.name.toLowerCase().includes(spec.clip.toLowerCase()))||gltf.animations[0];
    if(clip){
      const mixer=new T.AnimationMixer(scene);
      const action=mixer.clipAction(clip);action.reset().play();
      mixer.update(Math.max(.001,clip.duration*spec.phase));
      scene.updateMatrixWorld(true);
    }
    applyEditorialPose(scene,spec.editorial);
    scene.traverse(object=>{if(object.isSkinnedMesh&&object.skeleton)object.skeleton.update()});
  }

  function applyEditorialPose(scene,poseName){
    const pose=EDITORIAL_POSES[poseName];
    if(!pose)return;
    const bones={};
    scene.traverse(object=>{if(object.isBone)bones[object.name]=object});
    Object.keys(pose).forEach(name=>{
      const bone=bones[name],rotation=pose[name];
      if(!bone)return;
      bone.rotation.x+=rotation[0]*D;
      bone.rotation.y+=rotation[1]*D;
      bone.rotation.z+=rotation[2]*D;
    });
    scene.updateMatrixWorld(true);
  }

  function skinnedVertex(mesh,index,target){
    target.fromBufferAttribute(mesh.geometry.attributes.position,index);
    if(mesh.isSkinnedMesh&&typeof mesh.boneTransform==='function')mesh.boneTransform(index,target);
    return target.applyMatrix4(mesh.matrixWorld);
  }

  function extractTriangles(scene){
    const triangles=[];
    const a=new T.Vector3(),b=new T.Vector3(),c=new T.Vector3(),ab=new T.Vector3(),ac=new T.Vector3(),normal=new T.Vector3();
    let totalArea=0;
    scene.updateMatrixWorld(true);
    scene.traverse(mesh=>{
      if(!mesh.isMesh||!mesh.geometry||!mesh.geometry.attributes.position)return;
      if(mesh.isSkinnedMesh&&mesh.skeleton)mesh.skeleton.update();
      const geometry=mesh.geometry,index=geometry.index,triangleCount=index?index.count/3:geometry.attributes.position.count/3;
      for(let triangle=0;triangle<triangleCount;triangle++){
        const ia=index?index.getX(triangle*3):triangle*3;
        const ib=index?index.getX(triangle*3+1):triangle*3+1;
        const ic=index?index.getX(triangle*3+2):triangle*3+2;
        skinnedVertex(mesh,ia,a);skinnedVertex(mesh,ib,b);skinnedVertex(mesh,ic,c);
        ab.subVectors(b,a);ac.subVectors(c,a);normal.crossVectors(ab,ac);
        const area=normal.length()*.5;
        if(area<1e-10)continue;
        totalArea+=area;
        triangles.push({a:a.clone(),b:b.clone(),c:c.clone(),normal:normal.clone().normalize(),ceiling:totalArea});
      }
    });
    return{triangles,totalArea};
  }

  function chooseTriangle(data,value){
    let low=0,high=data.triangles.length-1;
    while(low<high){const mid=(low+high)>>1;if(value<=data.triangles[mid].ceiling)high=mid;else low=mid+1}
    return data.triangles[low];
  }

  function mannequinFacePoint(index,total){
    const t=index/Math.max(1,total-1);
    if(t<.34){
      const local=t/.34,side=local<.5?-1:1,angle=(local%.5)*2*TAU;
      return[side*.039+Math.cos(angle)*.017,.477+Math.sin(angle)*.0085,.101+Math.cos(angle)*.003];
    }
    if(t<.56){
      const local=(t-.34)/.22;
      return[Math.sin(local*Math.PI)*.0085,.468-local*.058,.111-Math.sin(local*Math.PI)*.004];
    }
    if(t<.82){
      const angle=(t-.56)/.26*TAU;
      return[Math.cos(angle)*.041,.4+Math.sin(angle)*.0105,.099];
    }
    const angle=(t-.82)/.18*Math.PI;
    return[Math.cos(angle)*.088,.438-Math.sin(angle)*.083,.082];
  }

  function sampleAnimatedSurface(gltf,spec,count){
    setAnimationPose(gltf,spec);
    const data=extractTriangles(gltf.scene);
    if(!data.triangles.length)throw new Error('Human mesh contains no sampleable triangles.');
    const raw=new Float32Array(count*3);
    const p=new T.Vector3(),bbox=new T.Box3();
    for(let i=0;i<count;i++){
      const triangle=chooseTriangle(data,Math.random()*data.totalArea);
      const r1=Math.sqrt(Math.random()),r2=Math.random();
      const wa=1-r1,wb=r1*(1-r2),wc=r1*r2;
      p.set(triangle.a.x*wa+triangle.b.x*wb+triangle.c.x*wc,triangle.a.y*wa+triangle.b.y*wb+triangle.c.y*wc,triangle.a.z*wa+triangle.b.z*wb+triangle.c.z*wc);
      if(Math.random()<.44)p.addScaledVector(triangle.normal,-Math.pow(Math.random(),1.7)*.08);
      p.x+=gaussian()*.008;p.y+=gaussian()*.005;p.z+=gaussian()*.008;
      raw[i*3]=p.x;raw[i*3+1]=p.y;raw[i*3+2]=p.z;bbox.expandByPoint(p);
    }
    const center=bbox.getCenter(new T.Vector3()),height=Math.max(.001,bbox.max.y-bbox.min.y),normalizer=1.12/height;
    const lean=spec.lean||0,twist=spec.twist||0,profile=FASHION_PROFILES[spec.profile]||FASHION_PROFILES.couture;
    // Keep every model the same apparent height while moving the hip line up.
    // This produces longer editorial legs without simply stretching the cloud.
    const fashionNormalizer=2/(profile.leg+profile.upper),featureCount=Math.max(84,Math.floor(count*.011)),featureStart=count-featureCount;
    for(let i=0;i<count;i++){
      const i3=i*3;
      let x=(raw[i3]-center.x)*normalizer,y=(raw[i3+1]-center.y)*normalizer,z=(raw[i3+2]-center.z)*normalizer;
      let sourceY=y;
      if(i>=featureStart){
        const feature=mannequinFacePoint(i-featureStart,featureCount);
        x=feature[0];sourceY=feature[1];y=sourceY;z=feature[2]+gaussian()*.0025;
      }else if(sourceY>.345){
        // Project the head region toward a clean oval shell: no hair mass, no boxy cranium.
        const hx=x/.104,hy=(sourceY-.455)/.13,hz=z/.098,length=Math.max(.001,Math.sqrt(hx*hx+hy*hy+hz*hz));
        x=lerp(x,hx/length*.104,.82);
        y=lerp(sourceY,.455+hy/length*.13,.82);
        z=lerp(z,hz/length*.098,.82);
        sourceY=y;
      }
      y=(sourceY<0?sourceY*profile.leg:sourceY*profile.upper)*fashionNormalizer;
      const waistBand=Math.exp(-Math.pow((sourceY-.09)/.115,2));
      const shoulderBand=Math.exp(-Math.pow((sourceY-.255)/.105,2));
      const hipBand=Math.exp(-Math.pow((sourceY+.045)/.105,2));
      const headBand=smoothBand(sourceY,.37,.6,.025);
      const torsoShape=1+(profile.waist-1)*waistBand+(profile.shoulder-1)*shoulderBand+(profile.hip-1)*hipBand+(profile.head-1)*headBand;
      x*=torsoShape;
      z*=profile.depth*(1-waistBand*.09);
      // A tiny asymmetrical couture curve stops the silhouettes feeling cloned.
      x+=profile.curve*Math.sin(clamp((sourceY+.32)/.7,0,1)*Math.PI);
      const normalizedY=clamp(y/.58,-1,1);
      const slice=twist*normalizedY+Math.sin((normalizedY+.2)*2.2)*.045;
      const cos=Math.cos(slice),sin=Math.sin(slice),rx=x*cos-z*sin,rz=x*sin+z*cos;
      x=rx+lean*(y*y-.08)+Math.sin((y+.55)*Math.PI)*lean*.14;
      z=rz+Math.sin((y+.48)*Math.PI*1.3)*lean*.07;
      raw[i3]=x;raw[i3+1]=y;raw[i3+2]=z;
    }
    return raw;
  }

  function smoothBand(value,start,end,feather){
    const enter=clamp((value-start)/feather,0,1),leave=1-clamp((value-end)/feather,0,1);
    return enter*enter*(3-2*enter)*leave*leave*(3-2*leave);
  }

  function ellipsoidCloud(count,variant){
    const out=new Float32Array(count*3);
    const groups=[{w:.14,c:[0,.43,0],r:[.105,.13,.11]},{w:.08,c:[0,.29,0],r:[.075,.08,.075]},{w:.36,c:[0,.05,0],r:[.205,.29,.14]},{w:.14,c:[0,-.19,0],r:[.17,.15,.14]},{w:.28,c:[0,-.4,0],r:[.23,.25,.13]}];
    let cursor=0;
    groups.forEach((group,g)=>{
      const amount=g===groups.length-1?count-cursor:Math.floor(count*group.w);
      for(let j=0;j<amount;j++,cursor++){
        const theta=Math.random()*TAU,phi=Math.acos(Math.random()*2-1),radius=Math.pow(Math.random(),.33);
        const i3=cursor*3;
        out[i3]=group.c[0]+Math.sin(phi)*Math.cos(theta)*group.r[0]*radius;
        out[i3+1]=group.c[1]+Math.cos(phi)*group.r[1]*radius;
        out[i3+2]=group.c[2]+Math.sin(phi)*Math.sin(theta)*group.r[2]*radius;
      }
    });
    return out;
  }

  function decodeWantedReference(){
    const reference=window.WANTED_HERO_REFERENCE;
    if(!reference||!reference.packed||!reference.figures)throw new Error('Wanted reference point data is missing.');
    const key=[211,73,158,39,122,250,17,96,181,44,233,140],encoded=atob(reference.packed),bytes=new Uint8Array(encoded.length);
    for(let i=0;i<encoded.length;i++)bytes[i]=encoded.charCodeAt(i)^key[i%key.length]^((i*31)&255);
    const view=new DataView(bytes.buffer),clouds=[];
    let byteOffset=0;
    reference.figures.forEach(meta=>{
      const out=new Float32Array(meta.n*3),normalizer=1.12/(meta.RR*2),M=meta.M;
      let minY=Infinity,maxY=-Infinity;
      for(let i=0;i<meta.n;i++){
        const x=view.getInt16(byteOffset,true)/100,y=view.getInt16(byteOffset+2,true)/100,z=view.getInt16(byteOffset+4,true)/100;byteOffset+=6;
        const tx=M[0]*x+M[1]*y+M[2]*z,ty=M[3]*x+M[4]*y+M[5]*z,tz=M[6]*x+M[7]*y+M[8]*z,j=i*3;
        out[j]=tx*normalizer;out[j+1]=-ty*normalizer;out[j+2]=tz*normalizer;
        minY=Math.min(minY,out[j+1]);maxY=Math.max(maxY,out[j+1]);
      }
      clouds.push({points:out,meta:Object.assign({},meta,{coverage:(maxY-minY)/1.12})});
    });
    return{clouds,figures:reference.figures};
  }

  async function buildCatalog(){
    const wanted=decodeWantedReference(),order=[4,2,0,3,1],outer=order.map(index=>wanted.clouds[index]);
    return{
      source:'Wanted reference point clouds · hero, THINK and BUILD',
      hero:[outer[0].points,outer[1].points,outer[2].points,outer[3].points,outer[4].points],
      heroMeta:outer.map(item=>item.meta),
      thinkSingle:wanted.clouds[3],
      buildSingle:wanted.clouds[1]
    };
  }
  const CATALOG_PROMISE=buildCatalog();

  const VERTEX_SHADER=`
    precision highp float;
    uniform float uTime,uAssemble,uDisperse,uAlpha,uPixelRatio,uPointSize,uPointerActive;
    uniform vec2 uMouse,uMouseVelocity,uTilt;
    uniform vec3 uCenters[5];
    uniform float uScales[5],uSpins[5];
    attribute vec3 aScatter,aLoose,aColor;
    attribute float aFigure,aSeed,aFeature;
    varying vec3 vColor;
    varying float vAlpha,vEnergy,vSeed;
    vec3 mod289(vec3 x){return x-floor(x*(1.0/289.0))*289.0;}vec4 mod289(vec4 x){return x-floor(x*(1.0/289.0))*289.0;}vec4 permute(vec4 x){return mod289(((x*34.0)+1.0)*x);}vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-.85373472095314*r;}
    float snoise(vec3 v){const vec2 C=vec2(1.0/6.0,1.0/3.0);const vec4 D=vec4(0.0,.5,1.0,2.0);vec3 i=floor(v+dot(v,C.yyy));vec3 x0=v-i+dot(i,C.xxx);vec3 g=step(x0.yzx,x0.xyz),l=1.0-g,i1=min(g.xyz,l.zxy),i2=max(g.xyz,l.zxy);vec3 x1=x0-i1+C.xxx,x2=x0-i2+C.yyy,x3=x0-D.yyy;i=mod289(i);vec4 p=permute(permute(permute(i.z+vec4(0.0,i1.z,i2.z,1.0))+i.y+vec4(0.0,i1.y,i2.y,1.0))+i.x+vec4(0.0,i1.x,i2.x,1.0));float n_=1.0/7.0;vec3 ns=n_*D.wyz-D.xzx;vec4 j=p-49.0*floor(p*ns.z*ns.z),x_=floor(j*ns.z),y_=floor(j-7.0*x_),x=x_*ns.x+ns.yyyy,y=y_*ns.x+ns.yyyy,h=1.0-abs(x)-abs(y);vec4 b0=vec4(x.xy,y.xy),b1=vec4(x.zw,y.zw),s0=floor(b0)*2.0+1.0,s1=floor(b1)*2.0+1.0,sh=-step(h,vec4(0.0)),a0=b0.xzyw+s0.xzyw*sh.xxyy,a1=b1.xzyw+s1.xzyw*sh.zzww;vec3 p0=vec3(a0.xy,h.x),p1=vec3(a0.zw,h.y),p2=vec3(a1.xy,h.z),p3=vec3(a1.zw,h.w);vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));p0*=norm.x;p1*=norm.y;p2*=norm.z;p3*=norm.w;vec4 m=max(.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.0);m*=m;return 42.0*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));}
    mat2 rot(float a){float s=sin(a),c=cos(a);return mat2(c,-s,s,c);}
    void figureData(float id,out vec3 center,out float scale,out float spin){center=uCenters[0];scale=uScales[0];spin=uSpins[0];if(id>.5){center=uCenters[1];scale=uScales[1];spin=uSpins[1];}if(id>1.5){center=uCenters[2];scale=uScales[2];spin=uSpins[2];}if(id>2.5){center=uCenters[3];scale=uScales[3];spin=uSpins[3];}if(id>3.5){center=uCenters[4];scale=uScales[4];spin=uSpins[4];}}
    void main(){
      vec3 center;float scale;float spin;figureData(aFigure,center,scale,spin);
      vec3 local=position;local.xz=rot(spin)*local.xz;local.yz=rot(-uTilt.y*.2)*local.yz;local.xz=rot(uTilt.x*.3)*local.xz;
      vec3 target=local*scale+center;
      float assemble=smoothstep(0.0,1.0,uAssemble),vortexAngle=(1.0-assemble)*(7.0+aSeed*12.0)+uTime*(.25+aSeed*.18);
      vec3 vortex=aScatter;vortex.xy=rot(vortexAngle)*vortex.xy;vortex.z+=sin(vortexAngle*1.7+aSeed*16.0)*(1.0-assemble)*2.0;vortex.xy*=1.0+(1.0-assemble)*(.12+aSeed*.22);
      float loosePulse=.82+.18*sin(uTime*.72+aSeed*12.0);
      vec3 looseTarget=target+aLoose*loosePulse;
      vec3 world=mix(vortex,looseTarget,assemble);
      float isCenter=1.0-step(.48,abs(aFigure-2.0)),disperse=smoothstep(0.0,.55,uDisperse);
      vec3 outward=aScatter*1.65+vec3(normalize(center.xy+vec2(.001))*5.0,(aSeed-.5)*6.0);world=mix(world,outward,disperse*(1.0-isCenter));
      float n1=snoise(vec3(target*.72+vec3(0.0,0.0,uTime*.19+aSeed*3.0)));float n2=snoise(vec3(target*.56+vec3(13.2,4.7,uTime*.15-aSeed*2.0)));
      float breath=sin(uTime*1.28+position.y*12.0+aSeed*6.2831853)*.5+.5;vec3 fluid=normalize(vec3(n1,n2,sin(n1*2.6+n2*2.1+aSeed*7.0))+.001);
      world+=fluid*(.018+.027*breath)*assemble;
      float pointerSpeed=clamp(length(uMouseVelocity)*1.2,0.0,1.4),surfaceDistance=length(target.xy-uMouse);
      float condensation=(1.0-smoothstep(.14,1.58+pointerSpeed*.08,surfaceDistance))*uPointerActive*assemble;
      condensation*=1.0-disperse*(1.0-isCenter);
      float settle=condensation*condensation*(3.0-2.0*condensation);
      vec3 focusedSurface=target+fluid*(.006+.008*(1.0-settle));
      world=mix(world,focusedSurface,settle);
      vec4 mvPosition=modelViewMatrix*vec4(world,1.0);gl_Position=projectionMatrix*mvPosition;gl_PointSize=uPointSize*uPixelRatio*clamp(12.0/max(5.0,-mvPosition.z),.72,1.72)*(.78+aSeed*.38+settle*.2)*(1.0+aFeature*.2);
      float depthTint=clamp((world.z+3.0)/7.0,0.0,1.0);vec3 neon=mix(vec3(.32,.82,1.0),vec3(.61,.35,1.0),depthTint);vec3 color=mix(aColor,neon,.08+.12*depthTint);vec3 featureColor=mix(color,color*.32,aFeature*(.04+.76*settle));vColor=mix(featureColor,vec3(1.0),(settle*.14+max(0.0,n1)*.04)*(1.0-aFeature*.82));vEnergy=settle;vSeed=aSeed;vAlpha=uAlpha*(1.0-disperse*(1.0-isCenter))*(.62+.2*breath+.18*settle);
    }`;

  const FRAGMENT_SHADER=`precision highp float;varying vec3 vColor;varying float vAlpha,vEnergy,vSeed;void main(){vec2 uv=gl_PointCoord-.5;float angle=(fract(vSeed*17.13)-.5)*.42,s=sin(angle),c=cos(angle);uv=mat2(c,-s,s,c)*uv;uv.x*=mix(.84,1.18,fract(vSeed*8.71));vec2 q=abs(uv)-vec2(.31,.3);float roundedBox=length(max(q,0.0))+min(max(q.x,q.y),0.0)-.15;float mask=1.0-smoothstep(-.025,.055,roundedBox);float core=1.0-smoothstep(-.12,.015,roundedBox);float alpha=mask*vAlpha;if(alpha<.012)discard;gl_FragColor=vec4(vColor*(1.0+core*.1+vEnergy*.16),alpha);}`;

  class GPUParticleBody{
    constructor(canvas,options={}){
      this.canvas=canvas;this.options=options;this.group=!!options.group;this.alpha=1;this.progress=0;this.visible=true;this.loaded=false;
      this.scene=new T.Scene();this.camera=new T.PerspectiveCamera(38,1,.1,100);this.camera.position.set(0,0,12);
      this.renderer=new T.WebGLRenderer({canvas,alpha:true,antialias:false,powerPreference:'high-performance',premultipliedAlpha:true});this.renderer.setClearColor(0,0);if('outputEncoding'in this.renderer)this.renderer.outputEncoding=T.sRGBEncoding;
      this.renderer.setPixelRatio(Math.min(devicePixelRatio||1,2));
      this.raycaster=new T.Raycaster();this.mousePlane=new T.Plane(new T.Vector3(0,0,1),0);this.mouseNdc=new T.Vector2();this.mouseWorld=new T.Vector3(999,999,0);this.mouseVelocity=new T.Vector2();
      this.centers=Array.from({length:5},()=>new T.Vector3());this.scales=new Float32Array(5);this.spins=new Float32Array(5);this.spinSpeed=this.group?[-.025,.018,0,-.018,.024]:[0,0,0,0,0];
      this.ready=CATALOG_PROMISE.then(catalog=>{this.catalogSource=catalog.source;this.makeGeometry(catalog);this.startTime=performance.now();this.loaded=true;return this});
      this.resize();new ResizeObserver(()=>this.resize()).observe(canvas);new IntersectionObserver(entries=>{this.visible=entries[0].isIntersecting},{rootMargin:'140px'}).observe(canvas);
      this.loop=this.loop.bind(this);requestAnimationFrame(this.loop);
    }
    makeGeometry(catalog){
      const entries=this.group?[catalog.dancer,catalog.crouch,catalog.impact,catalog.think,catalog.build]:[this.options.pose==='think'?catalog.thinkSingle:catalog.buildSingle];
      const count=entries.reduce((sum,array)=>sum+array.length/3,0),positions=new Float32Array(count*3),scatter=new Float32Array(count*3),loose=new Float32Array(count*3),colors=new Float32Array(count*3),figures=new Float32Array(count),seeds=new Float32Array(count),features=new Float32Array(count);
      let cursor=0;
      entries.forEach((array,figure)=>{
        const palette=this.group?HERO_PALETTES[figure]:SINGLE_PALETTES[this.options.pose==='think'?'think':'build'],top=hexRgb(palette[0]),bottom=hexRgb(palette[1]);
        const entryCount=array.length/3,featureStart=entryCount-Math.max(84,Math.floor(entryCount*.011));
        for(let i=0;i<entryCount;i++,cursor++){
          const source=i*3,target=cursor*3,x=array[source],y=array[source+1],z=array[source+2],color=mixRgb(top,bottom,clamp((.58-y)/1.16,0,1));
          positions[target]=x;positions[target+1]=y;positions[target+2]=z;colors[target]=color[0];colors[target+1]=color[1];colors[target+2]=color[2];figures[cursor]=figure;seeds[cursor]=Math.random();features[cursor]=i>=featureStart?1:0;
          const theta=Math.random()*TAU,phi=Math.acos(Math.random()*2-1),radius=4.8+Math.pow(Math.random(),.64)*10.5;scatter[target]=Math.sin(phi)*Math.cos(theta)*radius;scatter[target+1]=Math.sin(phi)*Math.sin(theta)*radius*.72;scatter[target+2]=Math.cos(phi)*radius*.52;
          const looseAngle=Math.random()*TAU,looseRadius=.055+Math.pow(Math.random(),.48)*.42;loose[target]=Math.cos(looseAngle)*looseRadius*(.72+Math.random()*.42);loose[target+1]=Math.sin(looseAngle)*looseRadius;loose[target+2]=gaussian()*looseRadius*.48;
        }
      });
      const geometry=new T.BufferGeometry();geometry.setAttribute('position',new T.BufferAttribute(positions,3));geometry.setAttribute('aScatter',new T.BufferAttribute(scatter,3));geometry.setAttribute('aLoose',new T.BufferAttribute(loose,3));geometry.setAttribute('aColor',new T.BufferAttribute(colors,3));geometry.setAttribute('aFigure',new T.BufferAttribute(figures,1));geometry.setAttribute('aSeed',new T.BufferAttribute(seeds,1));geometry.setAttribute('aFeature',new T.BufferAttribute(features,1));
      this.uniforms={uTime:{value:0},uAssemble:{value:REDUCED?1:0},uDisperse:{value:0},uAlpha:{value:1},uPixelRatio:{value:Math.min(devicePixelRatio||1,1.8)},uPointSize:{value:this.group?2.6:2.85},uPointerActive:{value:0},uMouse:{value:new T.Vector2(999,999)},uMouseVelocity:{value:new T.Vector2()},uTilt:{value:new T.Vector2()},uCenters:{value:this.centers},uScales:{value:this.scales},uSpins:{value:this.spins}};
      const material=new T.ShaderMaterial({uniforms:this.uniforms,vertexShader:VERTEX_SHADER,fragmentShader:FRAGMENT_SHADER,transparent:true,depthTest:false,depthWrite:false,blending:T.NormalBlending});this.points=new T.Points(geometry,material);this.points.frustumCulled=false;this.scene.add(this.points);this.particleCount=count;this.resize();
    }
    resize(){
      const width=Math.max(1,this.canvas.clientWidth),height=Math.max(1,this.canvas.clientHeight);this.width=width;this.height=height;this.camera.aspect=width/height;this.camera.updateProjectionMatrix();this.renderer.setPixelRatio(Math.min(devicePixelRatio||1,1.8));this.renderer.setSize(width,height,false);
      const viewHeight=2*Math.tan(T.MathUtils.degToRad(this.camera.fov*.5))*this.camera.position.z,viewWidth=viewHeight*this.camera.aspect;this.viewHeight=viewHeight;this.viewWidth=viewWidth;
      if(this.group){const xs=[.135,.315,.5,.69,.865],ys=[.51,.57,.535,.55,.5],base=[6.2,5.75,6.35,6.05,6.7],mobile=clamp(this.camera.aspect/.98,.7,1);for(let i=0;i<5;i++){this.centers[i].set((xs[i]-.5)*viewWidth,(.5-ys[i])*viewHeight,(i-2)*.12);this.scales[i]=base[i]*mobile}}
      else{this.centers[0].set(((this.options.cxRatio||.72)-.5)*viewWidth,-.22,0);this.scales[0]=(this.options.scale||.72)*9.65;for(let i=1;i<5;i++){this.centers[i].set(0,0,0);this.scales[i]=0}}
      if(this.uniforms)this.uniforms.uPixelRatio.value=Math.min(devicePixelRatio||1,1.8);
    }
    setProgress(value){this.progress=clamp(value,0,1)}
    updateMouse(now){
      const rect=this.canvas.getBoundingClientRect(),inside=POINTER.inside&&POINTER.x>=rect.left&&POINTER.x<=rect.right&&POINTER.y>=rect.top&&POINTER.y<=rect.bottom;
      if(inside){this.mouseNdc.set((POINTER.x-rect.left)/rect.width*2-1,-((POINTER.y-rect.top)/rect.height*2-1));this.raycaster.setFromCamera(this.mouseNdc,this.camera);this.raycaster.ray.intersectPlane(this.mousePlane,this.mouseWorld);this.uniforms.uMouse.value.lerp(new T.Vector2(this.mouseWorld.x,this.mouseWorld.y),.3);this.uniforms.uTilt.value.lerp(this.mouseNdc,.1);this.mouseVelocity.lerp(new T.Vector2(POINTER.vx/rect.width*this.viewWidth*16,-POINTER.vy/rect.height*this.viewHeight*16),.24);this.uniforms.uMouseVelocity.value.copy(this.mouseVelocity);this.uniforms.uPointerActive.value=lerp(this.uniforms.uPointerActive.value,1,.2)}
      else{this.uniforms.uMouse.value.lerp(new T.Vector2(999,999),.18);this.uniforms.uTilt.value.lerp(new T.Vector2(),.08);this.mouseVelocity.multiplyScalar(.82);this.uniforms.uMouseVelocity.value.copy(this.mouseVelocity);this.uniforms.uPointerActive.value=lerp(this.uniforms.uPointerActive.value,0,.16)}
      POINTER.vx*=.91;POINTER.vy*=.91;
    }
    updateLabels(){if(!this.group)return;document.querySelectorAll('[data-fig]').forEach(label=>{const i=Number(label.dataset.fig),v=new T.Vector3(this.centers[i].x,this.centers[i].y+this.scales[i]*.67,this.centers[i].z).project(this.camera);label.style.left=`${(v.x*.5+.5)*this.width}px`;label.style.top=`${(-v.y*.5+.5)*this.height}px`;label.style.opacity=String(i===2?1:1-clamp((this.progress-.08)/.34,0,1))})}
    loop(now){
      if(this.loaded&&this.visible){const time=now*.001;if(this.group){this.uniforms.uAssemble.value=REDUCED?1:clamp((now-this.startTime-100)/1850,0,1);this.uniforms.uDisperse.value=this.progress}else{this.uniforms.uAssemble.value=REDUCED?1:this.progress;this.uniforms.uDisperse.value=0}for(let i=0;i<(this.group?5:1);i++){const baseSpin=this.group?(i-2)*.22:0;this.spins[i]=time*this.spinSpeed[i]*(this.group&&i===2?1+this.progress*5.5:1)+baseSpin}this.uniforms.uTime.value=time;this.uniforms.uAlpha.value=this.alpha;this.updateMouse(now);this.updateLabels();this.renderer.render(this.scene,this.camera)}requestAnimationFrame(this.loop);
    }
  }
  const WANTED_VERTEX_SHADER=`
    precision highp float;
    uniform float uTime,uAssemble,uDisperse,uAlpha,uPixelRatio,uPointSize,uPointerActive,uCursorRadius;
    uniform vec2 uMouse;
    uniform vec3 uCenters[5];
    uniform float uScales[5],uSpins[5],uPointSizes[5];
    attribute vec3 aScatter,aLoose,aColor,aColor2;
    attribute vec2 aGrad;
    attribute float aFigure,aSeed,aFeature;
    varying vec3 vColor;
    varying float vAlpha,vFocus;
    mat2 rot(float a){float s=sin(a),c=cos(a);return mat2(c,-s,s,c);}
    void figureData(float id,out vec3 center,out float scale,out float spin){
      center=uCenters[0];scale=uScales[0];spin=uSpins[0];
      if(id>.5){center=uCenters[1];scale=uScales[1];spin=uSpins[1];}
      if(id>1.5){center=uCenters[2];scale=uScales[2];spin=uSpins[2];}
      if(id>2.5){center=uCenters[3];scale=uScales[3];spin=uSpins[3];}
      if(id>3.5){center=uCenters[4];scale=uScales[4];spin=uSpins[4];}
    }
    float figurePointSize(float id){float size=uPointSizes[0];if(id>.5)size=uPointSizes[1];if(id>1.5)size=uPointSizes[2];if(id>2.5)size=uPointSizes[3];if(id>3.5)size=uPointSizes[4];return size;}
    void main(){
      vec3 center;float scale;float spin;figureData(aFigure,center,scale,spin);
      vec3 local=position;local.xz=rot(spin)*local.xz;
      vec3 target=local*scale+center;
      float assemble=smoothstep(0.0,1.0,uAssemble);
      float vortexAngle=(1.0-assemble)*(7.0+aSeed*12.0)+uTime*(.25+aSeed*.18);
      vec3 vortex=aScatter;vortex.xy=rot(vortexAngle)*vortex.xy;
      vortex.z+=sin(vortexAngle*1.7+aSeed*16.0)*(1.0-assemble)*2.0;
      vec3 looseLocal=local*.78;looseLocal.xy+=aLoose.xy*.58;
      vec3 looseTarget=looseLocal*scale+center;
      vec3 world=mix(vortex,looseTarget,assemble);
      float distanceToSurface=length(target.xy-uMouse);
      float edge=clamp(1.0-distanceToSurface/max(.001,uCursorRadius),0.0,1.0);
      float mouseFocus=edge*edge*(3.0-2.0*edge)*uPointerActive*assemble;
      float focus=mix(.32,1.0,mouseFocus);
      float micro=sin(uTime*.72+aSeed*31.0+position.y*12.0)*.0045*scale;
      vec3 living=target+vec3(cos(aSeed*31.0),sin(aSeed*47.0),sin(aSeed*23.0))*micro;
      world=mix(world,living,focus);
      float isCenter=1.0-step(.48,abs(aFigure-2.0));
      float disperse=smoothstep(.52,.70,uDisperse)*(1.0-isCenter);
      vec3 direction=normalize(vec3(center.xy+vec2((aSeed-.5)*.45,.001),(aSeed-.5)*1.8));
      vec3 exitCloud=aScatter*1.42+direction*(3.0+aSeed*4.0);
      world=mix(world,exitCloud,disperse);
      float y01=clamp((position.y+.56)/1.12,0.0,1.0),gy=1.0-y01;
      float gradientWidth=max(.0001,(aGrad.y-aGrad.x)*.7);
      float gradientPhase=(gy-uTime*.075-aGrad.x)/gradientWidth;
      float xw=mod(gradientPhase,3.2);
      float colorFlow=clamp(xw,0.0,1.0)-clamp(xw-1.6,0.0,1.0);
      vec3 color=mix(aColor,aColor2,colorFlow);
      vec4 mvPosition=modelViewMatrix*vec4(world,1.0);
      gl_Position=projectionMatrix*mvPosition;
      gl_PointSize=figurePointSize(aFigure)*uPixelRatio*mix(.40,1.0,focus);
      vColor=color;vFocus=focus;
      vAlpha=uAlpha*(1.0-disperse)*mix(.30,1.0,focus);
    }`;

  const WANTED_FRAGMENT_SHADER=`
    precision highp float;
    varying vec3 vColor;
    varying float vAlpha,vFocus;
    void main(){
      vec2 q=abs(gl_PointCoord-.5);
      float corner=.12,feather=.10,b=.5-corner;
      float d=length(max(q-vec2(b),0.0))-corner;
      float mask=1.0-smoothstep(-feather,feather,d);
      float alpha=mask*vAlpha;
      if(alpha<.012)discard;
      vec3 sourceGlow=mix(vColor,vec3(1.0),.08+.10*pow(vFocus,.8));
      gl_FragColor=vec4(sourceGlow,alpha*.90);
    }`;

  const WANTED_GLOW_VERTEX_SHADER=WANTED_VERTEX_SHADER.replace(
    'gl_PointSize=figurePointSize(aFigure)*uPixelRatio*mix(.40,1.0,focus);',
    'gl_PointSize=figurePointSize(aFigure)*uPixelRatio*6.5*mix(.78,1.02,focus);'
  );
  const WANTED_GLOW_FRAGMENT_SHADER=`
    precision highp float;
    varying vec3 vColor;
    varying float vAlpha,vFocus;
    void main(){
      float radius=length(gl_PointCoord-.5)*2.0;
      float halo=(1.0-smoothstep(.08,1.0,radius));
      halo*=halo*(.0015+.0040*pow(vFocus,.8))*vAlpha;
      if(halo<.00018)discard;
      gl_FragColor=vec4(vec3(1.0),halo);
    }`;

  const WANTED_AURA_VERTEX_SHADER=WANTED_VERTEX_SHADER.replace(
    'gl_PointSize=figurePointSize(aFigure)*uPixelRatio*mix(.40,1.0,focus);',
    'gl_PointSize=figurePointSize(aFigure)*uPixelRatio*18.0*mix(.84,1.0,focus);'
  );
  const WANTED_AURA_FRAGMENT_SHADER=`
    precision highp float;
    varying vec3 vColor;
    varying float vAlpha,vFocus;
    void main(){
      float radius=length(gl_PointCoord-.5)*2.0;
      float aura=1.0-smoothstep(.02,1.0,radius);
      aura=aura*aura*aura*(.0010+.0024*pow(vFocus,.72))*vAlpha;
      if(aura<.00012)discard;
      gl_FragColor=vec4(vec3(1.0),aura);
    }`;

  class WantedParticleBody{
    constructor(canvas,options={}){
      this.canvas=canvas;this.options=options;this.group=!!options.group;this.alpha=1;this.progress=0;this.visible=true;this.loaded=false;
      this.scene=new T.Scene();this.camera=new T.PerspectiveCamera(38,1,.1,100);this.camera.position.set(0,0,12);
      this.renderer=new T.WebGLRenderer({canvas,alpha:true,antialias:false,powerPreference:'high-performance',premultipliedAlpha:true});
      this.renderer.setClearColor(0,0);if('outputEncoding'in this.renderer)this.renderer.outputEncoding=T.sRGBEncoding;
      this.renderer.setPixelRatio(Math.min(devicePixelRatio||1,1.8));
      this.raycaster=new T.Raycaster();this.mousePlane=new T.Plane(new T.Vector3(0,0,1),0);this.mouseNdc=new T.Vector2();this.mouseWorld=new T.Vector3();
      this.centers=Array.from({length:5},()=>new T.Vector3());this.scales=new Float32Array(5);this.spins=new Float32Array(5);this.pointSizes=new Float32Array(5);
      const singlePeriod=options.pose==='think'?-18:46;
      this.spinSpeed=this.group?[TAU/-40,TAU/24,TAU/20,TAU/-18,TAU/46]:[TAU/singlePeriod,0,0,0,0];
      this.labelAnchors=[];this.labelSamples=[];this.tmpPoint=new T.Vector3();this.tmpNdc=new T.Vector3();
      this.lightNodes=[];
      this.ready=CATALOG_PROMISE.then(catalog=>{this.catalogSource=catalog.source;this.makeGeometry(catalog);this.startTime=performance.now();this.loaded=true;return this});
      this.resize();new ResizeObserver(()=>this.resize()).observe(canvas);
      new IntersectionObserver(entries=>{this.visible=entries[0].isIntersecting},{rootMargin:'140px'}).observe(canvas);
      this.loop=this.loop.bind(this);requestAnimationFrame(this.loop);
    }
    makeGeometry(catalog){
      const single=this.options.pose==='think'?catalog.thinkSingle:catalog.buildSingle;
      const entries=this.group?catalog.hero:[single.points];
      this.entries=entries;this.figureMeta=this.group?catalog.heroMeta:[single.meta];
      const count=entries.reduce((sum,array)=>sum+array.length/3,0);
      const positions=new Float32Array(count*3),scatter=new Float32Array(count*3),loose=new Float32Array(count*3),colors=new Float32Array(count*3),colors2=new Float32Array(count*3),gradients=new Float32Array(count*2),figures=new Float32Array(count),seeds=new Float32Array(count),features=new Float32Array(count);
      let cursor=0;
      entries.forEach((array,figure)=>{
        const meta=this.figureMeta[figure],palette=[meta.fill,meta.fill2];
        const bottom=byteRgb(palette[0]),top=byteRgb(palette[1]),gradient=meta.grad;
        const entryCount=array.length/3,featureStart=entryCount+1;
        let maxY=-Infinity,topX=0,topZ=0,topN=0;
        const stride=Math.max(1,Math.floor(entryCount/360)),samples=[];
        for(let i=0;i<entryCount;i++,cursor++){
          const source=i*3,target=cursor*3,x=array[source],y=array[source+1],z=array[source+2];
          positions[target]=x;positions[target+1]=y;positions[target+2]=z;
          colors[target]=bottom[0];colors[target+1]=bottom[1];colors[target+2]=bottom[2];colors2[target]=top[0];colors2[target+1]=top[1];colors2[target+2]=top[2];
          gradients[cursor*2]=gradient[0];gradients[cursor*2+1]=gradient[1];
          figures[cursor]=figure;seeds[cursor]=Math.random();features[cursor]=i>=featureStart?1:0;
          const theta=Math.random()*TAU,phi=Math.acos(Math.random()*2-1),radius=4.6+Math.pow(Math.random(),.66)*9.4;
          scatter[target]=Math.sin(phi)*Math.cos(theta)*radius;scatter[target+1]=Math.sin(phi)*Math.sin(theta)*radius*.72;scatter[target+2]=Math.cos(phi)*radius*.52;
          const fract=value=>value-Math.floor(value),h1=fract(Math.sin(x*12.9898+y*78.233+z*45.164)*43758.5453),h2=fract(Math.sin(x*93.989+y*67.345+z*24.123)*24634.6345),h3=fract(Math.sin(x*43.32+y*11.135+z*73.63)*35624.234),looseRadius=1.008*(.12+.42*h1)*(.55+.45*h3)*.1923,looseAngle=h2*TAU;
          loose[target]=Math.cos(looseAngle)*looseRadius;loose[target+1]=Math.sin(looseAngle)*looseRadius;loose[target+2]=0;
          if(i%stride===0)samples.push(new T.Vector3(x,y,z));
          if(y>maxY){maxY=y;topX=x;topZ=z;topN=1}else if(y>maxY-.018){topX+=x;topZ+=z;topN++}
        }
        if(meta.crown){
          const crown=meta.crown,M=meta.M,k=1.12/(meta.RR*2),x=crown[0],y=crown[1],z=crown[2];
          this.labelAnchors.push(new T.Vector3((M[0]*x+M[1]*y+M[2]*z)*k,-(M[3]*x+M[4]*y+M[5]*z)*k,(M[6]*x+M[7]*y+M[8]*z)*k));
        }else this.labelAnchors.push(new T.Vector3(topX/Math.max(1,topN),maxY,topZ/Math.max(1,topN)));
        this.labelSamples.push(samples);
      });
      const geometry=new T.BufferGeometry();
      geometry.setAttribute('position',new T.BufferAttribute(positions,3));geometry.setAttribute('aScatter',new T.BufferAttribute(scatter,3));geometry.setAttribute('aLoose',new T.BufferAttribute(loose,3));geometry.setAttribute('aColor',new T.BufferAttribute(colors,3));geometry.setAttribute('aColor2',new T.BufferAttribute(colors2,3));geometry.setAttribute('aGrad',new T.BufferAttribute(gradients,2));geometry.setAttribute('aFigure',new T.BufferAttribute(figures,1));geometry.setAttribute('aSeed',new T.BufferAttribute(seeds,1));geometry.setAttribute('aFeature',new T.BufferAttribute(features,1));
      this.uniforms={uTime:{value:0},uAssemble:{value:REDUCED?1:0},uDisperse:{value:0},uAlpha:{value:1},uPixelRatio:{value:Math.min(devicePixelRatio||1,2)},uPointSize:{value:this.group?2.8:2.85},uPointerActive:{value:this.group?1:0},uCursorRadius:{value:1},uMouse:{value:new T.Vector2()},uCenters:{value:this.centers},uScales:{value:this.scales},uSpins:{value:this.spins},uPointSizes:{value:this.pointSizes}};
      const auraMaterial=new T.ShaderMaterial({uniforms:this.uniforms,vertexShader:WANTED_AURA_VERTEX_SHADER,fragmentShader:WANTED_AURA_FRAGMENT_SHADER,transparent:true,depthTest:false,depthWrite:false,blending:T.NormalBlending});
      this.auraPoints=new T.Points(geometry,auraMaterial);this.auraPoints.frustumCulled=false;this.auraPoints.renderOrder=0;this.scene.add(this.auraPoints);
      const glowMaterial=new T.ShaderMaterial({uniforms:this.uniforms,vertexShader:WANTED_GLOW_VERTEX_SHADER,fragmentShader:WANTED_GLOW_FRAGMENT_SHADER,transparent:true,depthTest:false,depthWrite:false,blending:T.AdditiveBlending});
      this.glowPoints=new T.Points(geometry,glowMaterial);this.glowPoints.frustumCulled=false;this.glowPoints.renderOrder=2;this.scene.add(this.glowPoints);
      const material=new T.ShaderMaterial({uniforms:this.uniforms,vertexShader:WANTED_VERTEX_SHADER,fragmentShader:WANTED_FRAGMENT_SHADER,transparent:true,depthTest:false,depthWrite:false,blending:T.NormalBlending});
      this.points=new T.Points(geometry,material);this.points.frustumCulled=false;this.points.renderOrder=1;this.scene.add(this.points);this.particleCount=count;this.resize();
    }
    resize(){
      const width=Math.max(1,this.canvas.clientWidth),height=Math.max(1,this.canvas.clientHeight);this.width=width;this.height=height;
      this.camera.aspect=width/height;this.camera.updateProjectionMatrix();this.renderer.setPixelRatio(Math.min(devicePixelRatio||1,2));this.renderer.setSize(width,height,false);
      const viewHeight=2*Math.tan(T.MathUtils.degToRad(this.camera.fov*.5))*this.camera.position.z,viewWidth=viewHeight*this.camera.aspect;this.viewHeight=viewHeight;this.viewWidth=viewWidth;this.sceneScale=Math.max(width/1600,height/900);
      if(this.group&&this.figureMeta){
        this.figureMeta.forEach((meta,i)=>{
          const pxX=width*.5+(meta.cx-800)*this.sceneScale,pxY=height*.5+(meta.cy-450)*this.sceneScale;
          this.centers[i].set((pxX/width-.5)*viewWidth,(.5-pxY/height)*viewHeight,(meta.z-2.2)*.035);
          const fullDesignHeight=meta.hPx*this.sceneScale*.96;
          this.scales[i]=fullDesignHeight/height*viewHeight/1.12;
          this.pointSizes[i]=Math.max(1.5,.227*(meta.hPx/(2*meta.RR))*this.sceneScale);
        });
      }else{
        this.centers[0].set(((this.options.cxRatio||.72)-.5)*viewWidth,((.5-(this.options.cyRatio||.52))*viewHeight),0);
        const meta=this.figureMeta&&this.figureMeta[0];
        if(meta){
          const targetHeightRatio=this.options.heightRatio||.86,actualNormalizedHeight=1.12*Math.max(.01,meta.coverage||1);
          this.scales[0]=targetHeightRatio*viewHeight/actualNormalizedHeight;
          this.pointSizes[0]=Math.max(1.5,.227*(meta.hPx/(2*meta.RR))*this.sceneScale);
        }
        for(let i=1;i<5;i++){this.centers[i].set(0,0,0);this.scales[i]=0}
      }
      if(this.uniforms){this.uniforms.uPixelRatio.value=Math.min(devicePixelRatio||1,2);this.uniforms.uCursorRadius.value=2400/height*viewHeight}
    }
    setProgress(value){this.progress=clamp(value,0,1)}
    updateMouse(){
      if(!this.uniforms)return;
      const rect=this.canvas.getBoundingClientRect(),inside=POINTER.inside&&POINTER.x>=rect.left&&POINTER.x<=rect.right&&POINTER.y>=rect.top&&POINTER.y<=rect.bottom;
      if(inside){
        this.mouseNdc.set((POINTER.x-rect.left)/rect.width*2-1,-((POINTER.y-rect.top)/rect.height*2-1));this.raycaster.setFromCamera(this.mouseNdc,this.camera);this.raycaster.ray.intersectPlane(this.mousePlane,this.mouseWorld);
        this.uniforms.uMouse.value.lerp(new T.Vector2(this.mouseWorld.x,this.mouseWorld.y),.14);this.uniforms.uPointerActive.value=lerp(this.uniforms.uPointerActive.value,1,.14);
      }else this.uniforms.uPointerActive.value=lerp(this.uniforms.uPointerActive.value,0,.12);
    }
    rotatedWorld(local,index,target){
      const spin=this.spins[index],c=Math.cos(spin),s=Math.sin(spin),x=local.x*c+local.z*s,z=-local.x*s+local.z*c;
      return target.set(x*this.scales[index]+this.centers[index].x,local.y*this.scales[index]+this.centers[index].y,z*this.scales[index]+this.centers[index].z);
    }
    updateLabels(){
      if(!this.group||!this.figureMeta)return;
      const rect=this.canvas.getBoundingClientRect(),offsets=[[53.4,16.4],[48.1,16.5],[80,0],[-49.7,16.7],[-52.1,18.4]];
      document.querySelectorAll('[data-fig]').forEach(label=>{
        const i=Number(label.dataset.fig),world=this.rotatedWorld(this.labelAnchors[i],i,this.tmpPoint),projected=this.tmpNdc.copy(world).project(this.camera);
        const x=(projected.x*.5+.5)*this.width+offsets[i][0]*this.sceneScale,y=(-projected.y*.5+.5)*this.height-20*this.sceneScale+offsets[i][1]*this.sceneScale;
        label.style.left=`${x}px`;label.style.top=`${y}px`;
        const fade=i===2?1:1-clamp((this.progress-.52)/.18,0,1);label.style.opacity=String(fade);
        let active=i===2&&document.body.classList.contains('intro-complete');
        if(!active&&fade>.02&&POINTER.inside){
          const maxD=28*28;
          for(const sample of this.labelSamples[i]){
            const p=this.rotatedWorld(sample,i,this.tmpPoint).project(this.camera),sx=rect.left+(p.x*.5+.5)*rect.width,sy=rect.top+(-p.y*.5+.5)*rect.height,dx=sx-POINTER.x,dy=sy-POINTER.y;
            if(dx*dx+dy*dy<maxD){active=true;break}
          }
        }
        label.classList.toggle('active',active);
      });
      this.lightNodes.forEach((light,i)=>{
        const p=this.tmpNdc.copy(this.centers[i]).project(this.camera),x=(p.x*.5+.5)*this.width,y=(-p.y*.5+.5)*this.height;
        const fullHeight=this.figureMeta[i].hPx*this.sceneScale,dx=rect.left+x-POINTER.x,dy=rect.top+y-POINTER.y;
        const proximity=1-clamp(Math.hypot(dx,dy)/(this.width*.62),0,1),fade=i===2?1:1-clamp((this.progress-.52)/.18,0,1);
        light.style.left=`${x}px`;light.style.top=`${y}px`;light.style.width=`${Math.max(280,fullHeight*.48)}px`;light.style.height=`${Math.max(380,fullHeight*.68)}px`;
        light.style.opacity=String(fade*(.46+proximity*.28));
      });
    }
    loop(now){
      if(this.loaded&&this.visible){
        const time=Math.max(0,(now-this.startTime)*.001);
        if(this.group){this.uniforms.uAssemble.value=REDUCED?1:clamp((now-this.startTime-100)/1850,0,1);this.uniforms.uDisperse.value=this.progress}
        else{this.uniforms.uAssemble.value=REDUCED?1:this.progress;this.uniforms.uDisperse.value=0}
        for(let i=0;i<(this.group?5:1);i++)this.spins[i]=time*this.spinSpeed[i];
        this.uniforms.uTime.value=time;this.uniforms.uAlpha.value=this.alpha;this.updateMouse();this.updateLabels();this.renderer.render(this.scene,this.camera);
      }
      requestAnimationFrame(this.loop);
    }
  }
  window.GPUParticleBody=WantedParticleBody;
})();
