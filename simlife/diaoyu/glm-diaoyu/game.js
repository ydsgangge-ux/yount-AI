/* =========================================================
   俄罗斯钓鱼 · 网页版
   纯 JS + Canvas 实现
   ========================================================= */

const canvas = document.getElementById('scene');
const ctx = canvas.getContext('2d');

let W = 0, H = 0, DPR = window.devicePixelRatio || 1;
function resize() {
  W = window.innerWidth;
  H = window.innerHeight;
  canvas.width = W * DPR;
  canvas.height = H * DPR;
  canvas.style.width = W + 'px';
  canvas.style.height = H + 'px';
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
}
window.addEventListener('resize', resize);
resize();

/* ---------- 鱼类配置 ---------- */
const FISH_TYPES = [
  { id:'rudd',   name:'拟鲤',     emoji:'🐟', rarity:1, coin:8,   exp:5,  size:[14,22], color:'#c0c8d0', stamina:60,  speed:1.0, weight:[0.1,0.6] },
  { id:'roach',  name:'斜齿鳊',   emoji:'🐠', rarity:1, coin:12,  exp:8,  size:[18,28], color:'#e8d8a0', stamina:80,  speed:1.1, weight:[0.2,1.0] },
  { id:'perch',  name:'河鲈',     emoji:'🐡', rarity:2, coin:25,  exp:15, size:[22,34], color:'#9bc26b', stamina:110, speed:1.3, weight:[0.4,2.0] },
  { id:'pike',   name:'梭鲈',     emoji:'🦈', rarity:3, coin:80,  exp:40, size:[40,60], color:'#5a7a5a', stamina:180, speed:1.6, weight:[1.5,8.0] },
  { id:'catfish',name:'六须鲶', emoji:'🐋', rarity:4, coin:200, exp:90, size:[55,90], color:'#4a4030', stamina:280, speed:0.9, weight:[4,25] },
  { id:'sturgeon',name:'鲟鱼',   emoji:'🐲', rarity:5, coin:500, exp:200,size:[70,120],color:'#6a6a78', stamina:400, speed:0.8, weight:[8,60] },
];

/* ---------- 游戏状态 ---------- */
const game = {
  state: 'idle',           // idle / casting / waiting / fighting / reeling
  time: 0,                 // 总时间秒
  dayTime: 8.0,            // 0-24 时
  coin: 0,
  exp: 0,
  level: 1,
  nextExp: 100,
  caughtTotal: 0,
  dex: {},                 // id -> count
  // 鱼竿
  rod: { x: 0, y: 0, tipX: 0, tipY: 0, angle: -0.6, sway: 0 },
  bobber: { x: 0, y: 0, vx: 0, vy: 0, active: false, inWater: false, bob: 0 },
  // 当前咬钩鱼
  hookedFish: null,
  // 搏斗
  tension: 50,             // 0-100
  fishStam: 100,
  tensionDir: 0,            // 鱼拉力方向
  tensionTarget: 50,
  // 鱼群
  fishes: [],
  // 粒子
  particles: [],
  ripples: [],
  // 提示
  biteTimer: 0,
  waitTimer: 0,
  // 点击
  mouseX: 0, mouseY: 0,
};

/* ---------- 工具 ---------- */
const rnd = (a,b)=> a + Math.random()*(b-a);
const rndi = (a,b)=> Math.floor(rnd(a,b+1));
const clamp = (v,a,b)=> Math.max(a, Math.min(b, v));
const dist = (x1,y1,x2,y2)=> Math.hypot(x2-x1, y2-y1);

/* ---------- 水面参数 ---------- */
const waterLine = () => H * 0.58;

/* ---------- 初始化鱼群 ---------- */
function spawnFishes() {
  game.fishes = [];
  const count = 12;
  for (let i = 0; i < count; i++) {
    spawnOneFish();
  }
}
function spawnOneFish() {
  // 按等级限制鱼的稀有度
  const maxRarity = Math.min(5, 1 + Math.floor(game.level / 2));
  const pool = FISH_TYPES.filter(f => f.rarity <= maxRarity);
  // 稀有度越高出现概率越低
  const weights = pool.map(f => 1 / f.rarity);
  const total = weights.reduce((a,b)=>a+b, 0);
  let r = Math.random() * total, pick = pool[0];
  for (let i = 0; i < pool.length; i++) {
    r -= weights[i];
    if (r <= 0) { pick = pool[i]; break; }
  }
  const wly = waterLine();
  const fish = {
    type: pick,
    x: Math.random() < 0.5 ? -50 : W + 50,
    y: rnd(wly + 50, H - 30),
    dir: 0,
    speed: rnd(0.4, 0.9) * pick.speed,
    size: rnd(pick.size[0], pick.size[1]),
    weight: rnd(pick.weight[0], pick.weight[1]),
    tail: 0,
    targetDepth: rnd(wly + 50, H - 30),
    interest: 0,             // 对鱼漂的兴趣 0-1
    state: 'roam',
  };
  fish.dir = fish.x < 0 ? 1 : -1;
  game.fishes.push(fish);
}

/* ---------- 抛竿 ---------- */
canvas.addEventListener('click', (e) => {
  if (game.state === 'idle') {
    castRod(e.clientX, e.clientY);
  }
});

function castRod(tx, ty) {
  if (game.state !== 'idle') return;
  if (ty < waterLine() + 10) { showToast('需要抛到水面'); return; }
  game.state = 'casting';
  setHint('抛竿中...');
  const btn = document.getElementById('action-btn');
  btn.disabled = true;

  // 鱼竿位置（左下角岸边）
  game.rod.x = 60;
  game.rod.y = waterLine() - 8;

  // 抛物线投掷
  const sx = game.rod.x + 40, sy = game.rod.y - 60;
  game.bobber.x = sx; game.bobber.y = sy;
  game.bobber.vx = (tx - sx) * 0.022;
  game.bobber.vy = -8;
  game.bobber.active = true;
  game.bobber.inWater = false;
}

/* ---------- 咬钩等待 ---------- */
function startWaiting() {
  game.state = 'waiting';
  setHint('等待鱼咬钩... 点击可提前收线');
  game.waitTimer = 0;
  game.biteTimer = rnd(4, 12);
  const btn = document.getElementById('action-btn');
  btn.disabled = false;
  btn.textContent = '收 线';
}

// 等待时点击收线
document.getElementById('action-btn').addEventListener('click', () => {
  if (game.state === 'waiting') {
    retrieveLine();
  }
});
// 等待时画布点击也算收线
canvas.addEventListener('click', () => {
  if (game.state === 'waiting') retrieveLine();
}, true);

function retrieveLine() {
  game.bobber.active = false;
  game.state = 'idle';
  setHint('点击水面 抛 出鱼竿');
  const btn = document.getElementById('action-btn');
  btn.disabled = false;
  btn.textContent = '抛 竿';
  showToast('收线了，没鱼');
}

/* ---------- 咬钩 → 搏斗 ---------- */
function fishBites(fish) {
  game.hookedFish = fish;
  game.state = 'fighting';
  game.tension = 50;
  game.tensionTarget = 50;
  game.fishStam = 100;
  game.bobber.bob = 8;
  spawnSplash(game.bobber.x, waterLine(), 18);
  spawnRipple(game.bobber.x, waterLine());
  setHint('上钩了！');

  // 显示战斗面板
  document.getElementById('fight-panel').classList.remove('hidden');
  document.getElementById('fish-name').textContent = '???';
  document.getElementById('fish-stam').textContent = '100';
  document.getElementById('action-btn').disabled = true;
}

/* 搏斗操作 */
let pulling = false, releasing = false;
document.getElementById('pull-btn').addEventListener('mousedown', ()=> pulling = true);
document.getElementById('pull-btn').addEventListener('mouseup',   ()=> pulling = false);
document.getElementById('pull-btn').addEventListener('mouseleave',()=> pulling = false);
document.getElementById('pull-btn').addEventListener('touchstart',(e)=>{ e.preventDefault(); pulling = true; });
document.getElementById('pull-btn').addEventListener('touchend',  (e)=>{ e.preventDefault(); pulling = false; });
document.getElementById('release-btn').addEventListener('mousedown', ()=> releasing = true);
document.getElementById('release-btn').addEventListener('mouseup',   ()=> releasing = false);
document.getElementById('release-btn').addEventListener('mouseleave',()=> releasing = false);
document.getElementById('release-btn').addEventListener('touchstart',(e)=>{ e.preventDefault(); releasing = true; });
document.getElementById('release-btn').addEventListener('touchend',  (e)=>{ e.preventDefault(); releasing = false; });

function updateFight(dt) {
  const f = game.hookedFish;
  if (!f) return;

  // 鱼的拉力方向变化
  game.tensionDir += rnd(-1, 1) * dt * 60;
  game.tensionTarget = clamp(50 + game.tensionDir, 5, 95);
  game.tensionDir *= 0.96;

  // 玩家操作影响
  if (pulling) {
    game.tension += 35 * dt;
    game.fishStam -= (8 + f.type.stamina/40) * dt;
  } else if (releasing) {
    game.tension -= 35 * dt;
    game.fishStam += 1 * dt;
  } else {
    game.tension += (game.tensionTarget - game.tension) * dt * 0.8;
  }

  // 张力自然漂移向目标
  game.tension += (game.tensionTarget - game.tension) * dt * 0.5;
  game.tension = clamp(game.tension, 0, 100);
  game.fishStam = clamp(game.fishStam, 0, 100);

  // 鱼挣扎时鱼漂抖动
  game.bobber.bob = Math.sin(performance.now()*0.02) * 4 + 2;

  // 更新 UI
  document.getElementById('tension-ind').style.left = game.tension + '%';
  document.getElementById('fish-stam').textContent = Math.round(game.fishStam);

  // 张力过高断线
  if (game.tension >= 99) {
    showToast('💥 线断了！鱼跑了');
    endFight(false);
  }
  // 张力过低脱钩
  else if (game.tension <= 1) {
    showToast('💨 鱼脱钩了');
    endFight(false);
  }
  // 鱼力耗尽，捕获
  else if (game.fishStam <= 0) {
    endFight(true);
  }
}

function endFight(success) {
  const f = game.hookedFish;
  document.getElementById('fight-panel').classList.add('hidden');
  pulling = releasing = false;
  if (success && f) {
    // 奖励
    const coinGain = Math.round(f.type.coin * (0.8 + f.weight / f.type.weight[1] * 0.4));
    const expGain = Math.round(f.type.exp * (0.8 + f.weight / f.type.weight[1] * 0.4));
    game.coin += coinGain;
    game.exp += expGain;
    game.caughtTotal++;
    game.dex[f.type.id] = (game.dex[f.type.id] || 0) + 1;
    // 移除该鱼
    const idx = game.fishes.indexOf(f);
    if (idx >= 0) game.fishes.splice(idx, 1);
    spawnOneFish();
    // 升级判定
    while (game.exp >= game.nextExp) {
      game.exp -= game.nextExp;
      game.level++;
      game.nextExp = Math.round(game.nextExp * 1.5);
      showToast('🎉 升级！Lv.' + game.level);
    }
    showToast(`捕获 ${f.type.name} +${coinGain}💰 +${expGain}✨`);
    updateDex();
    spawnSplash(game.bobber.x, waterLine(), 24);
  } else {
    // 鱼跑了
    if (f) {
      f.state = 'flee';
      f.interest = 0;
    }
  }
  game.hookedFish = null;
  game.bobber.active = false;
  game.state = 'idle';
  setHint('点击水面 抛 出鱼竿');
  document.getElementById('action-btn').disabled = false;
  document.getElementById('action-btn').textContent = '抛 竿';
  updateHUD();
}

/* ---------- 粒子 ---------- */
function spawnSplash(x, y, n) {
  for (let i = 0; i < n; i++) {
    game.particles.push({
      x, y,
      vx: rnd(-3, 3),
      vy: rnd(-7, -2),
      life: rnd(0.4, 0.9),
      maxLife: 0.9,
      size: rnd(1.5, 3.5),
      type: 'drop',
    });
  }
}
function spawnRipple(x, y) {
  game.ripples.push({ x, y, r: 4, maxR: 60, life: 1 });
}
function spawnSparkle(x, y) {
  game.particles.push({
    x, y, vx: rnd(-0.4,0.4), vy: rnd(-1.2,-0.3),
    life: rnd(0.8, 1.6), maxLife: 1.6,
    size: rnd(0.8, 1.8), type: 'spark'
  });
}

function updateParticles(dt) {
  for (let i = game.particles.length - 1; i >= 0; i--) {
    const p = game.particles[i];
    p.x += p.vx;
    p.y += p.vy;
    if (p.type === 'drop') {
      p.vy += 0.4; // 重力
    } else if (p.type === 'spark') {
      p.vy += 0.02;
    }
    p.life -= dt;
    if (p.life <= 0) game.particles.splice(i, 1);
  }
  for (let i = game.ripples.length - 1; i >= 0; i--) {
    const r = game.ripples[i];
    r.r += 60 * dt;
    r.life -= dt * 1.2;
    if (r.life <= 0 || r.r > r.maxR) game.ripples.splice(i, 1);
  }
}

/* ---------- 更新逻辑 ---------- */
function update(dt) {
  game.time += dt;
  // 昼夜 1 现实秒 = 0.1 游戏小时
  game.dayTime += dt * 0.1;
  if (game.dayTime >= 24) game.dayTime -= 24;
  updateTODLabel();

  // 鱼竿摆动
  game.rod.sway = Math.sin(game.time * 1.5) * 0.02;

  // 抛竿中
  if (game.state === 'casting') {
    game.bobber.vy += 0.35;
    game.bobber.x += game.bobber.vx;
    game.bobber.y += game.bobber.vy;
    if (game.bobber.y >= waterLine()) {
      game.bobber.y = waterLine();
      game.bobber.inWater = true;
      spawnSplash(game.bobber.x, waterLine(), 14);
      spawnRipple(game.bobber.x, waterLine());
      startWaiting();
    }
  }

  // 等待咬钩
  if (game.state === 'waiting') {
    game.waitTimer += dt;
    game.bobber.bob = Math.sin(game.time * 2) * 1.5;
    // 鱼漂小幅涟漪
    if (Math.random() < dt * 1.5) spawnRipple(game.bobber.x, waterLine());

    // 找最近的鱼，让它对鱼漂感兴趣
    let nearest = null, nd = 9999;
    for (const f of game.fishes) {
      if (f.state === 'flee' || f.state === 'hooked') continue;
      const d = dist(f.x, f.y, game.bobber.x, waterLine() + 40);
      if (d < nd) { nd = d; nearest = f; }
    }
    if (nearest && nd < 350) {
      nearest.interest = Math.min(1, nearest.interest + dt * 0.3);
      nearest.state = 'curious';
    }

    // 计时咬钩
    game.biteTimer -= dt;
    if (game.biteTimer <= 0 && nearest && nearest.state === 'curious') {
      nearest.state = 'hooked';
      fishBites(nearest);
    } else if (game.biteTimer <= 0) {
      // 重置等待
      game.biteTimer = rnd(3, 8);
    }
  }

  // 搏斗
  if (game.state === 'fighting') {
    updateFight(dt);
  }

  // 鱼群行为
  for (const f of game.fishes) {
    f.tail += dt * 8 * f.speed;
    if (f.state === 'hooked') {
      // 鱼跟随鱼漂，并剧烈摆动
      const tx = game.bobber.x + Math.sin(game.time*8) * 12;
      const ty = waterLine() + 30 + Math.sin(game.time*6) * 6;
      f.x += (tx - f.x) * 0.2;
      f.y += (ty - f.y) * 0.2;
      f.dir = Math.sin(game.time*4) > 0 ? 1 : -1;
    } else if (f.state === 'curious') {
      // 朝鱼漂游
      const tx = game.bobber.x, ty = waterLine() + 30;
      const dx = tx - f.x, dy = ty - f.y;
      const d = Math.hypot(dx, dy) || 1;
      f.x += (dx/d) * f.speed * 60 * dt;
      f.y += (dy/d) * f.speed * 60 * dt;
      f.dir = dx > 0 ? 1 : -1;
    } else if (f.state === 'flee') {
      f.x += f.dir * f.speed * 90 * dt;
      f.interest = Math.max(0, f.interest - dt * 0.5);
      if (f.interest <= 0) f.state = 'roam';
    } else {
      // 自由游动
      f.x += f.dir * f.speed * 40 * dt;
      // 上下漂移
      if (Math.abs(f.y - f.targetDepth) < 5) {
        f.targetDepth = rnd(waterLine() + 50, H - 30);
      }
      f.y += (f.targetDepth - f.y) * 0.3 * dt;
      // 出界回收
      if (f.x < -80) { f.x = -80; f.dir = 1; }
      if (f.x > W + 80) { f.x = W + 80; f.dir = -1; }
      if (Math.random() < dt * 0.3) f.dir *= -1;
    }
  }

  // 张力条（搏斗中）和等待中显示提示力度
  if (game.state === 'fighting') {
    document.getElementById('power-fill').style.width = game.tension + '%';
  }

  // 夜晚星光
  if (isNight() && Math.random() < dt * 4) {
    spawnSparkle(rnd(0, W), rnd(0, waterLine() * 0.7));
  }

  updateParticles(dt);
}

function isNight() {
  const t = game.dayTime;
  return t < 6 || t > 19;
}
function updateTODLabel() {
  const t = game.dayTime;
  let label = '白天';
  if (t < 5 || t > 21) label = '深夜';
  else if (t < 7) label = '黎明';
  else if (t < 17) label = '白天';
  else if (t < 19) label = '黄昏';
  else label = '夜晚';
  document.getElementById('tod-label').textContent = label;
}

/* ---------- 渲染 ---------- */
function getSkyColors() {
  const t = game.dayTime;
  // 关键时段插值
  let top, bot;
  if (t < 5) { top = '#0a0e1f'; bot = '#1a2444'; }            // 深夜
  else if (t < 7) { const k = (t-5)/2; top = lerpColor('#0a0e1f','#3a3a6a',k); bot = lerpColor('#1a2444','#e8a07a',k); } // 黎明
  else if (t < 9) { const k = (t-7)/2; top = lerpColor('#3a3a6a','#5fa8e8',k); bot = lerpColor('#e8a07a','#bfe3ff',k); } // 清晨
  else if (t < 17) { top = '#5fa8e8'; bot = '#bfe3ff'; }       // 白天
  else if (t < 19) { const k = (t-17)/2; top = lerpColor('#5fa8e8','#3a2a5a',k); bot = lerpColor('#bfe3ff','#e89060',k); } // 黄昏
  else if (t < 21) { const k = (t-19)/2; top = lerpColor('#3a2a5a','#0a0e1f',k); bot = lerpColor('#e89060','#1a2444',k); } // 夜晚
  else { top = '#0a0e1f'; bot = '#1a2444'; }
  return { top, bot };
}
function lerpColor(a, b, t) {
  const pa = hexToRgb(a), pb = hexToRgb(b);
  const r = Math.round(pa.r + (pb.r-pa.r)*t);
  const g = Math.round(pa.g + (pb.g-pa.g)*t);
  const bl = Math.round(pa.b + (pb.b-pa.b)*t);
  return `rgb(${r},${g},${bl})`;
}
function hexToRgb(h) {
  h = h.replace('#','');
  return { r: parseInt(h.slice(0,2),16), g: parseInt(h.slice(2,4),16), b: parseInt(h.slice(4,6),16) };
}

function render() {
  ctx.clearRect(0, 0, W, H);

  // 天空渐变
  const sky = getSkyColors();
  const wly = waterLine();
  const gSky = ctx.createLinearGradient(0, 0, 0, wly);
  gSky.addColorStop(0, sky.top);
  gSky.addColorStop(1, sky.bot);
  ctx.fillStyle = gSky;
  ctx.fillRect(0, 0, W, wly);

  // 太阳/月亮
  drawSunMoon();

  // 远山
  drawMountains();

  // 云
  drawClouds();

  // 水面
  drawWater();

  // 水下鱼
  drawFishes();

  // 涟漪
  drawRipples();

  // 岸边/码头
  drawDock();

  // 鱼竿和线
  drawRod();

  // 鱼漂
  drawBobber();

  // 粒子
  drawParticles();

  // 夜晚遮罩
  if (isNight()) {
    ctx.fillStyle = 'rgba(10, 14, 35, 0.35)';
    ctx.fillRect(0, 0, W, H);
  }
}

function drawSunMoon() {
  const t = game.dayTime;
  const skyH = waterLine();
  let x, y, isSun = (t >= 6 && t <= 18);
  if (isSun) {
    const k = (t - 6) / 12; // 0-1
    x = W * (0.1 + k * 0.8);
    y = skyH - Math.sin(k * Math.PI) * (skyH * 0.7);
    ctx.save();
    const glow = ctx.createRadialGradient(x, y, 0, x, y, 90);
    glow.addColorStop(0, 'rgba(255, 230, 140, 0.6)');
    glow.addColorStop(1, 'rgba(255, 230, 140, 0)');
    ctx.fillStyle = glow;
    ctx.fillRect(x-90, y-90, 180, 180);
    ctx.fillStyle = '#ffe9a8';
    ctx.beginPath();
    ctx.arc(x, y, 28, 0, Math.PI*2);
    ctx.fill();
    ctx.restore();
  } else {
    let mt = t < 6 ? t + 6 : t - 18; // 0-12
    const k = mt / 12;
    x = W * (0.1 + k * 0.8);
    y = skyH - Math.sin(k * Math.PI) * (skyH * 0.7);
    ctx.save();
    ctx.fillStyle = '#e8eaf0';
    ctx.beginPath();
    ctx.arc(x, y, 22, 0, Math.PI*2);
    ctx.fill();
    // 月牙阴影
    ctx.fillStyle = getSkyColors().top;
    ctx.beginPath();
    ctx.arc(x-8, y-4, 22, 0, Math.PI*2);
    ctx.fill();
    ctx.restore();
  }
}

function drawMountains() {
  const wly = waterLine();
  // 远山
  ctx.fillStyle = 'rgba(60, 80, 120, 0.55)';
  ctx.beginPath();
  ctx.moveTo(0, wly);
  let x = 0;
  const seed = 12345;
  let s = seed;
  while (x <= W) {
    s = (s * 9301 + 49297) % 233280;
    const h = 40 + (s / 233280) * 80;
    ctx.lineTo(x, wly - h);
    x += 80;
  }
  ctx.lineTo(W, wly);
  ctx.closePath();
  ctx.fill();
  // 近山
  ctx.fillStyle = 'rgba(40, 60, 90, 0.7)';
  ctx.beginPath();
  ctx.moveTo(0, wly);
  x = 0; s = 54321;
  while (x <= W) {
    s = (s * 9301 + 49297) % 233280;
    const h = 20 + (s / 233280) * 50;
    ctx.lineTo(x, wly - h);
    x += 60;
  }
  ctx.lineTo(W, wly);
  ctx.closePath();
  ctx.fill();
}

function drawClouds() {
  const wly = waterLine();
  ctx.save();
  ctx.fillStyle = 'rgba(255,255,255,0.7)';
  const offset = (game.time * 8) % (W + 200);
  for (let i = 0; i < 5; i++) {
    const x = ((i * 280) + offset) % (W + 200) - 100;
    const y = 40 + (i * 37) % 80;
    drawCloud(x, y, 40 + (i*13)%30);
  }
  ctx.restore();
}
function drawCloud(x, y, r) {
  ctx.beginPath();
  ctx.arc(x, y, r*0.7, 0, Math.PI*2);
  ctx.arc(x+r*0.7, y+5, r*0.6, 0, Math.PI*2);
  ctx.arc(x-r*0.7, y+5, r*0.55, 0, Math.PI*2);
  ctx.arc(x, y+10, r*0.8, 0, Math.PI*2);
  ctx.fill();
}

function drawWater() {
  const wly = waterLine();
  // 水体渐变
  const t = game.dayTime;
  let waterTop, waterBot;
  if (isNight()) { waterTop = '#1a3550'; waterBot = '#08121e'; }
  else if (t < 7 || t > 17) { waterTop = '#3a5a78'; waterBot = '#1a2a3a'; }
  else { waterTop = '#4a90c8'; waterBot = '#0e3a5a'; }
  const g = ctx.createLinearGradient(0, wly, 0, H);
  g.addColorStop(0, waterTop);
  g.addColorStop(1, waterBot);
  ctx.fillStyle = g;
  ctx.fillRect(0, wly, W, H - wly);

  // 水面波浪线
  ctx.save();
  ctx.strokeStyle = 'rgba(255,255,255,0.15)';
  ctx.lineWidth = 1.2;
  for (let i = 0; i < 6; i++) {
    const y = wly + i * 8 + 4;
    ctx.beginPath();
    for (let x = 0; x <= W; x += 6) {
      const yy = y + Math.sin((x * 0.02) + game.time * (1.2 + i*0.2) + i) * (2 - i*0.2);
      if (x === 0) ctx.moveTo(x, yy);
      else ctx.lineTo(x, yy);
    }
    ctx.stroke();
  }
  ctx.restore();

  // 水面高光反射
  ctx.save();
  ctx.fillStyle = 'rgba(255,255,255,0.08)';
  for (let i = 0; i < 20; i++) {
    const x = (i * 73 + game.time * 20) % W;
    const y = wly + 6 + (i % 4) * 4;
    ctx.fillRect(x, y, 20, 1);
  }
  ctx.restore();
}

function drawFishes() {
  for (const f of game.fishes) {
    drawFish(f);
  }
}
function drawFish(f) {
  const s = f.size;
  ctx.save();
  ctx.translate(f.x, f.y);
  ctx.scale(f.dir, 1);
  // 身体
  ctx.fillStyle = f.type.color;
  ctx.beginPath();
  ctx.ellipse(0, 0, s*0.5, s*0.25, 0, 0, Math.PI*2);
  ctx.fill();
  // 尾巴
  const tailWag = Math.sin(f.tail) * 0.4;
  ctx.beginPath();
  ctx.moveTo(-s*0.4, 0);
  ctx.lineTo(-s*0.7, -s*0.25 + tailWag*s*0.1);
  ctx.lineTo(-s*0.7, s*0.25 + tailWag*s*0.1);
  ctx.closePath();
  ctx.fill();
  // 眼睛
  ctx.fillStyle = '#fff';
  ctx.beginPath();
  ctx.arc(s*0.3, -s*0.05, s*0.06, 0, Math.PI*2);
  ctx.fill();
  ctx.fillStyle = '#000';
  ctx.beginPath();
  ctx.arc(s*0.32, -s*0.05, s*0.03, 0, Math.PI*2);
  ctx.fill();
  ctx.restore();
}

function drawRipples() {
  ctx.save();
  for (const r of game.ripples) {
    ctx.strokeStyle = `rgba(255,255,255,${r.life * 0.4})`;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.ellipse(r.x, r.y, r.r, r.r * 0.35, 0, 0, Math.PI*2);
    ctx.stroke();
  }
  ctx.restore();
}

function drawDock() {
  const wly = waterLine();
  // 木板平台
  ctx.fillStyle = '#3a2818';
  ctx.fillRect(0, wly - 14, 90, 14);
  ctx.fillStyle = '#4a3422';
  ctx.fillRect(0, wly - 14, 90, 4);
  // 木纹
  ctx.strokeStyle = 'rgba(0,0,0,0.3)';
  ctx.lineWidth = 1;
  for (let i = 0; i < 4; i++) {
    ctx.beginPath();
    ctx.moveTo(i * 25, wly - 14);
    ctx.lineTo(i * 25, wly);
    ctx.stroke();
  }
  // 立柱
  ctx.fillStyle = '#2a1c10';
  ctx.fillRect(75, wly, 8, 30);
  // 倒影
  ctx.fillStyle = 'rgba(58, 40, 24, 0.3)';
  ctx.fillRect(0, wly, 90, 6);
}

function drawRod() {
  const wly = waterLine();
  const rx = 60, ry = wly - 14;
  // 钓鱼者简笔
  ctx.save();
  ctx.fillStyle = '#2a3a5a';
  // 身体
  ctx.fillRect(rx - 8, ry - 38, 16, 24);
  // 头
  ctx.beginPath();
  ctx.arc(rx, ry - 44, 9, 0, Math.PI*2);
  ctx.fill();
  // 帽子
  ctx.fillStyle = '#5a3a2a';
  ctx.fillRect(rx - 11, ry - 50, 22, 4);
  ctx.fillRect(rx - 7, ry - 56, 14, 6);

  // 鱼竿
  const baseX = rx + 4, baseY = ry - 30;
  const tipX = baseX + Math.cos(game.rod.angle + game.rod.sway) * 80;
  const tipY = baseY + Math.sin(game.rod.angle + game.rod.sway) * 80;
  game.rod.tipX = tipX; game.rod.tipY = tipY;

  ctx.strokeStyle = '#6a4020';
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(baseX, baseY);
  // 弧形鱼竿
  const midX = (baseX + tipX) / 2 + 5;
  const midY = (baseY + tipY) / 2 - 8;
  ctx.quadraticCurveTo(midX, midY, tipX, tipY);
  ctx.stroke();
  ctx.restore();

  // 鱼线
  if (game.bobber.active || game.state === 'fighting') {
    ctx.strokeStyle = 'rgba(255,255,255,0.6)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(tipX, tipY);
    // 曲线下垂
    const bx = game.bobber.x, by = game.bobber.y;
    const ctrlX = (tipX + bx) / 2;
    const ctrlY = Math.max(tipY, by) + 20;
    ctx.quadraticCurveTo(ctrlX, ctrlY, bx, by);
    ctx.stroke();
  }
}

function drawBobber() {
  if (!game.bobber.active && game.state !== 'fighting') return;
  const b = game.bobber;
  const y = b.y + b.bob;
  ctx.save();
  // 浮标
  ctx.fillStyle = '#e74c3c';
  ctx.beginPath();
  ctx.arc(b.x, y, 5, 0, Math.PI, true);
  ctx.fill();
  ctx.fillStyle = '#fff';
  ctx.beginPath();
  ctx.arc(b.x, y, 5, Math.PI, 0, true);
  ctx.fill();
  // 顶部小杆
  ctx.strokeStyle = '#333';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(b.x, y - 5);
  ctx.lineTo(b.x, y - 12);
  ctx.stroke();
  ctx.restore();
}

function drawParticles() {
  for (const p of game.particles) {
    const alpha = p.life / p.maxLife;
    if (p.type === 'drop') {
      ctx.fillStyle = `rgba(180, 220, 255, ${alpha})`;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size, 0, Math.PI*2);
      ctx.fill();
    } else if (p.type === 'spark') {
      ctx.fillStyle = `rgba(255, 240, 200, ${alpha})`;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.size, 0, Math.PI*2);
      ctx.fill();
    }
  }
}

/* ---------- HUD ---------- */
function updateHUD() {
  document.getElementById('lvl').textContent = game.level;
  document.getElementById('coin').textContent = game.coin;
  document.getElementById('caught').textContent = game.caughtTotal;
}

function updateDex() {
  const list = document.getElementById('dex-list');
  list.innerHTML = '';
  for (const t of FISH_TYPES) {
    const unlocked = game.dex[t.id] > 0;
    const div = document.createElement('div');
    div.className = 'dex-item ' + (unlocked ? 'unlocked' : 'locked');
    div.innerHTML = `
      <span>${unlocked ? t.emoji : '❓'} ${unlocked ? t.name : '???'}</span>
      <span class="count">${unlocked ? '×' + game.dex[t.id] : ''}</span>
    `;
    list.appendChild(div);
  }
}

function setHint(t) {
  document.getElementById('hint').textContent = t;
}

let toastTimer = null;
function showToast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2200);
}

/* ---------- 主循环 ---------- */
let lastT = performance.now();
function loop(t) {
  const dt = Math.min(0.05, (t - lastT) / 1000);
  lastT = t;
  update(dt);
  render();
  requestAnimationFrame(loop);
}

/* ---------- 启动 ---------- */
spawnFishes();
updateDex();
updateHUD();
setHint('点击水面 抛 出鱼竿');
requestAnimationFrame(loop);
