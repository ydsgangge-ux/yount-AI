/**
 * SimLife Canvas 渲染器 v7
 * 左边场景 canvas (640x360)：ComfyUI 场景图
 * 右边人物 canvas (256x512)：ComfyUI 角色立绘
 * 支持现代世界 + 异世界（fantasy）两套素材
 */

const W = 640;
const H = 360;
const CHAR_W = 256;
const CHAR_H = 512;

// ── 现代世界 场景背景图映射 ──────────────────────────────
const BG_MAP = {
  'HOME_SLEEPING': 'home_sleeping.png',
  'HOME_MORNING': 'home_morning.png',
  'HOME_EVENING': 'home_evening.png',
  'HOME_WEEKEND_LAZY': 'home_sleeping.png',
  'HOME_WORKING': 'home_working.png',
  'COMMUTE_TO_WORK': 'commute_subway.png',
  'COMMUTE_TO_HOME': 'commute_subway_night.png',
  'OFFICE_WORKING': 'office_working.png',
  'OFFICE_MEETING': 'office_meeting.png',
  'OFFICE_LUNCH': 'office_lunch.png',
  'CAFE': 'cafe.png',
  'PARK': 'park.png',
  'SUPERMARKET': 'supermarket.png',
  'STREET_WANDERING': 'street.png',
  'FRIEND_HANGOUT': 'cafe_warm.png',
  'OVERTIME': 'office_night.png',
  'CAFE_WORKING': 'cafe_working.png',
  'OUTDOOR_WORKING': 'outdoor_working.png',
  'STUDIO_WORKING': 'studio_working.png',
  'AIRPORT': 'airport.png',
  'TOURING': 'touring.png',
  'HOTEL': 'hotel.png',
  'LOCAL_FOOD': 'local_food.png',
  'SCENIC_DRIVE': 'scenic_drive.png',
  'RESTAURANT_LOCAL': 'restaurant.png',
  'TRAIN_STATION': 'train_station.png',
};

// ── 异世界 场景背景图映射（bg_hint → 文件名） ────────────
const FANTASY_BG_MAP = {
  'town_square': 'town_square.png',
  'tavern': 'tavern.png',
  'forest': 'forest.png',
  'castle': 'castle.png',
  'magic_academy': 'magic_academy.png',
  'dungeon': 'dungeon.png',
  'market': 'market.png',
  'plains': 'plains.png',
  'lakeside': 'lakeside.png',
  'mountain_pass': 'mountain_pass.png',
  'shrine': 'shrine.png',
  'night_camp': 'night_camp.png',
};

// ── 角色立绘映射 ──────────────────────────────
const CHAR_MAP = {
  modern: {
    female: {
      idle: 'char_female_idle.png', walk: 'char_female_walk.png',
      sit: 'char_female_sit.png', talk: 'char_female_talk.png', think: 'char_female_think.png',
    },
    male: {
      idle: 'char_male_idle.png', walk: 'char_male_walk.png',
      sit: 'char_male_sit.png', talk: 'char_male_talk.png', think: 'char_male_think.png',
    },
  },
  fantasy: {
    female: {
      idle: 'char_female_idle.png', walk: 'char_female_walk.png',
      sit: 'char_female_sit.png', talk: 'char_female_talk.png', think: 'char_female_think.png',
    },
    male: {
      idle: 'char_male_idle.png', walk: 'char_male_walk.png',
      sit: 'char_male_sit.png', talk: 'char_male_talk.png', think: 'char_male_think.png',
    },
  },
};

// ── 现代世界 场景 → 主角动作 ──────────────────────────────
const SCENE_ACTION = {
  'HOME_SLEEPING': 'sleep', 'HOME_MORNING': 'idle', 'HOME_EVENING': 'sit',
  'HOME_WEEKEND_LAZY': 'sleep', 'HOME_WORKING': 'think',
  'COMMUTE_TO_WORK': 'walk', 'COMMUTE_TO_HOME': 'walk',
  'OFFICE_WORKING': 'think', 'OFFICE_MEETING': 'talk', 'OFFICE_LUNCH': 'sit',
  'CAFE_WORKING': 'think', 'OUTDOOR_WORKING': 'think', 'STUDIO_WORKING': 'think',
  'CAFE': 'sit', 'PARK': 'walk', 'SUPERMARKET': 'walk', 'STREET_WANDERING': 'walk',
  'FRIEND_HANGOUT': 'talk', 'OVERTIME': 'think',
  'AIRPORT': 'walk', 'TOURING': 'walk', 'HOTEL': 'sit',
  'LOCAL_FOOD': 'sit', 'TRAIN_STATION': 'walk', 'SCENIC_DRIVE': 'sit', 'RESTAURANT_LOCAL': 'sit',
};

// ── 异世界 场景关键词 → 动作 ──────────────────────────────
const FANTASY_ACTION_KEYWORDS = [
  [['战斗', '打', '攻', '防', '副本', '地下', '冒险'], 'think'],
  [['走', '旅', '行', '巡', '巡逻', '探索', '移动'], 'walk'],
  [['坐', '休息', '酒馆', '旅馆', '营', '睡'], 'sit'],
  [['说', '谈', '聊', '商', '交易', '市场', '集市'], 'talk'],
  [['想', '思', '学', '修', '研究', '读', '图书馆', '学院'], 'think'],
];

// ── NPC 配置 ──────────────────────────────
const NPC_SCENES = {
  'OFFICE_WORKING': [{ gender: 'male', action: 'think' }],
  'OFFICE_MEETING': [{ gender: 'male', action: 'talk' }],
  'OFFICE_LUNCH': [{ gender: 'female', action: 'sit' }],
  'CAFE': [{ gender: 'female', action: 'sit' }],
  'CAFE_WORKING': [{ gender: 'male', action: 'think' }],
  'FRIEND_HANGOUT': [{ gender: 'male', action: 'talk' }],
  'TOURING': [{ gender: 'male', action: 'walk' }],
  'AIRPORT': [{ gender: 'male', action: 'walk' }],
  'LOCAL_FOOD': [{ gender: 'male', action: 'sit' }],
  'RESTAURANT_LOCAL': [{ gender: 'female', action: 'sit' }],
  'HOME_EVENING': [{ gender: 'male', action: 'sit' }],
  'SUPERMARKET': [{ gender: 'female', action: 'walk' }],
};


class Renderer {
  constructor(canvas, charCanvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.charCanvas = charCanvas;
    this.charCtx = charCanvas.getContext('2d');

    this.scene = null;
    this.mainChar = null;
    this.npcs = [];
    this.bgNpcs = [];
    this.time = 0;
    this.weather = 'cloudy';
    this.particles = [];
    this.fadeAlpha = 0;
    this.fading = false;
    this.fadeDir = 0;
    this.onFadeComplete = null;

    // ── 素材状态 ──
    this.bgImages = {};       // 已加载的背景图
    this.charImages = {};     // 已加载的角色立绘
    this.bgReady = false;
    this.charReady = false;
    this._charGender = null;
    this._isStoryMode = false;    // 当前是否异世界模式
    this._loadedWorld = null;     // 已加载素材的世界类型

    // 先加载现代世界背景
    this._loadBgImages('modern');
  }

  // ── 加载背景图 ──
  async _loadBgImages(worldType) {
    if (this._loadedWorld === worldType && this.bgReady) return;
    this._loadedWorld = worldType;
    this.bgReady = false;
    this.bgImages = {};

    const map = worldType === 'fantasy' ? FANTASY_BG_MAP : BG_MAP;
    const subDir = worldType === 'fantasy' ? 'fantasy' : '';
    const entries = Object.entries(map);
    let loaded = 0;

    for (const [key, filename] of entries) {
      try {
        const img = new Image();
        img.src = subDir
          ? `/static/assets/bg/${subDir}/${filename}`
          : `/static/assets/bg/${filename}`;
        await new Promise((resolve, reject) => {
          img.onload = resolve;
          img.onerror = reject;
        });
        this.bgImages[key] = img;
        loaded++;
      } catch (e) { /* 跳过 */ }
    }
    this.bgReady = loaded > 0;
    console.log(`[SimLife] 背景图加载完成 (${worldType}) ${loaded}/${entries.length}`);
  }

  // ── 加载角色立绘（指定世界+性别） ──
  async _loadCharImages(worldType, gender) {
    const cacheKey = `${worldType}_${gender}`;
    if (this._charGender === cacheKey && this.charReady) return;
    this._charGender = cacheKey;
    this.charReady = false;
    this.charImages = {};

    const poses = CHAR_MAP[worldType]?.[gender];
    if (!poses) return;

    const subDir = worldType === 'fantasy' ? 'fantasy' : '';
    const tasks = [];
    for (const [pose, filename] of Object.entries(poses)) {
      tasks.push(this._loadOneChar(worldType, gender, pose, filename, subDir));
    }
    await Promise.all(tasks);
    this.charReady = Object.keys(this.charImages).length > 0;
    console.log(`[SimLife] 角色立绘加载完成 (${worldType}/${gender}) ${Object.keys(this.charImages).length}/${tasks.length}`);
  }

  async _loadOneChar(worldType, gender, pose, filename, subDir) {
    try {
      const img = new Image();
      img.src = subDir
        ? `/static/assets/char/${subDir}/${filename}`
        : `/static/assets/char/${filename}`;
      await new Promise((resolve, reject) => {
        img.onload = resolve;
        img.onerror = reject;
      });
      this.charImages[`${gender}_${pose}`] = img;
    } catch (e) {
      console.warn(`[SimLife] 角色立绘加载失败: ${filename}`, e.message);
    }
  }

  // ── 基础绘制 ──
  clear(color = '#1a1a2e') {
    this.ctx.fillStyle = color;
    this.ctx.fillRect(0, 0, W, H);
  }

  fillCircle(cx, cy, r, color) {
    this.ctx.fillStyle = color;
    this.ctx.beginPath();
    this.ctx.arc(cx, cy, r, 0, Math.PI * 2);
    this.ctx.fill();
  }

  roundRect(x, y, w, h, r, color) {
    this.ctx.fillStyle = color;
    this.ctx.beginPath();
    this.ctx.roundRect(x, y, w, h, r);
    this.ctx.fill();
  }

  // ── 主渲染入口 ──
  drawScene(scene, mainChar, activeNpcs, bgNpcCount, isStoryMode, bgHint) {
    this.scene = scene;
    this.mainChar = mainChar;
    this._isStoryMode = !!isStoryMode;
    this.time++;

    const mainGender = (mainChar && mainChar.gender === 'male') ? 'male' : 'female';
    const worldType = this._isStoryMode ? 'fantasy' : 'modern';

    // 世界类型变化时重新加载背景
    if (this._loadedWorld !== worldType) {
      this._loadBgImages(worldType);
    }

    // 性别或世界变化时重新加载角色
    const charCacheKey = `${worldType}_${mainGender}`;
    if (this._charGender !== charCacheKey) {
      this._loadCharImages(worldType, mainGender);
    }

    // 确定主角动作
    let mainAction;
    if (this._isStoryMode) {
      mainAction = this._getFantasyAction(scene);
    } else {
      mainAction = SCENE_ACTION[scene] || 'idle';
    }

    this._drawSceneCanvas(scene, bgHint);
    this._drawCharCanvas(mainGender, mainAction, activeNpcs);
  }

  // ── 异世界场景名→动作 ──
  _getFantasyAction(sceneName) {
    if (!sceneName) return 'idle';
    for (const [keywords, action] of FANTASY_ACTION_KEYWORDS) {
      for (const kw of keywords) {
        if (sceneName.includes(kw)) return action;
      }
    }
    return 'idle';
  }

  // ── 场景 canvas ──
  _drawSceneCanvas(scene, bgHint) {
    this.clear('#1a1a2e');

    // 画背景图
    if (this.bgReady) {
      let bgKey;
      if (this._isStoryMode && bgHint) {
        bgKey = bgHint; // 异世界用后端返回的 bg_hint
      } else {
        bgKey = scene;  // 现代世界用场景枚举名
      }
      const bgImg = this.bgImages[bgKey];
      if (bgImg) {
        this.ctx.drawImage(bgImg, 0, 0, W, H);
      } else {
        // 没匹配到背景图，用默认
        this.ctx.fillStyle = '#2a2a3a';
        this.ctx.fillRect(0, 260, W, H - 260);
      }
    }

    // 天气粒子
    this._drawWeather(this.ctx);

    // 淡入淡出
    if (this.fading) {
      this.fadeAlpha += this.fadeDir * 0.04;
      if (this.fadeAlpha >= 1) { this.fadeAlpha = 1; if (this.onFadeComplete) this.onFadeComplete(); }
      if (this.fadeAlpha <= 0) { this.fadeAlpha = 0; this.fading = false; }
      this.ctx.fillStyle = `rgba(0,0,0,${this.fadeAlpha})`;
      this.ctx.fillRect(0, 0, W, H);
    }
  }

  // ── 人物 canvas ──
  _drawCharCanvas(gender, action, activeNpcs) {
    const c = this.charCtx;

    // 纯白背景
    c.fillStyle = '#ffffff';
    c.fillRect(0, 0, CHAR_W, CHAR_H);

    // action 映射
    let pose;
    if (action === 'sleep') pose = 'idle';
    else if (action === 'work' || action === 'stand' || action === 'phone') pose = 'think';
    else pose = action;

    // 画主角
    const key = `${gender}_${pose}`;
    const img = this.charImages[key];
    if (img) {
      const scale = Math.min(CHAR_W / img.width, CHAR_H / img.height) * 0.9;
      const drawW = Math.round(img.width * scale);
      const drawH = Math.round(img.height * scale);
      const drawX = Math.floor((CHAR_W - drawW) / 2);
      const drawY = Math.floor(CHAR_H - drawH);
      c.drawImage(img, drawX, drawY, drawW, drawH);
    }

    // NPC（仅现代世界有固定配置）
    if (!this._isStoryMode) {
      const npcList = NPC_SCENES[this.scene] || [];
      if (npcList.length > 0) {
        const npc = npcList[0];
        const npcKey = `${npc.gender}_${npc.action}`;
        const npcImg = this.charImages[npcKey];
        if (npcImg) {
          const npcScale = 0.5;
          const npcW = Math.round(npcImg.width * npcScale);
          const npcH = Math.round(npcImg.height * npcScale);
          c.drawImage(npcImg, CHAR_W - npcW - 10, CHAR_H - npcH, npcW, npcH);
        }
      }
    }

    // 底部渐变遮罩
    const grad = c.createLinearGradient(0, CHAR_H - 40, 0, CHAR_H);
    grad.addColorStop(0, 'rgba(255,255,255,0)');
    grad.addColorStop(1, 'rgba(255,255,255,0.8)');
    c.fillStyle = grad;
    c.fillRect(0, CHAR_H - 40, CHAR_W, 40);
  }

  startFade(callback) {
    this.fading = true;
    this.fadeDir = 1;
    this.fadeAlpha = 0;
    this.onFadeComplete = () => { if (callback) callback(); this.fadeDir = -1; };
  }

  setWeather(w) { this.weather = w; this.particles = []; }

  _drawWeather(ctx) {
    if (this.weather === 'rainy' || this.weather === 'heavy_rain') {
      const target = this.weather === 'heavy_rain' ? 120 : 60;
      while (this.particles.length < target) {
        this.particles.push({ x: Math.random() * W, y: Math.random() * H, speed: 4 + Math.random() * 6 });
      }
      ctx.strokeStyle = 'rgba(180,200,255,0.4)'; ctx.lineWidth = 1;
      for (const p of this.particles) {
        ctx.beginPath(); ctx.moveTo(p.x, p.y); ctx.lineTo(p.x - 1, p.y + p.speed * 2); ctx.stroke();
        p.y += p.speed; p.x -= 0.5;
        if (p.y > H) { p.y = -10; p.x = Math.random() * W; }
      }
    } else if (this.weather === 'snow') {
      while (this.particles.length < 50) {
        this.particles.push({ x: Math.random() * W, y: Math.random() * H, r: 1.5 + Math.random() * 2, speed: 0.5 + Math.random() * 1.5, drift: Math.random() * 2 - 1 });
      }
      ctx.fillStyle = 'rgba(255,255,255,0.7)';
      for (const p of this.particles) {
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2); ctx.fill();
        p.y += p.speed; p.x += Math.sin(this.time * 0.02 + p.drift) * 0.5;
        if (p.y > H) { p.y = -5; p.x = Math.random() * W; }
      }
    } else {
      if (this.particles.length > 0) this.particles = [];
    }
  }
}
