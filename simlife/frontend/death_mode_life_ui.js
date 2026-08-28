/*
 * 生活技能 UI（烹饪 / 锻造 / 钓鱼）
 * 三个网页小游戏，独立于战斗系统。
 * - 烹饪：顺序小游戏（步骤拖拽/点选排序，LLM/固定菜谱）
 * - 锻造：真实工艺步骤小游戏（加热→锻打→淬火→成型，时机判定）
 * - 钓鱼：抛竿收杆时机小游戏（参考 Switch / 魔兽世界鱼种）
 */
const LifeSkillsUI = {
  _data: null,
  _curTab: 'shop',
  _overlay: null,

  // 烹饪小游戏状态
  _cook: { recipe: null, steps: [], picked: [], active: false, timer: null },
  // 自由烹饪 · 中餐工序状态（切型/腌料/腌制时长/手法/火候时长）
  _cookFree: { cut: {}, marinade: [], marinade_t: '不腌', method: '', duration: '' },
  // 锻造小游戏状态
  _forge: { bp: null, steps: [], idx: 0, active: false, timer: null, window: 0, results: [] },
  // 钓鱼小游戏状态（实景 Canvas + 搏斗张力）
  _fish: {
    active: false, phase: 'idle',       // idle/casting/waiting/fighting
    pulling: false, releasing: false,
    time: 0, cv: null, ctx: null,
    rod: { x: 60, angle: -0.6, sway: 0 },
    bobber: { x: 0, y: 0, vx: 0, vy: 0, inWater: false, bob: 0, active: false },
    hookedFish: null,
    tension: 50, fishStam: 100, tensionDir: 0, tensionTarget: 50, maxTensionSeen: 50,
    biteTimer: 0, particles: [], ripples: [],
    timer: null, raf: null,
  },
  _zone: 'pond',
  _freeSel: { cook: {}, forge: {}, enchant: {} },   // 自由组合/附魔 材料选择
  _enchantItem: null,                              // 当前正在附魔的装备名

  // ── 打开主面板 ────────────────────────────────────
  async open() {
    document.getElementById('dm-life-btn')?.setAttribute('disabled', 'true');
    const resp = await fetch('/api/death-mode/life-skills');
    const data = await resp.json();
    document.getElementById('dm-life-btn')?.removeAttribute('disabled');
    if (data.error) { alert('生活技能不可用：' + data.error); return; }
    this._data = data;
    this._zone = data.fish_zone || 'pond';
    this._region = data.fish_region || null;
    this._renderOverlay();
    this._switchTab('shop');
  },

  close() {
    this._stopTimers();
    if (this._overlay) { this._overlay.remove(); this._overlay = null; }
  },

  _stopTimers() {
    if (this._cook.timer) clearInterval(this._cook.timer);
    if (this._forge.timer) clearInterval(this._forge.timer);
    if (this._fish.timer) clearInterval(this._fish.timer);
    if (this._fish.raf) cancelAnimationFrame(this._fish.raf);
    this._cook.timer = this._forge.timer = this._fish.timer = this._fish.raf = null;
  },

  _renderOverlay() {
    this.close();
    const ov = document.createElement('div');
    ov.id = 'life-skills-overlay';
    ov.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;z-index:99999;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,0.7);';
    ov.innerHTML = `
      <div style="width:min(960px,94vw);height:min(640px,92vh);background:linear-gradient(180deg,#0d1117,#161b22);border:1px solid #30363d;border-radius:12px;display:flex;flex-direction:column;overflow:hidden;box-shadow:0 0 60px rgba(0,0,0,0.8);">
        <div style="padding:10px 18px;background:#0d1117;border-bottom:1px solid #30363d;display:flex;align-items:center;justify-content:space-between;">
          <div style="display:flex;align-items:center;gap:10px;">
            <h3 style="margin:0;color:#58a6ff;font-size:15px;">🎒 生活技能</h3>
            <span id="ls-gold" style="font-size:12px;color:#d29922;"></span>
          </div>
          <button onclick="LifeSkillsUI.close()" style="padding:3px 12px;background:#21262d;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;cursor:pointer;font-size:12px;">✕ 关闭</button>
        </div>
        <div id="ls-body" style="flex:1;display:flex;min-height:0;overflow:hidden;">
          <div id="ls-side" style="width:170px;padding:10px;background:#0d1117;border-right:1px solid #30363d;overflow-y:auto;flex-shrink:0;"></div>
          <div id="ls-main" style="flex:1;overflow-y:auto;padding:14px;min-width:0;"></div>
        </div>
      </div>`;
    document.body.appendChild(ov);
    this._overlay = ov;
    this._renderSide();
  },

  _renderSide() {
    const d = this._data;
    const side = document.getElementById('ls-side');
    const skills = d.skills || {};
    const L = (k) => skills[k] || { level: 1, xp: 0, name: k, icon: '❔' };
    const stat = (k) => { const s = L(k); const need = s.level * 50; return { lv: s.level, xp: `${s.xp}/${need}`, pct: Math.min(100, s.xp / need * 100) }; };
    const tabs = [
      { id: 'shop', icon: '🏪', label: '商店' },
      { id: 'cook', icon: skills.cooking.icon, label: '烹饪', ...stat('cooking') },
      { id: 'forge', icon: skills.forging.icon, label: '锻造', ...stat('forging') },
      { id: 'fish', icon: skills.fishing.icon, label: '钓鱼', ...stat('fishing') },
      { id: 'dex', icon: '📖', label: '鱼类图鉴' },
      { id: 'bag', icon: '🎁', label: '背包' },
    ];
    side.innerHTML = tabs.map(t => `
      <div onclick="LifeSkillsUI._switchTab('${t.id}')" id="ls-tab-${t.id}" style="padding:9px 10px;margin-bottom:6px;border-radius:8px;border:1px solid #30363d;background:#161b22;cursor:pointer;">
        <div style="font-size:12px;color:#c9d1d9;">${t.icon} ${t.label}</div>
        ${t.lv ? `<div style="font-size:9px;color:#8b949e;margin-top:2px;">Lv.${t.lv} · 经验 ${t.xp}</div>
        <div style="height:4px;background:#0d1117;border-radius:2px;margin-top:3px;overflow:hidden;"><div style="height:100%;width:${t.pct}%;background:#a371f7;"></div></div>` : ''}
      </div>`).join('');
    document.getElementById('ls-gold').textContent = `💰 ${d.gold ?? 0} 金币`;
  },

  _switchTab(tab) {
    this._curTab = tab;
    this._stopTimers();
    document.querySelectorAll('#ls-side [id^=ls-tab-]').forEach(el => {
      const active = el.id === `ls-tab-${tab}`;
      el.style.borderColor = active ? '#58a6ff' : '#30363d';
      el.style.background = active ? '#1a2a3a' : '#161b22';
    });
    const main = document.getElementById('ls-main');
    if (tab === 'shop') this._renderShop(main);
    else if (tab === 'cook') this._renderCook(main);
    else if (tab === 'forge') this._renderForge(main);
    else if (tab === 'fish') this._renderFish(main);
    else if (tab === 'dex') this._renderDex(main);
    else this._renderBag(main);
  },

  async _reload(keepTab) {
    const resp = await fetch('/api/death-mode/life-skills');
    const data = await resp.json();
    if (!data.error) {
      this._data = data;
      this._zone = data.fish_zone || this._zone;
      this._region = data.fish_region || this._region;
      this._renderSide();
    }
    this._switchTab(keepTab || this._curTab);
  },

  // ── 商店 ──────────────────────────────────────────
  _renderShop(main) {
    const shop = this._data.shop || [];
    const inv = this._data.inventory || [];
    const invMap = {};
    inv.forEach(it => invMap[it.id] = it.qty || 0);
    main.innerHTML = `
      <h4 style="margin:0 0 10px;color:#d29922;font-size:14px;">🏪 原材料商店</h4>
      <div style="font-size:11px;color:#8b949e;margin-bottom:10px;">购买原材料用于烹饪、锻造与垂钓。高级材料随生活技能等级解锁。</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;">
        ${shop.map(m => `
          <div style="padding:10px;background:#161b22;border:1px solid #30363d;border-radius:8px;">
            <div style="font-size:13px;color:#c9d1d9;">${m.icon} ${m.name}</div>
            <div style="font-size:10px;color:#8b949e;margin:4px 0;">${this._typeName(m.type)} · 持有${invMap[m.id]||0}</div>
            ${m.effect?`<div style="font-size:9px;color:#f0883e;margin:2px 0;">✨${m.effect.name}: ${m.effect.desc||''}</div>`:''}
            <div style="display:flex;align-items:center;gap:6px;">
              <button onclick="LifeSkillsUI._buy('${m.id}',1)" style="flex:1;padding:4px;background:#1a3a1a;border:1px solid #3fb950;border-radius:5px;color:#3fb950;cursor:pointer;font-size:11px;">💰${m.price}</button>
              <button onclick="LifeSkillsUI._buy('${m.id}',5)" style="flex:1;padding:4px;background:#1a2a1a;border:1px solid #d29922;border-radius:5px;color:#d29922;cursor:pointer;font-size:11px;">×5</button>
            </div>
          </div>`).join('')}
      </div>`;
  },

  _typeName(t) {
    return { ingredient: '食材', ore: '矿材', misc: '材料', bait: '鱼饵', enchant: '附魔材料', rare: '稀有材料' }[t] || t;
  },

  async _buy(id, qty) {
    const resp = await fetch('/api/death-mode/life-skills/buy', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mat_id: id, qty }),
    });
    const r = await resp.json();
    if (r.error) { alert(r.message || '购买失败'); return; }
    this._data.gold = r.gold;
    this._data.inventory = r.inventory;
    this._renderSide();
    this._reload('shop');
  },

  // ── 背包 ──────────────────────────────────────────
  _renderBag(main) {
    const d = this._data;
    const inv = d.inventory || [];
    const foods = d.foods || [];
    const fish = d.fish_caught || [];
    const eq = d.equipment || [];
    const smats = d.shared_materials || [];
    const sitems = d.shared_items || [];
    const typeOrder = { ingredient: 0, ore: 1, misc: 2, bait: 3 };
    const sorted = [...inv].sort((a, b) => (typeOrder[a.type] ?? 9) - (typeOrder[b.type] ?? 9));

    const card = (title, color, items, itemHtml) => `
      <div style="margin-bottom:12px;">
        <div style="font-size:13px;color:${color};font-weight:600;margin-bottom:6px;">${title} (${items.length})</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:6px;">
          ${items.length ? items.map(itemHtml).join('') : `<div style="font-size:11px;color:#484f58;">（空）</div>`}
        </div>
      </div>`;

    main.innerHTML = `
      <h4 style="margin:0 0 10px;color:#c9d1d9;font-size:14px;">🎒 背包与产出</h4>
      ${card('📦 共享背包', '#f0883e', sitems, it => `
        <div style="padding:8px;background:${it.is_material?'#2d2d0d':'#1d1525'};border:1px solid ${this._rarityColor(it.rarity)};border-radius:7px;">
          <div style="font-size:12px;color:${this._rarityColor(it.rarity)};">${it.name} <span style="color:#8b949e;">×${it.qty}</span></div>
          <div style="font-size:9px;color:#8b949e;margin:2px 0;">${it.is_material?'生活材料':'可拆解'}</div>
          ${it.is_material
            ? `<button onclick="LifeSkillsUI._transferMaterial('${it.name}')" style="width:100%;padding:3px;background:#3d2a1a;border:1px solid #f0883e;border-radius:4px;color:#f0883e;cursor:pointer;font-size:10px;">⬇ 存入材料包</button>`
            : `<div style="display:flex;gap:4px;">
                <button onclick="LifeSkillsUI._dismantle('${it.name}')" style="flex:1;padding:3px;background:#2d1a3a;border:1px solid #a371f7;border-radius:4px;color:#a371f7;cursor:pointer;font-size:10px;">🔧 拆解</button>
                <button onclick="LifeSkillsUI._openEnchant('${it.name}')" style="flex:1;padding:3px;background:#2d2d0d;border:1px solid #f0883e;border-radius:4px;color:#f0883e;cursor:pointer;font-size:10px;">✨附魔</button>
              </div>`}
        </div>`)}
      ${card('🧱 原材料', '#58a6ff', sorted, it => `
        <div style="padding:8px;background:#161b22;border:1px solid #30363d;border-radius:7px;">
          <div style="font-size:12px;color:#c9d1d9;">${it.icon} ${it.name} <span style="color:#8b949e;">×${it.qty}</span></div>
          <div style="font-size:9px;color:#484f58;">${this._typeName(it.type)}${it.effect?` · <span style="color:#f0883e;">✨${it.effect.name}: ${it.effect.desc||''}</span>`:''}</div>
        </div>`)}
      ${card('🍲 食物', '#3fb950', foods, it => `
        <div style="padding:8px;background:#161b22;border:1px solid #30363d;border-radius:7px;">
          <div style="font-size:12px;color:#c9d1d9;">${it.icon} ${it.name} <span style="color:#8b949e;">×${it.qty}</span></div>
          <div style="font-size:9px;color:#8b949e;margin:2px 0;">${this._buffDesc(it.buff)}</div>
          <div style="display:flex;gap:4px;">
            <button onclick="LifeSkillsUI._eat('${it.name}','ai')" style="flex:1;padding:3px;background:#1a3a1a;border:1px solid #3fb950;border-radius:4px;color:#3fb950;cursor:pointer;font-size:10px;">AI 食用</button>
            <button onclick="LifeSkillsUI._eat('${it.name}','user')" style="flex:1;padding:3px;background:#1a2a3a;border:1px solid #58a6ff;border-radius:4px;color:#58a6ff;cursor:pointer;font-size:10px;">玩家食用</button>
            <button onclick="LifeSkillsUI._eat('${it.name}','both')" style="flex:1;padding:3px;background:#3d2a1a;border:1px solid #f0883e;border-radius:4px;color:#f0883e;cursor:pointer;font-size:10px;">一起食用</button>
          </div>
        </div>`)}
      ${card('🐟 鱼获', '#58a6ff', fish, it => `
        <div style="padding:8px;background:#161b22;border:1px solid #30363d;border-radius:7px;">
          <div style="font-size:12px;color:#c9d1d9;">${it.icon} ${it.name} <span style="color:#8b949e;">×${it.qty}</span></div>
          <div style="font-size:9px;color:#8b949e;margin:2px 0;">${this._rarityName(it.rarity)} · 能量${it.energy} · 价${it.price}</div>
          <div style="display:flex;gap:4px;">
            <button onclick="LifeSkillsUI._eat('${it.name}','ai')" style="flex:1;padding:3px;background:#1a3a1a;border:1px solid #3fb950;border-radius:4px;color:#3fb950;cursor:pointer;font-size:10px;">AI吃</button>
            <button onclick="LifeSkillsUI._eat('${it.name}','user')" style="flex:1;padding:3px;background:#1a2a3a;border:1px solid #58a6ff;border-radius:4px;color:#58a6ff;cursor:pointer;font-size:10px;">玩家吃</button>
            <button onclick="LifeSkillsUI._eat('${it.name}','both')" style="flex:1;padding:3px;background:#3d2a1a;border:1px solid #f0883e;border-radius:4px;color:#f0883e;cursor:pointer;font-size:10px;">一起吃</button>
            <button onclick="LifeSkillsUI._sellFish('${it.name}')" style="flex:1;padding:3px;background:#3d2a1a;border:1px solid #f0883e;border-radius:4px;color:#f0883e;cursor:pointer;font-size:10px;">售</button>
          </div>
        </div>`)}
      ${card('⚔️ 锻造装备', '#a371f7', eq, it => `
        <div style="padding:8px;background:#161b22;border:1px solid #30363d;border-radius:7px;">
          <div style="font-size:12px;color:#c9d1d9;">${it.icon} ${it.name} <span style="color:#8b949e;">×${it.qty}</span>${it.enchant?` <span style="color:#f0883e;font-size:10px;">✨${it.enchant.name}+${it.enchant.stat_value}</span>`:''}</div>
          <div style="font-size:9px;color:#8b949e;margin:2px 0;">${it.rarity_name||'稀有'} · 加成+${it.bonus}${it.desc?` · ${it.desc}`:''}</div>
          <div style="display:flex;gap:4px;">
            <button onclick="LifeSkillsUI._equipItem('${it.name}')" style="flex:1;padding:3px;background:#1a2a3a;border:1px solid #58a6ff;border-radius:4px;color:#58a6ff;cursor:pointer;font-size:10px;">放入共享背包</button>
            ${it.enchant?'':`<button onclick="LifeSkillsUI._openEnchant('${it.name}')" style="flex:1;padding:3px;background:#2d2d0d;border:1px solid #f0883e;border-radius:4px;color:#f0883e;cursor:pointer;font-size:10px;">✨附魔</button>`}
          </div>
        </div>`)}
      <div id="enchant-panel" style="margin-bottom:12px;"></div>
      ${d.buffs && d.buffs.length ? card('✨ 生效增益', '#d29922', d.buffs, it => `
        <div style="padding:8px;background:#2d2d0d;border:1px solid #d29922;border-radius:7px;font-size:11px;color:#d29922;">
          ${it.source}：${it.target==='user'?'玩家':'AI'} ${it.type==='attack'?'攻击':'防御'}+${it.value}（剩${it.turns}回合）
        </div>`) : ''}
    `;
  },

  async _dismantle(name) {
    if (!confirm(`要拆解「${name}」吗？拆解后该物品从共享背包消失，变为生活材料，可再用于锻造/附魔。`)) return;
    try {
      const resp = await fetch('/api/death-mode/life-skills/dismantle', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      const r = await resp.json();
      if (r.error) { alert(r.message || '拆解失败'); return; }
      alert(r.message);
      await this._reload('bag');
      this._switchTab('bag');
    } catch (e) { alert('拆解失败：' + e.message); }
  },

  async _transferMaterial(name) {
    try {
      const resp = await fetch('/api/death-mode/life-skills/transfer-material', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name }),
      });
      const r = await resp.json();
      if (r.error) { alert(r.message || '存入失败'); return; }
      alert(r.message);
      await this._reload('bag');
      this._switchTab('bag');
    } catch (e) { alert('存入失败：' + e.message); }
  },

  _buffDesc(b) {
    if (!b) return '';
    const name = { hp: '回复HP', mp: '回复MP', attack: '攻击加成', defense: '防御加成' }[b.type] || b.type;
    return `${name} +${b.value}${b.turns ? `（${b.turns}回合）` : ''}`;
  },

  _rarityName(r) {
    return { common: '普通', rare: '稀有', epic: '史诗', legendary: '传说' }[r] || r;
  },

  // ── 鱼类图鉴 ──────────────────────────────────────
  _renderDex(main) {
    const d = this._data;
    const dex = d.fish_dex || {};
    const all = d.fish_table || [];
    const zones = d.fish_zones || [];
    const lit = Object.keys(dex).length;
    main.innerHTML = `
      <h4 style="margin:0 0 10px;color:#58a6ff;font-size:14px;">📖 鱼类图鉴</h4>
      <div style="font-size:11px;color:#8b949e;margin-bottom:8px;">钓到新鱼种即自动点亮。尚未钓到的鱼始终神秘，等你亲手上钩。</div>
      <div style="font-size:12px;margin-bottom:12px;">已点亮 <b style="color:#f0883e;">${lit}</b> <span style="color:#8b949e;">/ ${all.length} 种</span></div>
      ${zones.map(z => {
        const fishes = all.filter(f => f.zones.includes(z.id));
        return `
        <div style="margin-bottom:14px;">
          <div style="font-size:12px;color:#58a6ff;margin-bottom:6px;">${z.name} <span style="color:#8b949e;font-size:10px;">${z.difficulty}</span></div>
          <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(96px,1fr));gap:8px;">
            ${fishes.map(f => {
              const rec = dex[f.id];
              if (rec) return `
                <div title="${f.name} · 钓到${rec.times}次 · 最大 ${rec.best}kg" style="padding:8px 6px;background:#0d1117;border:1px solid ${this._rarityColor(f.rarity)};border-radius:8px;text-align:center;cursor:default;">
                  ${this._fishSVG(f, 56)}
                  <div style="font-size:10px;color:#c9d1d9;margin-top:3px;">${f.name}</div>
                  <div style="font-size:9px;color:${this._rarityColor(f.rarity)};">${this._rarityName(f.rarity)}</div>
                </div>`;
              return `
                <div title="尚未钓到" style="padding:8px 6px;background:#0d1117;border:1px dashed #30363d;border-radius:8px;text-align:center;opacity:.55;">
                  <div style="height:30px;display:flex;align-items:center;justify-content:center;font-size:20px;color:#6e7681;">❓</div>
                  <div style="font-size:10px;color:#6e7681;margin-top:6px;">???</div>
                </div>`;
            }).join('')}
          </div>
        </div>`;
      }).join('')}`;
  },

  // 程序化矢量鱼形（依据 silhouette 参数绘制，无需图片素材）
  _fishSVG(f, size = 56) {
    const s = f.silhouette || {};
    const body = s.body || 'oval', tail = s.tail || 'fan', fin = s.fin || 'none';
    const pattern = s.pattern || 'none', mark = s.mark || 'none';
    const c = f.color || '#8b949e';
    const dark = this._shade(c, -30), stroke = this._shade(c, -45);
    const W = 100, H = 60, cy = 30;

    let bodyPath;
    switch (body) {
      case 'torpedo': bodyPath = `M10 ${cy} C22 ${cy - 18} 60 ${cy - 18} 80 ${cy - 5} L80 ${cy + 5} C60 ${cy + 20} 22 ${cy + 18} 10 ${cy} Z`; break;
      case 'slender': bodyPath = `M10 ${cy} C24 ${cy - 12} 58 ${cy - 12} 80 ${cy - 4} L80 ${cy + 4} C58 ${cy + 14} 24 ${cy + 14} 10 ${cy} Z`; break;
      case 'elongated': bodyPath = `M6 ${cy} C24 ${cy - 9} 58 ${cy - 9} 84 ${cy - 3} L84 ${cy + 3} C58 ${cy + 11} 24 ${cy + 11} 6 ${cy} Z`; break;
      case 'serpent': bodyPath = `M4 ${cy} Q22 ${cy - 12} 40 ${cy} T74 ${cy} L74 ${cy + 4} Q56 ${cy + 12} 40 ${cy + 4} T4 ${cy + 4} Z`; break;
      case 'bulbous': bodyPath = `M8 ${cy} C12 ${cy - 20} 40 ${cy - 20} 62 ${cy - 9} L70 ${cy - 3} L70 ${cy + 3} L62 ${cy + 9} C40 ${cy + 22} 12 ${cy + 22} 8 ${cy} Z`; break;
      case 'ray': bodyPath = `M46 ${cy} L16 ${cy - 22} L32 ${cy} L16 ${cy + 22} Z`; break;
      default: bodyPath = `M18 ${cy} C20 ${cy - 18} 62 ${cy - 18} 78 ${cy - 5} L78 ${cy + 5} C62 ${cy + 20} 20 ${cy + 20} 18 ${cy} Z`;
    }
    let tailPath = '';
    if (tail === 'fan') tailPath = `M80 ${cy} C88 ${cy - 12} 96 ${cy - 12} 100 ${cy - 6} L94 ${cy} L100 ${cy + 6} C96 ${cy + 12} 88 ${cy + 12} 80 ${cy} Z`;
    else if (tail === 'fork') tailPath = `M80 ${cy} L100 ${cy - 16} L88 ${cy} L100 ${cy + 16} Z`;
    else if (tail === 'crescent') tailPath = `M80 ${cy} C92 ${cy - 12} 100 ${cy - 14} 100 ${cy} C100 ${cy + 14} 92 ${cy + 12} 80 ${cy} Z`;

    const parts = [];
    if (tailPath) parts.push(`<path d="${tailPath}" fill="${c}" stroke="${stroke}" stroke-width="1.5"/>`);
    parts.push(`<path d="${bodyPath}" fill="${c}" stroke="${stroke}" stroke-width="1.5"/>`);
    if (fin === 'dorsal') parts.push(`<path d="M52 ${cy - 14} L58 ${cy - 26} L66 ${cy - 14} Z" fill="${dark}" stroke="${stroke}" stroke-width="1"/>`);
    else if (fin === 'adipose') parts.push(`<path d="M70 ${cy - 13} L74 ${cy - 20} L78 ${cy - 13} Z" fill="${dark}" stroke="${stroke}" stroke-width="1"/>`);
    if (pattern === 'stripes') {
      for (let x = 34; x <= 70; x += 8) parts.push(`<line x1="${x}" y1="${cy - 12}" x2="${x}" y2="${cy + 12}" stroke="${dark}" stroke-width="2.5" opacity=".55"/>`);
    } else if (pattern === 'spots') {
      [[40, cy - 6], [52, cy - 2], [44, cy + 4], [62, cy - 5], [70, cy + 2]].forEach(p => parts.push(`<circle cx="${p[0]}" cy="${p[1]}" r="2.6" fill="${dark}" opacity=".6"/>`));
    } else if (pattern === 'scales') {
      for (let x = 36; x <= 72; x += 9) parts.push(`<path d="M${x} ${cy} q 4.5 -6 9 0" fill="none" stroke="${dark}" stroke-width="2" opacity=".5"/>`);
    }
    if (mark === 'whisker') {
      parts.push(`<path d="M12 ${cy + 2} L4 ${cy + 8} M14 ${cy + 5} L6 ${cy + 12}" fill="none" stroke="${stroke}" stroke-width="1.6" opacity=".8"/>`);
    } else if (mark === 'snout') {
      parts.push(`<path d="M10 ${cy} L4 ${cy - 2} L4 ${cy + 2} Z" fill="${c}" stroke="${stroke}" stroke-width="1"/>`);
    } else if (mark === 'sail') {
      parts.push(`<path d="M30 ${cy - 12} C24 ${cy - 30} 48 ${cy - 30} 44 ${cy - 14} Z" fill="${dark}" stroke="${stroke}" stroke-width="1"/>`);
    } else if (mark === 'lantern') {
      parts.push(`<circle cx="16" cy="${cy - 10}" r="4" fill="#ffe9a3" stroke="#f0c33c" stroke-width="1"/><line x1="17" y1="${cy - 6}" x2="20" y2="${cy - 2}" stroke="${stroke}" stroke-width="1.5"/>`);
    } else if (mark === 'horn') {
      parts.push(`<path d="M40 ${cy - 14} L46 ${cy - 26} L52 ${cy - 14} Z" fill="#cfd6e4" stroke="${stroke}" stroke-width="1"/>`);
    }
    parts.push(`<circle cx="28" cy="${cy - 4}" r="3.4" fill="#111" stroke="#fff" stroke-width="1.2"/><circle cx="29" cy="${cy - 5}" r="1.1" fill="#fff"/>`);
    return `<svg width="${size}" height="${Math.round(size * H / W)}" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">${parts.join('')}</svg>`;
  },

  _shade(hex, amt) {
    const n = parseInt(hex.slice(1), 16);
    const r = Math.max(0, Math.min(255, (n >> 16) + amt));
    const g = Math.max(0, Math.min(255, ((n >> 8) & 255) + amt));
    const b = Math.max(0, Math.min(255, (n & 255) + amt));
    return '#' + ((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1);
  },

  async _eat(name, target) {
    const resp = await fetch('/api/death-mode/life-skills/eat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, target }),
    });
    const r = await resp.json();
    alert(r.message || r.error);
    this._reload('bag');
  },

  async _sellFish(name) {
    const resp = await fetch('/api/death-mode/life-skills/sell-fish', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    const r = await resp.json();
    alert(r.message || r.error);
    this._reload('bag');
  },

  async _equipItem(name) {
    const resp = await fetch('/api/death-mode/life-skills/equip-item', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    const r = await resp.json();
    alert(r.message || r.error);
    this._reload('bag');
  },

  // ── 附魔 ─────────────────────────────────────────
  _openEnchant(name) {
    this._enchantItem = name;
    this._freeSel.enchant = {};
    this._renderEnchantPanel();
  },

  _renderEnchantPanel() {
    const el = document.getElementById('enchant-panel');
    if (!el) return;
    const name = this._enchantItem;
    if (!name) { el.innerHTML = ''; return; }
    const item = (this._data.equipment || []).find(e => e.name === name)
      || (this._data.shared_items || []).find(s => s.name === name);
    if (!item) { el.innerHTML = ''; return; }
    const isShared = (this._data.equipment || []).every(e => e.name !== name);
    el.innerHTML = `
      <div style="padding:12px;background:#2d2d0d;border:1px solid #f0883e;border-radius:10px;">
        <div style="font-size:13px;color:#f0883e;font-weight:600;margin-bottom:8px;">✨ 附魔 <b>${item.icon||'⬜'} ${item.name}</b> ${isShared?`<span style="font-size:10px;color:#58a6ff;">（共享背包携带）</span>`:''}</div>
        <div style="font-size:11px;color:#8b949e;margin-bottom:8px;">选择附魔材料（附魔石/符文/水晶等），由大模型为装备附加属性。材料越稀有，附魔越强。</div>
        <div id="enchant-free-mats" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;"></div>
        <button onclick="LifeSkillsUI._submitEnchant()" ${item.enchant?'disabled':''} style="padding:6px 16px;background:linear-gradient(135deg,#f0883e,#d29922);border:none;border-radius:6px;color:#fff;cursor:pointer;font-size:12px;font-weight:bold;">✨ 开始附魔</button>
        <button onclick="LifeSkillsUI._closeEnchant()" style="padding:6px 12px;background:#21262d;border:1px solid #30363d;border-radius:6px;color:#8b949e;cursor:pointer;font-size:11px;margin-left:6px;">收起</button>
      </div>`;
    this._renderFreeMats('enchant-free-mats', 'enchant', ['enchant']);
  },

  _closeEnchant() {
    this._enchantItem = null;
    this._renderEnchantPanel();
  },

  async _submitEnchant() {
    if (!this._enchantItem) return;
    const sel = this._freeSel.enchant || {};
    const materials = Object.entries(sel).filter(([id, q]) => q > 0).map(([id, q]) => [id, q]);
    if (!materials.length) { alert('请先选择附魔材料'); return; }
    const resp = await fetch('/api/death-mode/life-skills/enchant', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_name: this._enchantItem, materials }),
    });
    const r = await resp.json();
    alert(r.message || r.error);
    this._freeSel.enchant = {};
    this._enchantItem = null;
    this._reload('bag');
  },

  // ── 烹饪：顺序小游戏 ──────────────────────────────
  _renderCook(main) {
    const d = this._data;
    const recipes = d.recipes || [];
    const invMap = {};
    (d.inventory || []).forEach(it => { invMap[it.id] = it.qty || 0; });
    const cooking = (d.skills || {}).cooking || { level: 1 };
    const known = d.recipes_known || [];

    const recipeCards = recipes.map(r => {
      const can = r.materials.every(([id, q]) => (invMap[id] || 0) >= q);
      const lvOk = cooking.level >= r.level;
      const isKnown = known.includes(r.id);
      return `
        <div style="padding:10px;background:${isKnown?'#12241a':'#161b22'};border:1px solid ${lvOk&&can?'#3fb950':'#30363d'};border-radius:8px;">
          <div style="font-size:13px;color:#c9d1d9;">${r.icon} ${r.name} ${isKnown?'✅':''}</div>
          <div style="font-size:10px;color:#8b949e;margin:3px 0;">Lv.${r.level} · ${this._buffDesc(r.buff)}</div>
          <div style="font-size:9px;color:#8b949e;margin-bottom:4px;">材料：${r.materials.map(([id,q])=>`${this._matName(id)}${(invMap[id]||0)>=q?'':'(!)'}×${q}`).join(' ')}</div>
          <button onclick="LifeSkillsUI._startCook('${r.id}')" ${lvOk&&can?'':'disabled'} style="width:100%;padding:4px;background:#1a3a1a;border:1px solid #3fb950;border-radius:5px;color:#3fb950;cursor:pointer;font-size:11px;">开始烹饪</button>
        </div>`;
    }).join('');

    main.innerHTML = `
      <h4 style="margin:0 0 10px;color:#3fb950;font-size:14px;">🍳 烹饪</h4>
      <div id="cook-minigame" style="margin-bottom:12px;"></div>
      <div style="padding:12px;background:#12241a;border:1px solid #3fb950;border-radius:10px;margin-bottom:12px;">
        <div style="font-size:13px;color:#3fb950;font-weight:600;margin-bottom:4px;">🧪 自由烹饪 <span style="font-size:10px;color:#8b949e;font-weight:normal;">（LLM 动态创作，材料任意搭配）</span></div>
        <div style="font-size:11px;color:#8b949e;margin-bottom:8px;">从背包挑选食材自由组合，由大模型为你生成一道独门料理。加入附魔/特殊材料还可能做出属性增益佳肴。</div>
        <div id="cook-free-mats" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;"></div>
        <button onclick="LifeSkillsUI._startCookFree()" style="padding:6px 16px;background:linear-gradient(135deg,#3fb950,#2ea043);border:none;border-radius:6px;color:#fff;cursor:pointer;font-size:12px;font-weight:bold;">🍲 开始自由烹饪</button>
      </div>
      <div style="font-size:11px;color:#8b949e;margin-bottom:8px;">选择菜谱开始烹饪。按正确顺序完成步骤（顺序小游戏），顺序越准品质越高。</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;">${recipeCards}</div>`;
    this._renderFreeMats('cook-free-mats', 'cook', ['ingredient']);
  },

  _matName(id) {
    const m = (this._data.shop || []).find(s => s.id === id);
    if (m) return m.name;
    const it = (this._data.inventory || []).find(i => i.id === id);
    return it ? it.name : id;
  },

  // 食材品质等级徽标（1普通~5珍稀）
  _gradeBadge(g) {
    const map = { 1: ['普通', '#8b949e'], 2: ['良好', '#3fb950'], 3: ['优质', '#58a6ff'],
                  4: ['稀有', '#a371f7'], 5: ['珍稀', '#f0883e'] };
    const [name, color] = map[g] || map[1];
    return `<span style="font-size:9px;color:${color};border:1px solid ${color}55;padding:0 4px;border-radius:8px;">${name}</span>`;
  },

  async _startCook(recipeId, free) {
    let recipe;
    if (free) {
      const sel = this._freeSel.cook || {};
      const materials = Object.entries(sel).filter(([id, q]) => q > 0).map(([id, q]) => [id, q]);
      if (!materials.length) { alert('请先挑选食材'); return; }
      recipe = { id: null, name: '自由创作', icon: '🍲', materials, steps: ['备料', '调味', '烹制'] };
      this._cook = { recipe, steps: this._shuffle(recipe.steps), picked: [], active: true, timer: null, free: true, materials };
    } else {
      recipe = (this._data.recipes || []).find(r => r.id === recipeId);
      if (!recipe) return;
      this._cook = { recipe, steps: this._shuffle(recipe.steps), picked: [], active: true, timer: null, free: false, materials: null };
    }
    this._renderCookGame();
  },

  _shuffle(arr) {
    const a = [...arr];
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  },

  _renderCookGame() {
    const c = this._cook;
    const el = document.getElementById('cook-minigame');
    if (!el || !c.recipe) return;
    const target = c.recipe.steps;
    const shuffled = c.steps;
    const pickedMap = {};
    c.picked.forEach(p => pickedMap[p] = true);

    el.innerHTML = `
      <div style="padding:12px;background:#12241a;border:1px solid #3fb950;border-radius:10px;">
        <div style="font-size:13px;color:#3fb950;font-weight:600;margin-bottom:8px;">🍳 ${c.recipe.name} · 按顺序选择步骤</div>
        <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;">
          ${shuffled.map((s, i) => pickedMap[i] ? ''
            : `<button onclick="LifeSkillsUI._cookPick(${i})" style="padding:6px 12px;background:#1a3a1a;border:1px solid #3fb950;border-radius:20px;color:#3fb950;cursor:pointer;font-size:12px;">${s}</button>`).join('')}
        </div>
        <div style="font-size:11px;color:#8b949e;margin-bottom:8px;">已选顺序：</div>
        <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px;">
          ${c.picked.map((p, i) => `<span style="padding:4px 10px;background:#0d2a1a;border:1px solid #3fb950;border-radius:4px;color:#c9d1d9;font-size:11px;">${i+1}. ${c.steps[p]}</span>`).join('')}
        </div>
        <div style="display:flex;gap:8px;">
          <button onclick="LifeSkillsUI._resetCook()" style="padding:5px 14px;background:#21262d;border:1px solid #30363d;border-radius:6px;color:#8b949e;cursor:pointer;font-size:11px;">重置</button>
          <button onclick="LifeSkillsUI._submitCook()" ${c.picked.length < target.length ? 'disabled' : ''} style="padding:5px 14px;background:#1a3a1a;border:1px solid #3fb950;border-radius:6px;color:#3fb950;cursor:pointer;font-size:12px;font-weight:bold;">🍳 完成烹饪</button>
        </div>
      </div>`;
  },

  _cookPick(i) {
    const c = this._cook;
    if (!c.active || c.picked.includes(i)) return;
    c.picked.push(i);
    this._renderCookGame();
  },

  _resetCook() {
    this._cook.picked = [];
    this._renderCookGame();
  },

  // ── 自由烹饪 · 中餐工序（切型/腌制/手法/火候）────────
  _startCookFree() {
    const sel = this._freeSel.cook || {};
    const materials = Object.entries(sel).filter(([id, q]) => q > 0).map(([id, q]) => [id, q]);
    if (!materials.length) { alert('请先挑选食材'); return; }
    this._cookFree = { cut: {}, marinade: [], marinade_t: '不腌', method: '', duration: '' };
    this._renderCookFree();
  },

  _cfSet(key, val) {
    // 腌制腌料：多选切换；其余（时长/手法/火候）单选
    if (key === 'marinade') {
      if (val === '不腌') {
        this._cookFree.marinade = ['不腌'];  // 选"不腌"则清空其他腌料
      } else {
        const arr = this._cookFree.marinade || [];
        this._cookFree.marinade = arr.includes('不腌')
          ? [val]
          : (arr.includes(val) ? arr.filter(x => x !== val) : [...arr, val]);
        if (!this._cookFree.marinade.length) this._cookFree.marinade = ['不腌'];
      }
    } else {
      this._cookFree[key] = val;
    }
    this._renderCookFree();
  },

  // 切配：每种食材各自选切法（多食材各自成刀工）
  _cfCut(mid, val) {
    this._cookFree.cut = this._cookFree.cut || {};
    this._cookFree.cut[mid] = val;
    this._renderCookFree();
  },

  _renderCookFree() {
    const cf = this._cookFree;
    const el = document.getElementById('cook-minigame');
    if (!el) return;
    const sel = this._freeSel.cook || {};
    const mats = Object.entries(sel).filter(([id, q]) => q > 0);
    const matDesc = mats.map(([id, q]) => `${this._matName(id)}×${q}`).join('、') || '（未选）';
    const CUT_OPTS = ['切丝', '切片', '切块', '切丁', '滚刀块', '剁末', '整条'];
    // ① 切配：每种食材各自选切法（多食材各自成刀工）
    const cutRows = mats.map(([id, q]) => {
      const chosen = (cf.cut && cf.cut[id]) || '';
      return `
      <div style="margin-bottom:6px;">
        <div style="font-size:11px;color:#c9d1d9;margin-bottom:3px;">${this._matName(id)}×${q} <span style="color:#8b949e;">的切法：</span></div>
        <div style="display:flex;flex-wrap:wrap;gap:5px;">
          ${CUT_OPTS.map(o => `<button onclick="LifeSkillsUI._cfCut('${id}','${o}')" style="padding:3px 9px;background:${chosen===o?'#2ea043':'#1a3a1a'};border:1px solid ${chosen===o?'#3fb950':'#2d5a2d'};border-radius:14px;color:${chosen===o?'#fff':'#3fb950'};cursor:pointer;font-size:10px;">${o}</button>`).join('')}
        </div>
      </div>`;
    }).join('');
    const group = (label, key, opts, multi) => {
      const isSel = (o) => multi
        ? ((cf[key] || []).includes(o))
        : (cf[key] === o);
      return `
      <div style="margin-bottom:8px;">
        <div style="font-size:11px;color:#8b949e;margin-bottom:4px;">${label}${multi ? '<span style="color:#58a6ff;">（可多选）</span>' : ''}</div>
        <div style="display:flex;flex-wrap:wrap;gap:5px;">
          ${opts.map(o => `<button onclick="LifeSkillsUI._cfSet('${key}','${o}')" style="padding:4px 10px;background:${isSel(o)?'#2ea043':'#1a3a1a'};border:1px solid ${isSel(o)?'#3fb950':'#2d5a2d'};border-radius:14px;color:${isSel(o)?'#fff':'#3fb950'};cursor:pointer;font-size:11px;">${o}</button>`).join('')}
        </div>
      </div>`;
    };
    const allCut = mats.length && mats.every(([id]) => cf.cut && cf.cut[id]);
    const ready = allCut && (cf.marinade || []).length && cf.marinade_t && cf.method && cf.duration;
    el.innerHTML = `
      <div style="padding:12px;background:#12241a;border:1px solid #3fb950;border-radius:10px;">
        <div style="font-size:13px;color:#3fb950;font-weight:600;margin-bottom:4px;">🧪 自由烹饪 · 中餐工序</div>
        <div style="font-size:11px;color:#c9d1d9;margin-bottom:8px;">食材：${matDesc}<span style="color:#8b949e;">（食材品质越高，成品越好、越易出完美）</span></div>
        <div style="font-size:11px;color:#8b949e;margin-bottom:4px;">① 切配 · 每种食材各自的刀工</div>
        ${cutRows}
        ${group('② 腌制 · 用什么腌料？', 'marinade', ['不腌', '盐', '生抽', '料酒', '姜葱', '蒜蓉', '花椒', '辣椒', '糖醋汁'], true)}
        ${group('腌制时长', 'marinade_t', ['不腌', '10分钟', '30分钟', '2小时'])}
        ${group('③ 制作手法', 'method', ['煎', '炒', '炸', '蒸', '炖', '烤', '煮', '焖', '爆'])}
        ${group('④ 火候时长', 'duration', ['短(急火)', '中', '长(慢火)'])}
        <div style="font-size:10px;color:#6e7681;margin-top:2px;">每种食材可分别切配（如鱼切片、葱切段）；火候与手法不匹配会出问题（如煎太久糊了、炖太短夹生），完成时会得到一句烹饪评语。腌料可多选组合（如盐+料酒+姜葱）。</div>
        <div style="display:flex;gap:8px;margin-top:8px;">
          <button onclick="LifeSkillsUI._startCookFree()" style="padding:5px 14px;background:#21262d;border:1px solid #30363d;border-radius:6px;color:#8b949e;cursor:pointer;font-size:11px;">重置</button>
          <button onclick="LifeSkillsUI._submitCookFree()" ${ready?'':'disabled'} style="padding:5px 14px;background:#1a3a1a;border:1px solid #3fb950;border-radius:6px;color:#3fb950;cursor:pointer;font-size:12px;font-weight:bold;">🍳 完成烹饪</button>
        </div>
      </div>`;
  },

  async _submitCookFree() {
    const cf = this._cookFree;
    const sel = this._freeSel.cook || {};
    const materials = Object.entries(sel).filter(([id, q]) => q > 0).map(([id, q]) => [id, q]);
    // 每种食材各自的切法描述，如「小麦切丝、鱼肉切片」
    const cutDesc = materials.map(([id]) =>
      `${this._matName(id)}${(cf.cut && cf.cut[id]) || ''}`).join('、');
    const resp = await fetch('/api/death-mode/life-skills/cook', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ materials, free: true,
        cut: cutDesc, marinade: (cf.marinade || []).join('+'), marinade_t: cf.marinade_t,
        method: cf.method, duration: cf.duration }),
    });
    const r = await resp.json();
    if (r.error) { alert(r.message || r.error); this._reload('cook'); return; }
    alert(r.message + (r.comment ? '\n📝 大厨评语：' + r.comment : '') + (r.poison ? '\n🦠 这料理吃了会食物中毒扣血！' : '') + (r.special ? '\n✨ 特殊效果：额外获得持续攻击/防御增益！' : '') + (r.level_up ? '\n🎉 烹饪升级！' : ''));
    this._freeSel.cook = {};
    this._reload('cook');
  },

  async _submitCook() {
    const c = this._cook;
    if (!c.recipe) return;
    const payload = c.free
      ? { materials: c.materials, steps: c.picked }
      : { recipe_id: c.recipe.id, steps: c.picked };
    const resp = await fetch('/api/death-mode/life-skills/cook', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const r = await resp.json();
    if (r.error) { alert(r.message || r.error); this._reload('cook'); return; }
    alert(r.message + (r.level_up ? '\n🎉 烹饪升级！' : ''));
    c.active = false;
    this._freeSel.cook = {};
    this._reload('cook');
  },

  // ── 自由组合材料选择器（通用）──────────────────────
  _renderFreeMats(containerId, selKey, types) {
    const sel = this._freeSel[selKey] = this._freeSel[selKey] || {};
    const inv = (this._data.inventory || []).filter(it => types.includes(it.type) && it.qty > 0);
    const el = document.getElementById(containerId);
    if (!el) return;
    if (!inv.length) {
      el.innerHTML = '<div style="font-size:11px;color:#6e7681;">背包里没有可用材料，先去商店购买，或通过探索/战斗采集吧。</div>';
      return;
    }
    el.innerHTML = inv.map(it => {
      const q = sel[it.id] || 0;
      return `<div style="display:flex;align-items:center;gap:4px;padding:4px 8px;background:#0d1117;border:1px solid ${q>0?'#58a6ff':'#30363d'};border-radius:6px;">
        <span style="font-size:11px;color:#c9d1d9;">${it.icon} ${it.name} ${this._gradeBadge(it.grade)}</span>
        <span style="font-size:10px;color:#6e7681;">×${it.qty}</span>
        ${q>0?`<button onclick="LifeSkillsUI._freeInc('${selKey}','${it.id}',-1)" style="width:20px;height:20px;border-radius:4px;border:1px solid #f85149;background:transparent;color:#f85149;cursor:pointer;font-size:12px;line-height:1;">−</button><span style="font-size:11px;color:#58a6ff;min-width:14px;text-align:center;">${q}</span>`:''}
        <button onclick="LifeSkillsUI._freeInc('${selKey}','${it.id}',1)" ${q>=it.qty?'disabled':''} style="width:20px;height:20px;border-radius:4px;border:1px solid #3fb950;background:transparent;color:#3fb950;cursor:pointer;font-size:12px;line-height:1;">+</button>
      </div>`;
    }).join('');
  },

  _freeInc(selKey, id, delta) {
    const sel = this._freeSel[selKey] = this._freeSel[selKey] || {};
    const it = (this._data.inventory || []).find(x => x.id === id);
    const max = it ? it.qty : 0;
    const cur = sel[id] || 0;
    const next = Math.max(0, Math.min(max, cur + delta));
    if (next <= 0) delete sel[id]; else sel[id] = next;
    this._renderFreeMats('cook-free-mats', 'cook', ['ingredient']);
    this._renderFreeMats('forge-free-mats', 'forge', ['ore', 'misc', 'enchant']);
    this._renderFreeMats('enchant-free-mats', 'enchant', ['enchant']);
  },

  // ── 锻造：真实工艺时机小游戏 ──────────────────────
  _renderForge(main) {
    const d = this._data;
    const bps = d.blueprints || [];
    const invMap = {};
    (d.inventory || []).forEach(it => { invMap[it.id] = it.qty || 0; });
    const forging = (d.skills || {}).forging || { level: 1 };
    const need = forging.level * 50;
    const fXp = forging.xp || 0;
    const fPct = Math.min(100, fXp / need * 100);
    const fRemain = Math.max(0, need - fXp);

    const cards = bps.map(b => {
      const can = b.materials.every(([id, q]) => (invMap[id] || 0) >= q);
      const lvOk = forging.level >= b.level;
      const isGear = !!b.fishing_gear;
      const sub = isGear ? '🎣 钓鱼装备' : `加成+${b.result.bonus}`;
      const missing = b.materials.filter(([id, q]) => (invMap[id] || 0) < q);
      const reasons = [];
      if (!lvOk) reasons.push(`需要锻造Lv.${b.level}`);
      if (missing.length) reasons.push(`缺：${missing.map(([id, q]) => `${this._matName(id)}×${q}`).join('、')}`);
      const ok = lvOk && can;
      return `
        <div style="padding:10px;background:#161b22;border:1px solid ${ok?'#a371f7':'#30363d'};border-radius:8px;">
          <div style="font-size:13px;color:#c9d1d9;">${b.icon} ${b.name} ${isGear?'🎣':''}</div>
          <div style="font-size:10px;color:#8b949e;margin:3px 0;">Lv.${b.level} · ${sub}</div>
          <div style="font-size:9px;color:#8b949e;margin-bottom:4px;">材料：${b.materials.map(([id,q])=>`${this._matName(id)}×${q}`).join(' ')}${missing.length?`<span style="color:#f85149;">（缺：${missing.map(([id,q])=>`${this._matName(id)}×${q}`).join('、')}）</span>`:''}</div>
          <button onclick="LifeSkillsUI._startForge('${b.id}')" ${ok?'':'disabled'} title="${reasons.join('；')}" style="width:100%;padding:4px;background:${ok?'#1a2a3a':'#161b22'};border:1px solid ${ok?'#a371f7':'#30363d'};border-radius:5px;color:${ok?'#a371f7':'#6e7681'};cursor:${ok?'pointer':'not-allowed'};font-size:11px;">${ok?'开始锻造':'❌ '+(missing.length?'材料不足':'等级不足')}</button>
        </div>`;
    }).join('');

    main.innerHTML = `
      <h4 style="margin:0 0 10px;color:#a371f7;font-size:14px;">🔨 锻造</h4>
      <div style="padding:10px;background:#1a1224;border:1px solid #a371f7;border-radius:10px;margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;align-items:center;font-size:12px;">
          <span style="color:#a371f7;font-weight:600;">锻造等级 Lv.${forging.level}</span>
          <span style="color:#8b949e;">经验 ${fXp}/${need}</span>
        </div>
        <div style="height:8px;background:#0d1117;border-radius:4px;margin-top:6px;overflow:hidden;">
          <div style="height:100%;width:${fPct}%;background:linear-gradient(90deg,#a371f7,#6e40c9);"></div>
        </div>
        <div style="font-size:10px;color:#8b949e;margin-top:4px;">距升级还差 ${fRemain} 经验 · 每次锻造成功都会获得经验</div>
      </div>
      <div id="forge-minigame" style="margin-bottom:12px;"></div>
      <div style="padding:12px;background:#1a1224;border:1px solid #a371f7;border-radius:10px;margin-bottom:12px;">
        <div style="font-size:13px;color:#a371f7;font-weight:600;margin-bottom:4px;">🧪 自由锻造 <span style="font-size:10px;color:#8b949e;font-weight:normal;">（LLM 动态成形，材料任意搭配）</span></div>
        <div style="font-size:11px;color:#8b949e;margin-bottom:8px;">从背包挑选矿石与材料自由搭配，由大模型为你锻造一件独一无二的装备，锻造完成后可通过背包装备到自己身上。加入附魔材料还能做出更稀有的神兵。</div>
        <div id="forge-free-mats" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;"></div>
        <button onclick="LifeSkillsUI._startForge(null, true)" style="padding:6px 16px;background:linear-gradient(135deg,#a371f7,#6e40c9);border:none;border-radius:6px;color:#fff;cursor:pointer;font-size:12px;font-weight:bold;">⚒️ 开始自由锻造</button>
      </div>
      <div style="font-size:11px;color:#8b949e;margin-bottom:8px;">按真实锻造工艺进行：趁金属处于最佳状态时点击执行每一步（时机判定）。指针越接近亮区，品质越高。钓鱼装备也可通过锻造打造。</div>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;">${cards}</div>`;
    this._renderFreeMats('forge-free-mats', 'forge', ['ore', 'misc', 'enchant']);
  },

  async _startForge(bpId, free) {
    let bp;
    if (free) {
      const sel = this._freeSel.forge || {};
      const materials = Object.entries(sel).filter(([id, q]) => q > 0).map(([id, q]) => [id, q]);
      if (!materials.length) { alert('请先挑选材料'); return; }
      bp = { id: null, name: '自由锻造', icon: '⚒️', steps: ['选材', '加热', '锻打', '淬火', '成型'], materials };
      this._forge = { bp, steps: bp.steps, idx: 0, active: true, timer: null, window: 0, results: [], free: true, materials };
    } else {
      bp = (this._data.blueprints || []).find(b => b.id === bpId);
      if (!bp) return;
      this._forge = { bp, steps: bp.steps, idx: 0, active: true, timer: null, window: 0, results: [], free: false, materials: null };
    }
    this._renderForgeGame();
  },

  _renderForgeGame() {
    const f = this._forge;
    const el = document.getElementById('forge-minigame');
    if (!el || !f.bp) return;
    const stepName = f.steps[f.idx];
    const stepIdx = f.idx;
    const total = f.steps.length;

    el.innerHTML = `
      <div style="padding:12px;background:#1a1224;border:1px solid #a371f7;border-radius:10px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <div style="font-size:13px;color:#a371f7;font-weight:600;">🔨 ${f.bp.name}</div>
          <div style="font-size:11px;color:#8b949e;">步骤 ${stepIdx+1}/${total}</div>
        </div>
        <div style="font-size:14px;color:#c9d1d9;margin-bottom:10px;">当前：<b style="color:#fff;">${this._stepIcon(stepName)} ${stepName}</b></div>
        <div style="position:relative;height:46px;background:#0d1117;border:1px solid #30363d;border-radius:8px;overflow:hidden;margin-bottom:8px;">
          <div id="forge-window" style="position:absolute;top:0;bottom:0;width:18%;background:rgba(167,139,250,0.35);border:1px solid #a371f7;"></div>
          <div id="forge-cursor" style="position:absolute;top:0;bottom:0;width:4px;background:#f85149;left:0%;"></div>
        </div>
        <div id="forge-msg" style="font-size:11px;color:#8b949e;margin-bottom:8px;">等待指针进入亮区...</div>
        <div style="display:flex;gap:8px;">
          <button onclick="LifeSkillsUI._forgeHit()" style="flex:1;padding:8px;background:linear-gradient(135deg,#a371f7,#6e40c9);border:none;border-radius:6px;color:#fff;cursor:pointer;font-size:13px;font-weight:bold;">🔨 执行：${this._forgeVerb(stepName)}</button>
          <button onclick="LifeSkillsUI._cancelForge()" style="padding:8px 14px;background:#21262d;border:1px solid #30363d;border-radius:6px;color:#8b949e;cursor:pointer;font-size:11px;">取消</button>
        </div>
        <div id="forge-history" style="margin-top:8px;display:flex;flex-wrap:wrap;gap:4px;">
          ${f.results.map((r, i) => `<span style="padding:2px 8px;border-radius:4px;font-size:10px;background:${this._qColor(r)}22;border:1px solid ${this._qColor(r)};color:${this._qColor(r)};">${i+1}.${this._qName(r)}</span>`).join('')}
        </div>
      </div>`;

    // 开始指针动画
    this._stopTimers();
    let pos = 0, dir = 1;
    const win = 0.18 + (Math.random() * 0.2);
    f.window = win;
    document.getElementById('forge-window').style.left = (Math.random() * (1 - win) * 100) + '%';
    f.timer = setInterval(() => {
      pos += dir * 1.6;           // 速度
      if (pos >= 100) { pos = 100; dir = -1; }
      if (pos <= 0) { pos = 0; dir = 1; }
      const cur = document.getElementById('forge-cursor');
      if (cur) cur.style.left = pos + '%';
      f.cursorPos = pos;
    }, 30);
  },

  _forgeHit() {
    const f = this._forge;
    if (!f.active) return;
    const winEl = document.getElementById('forge-window');
    const winLeft = parseFloat(winEl.style.left) || 0;
    const win = f.window;
    const pos = f.cursorPos || 0;
    // 判定：指针相对亮区中心
    const center = winLeft + win / 2;
    const diff = Math.abs(pos - center);
    let q;
    if (diff < win * 0.25) q = 'perfect';
    else if (diff < win * 0.55) q = 'good';
    else q = 'normal';

    f.results.push(q);
    f.idx++;
    const msg = document.getElementById('forge-msg');
    if (msg) msg.textContent = `${this._stepNameByIdx(f.idx-1)}：${this._qName(q)}（${this._qColor(q)}）`;

    if (f.idx >= f.steps.length) {
      this._submitForge();
    } else {
      this._renderForgeGame();
    }
  },

  _stepNameByIdx(i) { return this._forge.steps[i] || ''; },

  _stepIcon(s) {
    return { 选材: '⛏', 加热: '🔥', 锻打: '🔨', 折叠锻打: '🔨', 淬火: '💧', 回火: '🔥', 成型: '⚙️', 打磨: '✨' }[s] || '🔨';
  },
  _forgeVerb(s) {
    return { 选材: '挑选', 加热: '升温', 锻打: '锤击', 折叠锻打: '折叠', 淬火: '淬炼', 回火: '回火', 成型: '定型', 打磨: '打磨' }[s] || s;
  },
  _qName(q) { return { perfect: '完美', good: '良好', normal: '普通' }[q] || q; },
  _qColor(q) { return { perfect: '#3fb950', good: '#d29922', normal: '#8b949e' }[q] || '#8b949e'; },

  _cancelForge() {
    this._stopTimers();
    this._forge.active = false;
    this._renderForge(document.getElementById('ls-main'));
  },

  async _submitForge() {
    const f = this._forge;
    this._stopTimers();
    f.active = false;
    const steps = f.results.map(q => q === 'perfect' ? 0 : q === 'good' ? 1 : 2);
    const payload = f.free
      ? { materials: f.materials, steps }
      : { blueprint_id: f.bp.id, steps };
    const resp = await fetch('/api/death-mode/life-skills/forge', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const r = await resp.json();
    if (r.error) { alert(r.message || r.error); this._reload('forge'); return; }
    alert(r.message + (r.level_up ? '\n🎉 锻造升级！' : ''));
    this._freeSel.forge = {};
    this._reload('forge');
  },

  // ── 钓鱼：实景小游戏（参考 glm-diaoyu：昼夜/水面/搏斗张力）──
  _zoneName() {
    const z = (this._data.fish_zones || []).find(x => x.id === this._zone);
    return z ? z.name : this._zone;
  },

  _renderFish(main) {
    const d = this._data;
    const owned = d.fish_gear_owned || [];
    const eq = d.fish_gear_equipped || {};
    const zones = d.fish_zones || [];
    const earnings = d.fish_earnings || 0;
    const region = this._region || null;
    const zoneObj = zones.find(z => z.id === this._zone);
    const fishByZone = {};
    (d.fish_table || []).forEach(f => f.zones.forEach(z => (fishByZone[z] = fishByZone[z] || []).push(f)));

    // 当前区域信息（决定可钓到的鱼）
    const regionInfo = region
      ? `<div style="font-size:12px;color:#e6edf3;padding:6px 10px;background:linear-gradient(135deg,#1a2a3a,#0d1117);border:1px solid #30363d;border-radius:8px;margin-bottom:8px;">
          📍 当前所在：<b style="color:#58a6ff;">${region.name}</b>
          <span style="font-size:10px;color:#8b949e;">（危险度 ${'★'.repeat(region.danger_level || 1)}${'☆'.repeat(Math.max(0, 5 - (region.danger_level || 1)))})</span>
          <div style="font-size:10px;color:#8b949e;margin-top:2px;">此处水域：${zoneObj ? zoneObj.name : this._zone} · 可钓到下方图鉴中的鱼</div>
        </div>`
      : `<div style="font-size:12px;color:#e6edf3;padding:6px 10px;background:#1a2a3a;border:1px solid #30363d;border-radius:8px;margin-bottom:8px;">📍 当前水域：<b style="color:#58a6ff;">${zoneObj ? zoneObj.name : this._zone}</b></div>`;

    const zoneChips = zones.map(z => {
      const locked = earnings < z.need;
      const active = this._zone === z.id;
      return `<span title="鱼获水域由所在区域决定，此处仅作图鉴参考"
        style="padding:5px 12px;margin:2px;border-radius:20px;font-size:12px;cursor:default;
        background:${active ? '#1a2a3a' : '#161b22'};
        border:1px solid ${active ? '#58a6ff' : (locked ? '#3a3a3a' : '#30363d')};
        color:${locked ? '#6e7681' : '#8b949e'};">${locked ? '🔒 ' : ''}${z.name}${locked ? '·' + z.need : ''}</span>`;
    }).join('');

    const gear = (slot, label, icon, list) => {
      const cur = eq[slot];
      return `<div style="margin-bottom:8px;">
        <div style="font-size:11px;color:#8b949e;margin-bottom:4px;">${icon} ${label}</div>
        ${(list || []).map(g => {
          const isOn = cur === g.id, isOwned = owned.includes(g.id);
          const action = isOn
            ? `<span style="color:#58a6ff;font-size:10px;">✓ 装备中</span>`
            : isOwned
              ? `<button onclick="LifeSkillsUI._equipGear('${g.id}')" style="padding:2px 8px;background:#1a2a3a;border:1px solid #58a6ff;border-radius:6px;color:#58a6ff;cursor:pointer;font-size:10px;">穿戴</button>`
              : `<button onclick="LifeSkillsUI._buyGear('${g.id}')" style="padding:2px 8px;background:#21262d;border:1px solid #d29922;border-radius:6px;color:#d29922;cursor:pointer;font-size:10px;">${g.price > 0 ? g.price + '💰' : '免费'}</button>`;
          return `<div style="display:flex;justify-content:space-between;align-items:center;padding:3px 6px;border:1px solid ${isOn ? '#58a6ff' : '#21262d'};border-radius:6px;margin-bottom:3px;background:#0d1117;">
            <span style="font-size:11px;color:#c9d1d9;">${g.name}</span>${action}</div>`;
        }).join('')}
      </div>`;
    };

    main.innerHTML = `
      <h4 style="margin:0 0 10px;color:#58a6ff;font-size:14px;">🎣 钓鱼</h4>
      ${regionInfo}
      <div style="display:flex;gap:12px;flex-wrap:wrap;">
        <div style="flex:1;min-width:300px;">
          <div style="position:relative;border:1px solid #30363d;border-radius:10px;overflow:hidden;background:#0a1626;">
            <canvas id="fish-canvas" style="display:block;width:100%;height:280px;"></canvas>
            <div id="fish-hintbar" style="position:absolute;top:8px;left:8px;right:8px;display:flex;justify-content:space-between;align-items:center;font-size:11px;color:#e6edf3;text-shadow:0 1px 2px #000;">
              <span id="fish-hint">点击水面抛竿</span><span id="fish-info"></span>
            </div>
            <div id="fish-tensionbar" style="position:absolute;left:8px;right:8px;bottom:8px;height:14px;background:rgba(0,0,0,0.5);border-radius:7px;overflow:hidden;display:none;">
              <div id="fish-tensionfill" style="height:100%;width:50%;background:linear-gradient(90deg,#58a6ff,#f0883e,#f85149);transition:width .05s;"></div>
            </div>
          </div>
          <div id="fish-controls" style="margin-top:8px;gap:8px;display:none;">
            <button onmousedown="LifeSkillsUI._pull(true)" onmouseup="LifeSkillsUI._pull(false)" onmouseleave="LifeSkillsUI._pull(false)" ontouchstart="LifeSkillsUI._pull(true)" ontouchend="LifeSkillsUI._pull(false)" style="flex:1;padding:10px;background:linear-gradient(135deg,#f0883e,#d29922);border:none;border-radius:8px;color:#fff;font-size:14px;font-weight:bold;cursor:pointer;">▲ 拉线</button>
            <button onmousedown="LifeSkillsUI._release(true)" onmouseup="LifeSkillsUI._release(false)" onmouseleave="LifeSkillsUI._release(false)" ontouchstart="LifeSkillsUI._release(true)" ontouchend="LifeSkillsUI._release(false)" style="flex:1;padding:10px;background:linear-gradient(135deg,#58a6ff,#1f6feb);border:none;border-radius:8px;color:#fff;font-size:14px;font-weight:bold;cursor:pointer;">▼ 放线</button>
          </div>
          <div style="margin-top:8px;font-size:11px;color:#8b949e;">点击水面抛竿。浮漂徐徐浮动时等鱼咬钩——浮漂一沉，立刻点击水面提竿！然后按住「拉线」提升张力、按住「放线」泄力；张力过高断线、过低脱钩，耗尽鱼的耐力即捕获。不同区域栖息着不同的鱼，想钓到特定鱼种就前往对应的区域。</div>
          <div style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;">${zoneChips}</div>
        </div>
        <div style="width:250px;flex-shrink:0;">
          <div style="font-size:12px;color:#d29922;margin-bottom:6px;">🎒 钓具</div>
          ${gear('rod', '鱼竿', '🎣', d.fish_gear_rod)}
          ${gear('reel', '卷线轮', '⚙️', d.fish_gear_reel)}
          ${gear('line', '鱼线', '🧵', d.fish_gear_line)}
          ${gear('bait', '鱼饵', '🪱', d.fish_gear_bait)}
        </div>
      </div>
      <div style="font-size:11px;color:#8b949e;margin-top:10px;">📖 当前可钓（${zoneObj ? zoneObj.name : this._zone}·累计收益 ${earnings}💰，每种品质仅展示一种）：</div>
      <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:6px;">
        ${(() => {
          const zoneFish = fishByZone[this._zone] || [];
          const shown = [];
          const seen = {};
          zoneFish.forEach(f => { if (!seen[f.rarity]) { seen[f.rarity] = true; shown.push(f); } });
          const total = zoneFish.length;
          return shown.map(f => `
            <span title="该水域共 ${total} 种鱼，其余需钓到后在图鉴中点亮" style="padding:3px 8px;background:#0d1117;border:1px solid ${this._rarityColor(f.rarity)};border-radius:20px;font-size:10px;color:${this._rarityColor(f.rarity)};">${f.icon} ${f.name} ${this._rarityName(f.rarity)}</span>`).join('')
            + (total > shown.length ? `<span style="padding:3px 8px;background:#0d1117;border:1px dashed #30363d;border-radius:20px;font-size:10px;color:#8b949e;">+${total - shown.length} 神秘鱼种</span>` : '');
        })()}
      </div>`;
    this._initFishCanvas();
  },

  _rarityColor(r) {
    return { common: '#8b949e', rare: '#58a6ff', epic: '#a371f7', legendary: '#f0883e' }[r] || '#8b949e';
  },

  // ── 钓具 / 水域操作 ────────────────────────────────
  async _buyGear(id) {
    const resp = await fetch('/api/death-mode/life-skills/fish-buy-gear', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ gear_id: id }),
    });
    const r = await resp.json();
    if (r.error) { alert(r.message || r.error); return; }
    alert(r.message); this._reload('fish');
  },

  async _equipGear(id) {
    const resp = await fetch('/api/death-mode/life-skills/fish-equip', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ gear_id: id }),
    });
    const r = await resp.json();
    if (r.error) { alert(r.message || r.error); return; }
    alert(r.message); this._reload('fish');
  },

  async _setZone(z) {
    if (this._fish.phase !== 'idle') { alert('请先收线再切换水域'); return; }
    const resp = await fetch('/api/death-mode/life-skills/fish-set-zone', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ zone: z }),
    });
    const r = await resp.json();
    if (r.error) { alert(r.message || r.error); return; }
    this._zone = r.fish_zone || z;
    this._reload('fish');
  },

  _equipped() {
    const d = this._data, eq = d.fish_gear_equipped || {};
    const find = (slot, list) => (list || []).find(g => g.id === eq[slot]) || (list || [])[0] || {};
    return { rod: find('rod', d.fish_gear_rod), reel: find('reel', d.fish_gear_reel), line: find('line', d.fish_gear_line), bait: find('bait', d.fish_gear_bait) };
  },

  // 客户端选鱼（与后端 pick_fish 同逻辑）
  _pickFish(zoneId) {
    const d = this._data;
    const available = (d.fish_table || []).filter(f => f.zones.includes(zoneId));
    if (!available.length) return null;
    const bait = this._equipped().bait || { family: '杂鱼', bite: 1.15 };
    const rod = this._equipped().rod || {};
    const level = (d.skills.fishing || {}).level || 1;
    const weighted = [];
    for (const f of available) {
      let w = f.aggress;
      if (bait.family === f.family) w *= bait.bite;
      else if (bait.family === '传说' && f.legendary) w *= bait.bite;
      // 鱼竿抛投力：抛得越远，越容易勾到力量型大鱼（fight 高）
      if (f.fight > 60) w *= 0.6 + (rod.cast || 40) / 100;
      weighted.push([f, Math.max(0.05, w)]);
    }
    const total = weighted.reduce((a, b) => a + b[1], 0);
    let r = Math.random() * total;
    for (const [f, w] of weighted) { r -= w; if (r <= 0) return f; }
    return weighted[weighted.length - 1][0];
  },

  _weight(fish) {
    if (Math.random() < 0.15) return +(fish.min + (fish.max - fish.min) * 0.9).toFixed(1);
    return +(fish.min + (fish.max - fish.min) * (Math.random() ** 1.6)).toFixed(1);
  },

  // ── Canvas 实景引擎 ────────────────────────────────
  _flamp(v, a, b) { return Math.max(a, Math.min(b, v)); },

  _initFishCanvas() {
    const cv = document.getElementById('fish-canvas');
    if (!cv) return;
    const rect = cv.getBoundingClientRect();
    cv.width = rect.width || 300;
    cv.height = rect.height || 280;
    const f = this._fish;
    f.cv = cv; f.ctx = cv.getContext('2d');
    f.phase = 'idle'; f.time = Math.random() * 100;
    f.bobber = { x: 0, y: 0, vx: 0, vy: 0, inWater: false, bob: 0, active: false };
    f.hookedFish = null;
    f.tension = 50; f.fishStam = 100; f.tensionDir = 0; f.tensionTarget = 50; f.maxTensionSeen = 50;
    f.particles = []; f.ripples = []; f.pulling = false; f.releasing = false; f.biteTimer = 0;
    cv.onclick = (e) => this._onCanvasClick(e);
    document.getElementById('fish-controls').style.display = 'none';
    document.getElementById('fish-tensionbar').style.display = 'none';
    this._setHint('点击水面抛竿');
    this._setInfo(this._zoneName());
    this._stopTimers();
    const loop = () => { f.raf = requestAnimationFrame(loop); this._fishUpdate(); this._drawFishScene(); };
    f.raf = requestAnimationFrame(loop);
  },

  _setHint(t) { const el = document.getElementById('fish-hint'); if (el) el.textContent = t; },
  _setInfo(t) { const el = document.getElementById('fish-info'); if (el) el.textContent = t; },

  _onCanvasClick(e) {
    const f = this._fish;
    if (f.phase === 'idle') this._castRod(e);
    else if (f.phase === 'bite') this._pickAndHook();   // 浮漂下沉，点击提竿
    else if (f.phase === 'waiting') this._endFight(false, '收线了，没鱼');
  },

  _castRod(e) {
    const f = this._fish;
    const rect = f.cv.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const H = f.cv.height, waterLine = H * 0.58;
    if (my < waterLine + 10) { this._setHint('需要抛到水面'); return; }
    f.phase = 'casting';
    f.rod.x = 60; f.rod.y = waterLine - 8;
    const sx = f.rod.x + 40, sy = f.rod.y - 60;
    f.bobber = { x: sx, y: sy, vx: (mx - sx) * 0.022, vy: -8, inWater: false, bob: 0, active: true };
    this._setHint('抛竿中...');
  },

  _fishUpdate() {
    const f = this._fish, dt = 1 / 60;
    f.time += dt;
    if (!f.cv) return;
    const W = f.cv.width, H = f.cv.height, waterLine = H * 0.58;
    if (f.phase === 'casting') {
      f.bobber.vy += 0.35; f.bobber.x += f.bobber.vx; f.bobber.y += f.bobber.vy;
      if (f.bobber.y >= waterLine) {
        f.bobber.y = waterLine; f.bobber.inWater = true;
        this._spawnSplash(f.bobber.x, waterLine, 14); this._spawnRipple(f.bobber.x, waterLine);
        f.phase = 'waiting'; f.biteTimer = 3 + Math.random() * 5;
        this._setHint('等待鱼儿咬钩...');
      }
    } else if (f.phase === 'waiting') {
      f.bobber.bob = Math.sin(f.time * 2) * 1.5;
      if (Math.random() < dt * 1.5) this._spawnRipple(f.bobber.x, waterLine);
      f.biteTimer -= dt;
      if (f.biteTimer <= 0) {
        // 浮漂下沉，进入提竿窗口（宽松容错：2.5 秒内点击即中）
        f.phase = 'bite';
        f.biteTimer = 2.5;
        this._setHint('浮漂沉了！快点击水面提竿！');
        this._spawnSplash(f.bobber.x, waterLine, 10);
      }
    } else if (f.phase === 'bite') {
      f.biteTimer -= dt;
      if (f.biteTimer <= 0) {
        // 超时未提竿：鱼跑了，重新等鱼
        f.phase = 'waiting'; f.biteTimer = 3 + Math.random() * 5;
        this._setHint('慢了一步，鱼跑了，重新等鱼...');
      }
    } else if (f.phase === 'fighting') {
      this._updateFight(dt);
    }
    for (let i = f.particles.length - 1; i >= 0; i--) {
      const p = f.particles[i]; p.x += p.vx; p.y += p.vy;
      if (p.type === 'drop') p.vy += 0.4;
      p.life -= dt; if (p.life <= 0) f.particles.splice(i, 1);
    }
    for (let i = f.ripples.length - 1; i >= 0; i--) {
      const r = f.ripples[i]; r.r += 60 * dt; r.life -= dt * 1.2;
      if (r.life <= 0 || r.r > r.maxR) f.ripples.splice(i, 1);
    }
    f.rod.sway = Math.sin(f.time * 1.5) * 0.02;
  },

  // 装备组合值 vs 鱼难度：返回「装备不足压力」0(无)~0.9(极大)
  _gearPressure(fish) {
    const eq = this._equipped();
    const gearPower = (eq.rod.fight || 0) * 1.2 + (eq.rod.cast || 0) * 0.2
      + (eq.reel.drag || 0) * 1.0 + (eq.reel.speed || 0) * 0.3
      + (eq.line.maxTension || 0) * 0.6;
    const diff = (fish.strength || 0) + (fish.fight || 0) * 0.5 + (fish.max || 0) * 1.0;
    if (diff <= 0) return 0;
    return Math.max(0, Math.min(0.9, 1 - gearPower / diff));
  },

  // 装备不足导致的失败：脱钩/断线/爆杆（断线、爆杆需重新购买装备）
  async _gearFail(fish) {
    const f = this._fish;
    const heavy = f._pres > 0.6;   // 差距极大 → 爆杆概率高
    const r = Math.random();
    if (!heavy && r < 0.35) {
      this._endFight(false, `💨 ${fish.name} 脱钩跑了！`); return;
    }
    const isRod = heavy ? r < 0.5 : r < 0.7;
    const slot = isRod ? 'rod' : 'line';
    let msg = '';
    try {
      const resp = await fetch('/api/death-mode/life-skills/fish-damage', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slot }),
      });
      const rj = await resp.json();
      if (rj.broken) msg = `（${rj.message}）`;
    } catch (e) { /* 网络异常不阻断 */ }
    const name = slot === 'rod' ? '鱼竿' : '鱼线';
    this._reload('fish');
    this._endFight(false, `💥 ${fish.name} 实在太猛，你的${name}不堪重负${isRod ? '爆杆' : '断了'}！${msg}`);
  },

  _pickAndHook() {
    const f = this._fish;
    const fish = this._pickFish(this._zone);
    if (!fish) { f.biteTimer = 3 + Math.random() * 4; return; }
    f.hookedFish = fish;
    f.phase = 'fighting';
    f.tension = 50; f.tensionTarget = 50; f.tensionDir = 0; f.fishStam = 100; f.maxTensionSeen = 50;
    f._failAcc = 0;
    f._pres = this._gearPressure(fish);
    f.bobber.bob = 8;
    this._spawnSplash(f.bobber.x, f.cv.height * 0.58, 18);
    this._spawnRipple(f.bobber.x, f.cv.height * 0.58);
    this._setHint('上钩了！按住拉/放控制张力，耗尽鱼耐力即捕获');
    document.getElementById('fish-controls').style.display = 'flex';
    document.getElementById('fish-tensionbar').style.display = 'block';
    this._updateFightHud();
  },

  _updateFight(dt) {
    const f = this._fish, fish = f.hookedFish;
    if (!fish) return;
    const eq = this._equipped();
    const breakLimit = Math.min(100, (eq.line.maxTension || 90));
    const drag = eq.reel.drag || 0;
    f.tensionDir += (Math.random() * 2 - 1) * dt * 60;
    f.tensionTarget = this._flamp(50 + f.tensionDir, 5, 95);
    f.tensionDir *= 0.96;
    if (f.pulling) {
      // 线强度提供张力缓冲：强线拉线时张力涨得慢，更不易断线
      const lineBuf = Math.max(1, (eq.line.maxTension || 90) / 90);
      const inc = Math.max(5, (35 - drag * 0.4) / lineBuf);
      f.tension += inc * dt;
      f.fishStam -= (8 + fish.strength / 40) * dt * (1 + (eq.rod.fight || 0) / 100);
    } else if (f.releasing) {
      // 卷线轮速度：速度越快，放线时张力降得越快（更容易缓解断线风险）
      f.tension -= 35 * (1 + (eq.reel.speed || 30) / 100) * dt; f.fishStam += 1 * dt;
    } else {
      f.tension += (f.tensionTarget - f.tension) * dt * 0.8;
    }
    f.tension += (f.tensionTarget - f.tension) * dt * 0.5;
    f.tension = this._flamp(f.tension, 0, 100);
    f.fishStam = this._flamp(f.fishStam, 0, 100);
    f.maxTensionSeen = Math.max(f.maxTensionSeen, f.tension);
    // 装备组合 vs 鱼难度：装备不足时累积「失败压力」，压力满则脱钩/断线/爆杆
    if (f._pres > 0) {
      let growth = f._pres * 0.5;
      if (f.tension > 70) growth += 0.3;   // 张力警戒线附近压力暴涨
      if (f.tension < 30) growth *= 0.3;    // 稳住低张力可大幅缓解
      f._failAcc = (f._failAcc || 0) + growth * dt;
      if (f._failAcc >= 1) { f._failAcc = 0; this._gearFail(fish); return; }
    }
    f.bobber.bob = Math.sin(performance.now() * 0.02) * 4 + 2;
    this._updateFightHud();
    if (f.tension >= breakLimit) this._endFight(false, '💥 线断了！鱼跑了');
    else if (f.tension <= 1) this._endFight(false, '💨 鱼脱钩了');
    else if (f.fishStam <= 0) this._endFight(true, null);
  },

  _updateFightHud() {
    const f = this._fish;
    const info = document.getElementById('fish-info');
    const fill = document.getElementById('fish-tensionfill');
    if (f.hookedFish) {
      const fish = f.hookedFish;
      if (info) info.textContent = `🎣 ${fish.name} · 张力${Math.round(f.tension)} · 耐力${Math.round(f.fishStam)}`;
    }
    if (fill) fill.style.width = f.tension + '%';
  },

  _pull(v) { this._fish.pulling = v; },
  _release(v) { this._fish.releasing = v; },

  _spawnSplash(x, y, n) {
    const f = this._fish;
    for (let i = 0; i < n; i++) f.particles.push({
      x, y, vx: (Math.random() * 2 - 1) * 4, vy: -2 - Math.random() * 5,
      life: 0.4 + Math.random() * 0.5, maxLife: 0.9, size: 1.5 + Math.random() * 2, type: 'drop',
    });
  },
  _spawnRipple(x, y) { this._fish.ripples.push({ x, y, r: 4, maxR: 60, life: 1 }); },

  async _endFight(success, failMsg) {
    const f = this._fish;
    const fish = f.hookedFish;
    document.getElementById('fish-controls').style.display = 'none';
    document.getElementById('fish-tensionbar').style.display = 'none';
    f.pulling = f.releasing = false;
    f.hookedFish = null; f.bobber.active = false; f.phase = 'idle';
    if (success && fish) {
      const weight = this._weight(fish);
      const line = this._equipped().line;
      const maxT = line.maxTension || 90;
      // 线越强，「张力峰值」越容易低于 80% 上限 → 越容易出完美品质
      const quality = f.maxTensionSeen < maxT * 0.8 ? 'perfect' : 'good';
      this._setHint('搏斗成功！结算中...');
      const resp = await fetch('/api/death-mode/life-skills/fish', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ zone: this._zone, fish_id: fish.id, weight, quality }),
      });
      const r = await resp.json();
      if (r.error) { this._setHint(r.message || r.error); this._reload('fish'); return; }
      this._spawnSplash(f.bobber.x, f.cv.height * 0.58, 24);
      this._setHint((r.level_up ? '🎉 升级！' : '') + r.message);
      alert(r.message + (r.level_up ? '\n🎉 钓鱼升级！' : ''));
      this._reload('fish');
    } else {
      this._setHint(failMsg || '鱼跑了');
    }
  },

  _drawFishScene() {
    const f = this._fish, ctx = f.ctx;
    if (!ctx) return;
    const W = f.cv.width, H = f.cv.height, waterLine = H * 0.58, t = f.time;
    const day = 0.5 + 0.5 * Math.sin(t * 0.1);
    // 天空
    const sky = ctx.createLinearGradient(0, 0, 0, waterLine);
    sky.addColorStop(0, `hsl(${210 + day * 30},60%,${day * 40 + 8}%)`);
    sky.addColorStop(1, `hsl(210,50%,${day * 30 + 15}%)`);
    ctx.fillStyle = sky; ctx.fillRect(0, 0, W, waterLine);
    // 太阳/月亮
    ctx.globalAlpha = 0.6; ctx.fillStyle = day > 0.5 ? '#fff7d6' : '#e8ecf5';
    ctx.beginPath(); ctx.arc(W * 0.8, waterLine - 40, day > 0.5 ? 14 : 10, 0, Math.PI * 2); ctx.fill();
    ctx.globalAlpha = 1;
    // 远山
    ctx.fillStyle = `hsl(210,30%,${day * 18 + 8}%)`;
    ctx.beginPath(); ctx.moveTo(0, waterLine);
    for (let x = 0; x <= W; x += 20) ctx.lineTo(x, waterLine - 20 - Math.sin(x * 0.02 + t) * 8 - Math.sin(x * 0.05) * 12);
    ctx.lineTo(W, waterLine); ctx.closePath(); ctx.fill();
    // 水面
    const water = ctx.createLinearGradient(0, waterLine, 0, H);
    water.addColorStop(0, `hsl(${200 + day * 15},50%,${day * 30 + 14}%)`);
    water.addColorStop(1, `hsl(210,50%,${day * 20 + 6}%)`);
    ctx.fillStyle = water; ctx.fillRect(0, waterLine, W, H - waterLine);
    // 波光
    ctx.strokeStyle = 'rgba(255,255,255,0.15)'; ctx.lineWidth = 1;
    for (let i = 0; i < 8; i++) {
      const y = waterLine + 12 + i * ((H - waterLine) / 9);
      ctx.beginPath(); ctx.moveTo(0, y);
      for (let x = 0; x <= W; x += 8) ctx.lineTo(x, y + Math.sin(x * 0.03 + t * 2 + i) * 2);
      ctx.stroke();
    }
    // 岸边码头
    ctx.fillStyle = '#4a3a28'; ctx.fillRect(0, waterLine - 6, 120, 14);
    ctx.fillStyle = '#3a2c1e'; ctx.fillRect(0, waterLine - 6, 120, 6);
    // 鱼竿（按装备的竿换造型/颜色/粗细；竿身末端即鱼线起点，保持对齐）
    const _rodMap = {
      rod1: { body:'#8a6a3a', lw:5, len:140, reel:'#7a6a55' },   // 木竿
      rod2: { body:'#3b4450', lw:3.5, len:160, reel:'#93a0ae' }, // 碳素竿
      rod3: { body:'#5a4632', lw:8, len:120, reel:'#8a6b3f' },   // 鲟鱼重竿
      rod4: { body:'#1a5a66', lw:3, len:170, reel:'#3fd0e0' },   // 深渊神竿
    };
    const _eqRod = (this._equipped() || {}).rod || {};
    const _rs = _rodMap[_eqRod.id] || _rodMap.rod1;
    const rod = f.rod, angle = -0.6 + rod.sway, len = _rs.len;
    const tipX = rod.x + Math.cos(angle) * len, tipY = (waterLine - 6) + Math.sin(angle) * len;
    // 竿身（末端即鱼线连接处，鱼线从这里垂出）
    ctx.strokeStyle = _rs.body; ctx.lineWidth = _rs.lw; ctx.lineCap = 'round';
    ctx.beginPath(); ctx.moveTo(rod.x, waterLine - 6); ctx.lineTo(tipX, tipY); ctx.stroke();
    // 卷线轮（竿身中段）
    const _rx = rod.x + Math.cos(angle) * (len * 0.34);
    const _ry = (waterLine - 6) + Math.sin(angle) * (len * 0.34);
    ctx.save(); ctx.translate(_rx, _ry); ctx.rotate(angle);
    ctx.fillStyle = _rs.reel;
    ctx.beginPath(); ctx.ellipse(0, 0, _rs.lw + 4, _rs.lw + 1, 0, 0, Math.PI * 2); ctx.fill();
    ctx.strokeStyle = 'rgba(0,0,0,0.35)'; ctx.lineWidth = 1; ctx.stroke();
    ctx.restore();
    // 鱼线
    if (f.bobber.active || f.phase === 'fighting') {
      ctx.strokeStyle = 'rgba(230,230,230,0.7)'; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(tipX, tipY); ctx.lineTo(f.bobber.x, f.bobber.y); ctx.stroke();
    }
    // 浮漂
    if (f.bobber.inWater || f.phase === 'fighting') {
      let bobY;
      if (f.phase === 'bite') {
        // 咬钩瞬间：浮漂被猛地拉入水下（下沉抖动）
        bobY = waterLine + 4 + Math.sin(f.time * 16) * 2;
      } else {
        bobY = waterLine - Math.abs(Math.sin(t * 2 + f.bobber.bob) * 1.5);
      }
      f.bobberY = bobY;
      ctx.fillStyle = '#f44336'; ctx.beginPath(); ctx.arc(f.bobber.x, bobY, 5, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(f.bobber.x, bobY - 3, 2, 0, Math.PI * 2); ctx.fill();
    }
    // 搏斗时鱼挣扎水花
    if (f.phase === 'fighting' && f.hookedFish) {
      ctx.fillStyle = f.hookedFish.color; ctx.globalAlpha = 0.7;
      ctx.beginPath(); ctx.ellipse(f.bobber.x, waterLine + 20 + Math.sin(t * 8) * 6, 14, 6, 0, 0, Math.PI * 2); ctx.fill();
      ctx.globalAlpha = 1;
    }
    // 涟漪 + 粒子
    for (const r of f.ripples) {
      ctx.strokeStyle = 'rgba(255,255,255,' + r.life * 0.5 + ')';
      ctx.beginPath(); ctx.arc(r.x, r.y, r.r, 0, Math.PI * 2); ctx.stroke();
    }
    for (const p of f.particles) {
      ctx.fillStyle = 'rgba(255,255,255,' + p.life / p.maxLife + ')';
      ctx.beginPath(); ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2); ctx.fill();
    }
  },
};

// 浮标闪烁动画
const _lsStyle = document.createElement('style');
_lsStyle.textContent = '@keyframes lsblink{0%,100%{opacity:1;transform:scale(1)}50%{opacity:0.3;transform:scale(1.3)}}';
document.head.appendChild(_lsStyle);

// 暴露到全局
window.LifeSkillsUI = LifeSkillsUI;