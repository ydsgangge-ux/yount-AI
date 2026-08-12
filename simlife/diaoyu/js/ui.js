// ===== UI 系统 =====
// 渲染装备背包、商店、图鉴、水域等面板。

const UI = (() => {

  // 通用物品卡片风格
  const itemCard = (title, stats, price, owned, buyable, onBuy) => {
    const div = document.createElement('div');
    div.className = 'item-card' + (owned ? ' owned' : '');
    div.innerHTML = `
      <div class="ic-name">${title}</div>
      <div class="ic-stats">${stats.map(s => `<span>${s}</span>`).join('')}</div>
      ${price != null ? `<div class="ic-price">💰 ${price}</div>` : ''}
      ${buyable ? `<button class="buy-btn">${owned ? '已拥有' : '购买'}</button>` : ''}
    `;
    if (buyable && !owned && onBuy) {
      div.querySelector('.buy-btn').addEventListener('click', onBuy);
    }
    return div;
  };

  // ---------- 装备背包 ----------
  function renderBag() {
    const list = document.getElementById('bag-list');
    list.innerHTML = '';
    const inv = Game.state.inventory;
    if (inv.length === 0) {
      list.innerHTML = '<div class="empty">背包空空如也，去商店买点装备吧。</div>';
      return;
    }
    for (const item of inv) {
      const def = findItem(item.type, item.id);
      if (!def) continue;
      const owned = Game.state.equipped[item.type].id === item.id;
      const div = document.createElement('div');
      div.className = 'item-card' + (owned ? ' equipped' : '');
      div.innerHTML = `
        <div class="ic-name">${def.name}</div>
        <div class="ic-stats">${equipStats(item.type, def).map(s => `<span>${s}</span>`).join('')}</div>
        <div class="ic-desc">${def.desc}</div>
        <button class="buy-btn">${owned ? '已装备' : '装备'}</button>
      `;
      if (!owned) {
        div.querySelector('.buy-btn').addEventListener('click', () => {
          Game.state.equipped[item.type] = { id: def.id };
          Game.save();
          renderBag();
          renderEquipBar();
          toast('已装备 ' + def.name + '！');
        });
      }
      list.appendChild(div);
    }
  }

  // ---------- 商店 ----------
  function renderShop(type) {
    const list = document.getElementById('shop-list');
    list.innerHTML = '';
    const defs = DATA[type.toUpperCase() + 'S'];
    for (const def of defs) {
      const owned = Game.state.inventory.some(x => x.type === type && x.id === def.id);
      const equipped = Game.state.equipped[type].id === def.id;
      const canBuy = Game.state.gold >= def.price;
      const div = document.createElement('div');
      div.className = 'item-card' + (owned ? ' owned' : '') + (equipped ? ' equipped' : '');
      div.innerHTML = `
        <div class="ic-name">${def.name}</div>
        <div class="ic-stats">${equipStats(type, def).map(s => `<span>${s}</span>`).join('')}</div>
        <div class="ic-desc">${def.desc}</div>
        <div class="ic-price">💰 ${def.price}</div>
        <button class="buy-btn" ${equipped ? 'disabled' : ''}>${equipped ? '已装备' : owned ? '已拥有' : canBuy ? '购买' : '金币不足'}</button>
      `;
      if (!owned && canBuy) {
        div.querySelector('.buy-btn').addEventListener('click', () => {
          Game.state.gold -= def.price;
          Game.state.inventory.push({ type, id: def.id });
          Game.save();
          renderShop(type);
          toast('购买了 ' + def.name + '！');
        });
      } else if (owned && !equipped) {
        div.querySelector('.buy-btn').addEventListener('click', () => {
          Game.state.equipped[type] = { id: def.id };
          Game.save();
          renderShop(type);
          renderEquipBar();
          toast('已装备 ' + def.name + '！');
        });
      }
      list.appendChild(div);
    }
  }

  // 装备属性文本
  function equipStats(type, def) {
    switch (type) {
      case 'rod': return [`🎯 抛投 ${def.cast}`, `💪 控制 ${def.fight}`];
      case 'reel': return [`⚡ 收线 ${def.speed}`, `🛡 泄力 ${def.drag}`];
      case 'line': return [`🧵 强度 ${def.maxTension}`];
      case 'bait': return [`🍬 偏好 ${def.family}`, `🐟 咬钩 ×${def.bite}`];
    }
  }

  // ---------- 图鉴 ----------
  function renderCollection() {
    const list = document.getElementById('collection-list');
    list.innerHTML = '';
    const caught = Game.state.caught; // {id: {weight, count}}
    const count = Object.keys(caught).length;
    const total = DATA.FISH.length;
    document.getElementById('collection-progress').textContent = `(${count}/${total})`;
    for (const f of DATA.FISH) {
      const c = caught[f.id];
      const div = document.createElement('div');
      div.className = 'collection-item' + (c ? ' caught' : '');
      div.innerHTML = `
        <div class="ci-icon" style="background:${f.color}">${c ? '🐟' : '❓'}</div>
        <div class="ci-info">
          <b>${c ? f.name : '？？？'}</b>
          ${c ? `<span>最佳 ${c.weight}kg · ${c.count}条</span>` : `<span>未捕获</span>`}
          <div class="ci-desc">${c ? f.desc : '继续钓鱼来解锁图鉴吧。'}</div>
        </div>
      `;
      list.appendChild(div);
    }
  }

  // ---------- 水域地图 ----------
  function renderMap() {
    const list = document.getElementById('map-list');
    list.innerHTML = '';
    for (const [id, z] of Object.entries(DATA.ZONES)) {
      const unlocked = Game.state.gold >= z.need || Game.state.bestEarn >= z.need;
      const current = Game.state.zone === id;
      const div = document.createElement('div');
      div.className = 'map-card' + (unlocked ? ' unlocked' : ' locked') + (current ? ' current' : '');
      div.innerHTML = `
        <div class="mc-name">${z.name}</div>
        <div class="mc-diff">难度：${z.difficulty}</div>
        <div class="mc-desc">${z.desc}</div>
        ${!unlocked ? `<div class="mc-need">🔒 需累计收益 ${z.need} 金币</div>` : ''}
        ${current ? '<div class="mc-here">📍 当前所在</div>' : ''}
      `;
      if (unlocked && !current) {
        div.style.cursor = 'pointer';
        div.addEventListener('click', () => {
          Game.state.zone = id;
          Game.save();
          renderMap();
          renderTopbar();
          toast('前往 ' + z.name + '！');
        });
      }
      list.appendChild(div);
    }
  }

  // ---------- 顶部状态栏 ----------
  function renderTopbar() {
    document.getElementById('gold').textContent = Game.state.gold;
    document.getElementById('location-name').textContent = DATA.ZONES[Game.state.zone].name;
    document.getElementById('fish-count').textContent = Object.keys(Game.state.caught).length;
  }

  // ---------- 已装备栏 ----------
  function renderEquipBar() {
    const eq = Game.state.equipped;
    const rod = DATA.RODS.find(x => x.id === eq.rod.id);
    const reel = DATA.REELS.find(x => x.id === eq.reel.id);
    const line = DATA.LINES.find(x => x.id === eq.line.id);
    const bait = DATA.BAITS.find(x => x.id === eq.bait.id);
    document.getElementById('eq-rod').textContent = rod.name;
    document.getElementById('eq-reel').textContent = reel.name;
    document.getElementById('eq-line').textContent = line.name;
    document.getElementById('eq-bait').textContent = bait.name;
  }

  // 简化 toast
  function toast(msg) {
    const el = document.getElementById('bite-toast');
    el.textContent = msg;
    el.className = 'toast show';
    clearTimeout(el._t);
    el._t = setTimeout(() => el.className = 'toast hidden', 1200);
  }

  // 根据类型和id找定义
  function findItem(type, id) {
    const arr = DATA[type.toUpperCase() + 'S'];
    return arr && arr.find(x => x.id === id);
  }

  return { renderBag, renderShop, renderCollection, renderMap, renderTopbar, renderEquipBar, findItem };
})();