// ===== 核心钓鱼引擎 =====
// 负责抛竿、咬钩、提竿、遛鱼、收线的状态机与物理逻辑，不直接操作 DOM。

class Engine {
  constructor() {
    this.reset();
  }

  reset() {
    this.phase = 'idle';      // idle | aim | waiting | bite | fighting | landed
    this.power = 0;           // 蓄力 0~1
    this.powerDir = 1;        // 蓄力条方向
    this.castX = 0;           // 浮漂落点 x(0~1)
    this.castDist = 0;        // 落点距离 0~1
    this.bobber = { x:0, y:0, t:0, active:false };
    this.biteTimer = 0;       // 等待咬钩时间
    this.biteWindow = 0;      // 咬钩提示后剩余点击窗口
    this.fish = null;         // 当前咬钩的鱼定义
    this.fight = null;        // 遛鱼状态
    this.landed = null;       // 已上钩结果
    this.waitElapsed = 0;
  }

  // 开始蓄力
  startAim() {
    if (this.phase !== 'idle') return;
    this.phase = 'aim';
    this.power = 0;
    this.powerDir = 1;
  }

  // 蓄力更新 (由 render 每次帧推进)
  charge(dt) {
    if (this.phase !== 'aim') return;
    this.power += 0.5 * dt * this.powerDir;
    if (this.power >= 1) { this.power = 1; this.powerDir = -1; }
    if (this.power <= 0) { this.power = 0; this.powerDir = 1; }
  }

  // 释放抛竿
  cast(equip) {
    if (this.phase !== 'aim') return;
    const rod = equip.rod;
    this.castDist = 0.25 + this.power * 0.6 * (rod.cast / 100);
    this.castDist = Math.min(0.95, this.castDist);
    this.castX = 0.35 + this.castDist * 0.55;
    this.bobber = { x: 0.5, y: 0.35, t: 0, active: true };
    this.phase = 'flying';
    // 咬钩等待时间：距离越远越久
    this.biteTimer = 1.5 + this.castDist * 4;
    this.fish = this._pickFish(equip);
    this.waitElapsed = 0;
  }

  // 飞行中更新 (浮漂飞向落点)
  updateFlight(dt) {
    const targetX = this.castX;
    const targetY = Render.waterAt(targetX);
    this.bobber.t += dt * 1.6;
    const t = Math.min(1, this.bobber.t);
    this.bobber.x = this.bobber.x + (targetX - this.bobber.x) * t;
    this.bobber.y = this.bobber.y + (targetY - this.bobber.y) * t;
    if (this.bobber.t >= 1) {
      Render.splash(targetX, targetY);
      this.phase = 'waiting';
      this.bobber.active = true;
      this.bobber.x = targetX;
      this.bobber.y = targetY;
    }
  }

  // 等待咬钩
  updateWaiting(dt, equip) {
    this.waitElapsed += dt;
    this.biteTimer -= dt;
    // 浮漂起伏动画时间
    this.bobber.phase = (this.bobber.phase || 0) + dt;
    if (this.biteTimer <= 0) {
      // 触发咬钩
      this.phase = 'bite';
      this.biteWindow = 1.6; // 点击窗口
      Render.toast('咬钩了！快点击提竿！', 'bite');
    }
  }

  // 咬钩窗口更新
  updateBite(dt) {
    this.biteWindow -= dt;
    if (this.biteWindow <= 0) {
      // 错过 -> 鱼跑了
      this.phase = 'waiting';
      this.biteTimer = 2 + Math.random() * 3;
    }
  }

  // 提竿刺鱼
  hook(equip) {
    if (this.phase !== 'bite') return;
    const fish = this.fish;
    const rodFight = equip.rod.fight;
    // 刺鱼成功率：大鱼更难
    const sizeFactor = Math.random();
    const success = sizeFactor * (40 + rodFight) > fish.max * 0.6;
    if (!success) {
      Render.toast('提竿太早，脱钩了…', 'miss');
      this.phase = 'waiting';
      this.biteTimer = 2 + Math.random() * 3;
      return;
    }
    // 进入遛鱼
    const weight = this._randWeight(fish);
    this.fight = {
      fish,
      weight,
      distance: 0.7 + Math.random() * 0.25, // 0~1 到岸距离
      tension: 20,                          // 起手张力，避免立即松弛
      stamina: fish.fight,
      maxStamina: fish.fight,
      escape: 0,
      pullTimer: 0,
      bob: 0,
      dir: Math.random() > 0.5 ? 1 : -1,
      landed: false,
    };
    this.phase = 'fighting';
    Render.splashAtBobber();
    Render.toast(fish.name + ' 上钩了！开始遛鱼！', 'fight');
  }

  // 遛鱼更新
  updateFight(dt, equip) {
    const f = this.fight;
    f.bob += dt;
    // 鱼挣扎：周期性地产生张力
    f.pullTimer -= dt;
    const pullBurst = f.stamina > 0;
    if (pullBurst && f.pullTimer <= 0) {
      const pull = f.fish.strength * 0.30 * (0.7 + Math.random() * 0.6);
      f.tension += pull * (1 - (equip.reel.drag / 100) * 0.6);
      f.pullTimer = 1.0 + (1 - f.stamina / f.maxStamina) * 0.6;
      // 鱼挣扎时消耗耐力 (张力越高消耗越快)
      f.stamina -= f.fish.fight * 0.03 * (equip.reel.drag > 0 ? 1.2 : 1);
      if (f.stamina < 0) f.stamina = 0;
      // 随机横向摆动
      f.dir = (Math.random() > 0.4 ? 1 : -1) * (f.dir || 1);
    }
    // 张力自然衰减(较慢，让收线更可控)
    f.tension = Math.max(0, f.tension - 4 * dt);

    // 断线判定
    const lineMax = equip.line.maxTension;
    if (f.tension >= lineMax) {
      Render.toast('鱼太猛，钓线崩断了！', 'break');
      Render.breakLine();
      this.phase = 'idle';
      this.fight = null;
      return;
    }

    // 松弛判定：鱼还有劲却放任张力过低 -> 会脱钩
    const fishActive = f.stamina > 0;
    if (fishActive && f.tension < 8) {
      f.escape += dt * 4;
      if (f.escape >= 100) {
        Render.toast(f.fish.name + ' 挣脱跑掉了…', 'miss');
        this.phase = 'idle';
        this.fight = null;
        return;
      }
    } else {
      f.escape = Math.max(0, f.escape - dt * 20);
    }

    // 玩家收线 (按住鼠标)
    if (Engine.reeling) {
      const reelSpeed = equip.reel.speed / 100;
      const drag = equip.reel.drag / 100;
      // 鱼还有劲时收线会加剧张力
      f.tension += 1 * (1 - drag * 0.5) * dt;
      f.distance -= reelSpeed * 0.18 * dt;
      // 收线也消耗一点鱼耐力
      if (fishActive) f.stamina -= f.fish.fight * 0.015 * dt;
    }

    // 鱼累了之后张力快速衰减，收线更顺利
    if (!fishActive) f.tension = Math.max(0, f.tension - 25 * dt);

    // 上钩完成
    if (f.distance <= 0) {
      this.phase = 'landed';
      this.landed = this.fight;
      this.fight = null;
      Render.landFish();
    }
  }

  // 收线完成后的结算
  settle() {
    const f = this.landed;
    const value = f.fish.value * f.weight;
    this.landed = null;
    this.phase = 'idle';
    return { fish: f.fish, weight: f.weight, value: Math.round(value) };
  }

  // 随机权重
  _randWeight(fish) {
    // 偏向中间，偶尔出大物
    let r = Math.random();
    if (r < 0.15) return (fish.min + (fish.max - fish.min) * 0.9).toFixed(1); // 大物
    return (fish.min + (fish.max - fish.min) * Math.pow(Math.random(), 1.6)).toFixed(1);
  }

  // 选一条会咬钩的鱼
  _pickFish(equip) {
    const zoneId = Game.state.zone;
    const available = DATA.FISH.filter(f => f.zones.includes(zoneId));
    // 鱼饵偏好加成
    const bait = equip.bait;
    const weighted = [];
    for (const f of available) {
      let w = f.aggress;
      if (bait.family === f.family) w *= bait.bite;
      if (bait.family === '传说' && f.legendary) w *= bait.bite;
      weighted.push({ f, w });
    }
    // 加权随机
    const total = weighted.reduce((s, x) => s + x.w, 0);
    let r = Math.random() * total;
    for (const x of weighted) {
      r -= x.w;
      if (r <= 0) return x.f;
    }
    return weighted[weighted.length - 1].f;
  }

  // 全局静态：收线状态
  static reeling = false;
}

window.Engine = Engine;