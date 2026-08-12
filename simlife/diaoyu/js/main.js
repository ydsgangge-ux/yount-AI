// ===== 主控制器 =====
// 游戏状态、主循环、输入处理、面板切换与结算。

const Game = (() => {
  const state = {
    gold: 0,
    bestEarn: 0,          // 累计最高收益(用于解锁水域)
    zone: 'pond',
    equipped: {
      rod: { id: 'rod1' },
      reel: { id: 'reel1' },
      line: { id: 'line1' },
      bait: { id: 'bait1' },
    },
    inventory: [],        // [{type,id}]
    caught: {},           // {fishId: {weight, count}}
  };

  const SAVE_KEY = 'fishing_tale_save';
  let engine = new Engine();
  let raf = 0;
  let last = 0;

  function save() {
    try { localStorage.setItem(SAVE_KEY, JSON.stringify(state)); } catch (e) {}
  }

  function load() {
    try {
      const raw = localStorage.getItem(SAVE_KEY);
      if (raw) Object.assign(state, JSON.parse(raw));
    } catch (e) {}
  }

  // 当前装备(带定义)
  function equip() {
    const e = state.equipped;
    return {
      rod: DATA.RODS.find(x => x.id === e.rod.id),
      reel: DATA.REELS.find(x => x.id === e.reel.id),
      line: DATA.LINES.find(x => x.id === e.line.id),
      bait: DATA.BAITS.find(x => x.id === e.bait.id),
    };
  }

  // ===== 主循环 =====
  function loop(ts) {
    const dt = Math.min(0.05, (ts - last) / 1000 || 0.016);
    last = ts;

    // 引擎状态推进
    switch (engine.phase) {
      case 'aim': engine.charge(dt); break;
      case 'flying': engine.updateFlight(dt); break;
      case 'waiting': engine.updateWaiting(dt, equip()); break;
      case 'bite': engine.updateBite(dt); break;
      case 'fighting': engine.updateFight(dt, equip()); break;
    }
    // 遛鱼结束等待结算
    if (engine.phase === 'landed') {
      settle();
    }

    // 渲染
    Render.draw(dt);

    // 更新 UI 提示与张力条
    updateHUD();

    raf = requestAnimationFrame(loop);
  }

  function updateHUD() {
    const hint = document.getElementById('hint-text');
    const powerWrap = document.getElementById('powerbar-wrap');
    const tensionWrap = document.getElementById('tension-wrap');
    const powerbar = document.getElementById('powerbar');
    const tfill = document.getElementById('tension-fill');

    switch (engine.phase) {
      case 'idle':
        hint.textContent = '按住鼠标蓄力，松开发出';
        powerWrap.style.visibility = 'visible';
        tensionWrap.classList.add('hidden');
        powerbar.style.width = '0%';
        break;
      case 'aim':
        hint.textContent = '松开抛竿！';
        powerWrap.style.visibility = 'visible';
        tensionWrap.classList.add('hidden');
        powerbar.style.width = (engine.power * 100) + '%';
        break;
      case 'waiting':
        hint.textContent = '等待鱼儿咬钩…';
        powerWrap.style.visibility = 'hidden';
        tensionWrap.classList.add('hidden');
        break;
      case 'bite':
        hint.textContent = '🖱️ 快点击提竿！';
        powerWrap.style.visibility = 'hidden';
        tensionWrap.classList.add('hidden');
        break;
      case 'fighting':
        hint.textContent = '按住鼠标收线，注意张力别爆！';
        powerWrap.style.visibility = 'hidden';
        tensionWrap.classList.remove('hidden');
        const f = engine.fight;
        const lineMax = equip().line.maxTension;
        const pct = Math.min(100, (f.tension / lineMax) * 100);
        tfill.style.width = pct + '%';
        tfill.style.background = pct > 70 ? '#e74444' : pct > 40 ? '#e0a030' : '#3aa05a';
        break;
    }
  }

  // 结算一只鱼
  function settle() {
    const res = engine.settle();
    // 记录收益
    state.gold += res.value;
    if (state.gold > state.bestEarn) state.bestEarn = state.gold;
    // 记录图鉴
    const prev = state.caught[res.fish.id];
    if (!prev) state.caught[res.fish.id] = { weight: parseFloat(res.weight), count: 1 };
    else {
      prev.count++;
      if (res.weight > prev.weight) prev.weight = parseFloat(res.weight);
    }
    save();
    UI.renderTopbar();
    UI.renderCollection();
    // 展示收益
    const valEl = document.getElementById('result-toast');
    valEl.textContent = `💰 卖出 ${res.fish.name} ${res.weight}kg，获得 ${res.value} 金币！`;
    valEl.className = 'toast show landed';
    clearTimeout(valEl._t);
    valEl._t = setTimeout(() => valEl.className = 'toast hidden', 2000);
  }

  // ===== 输入处理 =====
  function bindInput() {
    const canvas = document.getElementById('game');

    canvas.addEventListener('mousedown', (e) => {
      e.preventDefault();
      if (engine.phase === 'idle' || engine.phase === 'waiting') {
        engine.startAim();
      } else if (engine.phase === 'bite') {
        engine.hook(equip());
      } else if (engine.phase === 'fighting') {
        Engine.reeling = true;
      }
    });

    canvas.addEventListener('mouseup', (e) => {
      e.preventDefault();
      if (engine.phase === 'aim') {
        engine.cast(equip());
      }
      Engine.reeling = false;
    });

    // 防止拖动选中
    canvas.addEventListener('dragstart', e => e.preventDefault());

    // 键盘 R 收线
    window.addEventListener('keydown', e => {
      if (e.key === 'r' || e.key === 'R') Engine.reeling = true;
    });
    window.addEventListener('keyup', e => {
      if (e.key === 'r' || e.key === 'R') Engine.reeling = false;
    });
  }

  // ===== 面板切换 =====
  function bindTabs() {
    document.querySelectorAll('.tab').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const panel = btn.dataset.panel;
        document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
        document.getElementById('panel-' + panel).classList.add('active');
        // 触发对应渲染
        if (panel === 'bag') UI.renderBag();
        if (panel === 'shop') UI.renderShop(lastShopType || 'rod');
        if (panel === 'collection') UI.renderCollection();
        if (panel === 'map') UI.renderMap();
      });
    });

    // 商店分类
    document.querySelectorAll('.stab').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.stab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        lastShopType = btn.dataset.type;
        UI.renderShop(lastShopType);
      });
    });
  }

  let lastShopType = 'rod';

  // ===== 初始化 =====
  function init() {
    load();
    Render.init(document.getElementById('game'));
    bindInput();
    bindTabs();
    UI.renderTopbar();
    UI.renderEquipBar();
    UI.renderCollection();
    UI.renderMap();
    UI.renderShop('rod');
    last = performance.now();
    raf = requestAnimationFrame(loop);
  }

  return { init, state, engine, equip, save };
})();

document.addEventListener('DOMContentLoaded', Game.init);