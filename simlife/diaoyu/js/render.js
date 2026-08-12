// ===== Canvas 渲染与动画特效 =====
// 负责绘制天空、水面、浮漂、鱼、粒子等，并管理所有视觉动画。

const Render = (() => {

  let canvas, ctx, W, H;
  const waterY0 = 0.42; // 水面起始(屏高比例)
  let shoreX = 0.16;    // 岸边 x 比例
  let time = 0;
  const particles = [];
  const clouds = [];
  let fishRender = null; // 遛鱼时的鱼绘制状态

  // 初始化
  function init(c) {
    canvas = c;
    ctx = c.getContext('2d');
    resize();
    window.addEventListener('resize', resize);
    // 初始化云
    clouds.length = 0;
    for (let i = 0; i < 5; i++) {
      clouds.push({ x: Math.random(), y: 0.08 + Math.random() * 0.15, s: 0.5 + Math.random() * 0.8, spd: 0.01 + Math.random() * 0.02 });
    }
  }

  function resize() {
    const parent = canvas.parentElement;
    W = parent.clientWidth;
    H = Math.max(420, parent.clientHeight);
    const dpr = window.devicePixelRatio || 1;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = W + 'px';
    canvas.style.height = H + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  // 水面y坐标(给定x比例)
  function waterAt(x) {
    const wave = Math.sin(x * Math.PI * 2 + time * 0.8) * 0.02;
    return H * (waterY0 + wave * 0.3);
  }

  // ===== 主绘制 =====
  function draw(dt) {
    time += dt;
    // 清屏
    ctx.clearRect(0, 0, W, H);
    drawSky();
    drawBackground();
    drawWater();
    drawShore();
    drawBobber();
    drawFish();
    drawParticles();
    drawRod();
  }

  function drawSky() {
    const g = ctx.createLinearGradient(0, 0, 0, H * waterY0);
    g.addColorStop(0, '#7ec8f0');
    g.addColorStop(1, '#cfe8f7');
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, W, H * waterY0);
    // 太阳
    ctx.fillStyle = 'rgba(255,240,180,0.9)';
    ctx.beginPath();
    ctx.arc(W * 0.8, H * 0.12, 26, 0, Math.PI * 2);
    ctx.fill();
    // 云
    for (const cl of clouds) {
      cl.x += cl.spd * 0.016;
      if (cl.x > 1.2) cl.x = -0.2;
      drawCloud(cl.x * W, cl.y * H, cl.s);
    }
  }

  function drawCloud(x, y, s) {
    ctx.fillStyle = 'rgba(255,255,255,0.85)';
    ctx.beginPath();
    for (let i = 0; i < 5; i++) {
      const ox = (i - 2) * 18 * s;
      const oy = Math.abs(i - 2) * 8 * s;
      ctx.arc(x + ox, y + oy, 14 * s, 0, Math.PI * 2);
    }
    ctx.fill();
  }

  function drawBackground() {
    // 远处的山/树轮廓
    ctx.fillStyle = 'rgba(70,120,90,0.5)';
    ctx.beginPath();
    ctx.moveTo(0, H * waterY0);
    for (let x = 0; x <= W; x += 20) {
      const y = H * waterY0 - (Math.sin(x * 0.012 + 2) * 30 + 20);
      ctx.lineTo(x, y);
    }
    ctx.lineTo(W, H * waterY0);
    ctx.closePath();
    ctx.fill();
    // 岸边草地
    ctx.fillStyle = 'rgba(90,150,80,0.85)';
    ctx.beginPath();
    ctx.moveTo(0, H * waterY0 + 10);
    ctx.quadraticCurveTo(W * shoreX, H * waterY0 - 30, W * (shoreX + 0.12), H * waterY0 + 40);
    ctx.lineTo(W * (shoreX + 0.12), H);
    ctx.lineTo(0, H);
    ctx.closePath();
    ctx.fill();
  }

  function drawWater() {
    const zoneTint = DATA.ZONES[Game.state.zone].tint;
    const g = ctx.createLinearGradient(0, H * waterY0, 0, H);
    g.addColorStop(0, '#3a7ca5');
    g.addColorStop(1, '#1b3a5c');
    ctx.fillStyle = g;
    ctx.fillRect(W * shoreX, H * waterY0, W - W * shoreX, H - H * waterY0);
    // 水面波纹
    ctx.strokeStyle = 'rgba(255,255,255,0.18)';
    ctx.lineWidth = 1.5;
    for (let i = 0; i < 14; i++) {
      const y = H * (waterY0 + 0.02) + i * ((H - H * waterY0) / 14);
      ctx.beginPath();
      for (let x = W * shoreX; x <= W; x += 8) {
        const yy = y + Math.sin(x * 0.02 + time * 1.5 + i) * 3;
        if (x === W * shoreX) ctx.moveTo(x, yy);
        else ctx.lineTo(x, yy);
      }
      ctx.stroke();
    }
    // 水域色调
    ctx.fillStyle = zoneTint;
    ctx.fillRect(W * shoreX, H * waterY0, W - W * shoreX, H - H * waterY0);
  }

  function drawShore() {
    // 岸边地面
    ctx.fillStyle = '#8a6a3a';
    ctx.fillRect(0, H * waterY0 + 8, W * shoreX, H - H * waterY0);
    // 草
    ctx.fillStyle = '#5f9a4a';
    for (let i = 0; i < 12; i++) {
      const gx = 8 + i * (W * shoreX / 12);
      const gy = H * waterY0 + 6 + Math.sin(i) * 12;
      ctx.beginPath();
      ctx.moveTo(gx, gy);
      ctx.lineTo(gx - 3, gy - 14);
      ctx.lineTo(gx + 3, gy - 12);
      ctx.lineTo(gx + 5, gy - 18);
      ctx.lineTo(gx + 8, gy - 10);
      ctx.closePath();
      ctx.fill();
    }
  }

  // ===== 浮漂 =====
  function drawBobber() {
    const e = Game.engine;
    if (!e.bobber.active && e.phase !== 'flying') return;
    const bx = e.bobber.x * W;
    const by = e.bobber.active ? e.bobber.y : Render.waterAt(e.bobber.x);
    // 水面涟漪
    ctx.strokeStyle = 'rgba(255,255,255,0.4)';
    ctx.lineWidth = 1.5;
    for (let i = 1; i <= 3; i++) {
      const r = i * 6 + Math.sin(time * 3) * 2;
      ctx.beginPath();
      ctx.arc(bx, waterAt(e.bobber.x), r, 0, Math.PI * 2);
      ctx.stroke();
    }
    // 浮漂身体
    const bob = e.phase === 'bite' ? Math.sin(time * 20) * 4 : Math.sin(time * 2) * 2;
    const dip = e.phase === 'bite' ? 6 : 0;
    const fy = by + dip + bob;
    // 杆 (浮漂上的小棒)
    ctx.strokeStyle = '#d33';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(bx, fy - 8);
    ctx.lineTo(bx, fy + 2);
    ctx.stroke();
    // 主体
    ctx.fillStyle = '#e74444';
    ctx.beginPath();
    ctx.moveTo(bx, fy);
    ctx.arc(bx, fy + 6, 5, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#f5f5f5';
    ctx.beginPath();
    ctx.arc(bx, fy + 6, 5, 0, Math.PI);
    ctx.fill();
    // 鱼线
    ctx.strokeStyle = 'rgba(255,255,255,0.5)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(W * 0.5, H * 0.2);
    ctx.quadraticCurveTo(W * 0.5, H * waterY0, bx, fy);
    ctx.stroke();
  }

  // ===== 遛鱼时的鱼 =====
  function drawFish() {
    const f = Game.engine.fight || fishRender;
    if (!f) return;
    const fd = DATA.FISH.find(x => x.id === f.fish.id);
    const bob = Math.sin(f.bob * 4) * 8;
    const px = (0.4 + f.distance * 0.5) * W;
    const py = H * (waterY0 + 0.08) + bob;
    const sz = 12 + f.weight * 1.2;
    const sx = f.dir || 1;
    // 鱼身
    ctx.save();
    ctx.translate(px, py);
    ctx.scale(sx, 1);
    ctx.fillStyle = fd.color;
    ctx.beginPath();
    ctx.ellipse(0, 0, sz, sz * 0.5, 0, 0, Math.PI * 2);
    ctx.fill();
    // 尾巴
    ctx.fillStyle = fd.color;
    ctx.beginPath();
    ctx.moveTo(-sz * 0.8, 0);
    ctx.lineTo(-sz * 1.3, -sz * 0.35);
    ctx.lineTo(-sz * 1.3, sz * 0.35);
    ctx.closePath();
    ctx.fill();
    // 眼睛
    ctx.fillStyle = '#fff';
    ctx.beginPath();
    ctx.arc(sz * 0.5, -sz * 0.1, sz * 0.12, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#111';
    ctx.beginPath();
    ctx.arc(sz * 0.55, -sz * 0.1, sz * 0.05, 0, Math.PI * 2);
    ctx.fill();
    // 鱼鳍
    ctx.fillStyle = 'rgba(0,0,0,0.15)';
    ctx.beginPath();
    ctx.moveTo(-sz * 0.2, -sz * 0.4);
    ctx.lineTo(-sz * 0.4, -sz * 0.8);
    ctx.lineTo(-sz * 0.7, -sz * 0.3);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
    // 水花
    if (Math.random() < 0.1) Render.splash(px / W, py / H, 1);
  }

  // ===== 鱼竿 =====
  function drawRod() {
    const e = Game.engine;
    const baseX = W * 0.08, baseY = H * 0.92;
    const ang = e.phase === 'aim' ? -0.5 : -0.9;
    const len = 90;
    ctx.strokeStyle = '#8a5a2a';
    ctx.lineWidth = 5;
    ctx.beginPath();
    ctx.moveTo(baseX, baseY);
    ctx.lineTo(baseX + Math.cos(ang) * len, baseY + Math.sin(ang) * len);
    ctx.stroke();
    ctx.strokeStyle = '#a8723a';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(baseX + Math.cos(ang) * len, baseY + Math.sin(ang) * len);
    ctx.lineTo(baseX + Math.cos(ang - 0.15) * (len + 24), baseY + Math.sin(ang - 0.15) * (len + 24));
    ctx.stroke();
  }

  // ===== 粒子系统 =====
  function splash(x, y, scale = 1) {
    const px = x * W, py = y * H;
    for (let i = 0; i < 12 * scale; i++) {
      const a = -Math.PI / 2 + (Math.random() - 0.5) * 1.2;
      const sp = (2 + Math.random() * 4) * scale;
      particles.push({
        x: px, y: py,
        vx: Math.cos(a) * sp * 40, vy: Math.sin(a) * sp * 40 - 20,
        life: 1, max: 0.6 + Math.random() * 0.4,
        r: 1.5 + Math.random() * 2.5,
        color: 'rgba(220,240,255,',
      });
    }
  }

  function drawParticles() {
    for (let i = particles.length - 1; i >= 0; i--) {
      const p = particles[i];
      p.life -= 1 / 60;
      p.vy += 100 * (1 / 60);
      p.x += p.vx * (1 / 60);
      p.y += p.vy * (1 / 60);
      if (p.life <= 0) { particles.splice(i, 1); continue; }
      ctx.fillStyle = p.color + (p.life * 0.9) + ')';
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  // 工具函数
  function toast(msg, type = 'info') {
    const el = document.getElementById(type === 'landed' ? 'result-toast' : 'bite-toast');
    if (!el) return;
    el.textContent = msg;
    el.className = 'toast show ' + type;
    clearTimeout(el._t);
    el._t = setTimeout(() => el.className = 'toast hidden', 1400);
  }

  function landFish() {
    const f = Game.engine.landed;
    const fd = DATA.FISH.find(x => x.id === f.fish.id);
    toast(`🎉 钓到 ${fd.name} ${f.weight}kg！`, 'landed');
    fishRender = f;
    setTimeout(() => { fishRender = null; }, 1600);
  }

  function breakLine() {
    splash(Game.engine.bobber.x, Game.engine.bobber.y, 2);
  }

  function splashAtBobber() {
    splash(Game.engine.bobber.x, Game.engine.bobber.y, 2);
  }

  return { init, draw, waterAt, splash, splashAtBobber, toast, breakLine, landFish, get W(){return W}, get H(){return H} };
})();