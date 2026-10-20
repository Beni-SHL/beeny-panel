(() => {
"use strict";
const pageData = JSON.parse(document.getElementById("dashboard-page-data").textContent);

const prefersReduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/* ── Clock ── */
function updateClock(){
  document.getElementById('dashTime').textContent =
    new Date().toLocaleDateString(document.documentElement.lang==='fa'?'fa-IR':'en-US',{weekday:'long',year:'numeric',month:'long',day:'numeric'})
    + ' · ' + new Date().toLocaleTimeString(document.documentElement.lang==='fa'?'fa-IR':'en-US',{hour:'2-digit',minute:'2-digit'});
}
updateClock(); setInterval(updateClock,60000);

document.getElementById('refreshBtn').addEventListener('click', function(){
  this.classList.add('spinning');
  setTimeout(()=>this.classList.remove('spinning'),700);
});

/* ── Generic eased number animator ── */
function animateNumber(el, target, opts){
  opts = opts || {};
  const duration = opts.duration || 1200;
  const formatter = opts.formatter || (v => Math.round(v));
  if(prefersReduced || target===0){ el.textContent = formatter(target); return; }
  const start = performance.now();
  function tick(now){
    const p = Math.min((now-start)/duration,1);
    const e = 1-Math.pow(1-p,3);
    el.textContent = formatter(target*e);
    if(p<1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

/* ── Animated integer counters (stat cards) ── */
document.querySelectorAll('.stat-value[data-target]').forEach((el,i)=>{
  const target = parseInt(el.getAttribute('data-target'))||0;
  setTimeout(()=> animateNumber(el, target, {duration:1000}), i*80);
});

/* ── Byte formatter shared by hero + tooltips ── */
function fmtGB(v){
  if(v>=1000) return (v/1000).toFixed(2)+' TB';
  return v.toFixed(1)+' GB';
}

/* ── Lifetime traffic hero ── */
(function(){
  const target = parseFloat(pageData.lifetime)||0;
  const el = document.getElementById('lifetimeValue');
  animateNumber(el, target, {duration:1600, formatter:fmtGB});

  const canvas = document.getElementById('lifetimeCanvas');
  const wrap = canvas.parentElement;
  const DPR = window.devicePixelRatio||1;

  const pts = pageData.cumulativeTraffic;
  const maxV = Math.max(...pts,1);

  let W,H,prog=0;
  function resize(){
    W=wrap.clientWidth; H=wrap.clientHeight||150;
    canvas.width=W*DPR; canvas.height=H*DPR;
    canvas.style.width=W+'px'; canvas.style.height=H+'px';
  }
  function draw(p){
    const ctx=canvas.getContext('2d');
    ctx.clearRect(0,0,canvas.width,canvas.height);
    ctx.scale(DPR,DPR);
    const padT=14,padB=10;
    const chartH=H-padT-padB;
    const step=W/(pts.length-1);
    const visibleCount = Math.max(2, Math.floor(pts.length*Math.min(1,p*1.1)));

    ctx.beginPath();
    for(let i=0;i<visibleCount;i++){
      const x=i*step;
      const y=padT+chartH-(pts[i]/maxV)*chartH;
      if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
    }
    const lastX=(visibleCount-1)*step;
    ctx.lineTo(lastX,padT+chartH);
    ctx.lineTo(0,padT+chartH);
    ctx.closePath();
    const grad=ctx.createLinearGradient(0,padT,0,padT+chartH);
    grad.addColorStop(0,'rgba(34,211,238,0.35)');
    grad.addColorStop(1,'rgba(34,211,238,0.02)');
    ctx.fillStyle=grad;
    ctx.fill();

    ctx.beginPath();
    for(let i=0;i<visibleCount;i++){
      const x=i*step;
      const y=padT+chartH-(pts[i]/maxV)*chartH;
      if(i===0) ctx.moveTo(x,y); else ctx.lineTo(x,y);
    }
    ctx.strokeStyle='rgba(34,211,238,0.9)';
    ctx.lineWidth=2.5;
    ctx.lineJoin='round';
    ctx.shadowColor='rgba(34,211,238,0.6)';
    ctx.shadowBlur=10;
    ctx.stroke();
    ctx.shadowBlur=0;

    if(visibleCount>=pts.length){
      const x=lastX, y=padT+chartH-(pts[pts.length-1]/maxV)*chartH;
      const pulse = prefersReduced?1:(0.7+Math.sin(performance.now()/300)*0.3);
      ctx.beginPath();
      ctx.arc(x-1,y,5*pulse,0,Math.PI*2);
      ctx.fillStyle='#22d3ee';
      ctx.shadowColor='#22d3ee'; ctx.shadowBlur=14;
      ctx.fill();
      ctx.shadowBlur=0;
    }
    ctx.setTransform(1,0,0,1,0,0);
  }
  function animate(){
    prog=Math.min(1,prog+0.02);
    draw(prog);
    if(prog<1) requestAnimationFrame(animate);
    else if(!prefersReduced){ requestAnimationFrame(function loop(){ draw(1); requestAnimationFrame(loop); }); }
  }
  function init(){ resize(); prog=0; if(prefersReduced){draw(1);} else animate(); }
  setTimeout(init,300);
  window.addEventListener('resize',()=>{resize();draw(1);});
})();

/* ── Expiring badges ── */
document.querySelectorAll('.user-mini-row[data-expire]').forEach(row=>{
  const exp   = new Date(row.getAttribute('data-expire'));
  const today = new Date(); today.setHours(0,0,0,0);
  const days  = Math.ceil((exp-today)/86400000);
  const badge = row.querySelector('.exp-badge');
  if(!badge) return;
  if(days<0){  badge.textContent=`Exp ${Math.abs(days)}d`; badge.className='mini-badge badge-expired'; }
  else if(days<=2){ badge.textContent=`${days}d`; badge.className='mini-badge badge-expired'; }
  else { badge.textContent=`${days}d`; badge.className='mini-badge badge-expiring'; }
});

/* ── Protocol donut (correct arc positioning) ── */
const ovpnCount = parseInt(pageData.openvpnUsers)||0;
const wgCount   = parseInt(pageData.wireguardUsers)||0;
const total     = ovpnCount + wgCount || 1;
const CIRC      = 2 * Math.PI * 52; // r=52 → 326.73

document.getElementById('donutTotal').textContent = total;

function animateDonut(){
  const start = performance.now();
  const dur   = 900;
  const ovpnFrac = ovpnCount / total;
  const wgFrac   = wgCount   / total;
  const ovpnEl = document.getElementById('donutOpenVPN');
  const wgEl   = document.getElementById('donutWG');
  wgEl.style.transition  = 'none';
  ovpnEl.style.transition= 'none';

  function frame(now){
    const prog = Math.min((now-start)/dur, 1);
    const e = 1 - Math.pow(1-prog,3);
    const ovpnDash = CIRC * ovpnFrac * e;
    const wgDash   = CIRC * wgFrac   * e;
    ovpnEl.style.strokeDashoffset = CIRC - ovpnDash;
    const wgRotDeg = ovpnFrac * 360;
    wgEl.setAttribute('transform',`rotate(${wgRotDeg},70,70)`);
    wgEl.style.strokeDashoffset = CIRC - wgDash;
    if(prog<1) requestAnimationFrame(frame);
    else{
      document.getElementById('ovpnBar').style.width=(ovpnFrac*100)+'%';
      document.getElementById('wgBar').style.width=(wgFrac*100)+'%';
    }
  }
  requestAnimationFrame(frame);
}
setTimeout(animateDonut, 400);

/* Hover a protocol row to emphasize its arc */
function linkProtoHover(rowId, arcEl){
  const row = document.getElementById(rowId);
  if(!row) return;
  row.addEventListener('mouseenter',()=> arcEl.setAttribute('stroke-width','22'));
  row.addEventListener('mouseleave',()=> arcEl.setAttribute('stroke-width','18'));
}
linkProtoHover('ovpnRow', document.getElementById('donutOpenVPN'));
linkProtoHover('wgRow', document.getElementById('donutWG'));

/* ── Animated bar chart (Canvas) with hover tooltip ── */
(function(){
  const canvas = document.getElementById('barCanvas');
  const wrap   = canvas.parentElement;
  const tip    = document.getElementById('chartTip');
  const DPR    = window.devicePixelRatio||1;
  let W,H,animProg=0,rafId;

  const totalTraffic = parseFloat(pageData.totalTraffic)||0;
  const dayLabels    = pageData.weekLabels;
  const rawData      = pageData.weekTraffic;
  const maxVal       = Math.max(...rawData,1);
  const peakIdx      = rawData.indexOf(Math.max(...rawData));

  const totalUsersN  = parseInt(pageData.totalUsers)||1;
  document.getElementById('avgTraffic').textContent = (totalTraffic/totalUsersN).toFixed(1)+' GB';
  document.getElementById('peakDay').textContent    = dayLabels[peakIdx];

  let barGeom = [];

  function resize(){
    W = wrap.clientWidth;
    H = wrap.clientHeight||140;
    canvas.width  = W*DPR;
    canvas.height = H*DPR;
    canvas.style.width  = W+'px';
    canvas.style.height = H+'px';
  }

  function draw(prog, hoverIdx){
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0,0,canvas.width,canvas.height);
    ctx.scale(DPR,DPR);

    const padL=4,padR=4,padT=14,padB=26;
    const chartW=W-padL-padR;
    const chartH=H-padT-padB;
    const n=rawData.length;
    const gap=Math.max(4, chartW*0.02);
    const bw=(chartW-gap*(n-1))/n;
    barGeom = [];

    ctx.strokeStyle='rgba(255,255,255,0.05)';
    ctx.lineWidth=1;
    [0.25,0.5,0.75,1].forEach(f=>{
      const y=padT+chartH*(1-f);
      ctx.beginPath();ctx.moveTo(padL,y);ctx.lineTo(W-padR,y);ctx.stroke();
    });

    ctx.fillStyle='rgba(255,255,255,0.15)';
    ctx.font=`9px 'BeenyInter',sans-serif`;
    ctx.textAlign='right';
    [0.5,1].forEach(f=>{
      const y=padT+chartH*(1-f)+3;
      ctx.fillText((maxVal*f).toFixed(1), padL+30, y);
    });

    rawData.forEach((val,i)=>{
      const x   = padL + i*(bw+gap);
      const fullH=(val/maxVal)*chartH;
      const barProg = Math.max(0, Math.min(1, (prog*1.5)-(i*0.08)));
      const h   = fullH * barProg;
      barGeom.push({x,w:bw,val,i});
      if(h<=0) return;
      const y   = padT+chartH-h;
      const isPeak = i===peakIdx;
      const isHover = hoverIdx===i;

      const grad=ctx.createLinearGradient(x,y,x,padT+chartH);
      if(isPeak){
        grad.addColorStop(0,`rgba(74,222,128,${isHover?1:0.95})`);
        grad.addColorStop(0.45,'rgba(74,222,128,0.5)');
        grad.addColorStop(1,'rgba(74,222,128,0.07)');
      } else {
        grad.addColorStop(0,`rgba(96,165,250,${isHover?1:0.85})`);
        grad.addColorStop(0.45,'rgba(96,165,250,0.38)');
        grad.addColorStop(1,'rgba(96,165,250,0.05)');
      }

      const r=Math.min(7,bw/2);
      ctx.beginPath();
      ctx.moveTo(x+r,y);
      ctx.lineTo(x+bw-r,y);
      ctx.quadraticCurveTo(x+bw,y,x+bw,y+r);
      ctx.lineTo(x+bw,padT+chartH);
      ctx.lineTo(x,padT+chartH);
      ctx.lineTo(x,y+r);
      ctx.quadraticCurveTo(x,y,x+r,y);
      ctx.closePath();
      ctx.fillStyle=grad;
      if(isHover){ ctx.shadowColor=isPeak?'#4ade80':'#60a5fa'; ctx.shadowBlur=16; }
      ctx.fill();
      ctx.shadowBlur=0;

      if(isPeak){
        ctx.shadowColor='#4ade80';
        ctx.shadowBlur=14;
      }
      ctx.fillStyle=isPeak?'rgba(74,222,128,0.95)':'rgba(96,165,250,0.75)';
      ctx.fillRect(x,y,bw,2);
      ctx.shadowBlur=0;

      if(prog>0.8){
        const labelAlpha=Math.min(1,(prog-0.8)*5);
        ctx.globalAlpha=labelAlpha;
        ctx.fillStyle=isPeak?'rgba(74,222,128,1)':'rgba(255,255,255,0.5)';
        ctx.font=`bold ${Math.min(11,bw*0.55)}px 'BeenyInter',sans-serif`;
        ctx.textAlign='center';
        ctx.fillText(val.toFixed(1),x+bw/2,y-5);
        ctx.globalAlpha=1;
      }

      ctx.fillStyle='rgba(255,255,255,0.28)';
      ctx.font=`${Math.min(10,bw*0.5)}px 'BeenyInter',sans-serif`;
      ctx.textAlign='center';
      ctx.fillText(dayLabels[i],x+bw/2,H-padB+16);
    });

    ctx.setTransform(1,0,0,1,0,0);
  }

  function animate(){
    if(animProg<1){
      animProg=Math.min(1,animProg+0.018);
      draw(animProg);
      rafId=requestAnimationFrame(animate);
    } else {
      draw(1);
    }
  }

  function init(){
    resize();
    cancelAnimationFrame(rafId);
    animProg=0;
    if(prefersReduced){ draw(1); } else animate();
  }

  const showTip = (e)=>{
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX-rect.left;
    const hit = barGeom.find(b=> mx>=b.x-4 && mx<=b.x+b.w+4);
    draw(1, hit?hit.i:null);
    if(hit){
      tip.classList.add('show');
      tip.style.left = Math.max(68,Math.min(W-68,hit.x+hit.w/2))+'px';
      tip.style.top = '12px';
      tip.innerHTML = `<span>${dayLabels[hit.i]}</span>${hit.val.toFixed(2)} GB`;
    } else {
      tip.classList.remove('show');
    }
  };
  canvas.addEventListener('mousemove',showTip);
  canvas.addEventListener('pointerdown',showTip);
  canvas.addEventListener('mouseleave', ()=>{ tip.classList.remove('show'); draw(1,null); });

  setTimeout(init,350);
  window.addEventListener('resize',()=>{resize();draw(1);});
})();

/* ── Scroll reveal ── */
if('IntersectionObserver' in window && !prefersReduced){
  const io = new IntersectionObserver((entries)=>{
    entries.forEach(entry=>{
      if(entry.isIntersecting){ entry.target.classList.add('in'); io.unobserve(entry.target); }
    });
  }, {threshold:0.15});
  document.querySelectorAll('.reveal').forEach(el=> io.observe(el));
} else {
  document.querySelectorAll('.reveal').forEach(el=> el.classList.add('in'));
}

/* ── Subtle tilt on interactive glass cards ── */
if(!prefersReduced && window.matchMedia('(hover:hover)').matches){
  document.querySelectorAll('.gc-int').forEach(card=>{
    let raf=null;
    card.addEventListener('mousemove',(e)=>{
      const rect=card.getBoundingClientRect();
      const px=(e.clientX-rect.left)/rect.width-0.5;
      const py=(e.clientY-rect.top)/rect.height-0.5;
      if(raf) cancelAnimationFrame(raf);
      raf=requestAnimationFrame(()=>{
        card.style.transform=`perspective(700px) rotateX(${(-py*3.2).toFixed(2)}deg) rotateY(${(px*3.2).toFixed(2)}deg) translateY(-2px)`;
      });
    });
    card.addEventListener('mouseleave',()=>{
      if(raf) cancelAnimationFrame(raf);
      card.style.transform='';
    });
  });
}

})();
