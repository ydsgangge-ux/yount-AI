/**
 * 死亡模式 UI v2 — 网页端作为行动日志查看器
 * 核心逻辑：
 * - 创建角色：仍在网页端完成
 * - 行动交互：在主程序（桌面宠物）中进行
 * - 网页端：自动刷新的行动日志 + 角色状态 + 地图
 */
const DeathModeUI = {
  _state: null,
  _classes: [],
  _logTimer: null,
  _lastLogTotal: 0,
  _userName: '',   // 用户角色名（用于替换日志中的"你"）

  // ── 初始化 ──────────────────────────────────────

  async init() {
    // 检查是否已有进行中的死亡模式游戏
    try {
      const resp = await fetch('/api/death-mode/state');
      const data = await resp.json();
      if (data.active && data.is_alive) {
        this._state = data;
        this.showLogPanel();
        return;
      }
    } catch (e) {}

    // 检查URL参数是否要求打开死亡模式
    const params = new URLSearchParams(location.search);
    if (params.get('death_mode') === '1') {
      this.showCreatePanel();
    }
  },

  // ── 角色创建 ──────────────────────────────────────

  async showCreatePanel() {
    const worlds = await this.loadWorlds();

    const overlay = document.createElement('div');
    overlay.id = 'death-mode-create';
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.85);z-index:9999;display:flex;align-items:center;justify-content:center;';

    overlay.innerHTML = `
      <div style="background:#0d1117;border:1px solid #30363d;border-radius:16px;padding:32px;max-width:560px;width:90%;max-height:90vh;overflow-y:auto;color:#c9d1d9;">
        <h2 style="margin:0 0 8px;color:#f85149;font-size:24px;">☠️ 死亡模式 — 高挑战</h2>
        <p style="color:#8b949e;font-size:13px;margin:0 0 24px;">系统角色与用户角色共同冒险，双方都可能死亡。死亡即 Game Over，存档进入名人堂。</p>

        <div style="margin-bottom:16px;padding:12px;background:#161b22;border-radius:8px;border-left:3px solid #58a6ff;">
          <div style="color:#58a6ff;font-size:12px;margin-bottom:8px;">⚔️ 系统角色（AI伙伴）</div>
          <input id="dm-name" type="text" placeholder="系统角色名字" style="width:100%;padding:8px 12px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:14px;box-sizing:border-box;margin-bottom:8px;" />
          <div id="dm-classes" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;">
            <div style="grid-column:1/-1;text-align:center;padding:12px;color:#8b949e;font-size:12px;">请先选择世界观</div>
          </div>
        </div>

        <div style="margin-bottom:16px;padding:12px;background:#161b22;border-radius:8px;border-left:3px solid #3fb950;">
          <div style="color:#3fb950;font-size:12px;margin-bottom:8px;">👤 用户角色（你）</div>
          <input id="dm-user-name" type="text" placeholder="你的名字（留空则用桌面宠物用户名）" style="width:100%;padding:8px 12px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:14px;box-sizing:border-box;margin-bottom:8px;" />
          <div id="dm-user-classes" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px;">
            <div style="grid-column:1/-1;text-align:center;padding:12px;color:#8b949e;font-size:12px;">请先选择世界观</div>
          </div>
        </div>

        <div style="margin-bottom:16px;">
          <label style="display:block;color:#58a6ff;font-size:13px;margin-bottom:6px;">选择世界观</label>
          <select id="dm-world" style="width:100%;padding:8px 12px;background:#161b22;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:14px;box-sizing:border-box;">
            ${worlds.map(w => `<option value="${w.world_id}">${w.world_name}</option>`).join('')}
          </select>
          <div id="dm-world-type-hint" style="font-size:11px;color:#8b949e;margin-top:4px;"></div>
        </div>

        <div style="margin-bottom:16px;">
          <label style="display:block;color:#58a6ff;font-size:13px;margin-bottom:6px;">成长模式</label>
          <select id="dm-growth" style="width:100%;padding:8px 12px;background:#161b22;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:14px;box-sizing:border-box;">
            <option value="fast">爽文模式（快速升级，大幅成长）</option>
            <option value="normal" selected>平衡模式（正常成长）</option>
            <option value="slow">慢热模式（每点属性都很珍贵）</option>
          </select>
        </div>

        <div id="dm-error" style="color:#f85149;font-size:13px;margin-bottom:12px;display:none;"></div>

        <div style="display:flex;gap:12px;">
          <button id="dm-cancel" style="flex:1;padding:10px;background:#21262d;border:1px solid #30363d;border-radius:8px;color:#c9d1d9;cursor:pointer;font-size:14px;">取消</button>
          <button id="dm-start" style="flex:1;padding:10px;background:#da3633;border:none;border-radius:8px;color:white;cursor:pointer;font-size:14px;font-weight:bold;">开始死亡模式</button>
        </div>
        <div style="margin-top:12px;font-size:11px;color:#8b949e;text-align:center;">创建后在主程序中对话冒险，网页端查看行动记录</div>
      </div>
    `;

    document.body.appendChild(overlay);

    let selectedClass = null;
    let selectedUserClass = null;
    let currentWorldType = null;

    const worldSelect = overlay.querySelector('#dm-world');
    const classesContainer = overlay.querySelector('#dm-classes');
    const userClassesContainer = overlay.querySelector('#dm-user-classes');
    const typeHint = overlay.querySelector('#dm-world-type-hint');

    const typeLabels = {
      fantasy: '奇幻魔法', xianxia: '仙侠修真', wuxia: '武侠江湖',
      post_apocalyptic: '末世废土', modern_power: '现世超武', scifi: '科幻未来',
    };

    function renderClassCards(container, classes, selectedVal, onSelect) {
      container.innerHTML = classes.map(c => `
        <div class="dm-class-card" data-id="${c.id}" style="padding:10px;background:#161b22;border:2px solid ${selectedVal===c.id?'#58a6ff':'#30363d'};border-radius:8px;cursor:pointer;text-align:center;transition:border-color 0.2s;">
          <div style="font-size:24px;margin-bottom:2px;">${c.icon}</div>
          <div style="font-weight:bold;color:#c9d1d9;font-size:12px;">${c.name}</div>
          <div style="font-size:10px;color:#8b949e;margin-top:2px;">HP:${c.base_hp} MP:${c.base_mp}</div>
        </div>
      `).join('');
      container.querySelectorAll('.dm-class-card').forEach(card => {
        card.addEventListener('click', () => {
          container.querySelectorAll('.dm-class-card').forEach(c => c.style.borderColor = '#30363d');
          card.style.borderColor = '#58a6ff';
          onSelect(card.dataset.id);
        });
      });
    }

    async function reloadClasses() {
      const worldId = worldSelect.value;
      if (!worldId) return;
      const loadingHtml = '<div style="grid-column:1/-1;text-align:center;padding:12px;color:#8b949e;font-size:12px;">加载职业中...</div>';
      classesContainer.innerHTML = loadingHtml;
      userClassesContainer.innerHTML = loadingHtml;
      try {
        const resp = await fetch(`/api/death-mode/classes?world_id=${encodeURIComponent(worldId)}`);
        const data = await resp.json();
        const classes = data.classes || [];
        currentWorldType = data.world_type || 'fantasy';
        typeHint.textContent = `世界类型：${typeLabels[currentWorldType] || currentWorldType}`;
        if (classes.length === 0) {
          const emptyHtml = '<div style="grid-column:1/-1;text-align:center;padding:12px;color:#f85149;font-size:12px;">无可用职业</div>';
          classesContainer.innerHTML = emptyHtml;
          userClassesContainer.innerHTML = emptyHtml;
          return;
        }
        renderClassCards(classesContainer, classes, null, (id) => { selectedClass = id; });
        selectedClass = null;
        renderClassCards(userClassesContainer, classes, null, (id) => { selectedUserClass = id; });
        selectedUserClass = null;
      } catch (e) {
        const errHtml = `<div style="grid-column:1/-1;text-align:center;padding:12px;color:#f85149;font-size:12px;">加载失败: ${e.message}</div>`;
        classesContainer.innerHTML = errHtml;
        userClassesContainer.innerHTML = errHtml;
      }
    }

    worldSelect.addEventListener('change', reloadClasses);
    if (worlds.length > 0) await reloadClasses();

    overlay.querySelector('#dm-cancel').addEventListener('click', () => overlay.remove());

    overlay.querySelector('#dm-start').addEventListener('click', async () => {
      const name = overlay.querySelector('#dm-name').value.trim();
      const userName = overlay.querySelector('#dm-user-name').value.trim();
      const worldId = worldSelect.value;
      const growth = overlay.querySelector('#dm-growth').value;
      const errEl = overlay.querySelector('#dm-error');
      if (!name) { errEl.textContent = '请填写系统角色名字'; errEl.style.display = 'block'; return; }
      if (!selectedClass) { errEl.textContent = '请为系统角色选择职业'; errEl.style.display = 'block'; return; }
      if (!selectedUserClass) { errEl.textContent = '请为用户角色选择职业'; errEl.style.display = 'block'; return; }
      errEl.style.display = 'none';
      const btn = overlay.querySelector('#dm-start');
      btn.textContent = '创建中...'; btn.disabled = true;
      try {
        const resp = await fetch('/api/death-mode/start', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ character_name: name, class_id: selectedClass, user_class_id: selectedUserClass, user_name: userName, world_id: worldId, growth_mode: growth }),
        });
        if (!resp.ok) { const err = await resp.json(); throw new Error(err.detail || '创建失败'); }
        const data = await resp.json();
        this._state = data;
        overlay.remove();
        this.showLogPanel();
      } catch (e) {
        errEl.textContent = e.message; errEl.style.display = 'block';
        btn.textContent = '开始死亡模式'; btn.disabled = false;
      }
    });
  },

  async loadClasses() {
    try {
      const resp = await fetch('/api/death-mode/classes');
      const data = await resp.json();
      this._classes = data.classes || [];
    } catch (e) { this._classes = []; }
    return this._classes;
  },

  async loadWorlds() {
    try {
      const resp = await fetch('/api/worlds');
      const data = await resp.json();
      return (data.worlds || []).filter(w => w.world_id !== 'modern');
    } catch (e) { return []; }
  },

  // ── 日志面板（主界面）──────────────────────────────

  showLogPanel() {
    const setup = document.getElementById('setup-overlay');
    if (setup) setup.style.display = 'none';

    let panel = document.getElementById('death-mode-panel');
    if (panel) panel.remove();

    panel = document.createElement('div');
    panel.id = 'death-mode-panel';
    panel.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:linear-gradient(135deg,#0d1117,#161b22);z-index:9999;display:flex;flex-direction:column;';

    panel.innerHTML = `
      <div style="padding:12px 20px;background:#0d1117;border-bottom:1px solid #30363d;display:flex;align-items:center;justify-content:space-between;">
        <div style="display:flex;align-items:center;gap:12px;">
          <h2 style="margin:0;color:#f85149;font-size:16px;">☠️ 死亡模式</h2>
          <span id="dm-header-char" style="font-size:12px;color:#8b949e;"></span>
        </div>
        <div style="display:flex;gap:8px;align-items:center;">
          <span id="dm-auto-refresh" style="font-size:11px;color:#3fb950;">● 自动刷新</span>
          <button id="dm-life-btn" style="padding:4px 12px;background:#1a2a3a;border:1px solid #58a6ff;border-radius:6px;color:#58a6ff;cursor:pointer;font-size:12px;">🎒 生活技能</button>
          <button id="dm-exit" style="padding:4px 12px;background:#21262d;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;cursor:pointer;font-size:12px;">退出</button>
        </div>
      </div>

      <div style="flex:1;display:flex;overflow:hidden;">
        <!-- 左侧：角色状态 -->
        <div id="dm-status-panel" style="width:220px;padding:12px;background:#0d1117;border-right:1px solid #30363d;overflow-y:auto;flex-shrink:0;">
          <div style="text-align:center;color:#484f58;padding:40px 0;">加载中...</div>
        </div>

        <!-- 中间：行动日志 -->
        <div style="flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0;">
          <div style="padding:8px 16px;border-bottom:1px solid #21262d;display:flex;align-items:center;justify-content:space-between;">
            <span style="font-size:13px;color:#58a6ff;font-weight:600;">📜 行动记录</span>
            <span id="dm-log-count" style="font-size:11px;color:#484f58;"></span>
          </div>
          <div id="dm-log-container" style="flex:1;overflow-y:auto;padding:12px 16px;">
            <div style="text-align:center;color:#484f58;padding:40px 0;">加载中...</div>
          </div>
        </div>

        <!-- 右侧：怪物信息栏（仅战斗时显示） -->
        <div id="dm-enemies-panel" style="width:160px;padding:8px;background:#0d1117;border-left:1px solid #30363d;overflow-y:auto;flex-shrink:0;display:none;">
          <div style="text-align:center;color:#484f58;padding:20px 0;font-size:11px;">未在战斗</div>
        </div>
      </div>
    `;

    document.body.appendChild(panel);

    panel.querySelector('#dm-exit').addEventListener('click', () => {
      this._stopAutoRefresh();
      panel.remove();
      const setupOverlay = document.getElementById('setup-overlay');
      if (setupOverlay) setupOverlay.style.display = '';
    });

    panel.querySelector('#dm-life-btn').addEventListener('click', () => {
      if (window.LifeSkillsUI) {
        window.LifeSkillsUI.open();
      } else {
        alert('生活技能模块未加载');
      }
    });

    // 加载状态和日志
    this._renderStatusPanel();
    this._loadAndRenderLog();

    // 启动自动刷新（每5秒）
    this._startAutoRefresh();
  },

  _startAutoRefresh() {
    this._stopAutoRefresh();
    this._logTimer = setInterval(() => {
      this._loadAndRenderLog();
      this._renderStatusPanel();
    }, 5000);
  },

  _stopAutoRefresh() {
    if (this._logTimer) {
      clearInterval(this._logTimer);
      this._logTimer = null;
    }
  },

  async _renderStatusPanel() {
    const panel = document.getElementById('dm-status-panel');
    if (!panel) return;

    try {
      const resp = await fetch('/api/death-mode/state');
      const state = await resp.json();
      if (!state.active) return;

      this._state = state;  // 更新缓存，供 showFullMap 等使用

      const char = state.character || {};
      const stats = char.stats || {};
      const hpPct = char.max_hp > 0 ? (char.hp / char.max_hp * 100) : 0;
      const mpPct = char.max_mp > 0 ? (char.mp / char.max_mp * 100) : 0;
      const expPct = char.exp_to_next > 0 ? (char.experience / char.exp_to_next * 100) : 0;
      const hpColor = hpPct > 60 ? '#3fb950' : hpPct > 30 ? '#d29922' : '#f85149';

      // 缓存用户名（用于替换日志中的"你"）
      const userChar = state.user_character || {};
      if (userChar.name) this._userName = userChar.name;

      // 更新头部（AI角色 + 用户名）
      const headerChar = document.getElementById('dm-header-char');
      if (headerChar) {
        headerChar.textContent = `${char.name || '?'} Lv.${char.level || 1} · HP ${char.hp}/${char.max_hp}${this._userName ? ' · 👤' + this._userName : ''}`;
      }

      // 装备（AI角色，4槽位显示，含卸下按钮 + 属性显示）
      const eqHtml = this._renderEquipmentSlots(char, 'ai');

      // 共享背包（从 state 读取，含属性显示）
      const sharedInv = state.shared_inventory || [];
      let invHtml = '';
      if (sharedInv.length > 0) {
        invHtml = sharedInv.map(item => {
          const slotIcon = this._getItemSlotIcon(item);
          // 属性描述
          let bonusText = '';
          if (item.bonus) {
            const dt = item.damage_type || 'physical';
            const bonusLabel = dt === 'magic' ? '法' : dt === 'ranged' ? '远' : dt === 'defense' ? '防' : '攻';
            bonusText += `${bonusLabel}+${item.bonus}`;
          }
          if (item.stat_bonus) {
            const sb = item.stat_bonus;
            const statLabels = {strength:'力',agility:'敏',intelligence:'智',vitality:'体',luck:'运'};
            const sbParts = Object.entries(sb).map(([k,v]) => `${statLabels[k]||k}+${v}`);
            if (sbParts.length > 0) bonusText += (bonusText ? ' ' : '') + sbParts.join(' ');
          }
          const bonusHtml = bonusText ? `<span style="font-size:9px;color:#3fb950;">${bonusText}</span>` : '';
          return `<div style="font-size:11px;color:${item.color || '#c9d1d9'};display:flex;justify-content:space-between;align-items:center;margin-bottom:2px;">
            <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;">${slotIcon} ${item.name}（${item.rarity_name || '普通'}）${bonusHtml}</span>
            <div style="display:flex;gap:3px;flex-shrink:0;">
              <button onclick="DeathModeUI._equipFromInv('${item.name}','ai')" style="font-size:9px;padding:1px 4px;background:#1a3a1a;border:1px solid #3fb950;border-radius:3px;color:#3fb950;cursor:pointer;">AI</button>
              <button onclick="DeathModeUI._equipFromInv('${item.name}','user')" style="font-size:9px;padding:1px 4px;background:#1a2a3a;border:1px solid #58a6ff;border-radius:3px;color:#58a6ff;cursor:pointer;">我</button>
              <button onclick="DeathModeUI._sellFromInv('${item.name}',${item.sell_price||5})" style="font-size:9px;padding:1px 4px;background:#3d2a1a;border:1px solid #f0883e;border-radius:3px;color:#f0883e;cursor:pointer;">售${item.sell_price||5}</button>
            </div>
          </div>`;
        }).join('');
      } else {
        invHtml = '<div style="font-size:11px;color:#484f58;">空</div>';
      }

      // 用户角色
      const uc = state.user_character;
      let ucHtml = '';
      if (uc && uc.class_name) {
        const uHpPct = uc.max_hp > 0 ? (uc.hp / uc.max_hp * 100) : 0;
        const uMpPct = uc.max_mp > 0 ? (uc.mp / uc.max_mp * 100) : 0;
        const uExpPct = uc.exp_to_next > 0 ? ((uc.experience || 0) / uc.exp_to_next * 100) : 0;
        const uHpColor = uHpPct > 60 ? '#3fb950' : uHpPct > 30 ? '#d29922' : '#f85149';
        const uStats = uc.stats || {};
        const uEqHtml = this._renderEquipmentSlots(uc, 'user');
        ucHtml = `
          <div style="margin-top:12px;padding-top:12px;border-top:1px dashed #30363d;">
            <div style="text-align:center;margin-bottom:8px;">
              <div style="font-size:20px;">👤</div>
              <div style="font-size:14px;font-weight:bold;color:#c9d1d9;">${uc.name || '用户'}</div>
              <div style="font-size:11px;color:#8b949e;">${uc.class_name || ''} Lv.${uc.level || 1}</div>
            </div>
            <div style="margin-bottom:8px;">
              <div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:1px;">
                <span style="color:#f85149;">HP</span><span style="color:#8b949e;">${uc.hp||0}/${uc.max_hp||0}</span>
              </div>
              <div style="height:8px;background:#21262d;border-radius:4px;overflow:hidden;">
                <div style="height:100%;width:${uHpPct}%;background:${uHpColor};transition:width 0.3s;"></div>
              </div>
            </div>
            <div style="margin-bottom:8px;">
              <div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:1px;">
                <span style="color:#58a6ff;">MP</span><span style="color:#8b949e;">${uc.mp||0}/${uc.max_mp||0}</span>
              </div>
              <div style="height:6px;background:#21262d;border-radius:3px;overflow:hidden;">
                <div style="height:100%;width:${uMpPct}%;background:#58a6ff;transition:width 0.3s;"></div>
              </div>
            </div>
            <div style="margin-bottom:8px;">
              <div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:1px;">
                <span style="color:#d29922;">EXP</span><span style="color:#8b949e;">${uc.experience||0}/${uc.exp_to_next||100}</span>
              </div>
              <div style="height:5px;background:#21262d;border-radius:3px;overflow:hidden;">
                <div style="height:100%;width:${uExpPct}%;background:#d29922;transition:width 0.3s;"></div>
              </div>
            </div>
            <div style="font-size:10px;color:#8b949e;margin-bottom:6px;">
              <div>💪力量${uStats.strength||5} 🏃敏捷${uStats.agility||5}</div>
              <div>🧠智力${uStats.intelligence||5} ❤️体质${uStats.vitality||5}</div>
              <div>🍀运气${uStats.luck||5}</div>
            </div>
            <div style="margin-bottom:6px;">
              <div style="font-size:10px;color:#3fb950;margin-bottom:2px;">装备</div>
              ${uEqHtml || '<div style="font-size:11px;color:#484f58;">无</div>'}
            </div>
            <div style="font-size:10px;color:#8b949e;margin-bottom:6px;">
              <div>💰 金币: ${uc.gold||0}</div>
            </div>
            <div style="margin-bottom:6px;">
              <button onclick="DeathModeUI.showSkillPanel('user')" style="width:100%;padding:5px;background:#1a2a3a;border:1px solid #58a6ff;border-radius:6px;color:#58a6ff;cursor:pointer;font-size:10px;">⚔️ 技能管理（我）</button>
            </div>
          </div>`;
      }

      // ── 新篇章按钮：始终显示（结局达成/未达成两种状态） ──
      const endingPending = state.ending_pending_transition === true;
      const endingTitle = state.ending_title || '隐藏结局';
      const endingDesc = state.ending_description || '';
      let newChapterHtml = '';
      if (endingPending) {
        // 结局已达成：紫色高亮，显示结局标题
        newChapterHtml = `
          <div id="dm-new-chapter-box" style="margin-bottom:12px;padding:10px;background:linear-gradient(135deg,#2d1a3a,#1a1a2d);border:1px solid #a371f7;border-radius:8px;text-align:center;">
            <div style="font-size:11px;color:#a371f7;font-weight:bold;margin-bottom:4px;">🏆 隐藏结局达成</div>
            <div style="font-size:12px;color:#e6edf3;font-weight:bold;margin-bottom:4px;">${endingTitle}</div>
            ${endingDesc ? `<div style="font-size:10px;color:#8b949e;margin-bottom:8px;line-height:1.4;">${endingDesc}</div>` : ''}
            <button id="dm-new-chapter-btn" onclick="DeathModeUI.confirmTransition(false)" style="width:100%;padding:8px;background:linear-gradient(135deg,#a371f7,#6e40c9);border:none;border-radius:6px;color:white;cursor:pointer;font-size:12px;font-weight:bold;">📖 开启新篇章</button>
            <div style="font-size:9px;color:#6e7681;margin-top:4px;">将总结本章并生成下一章故事（约30-60秒）</div>
          </div>`;
      } else {
        // 结局未达成：普通样式，提示可主动刷新剧情
        newChapterHtml = `
          <div id="dm-new-chapter-box" style="margin-bottom:12px;padding:8px;background:#161b22;border:1px dashed #30363d;border-radius:8px;text-align:center;">
            <button id="dm-new-chapter-btn" onclick="DeathModeUI.confirmTransition(true)" style="width:100%;padding:6px;background:#21262d;border:1px solid #6e7681;border-radius:6px;color:#c9d1d9;cursor:pointer;font-size:11px;">📖 开启新篇章</button>
            <div style="font-size:9px;color:#6e7681;margin-top:3px;">不满意当前剧情？主动开启新章节</div>
          </div>`;
      }

      panel.innerHTML = `
        ${newChapterHtml}
        <div style="text-align:center;margin-bottom:12px;">
          <div style="font-size:32px;">${char.class_icon || '⚔️'}</div>
          <div style="font-size:15px;font-weight:bold;color:#c9d1d9;margin-top:4px;">${char.name || '无名'}</div>
          <div style="font-size:11px;color:#8b949e;">${char.class_name || ''} Lv.${char.level || 1}</div>
        </div>

        <div style="margin-bottom:10px;">
          <div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:1px;">
            <span style="color:#f85149;">HP</span><span style="color:#8b949e;">${char.hp}/${char.max_hp}</span>
          </div>
          <div style="height:10px;background:#21262d;border-radius:5px;overflow:hidden;">
            <div style="height:100%;width:${hpPct}%;background:${hpColor};transition:width 0.3s;"></div>
          </div>
        </div>

        <div style="margin-bottom:10px;">
          <div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:1px;">
            <span style="color:#58a6ff;">MP</span><span style="color:#8b949e;">${char.mp}/${char.max_mp}</span>
          </div>
          <div style="height:7px;background:#21262d;border-radius:4px;overflow:hidden;">
            <div style="height:100%;width:${mpPct}%;background:#58a6ff;transition:width 0.3s;"></div>
          </div>
        </div>

        <div style="margin-bottom:10px;">
          <div style="display:flex;justify-content:space-between;font-size:10px;margin-bottom:1px;">
            <span style="color:#d29922;">EXP</span><span style="color:#8b949e;">${char.experience}/${char.exp_to_next}</span>
          </div>
          <div style="height:5px;background:#21262d;border-radius:3px;overflow:hidden;">
            <div style="height:100%;width:${expPct}%;background:#d29922;transition:width 0.3s;"></div>
          </div>
        </div>

        <div style="font-size:10px;color:#8b949e;margin-bottom:8px;">
          <div>💪力量${stats.strength||5} 🏃敏捷${stats.agility||5}</div>
          <div>🧠智力${stats.intelligence||5} ❤️体质${stats.vitality||5}</div>
          <div>🍀运气${stats.luck||5}</div>
        </div>

        <div style="margin-bottom:8px;">
          <button onclick="DeathModeUI.showSkillPanel('ai')" style="width:100%;padding:6px;background:#1a3a1a;border:1px solid #3fb950;border-radius:6px;color:#3fb950;cursor:pointer;font-size:11px;">⚔️ 技能管理（AI）</button>
        </div>

        <div style="display:flex;gap:4px;margin-bottom:8px;">
          <button onclick="DeathModeUI.showQuestPanel()" id="dm-quest-btn" style="flex:1;padding:6px;background:#2d1a3a;border:1px solid #a371f7;border-radius:6px;color:#a371f7;cursor:pointer;font-size:11px;">📜 任务</button>
          <button onclick="DeathModeUI.showNewsPanel()" id="dm-news-btn" style="flex:1;padding:6px;background:#3a2d1a;border:1px solid #d29922;border-radius:6px;color:#d29922;cursor:pointer;font-size:11px;">📰 酒馆新闻</button>
        </div>

        <div style="margin-bottom:8px;">
          <div style="font-size:10px;color:#58a6ff;margin-bottom:3px;">装备</div>
          ${eqHtml}
        </div>

        <div style="margin-bottom:8px;">
          <div style="font-size:10px;color:#d29922;margin-bottom:3px;">🎒 背包</div>
          ${invHtml}
        </div>

        <div style="font-size:10px;color:#8b949e;">
          <div>💰 金币: ${char.gold||0}</div>
          <div>📅 第${state.play_time_days||1}天</div>
          <div>⚔️ 击杀: ${state.kill_count||0}</div>
          ${state.in_combat ? '<div style="color:#f85149;">⚠️ 战斗中</div>' : ''}
          ${state.story?.current_location ? `<div>📍 ${state.story.current_location}</div>` : ''}
        </div>

        ${state.in_dungeon && state.dungeon ? this._renderDungeon(state) : this._renderMap(state)}

        ${this._renderParty(state)}

        ${ucHtml}
      `;

      // ── 渲染怪物信息栏 ──
      this._renderEnemiesPanel(state);
    } catch (e) {}
  },

  // ── 新篇章：二次确认 ──
  confirmTransition(force) {
    // force=true 表示结局未达成时主动开启
    const modal = document.createElement('div');
    modal.id = 'dm-confirm-transition';
    modal.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.8);z-index:10000;display:flex;align-items:center;justify-content:center;';

    let title, desc, confirmText, confirmColor;
    if (force) {
      // 主动放弃当前剧情
      title = '⚠️ 主动开启新篇章';
      desc = '当前隐藏结局尚未达成，主动开启将：<br>• 结束当前章节的故事线（不强制完结）<br>• 生成"未完篇章"过渡叙事<br>• 总结本章并传承到下一章<br>• 生成全新的世界故事和隐藏结局<br><br><span style="color:#d29922;">当前未完成的剧情悬念将被保留在章节总结中，但不会再推进。</span>';
      confirmText = '确认开启新篇章';
      confirmColor = 'linear-gradient(135deg,#d29922,#a371f7)';
    } else {
      // 结局已达成
      title = '🏆 开启新篇章';
      desc = '隐藏结局已达成，即将：<br>• 生成结局叙事（本章终章）<br>• 总结本章并传承到下一章<br>• 生成全新的世界故事和隐藏结局<br><br><span style="color:#3fb950;">角色参数保留，新章节将延续前作故事。</span>';
      confirmText = '确认开启新篇章';
      confirmColor = 'linear-gradient(135deg,#a371f7,#6e40c9)';
    }

    modal.innerHTML = `
      <div style="background:#0d1117;border:1px solid #a371f7;border-radius:12px;padding:24px;max-width:440px;width:92%;">
        <div style="color:#a371f7;font-size:15px;font-weight:bold;margin-bottom:12px;">${title}</div>
        <div style="color:#c9d1d9;font-size:12px;line-height:1.7;margin-bottom:20px;">${desc}</div>
        <div style="font-size:11px;color:#8b949e;margin-bottom:16px;padding:8px;background:#161b22;border-radius:6px;">⏱️ 处理时间约30-60秒，期间请勿关闭页面</div>
        <div style="display:flex;gap:12px;">
          <button id="dm-cancel-transition" style="flex:1;padding:10px;background:#21262d;border:1px solid #30363d;border-radius:8px;color:#c9d1d9;cursor:pointer;font-size:13px;">取消</button>
          <button id="dm-confirm-transition-btn" style="flex:1;padding:10px;background:${confirmColor};border:none;border-radius:8px;color:white;cursor:pointer;font-size:13px;font-weight:bold;">${confirmText}</button>
        </div>
      </div>`;
    document.body.appendChild(modal);

    modal.querySelector('#dm-cancel-transition').addEventListener('click', () => modal.remove());
    modal.querySelector('#dm-confirm-transition-btn').addEventListener('click', () => {
      modal.remove();
      this.transitionChapter(force);
    });
  },

  // ── 新篇章：手动触发章节衔接 ──
  async transitionChapter(force) {
    const btn = document.getElementById('dm-new-chapter-btn');
    if (btn) { btn.disabled = true; btn.textContent = '正在生成新章节…（约30-60秒）'; }

    // 进度提示遮罩
    const overlay = document.createElement('div');
    overlay.id = 'dm-transition-overlay';
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);z-index:10000;display:flex;align-items:center;justify-content:center;';
    overlay.innerHTML = `
      <div style="background:#0d1117;border:1px solid #a371f7;border-radius:12px;padding:32px 40px;text-align:center;max-width:380px;">
        <div style="font-size:32px;margin-bottom:12px;">📖</div>
        <div style="color:#a371f7;font-size:15px;font-weight:bold;margin-bottom:8px;">正在开启新篇章…</div>
        <div style="color:#8b949e;font-size:12px;line-height:1.6;">系统正在总结本章故事、生成下一章世界设定和开场叙事，请耐心等待约30-60秒。</div>
        <div style="margin-top:16px;font-size:20px;color:#a371f7;">⏳</div>
      </div>`;
    document.body.appendChild(overlay);

    try {
      const resp = await fetch('/api/death-mode/transition-chapter', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force: !!force }),
      });
      const data = await resp.json();
      overlay.remove();
      if (btn) { btn.disabled = false; btn.textContent = '📖 开启新篇章'; }

      if (!resp.ok || data.error) {
        const errMsg = (data && (data.detail || data.message)) || '章节衔接失败';
        this._showTransitionResult({ error: true, message: errMsg });
        return;
      }

      // 展示衔接结果（结局叙事 + 新章节开场）
      this._showTransitionResult(data);
      // 刷新状态面板和日志（新章节已生成）
      this._renderStatusPanel();
      this._loadAndRenderLog();
    } catch (e) {
      overlay.remove();
      if (btn) { btn.disabled = false; btn.textContent = '📖 开启新篇章'; }
      this._showTransitionResult({ error: true, message: e.message || '网络错误' });
    }
  },

  _showTransitionResult(data) {
    const modal = document.createElement('div');
    modal.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.85);z-index:10000;display:flex;align-items:center;justify-content:center;';

    if (data.error) {
      modal.innerHTML = `
        <div style="background:#0d1117;border:1px solid #f85149;border-radius:12px;padding:28px;max-width:420px;width:90%;">
          <div style="color:#f85149;font-size:16px;font-weight:bold;margin-bottom:12px;">❌ 章节衔接失败</div>
          <div style="color:#c9d1d9;font-size:13px;line-height:1.6;margin-bottom:20px;">${data.message || '未知错误'}</div>
          <button onclick="this.closest('div[style*=fixed]').remove()" style="width:100%;padding:8px;background:#21262d;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;cursor:pointer;">关闭</button>
        </div>`;
      document.body.appendChild(modal);
      return;
    }

    const completedCh = data.completed_chapter || '?';
    const newCh = data.new_chapter || '?';
    const isEndingCompleted = data.is_ending_completed !== false;
    const headerIcon = isEndingCompleted ? '🏆' : '📖';
    const headerLabel = isEndingCompleted ? '第' + completedCh + '章完结' : '第' + completedCh + '章暂别';
    const narrativeLabel = isEndingCompleted ? '📖 结局叙事' : '📖 未完篇章';
    modal.innerHTML = `
      <div style="background:#0d1117;border:1px solid #a371f7;border-radius:12px;padding:24px;max-width:520px;width:92%;max-height:85vh;overflow-y:auto;">
        <div style="text-align:center;margin-bottom:16px;">
          <div style="font-size:28px;margin-bottom:6px;">${headerIcon}</div>
          <div style="color:#a371f7;font-size:14px;font-weight:bold;">${headerLabel}</div>
          <div style="color:#e6edf3;font-size:16px;font-weight:bold;margin-top:4px;">${data.ending_title || '隐藏结局'}</div>
        </div>
        ${data.ending_narrative ? `
          <div style="background:#161b22;border-radius:8px;padding:12px;margin-bottom:16px;border-left:3px solid #a371f7;">
            <div style="color:#a371f7;font-size:11px;margin-bottom:6px;">${narrativeLabel}</div>
            <div style="color:#c9d1d9;font-size:13px;line-height:1.7;white-space:pre-wrap;">${data.ending_narrative}</div>
          </div>` : ''}
        ${data.chapter_summary ? `
          <div style="background:#161b22;border-radius:8px;padding:12px;margin-bottom:16px;border-left:3px solid #58a6ff;">
            <div style="color:#58a6ff;font-size:11px;margin-bottom:6px;">📋 章节总结（传承至下一章）</div>
            <div style="color:#8b949e;font-size:12px;line-height:1.7;white-space:pre-wrap;">${data.chapter_summary}</div>
          </div>` : ''}
        <div style="text-align:center;margin-bottom:16px;padding-top:12px;border-top:1px dashed #30363d;">
          <div style="font-size:28px;margin-bottom:6px;">✨</div>
          <div style="color:#3fb950;font-size:14px;font-weight:bold;">第${newCh}章开始</div>
        </div>
        ${data.new_chapter_narrative ? `
          <div style="background:#161b22;border-radius:8px;padding:12px;margin-bottom:16px;border-left:3px solid #3fb950;">
            <div style="color:#3fb950;font-size:11px;margin-bottom:6px;">🎬 新章节开场</div>
            <div style="color:#c9d1d9;font-size:13px;line-height:1.7;white-space:pre-wrap;">${data.new_chapter_narrative}</div>
          </div>` : ''}
        <button onclick="this.closest('div[style*=fixed]').remove()" style="width:100%;padding:10px;background:#a371f7;border:none;border-radius:8px;color:white;cursor:pointer;font-size:13px;font-weight:bold;">开始新冒险</button>
      </div>`;
    document.body.appendChild(modal);
  },

  // ── 怪物信息栏 ──
  _renderEnemiesPanel(state) {
    const panel = document.getElementById('dm-enemies-panel');
    if (!panel) return;

    const inCombat = state.in_combat;
    const enemies = state.enemies || [];

    if (!inCombat || enemies.length === 0) {
      panel.style.display = 'none';
      return;
    }

    panel.style.display = 'block';

    // 怪物图标映射
    const monsterIcons = {
      slime: '🟢', wolf: '🐺', spider: '🕷️', ghost: '👻', goblin: '👺',
      skeleton: '💀', dragon: '🐉', demon: '😈', element: '⚡', fungus: '🍄',
      bat: '🦇', snake: '🐍', bear: '🐻', troll: '🧌', bandit: '🗡️',
      orc: '🪓', mage: '🧙', knight: '🛡️', boss: '👑', elite: '⭐',
    };
    function getMonsterIcon(enemy) {
      const name = (enemy.name || '').toLowerCase();
      for (const [key, icon] of Object.entries(monsterIcons)) {
        if (name.includes(key)) return icon;
      }
      const type = enemy.type || '';
      if (type === 'boss') return '👑';
      if (type === 'elite') return '⭐';
      return '👹';
    }

    // 品质颜色映射
    function getEnemyColor(enemy) {
      const type = enemy.type || 'normal';
      if (type === 'boss') return '#f85149';
      if (type === 'elite') return '#d29922';
      return '#8b949e';
    }

    // 品质标签映射
    function getEnemyTypeLabel(enemy) {
      const type = enemy.type || 'normal';
      if (type === 'boss') return 'BOSS';
      if (type === 'elite') return '精英';
      return '普通';
    }

    const enemiesHtml = enemies.map(e => {
      const hpPct = e.max_hp > 0 ? Math.max(0, Math.min(100, e.hp / e.max_hp * 100)) : 0;
      const hpColor = hpPct > 60 ? '#f85149' : hpPct > 30 ? '#d29922' : '#484f58';
      const eColor = getEnemyColor(e);
      const eIcon = getMonsterIcon(e);
      const eType = getEnemyTypeLabel(e);
      const isAlive = e.hp > 0;
      const opacity = isAlive ? '1' : '0.4';

      // 属性摘要
      const stats = e.stats || {};
      const eAttack = e.attack_power || (stats.strength || 5) * 2 + (e.bonus || 0);
      const eDefense = e.defense_power || (stats.vitality || 5) * 1.5;
      const eDodge = e.dodge_chance ? `${Math.round(e.dodge_chance*100)}%` : '';

      // 技能列表（如果有）
      const skills = e.skills || [];
      const skillsHtml = skills.length > 0 ? skills.map(s =>
        `<span style="font-size:9px;color:#d29922;padding:1px 3px;background:#1a1a1a;border-radius:2px;margin-right:2px;">${s.name||s}</span>`
      ).join('') : '';

      // 装备（如果有）
      const eEq = e.equipment || [];
      const eEqHtml = eEq.length > 0 ? eEq.map(eq =>
        `<span style="font-size:9px;color:#58a6ff;">${eq.name||''}${eq.bonus?'+'+eq.bonus:''}</span>`
      ).join(' ') : '';

      return `<div style="margin-bottom:8px;padding:6px;background:#161b22;border-radius:6px;border:1px solid ${isAlive ? '#30363d' : '#21262d'};opacity:${opacity};">
        <div style="display:flex;align-items:center;gap:4px;margin-bottom:4px;">
          <span style="font-size:16px;">${eIcon}</span>
          <div style="flex:1;min-width:0;">
            <div style="font-size:11px;font-weight:bold;color:${eColor};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${e.name||'未知'}</div>
            <div style="font-size:9px;color:#484f58;">Lv.${e.level||1} ${eType}</div>
          </div>
        </div>
        <div style="margin-bottom:4px;">
          <div style="display:flex;justify-content:space-between;font-size:9px;margin-bottom:1px;">
            <span style="color:#f85149;">HP</span>
            <span style="color:#8b949e;">${e.hp}/${e.max_hp}</span>
          </div>
          <div style="height:5px;background:#21262d;border-radius:2px;overflow:hidden;">
            <div style="height:100%;width:${hpPct}%;background:${hpColor};transition:width 0.3s;"></div>
          </div>
        </div>
        ${isAlive ? `
        <div style="font-size:9px;color:#8b949e;margin-bottom:2px;">
          <div>⚔️攻击:${eAttack} 🛡️防御:${Math.round(eDefense)}</div>
          ${eDodge ? `<div>🏃闪避:${eDodge}</div>` : ''}
          ${skillsHtml ? `<div style="margin-top:2px;">${skillsHtml}</div>` : ''}
          ${eEqHtml ? `<div style="margin-top:1px;">${eEqHtml}</div>` : ''}
        </div>` : '<div style="font-size:9px;color:#484f58;text-align:center;">已击败</div>'}
      </div>`;
    }).join('');

    panel.innerHTML = `
      <div style="padding:4px 0 6px;text-align:center;">
        <span style="font-size:11px;color:#f85149;font-weight:600;">⚔️ 敌人</span>
        <span style="font-size:9px;color:#484f58;margin-left:4px;">${enemies.length}只</span>
      </div>
      ${enemiesHtml}
    `;
  },

  async _loadAndRenderLog() {
    const container = document.getElementById('dm-log-container');
    const countEl = document.getElementById('dm-log-count');
    if (!container) return;

    try {
      const resp = await fetch('/api/death-mode/log?limit=100');
      const data = await resp.json();
      if (data.error) {
        container.innerHTML = `<div style="text-align:center;color:#484f58;padding:40px 0;">暂无游戏</div>`;
        return;
      }

      const logs = data.logs || [];
      if (countEl) countEl.textContent = `共 ${data.total} 条记录`;

      // 用 data.total 判断是否有新日志（logs.length 受 limit 限制，超过100条后永远相等）
      if (data.total === this._lastLogTotal && container.children.length > 0) return;
      this._lastLogTotal = data.total;

      if (logs.length === 0) {
        container.innerHTML = `
          <div style="text-align:center;padding:60px 20px;">
            <div style="font-size:32px;margin-bottom:12px;">📜</div>
            <div style="color:#8b949e;font-size:14px;">还没有行动记录</div>
            <div style="color:#484f58;font-size:12px;margin-top:8px;">在主程序中对话开始冒险</div>
          </div>`;
        return;
      }

      container.innerHTML = logs.map(log => this._renderLogEntry(log)).join('');

      // 滚动到顶部（最新记录）
      container.scrollTop = 0;
    } catch (e) {
      container.innerHTML = `<div style="text-align:center;color:#f85149;padding:40px 0;">加载失败</div>`;
    }
  },

  // 将日志文本中的"你"替换为用户名
  _replaceYou(text) {
    if (!text) return text;
    const name = this._userName || '用户';
    // "你们" → "用户名们"（先处理，避免被后续拆散）
    // 单独"你" → 用户名
    return text
      .replace(/你们/g, name + '们')
      .replace(/你/g, name);
  },

  _renderLogEntry(log) {
    const type = log.type || 'action';
    const d = log.data || {};
    const time = log.time ? new Date(log.time).toLocaleTimeString('zh-CN', {hour:'2-digit',minute:'2-digit'}) : '';
    const day = log.day || 1;

    // 类型图标和颜色
    const typeConfig = {
      game_start:   { icon: '⚔️', color: '#58a6ff', label: '冒险开始' },
      scene:        { icon: '📖', color: '#8b949e', label: '场景' },
      action:       { icon: '🎯', color: '#c9d1d9', label: '行动' },
      combat_round: { icon: '⚔️', color: '#d29922', label: '战斗' },
      death_pending:{ icon: '☠️', color: '#f85149', label: '生死' },
      move:         { icon: '🗺️', color: '#3fb950', label: '移动' },
      npc_interact: { icon: '💬', color: '#d29922', label: 'NPC交互' },
      life_skill:   { icon: '🧰', color: '#b48cff', label: '生活技能' },
    };
    const cfg = typeConfig[type] || typeConfig.action;

    // 构建内容
    let content = '';

    if (type === 'game_start') {
      content = `<div style="color:#58a6ff;font-weight:bold;">${d.character_name} 开始了冒险！</div>
        <div style="font-size:12px;color:#8b949e;">职业：${d.class_name} · 世界：${d.world_name}</div>`;
    }
    else if (type === 'scene') {
      content = `<div style="color:#c9d1d9;font-size:13px;line-height:1.6;">${this._replaceYou(d.description || '')}</div>
        ${d.location ? `<div style="font-size:11px;color:#8b949e;margin-top:4px;">📍 ${d.location}</div>` : ''}
        ${d.choices ? `<div style="margin-top:6px;">${d.choices.map(c => {
          const riskColor = {low:'#3fb950',medium:'#d29922',high:'#f85149'}[c.risk]||'#8b949e';
          return `<div style="font-size:11px;color:#8b949e;padding:2px 0;">→ ${c.text} <span style="color:${riskColor};font-size:10px;">${c.risk||''}</span></div>`;
        }).join('')}</div>` : ''}`;
    }
    else if (type === 'action' || type === 'combat_round' || type === 'death_pending') {
      const actionLabel = d.action || (type === 'combat_round' ? '战斗回合' : (type === 'death_pending' ? '生死抉择' : '未知行动'));
      const outcome = d.outcome || '';

      // death_pending 类型：显示临终遗言
      if (type === 'death_pending') {
        content = `<div style="color:#f85149;font-size:13px;font-weight:600;">☠️ ${d.name || '角色'} 阵亡</div>
          <div style="font-size:12px;color:#8b949e;margin-top:2px;">死因：${this._replaceYou(d.cause || '')}</div>
          ${d.last_words ? `<div style="font-size:12px;color:#d29922;font-style:italic;margin-top:4px;padding:6px;background:#2d0d0d;border-radius:4px;">「${this._replaceYou(d.last_words)}」</div>` : ''}`;
      }

      // 战斗结果
      let combatHtml = '';
      if (d.combat) {
        if (d.combat.victory) {
          combatHtml = `<div style="padding:6px 8px;background:#0d2818;border-radius:4px;margin-top:4px;">
            <span style="color:#3fb950;font-size:12px;">⚔️ 胜利！</span>
            ${d.combat.enemy_names?.length ? `<span style="font-size:11px;color:#8b949e;">击败 ${d.combat.enemy_names.join('、')}</span>` : ''}
          </div>`;
        } else if (d.combat.combat_log?.length) {
          // 按轮次分行显示多回合战斗（[第N轮] 开头）
          const logText = this._replaceYou(d.combat.combat_log.join(''));
          const roundsHtml = d.combat.combat_log.map((rl, idx) => {
            const trimmed = this._replaceYou(rl).trim();
            // 提取轮次标记
            const m = trimmed.match(/^\[第(\d+)轮\]/);
            if (m) {
              const content = trimmed.replace(/^\[第\d+轮\]\s*/, '');
              return `<div style="font-size:11px;color:#8b949e;margin-top:1px;"><span style="color:#d29922;margin-right:3px;">⚔️ 第${m[1]}轮</span>${content}</div>`;
            }
            return `<div style="font-size:11px;color:#8b949e;margin-top:1px;">${trimmed}</div>`;
          }).join('');
          combatHtml = `<div style="padding:6px 8px;background:#161b22;border-radius:4px;margin-top:4px;max-height:120px;overflow-y:auto;">${roundsHtml}</div>`;
        }
      }

      // 奖励
      let rewardHtml = '';
      if (d.exp_gained || d.gold_gained) {
        rewardHtml = `<div style="font-size:11px;color:#d29922;margin-top:2px;">`;
        if (d.exp_gained) rewardHtml += `经验+${d.exp_gained} `;
        if (d.gold_gained) rewardHtml += `金币+${d.gold_gained}`;
        rewardHtml += `</div>`;
      }

      // 升级
      let levelHtml = '';
      if (d.leveled_up) {
        levelHtml = `<div style="font-size:12px;color:#58a6ff;font-weight:bold;margin-top:2px;">🎉 升级到 Lv.${d.new_level}！</div>`;
      }

      // 装备掉落
      let dropHtml = '';
      if (d.drops?.length) {
        dropHtml = `<div style="font-size:11px;margin-top:2px;">${d.drops.map(drop =>
          `<span style="color:${drop.color || '#c9d1d9'};">🎁 ${drop.name}（${drop.rarity_name || '普通'}）</span>`
        ).join(' ')}</div>`;
      }

      // 购买/交易获得的装备
      let tradeHtml = '';
      if (d.items_equipped?.length) {
        tradeHtml = `<div style="font-size:11px;margin-top:2px;">${d.items_equipped.map(ie =>
          `<span style="color:#3fb950;">🗡️ 获得 ${ie.equipped}${ie.replaced ? '（替换 ' + ie.replaced + '）' : ''}</span>`
        ).join(' ')}</div>`;
      }
      if (d.gold_spent) {
        tradeHtml += `<div style="font-size:11px;color:#f0883e;margin-top:2px;">💰 花费 ${d.gold_spent} 金币</div>`;
      }
      if (d.hp_change) {
        const hpColor = d.hp_change > 0 ? '#3fb950' : '#f85149';
        const hpSign = d.hp_change > 0 ? '+' : '';
        tradeHtml += `<div style="font-size:11px;color:${hpColor};margin-top:2px;">❤️ HP${hpSign}${d.hp_change}</div>`;
      }
      if (d.mp_change) {
        const mpColor = d.mp_change > 0 ? '#58a6ff' : '#f85149';
        const mpSign = d.mp_change > 0 ? '+' : '';
        tradeHtml += `<div style="font-size:11px;color:${mpColor};margin-top:2px;">💧 MP${mpSign}${d.mp_change}</div>`;
      }
      // 用户角色（同伴）的 HP/MP 变化
      const uName = this._userName || '用户';
      if (d.user_hp_change) {
        const hpColor = d.user_hp_change > 0 ? '#3fb950' : '#f85149';
        const hpSign = d.user_hp_change > 0 ? '+' : '';
        tradeHtml += `<div style="font-size:11px;color:${hpColor};margin-top:2px;">👤 ${uName} ❤️ HP${hpSign}${d.user_hp_change}</div>`;
      }
      if (d.user_mp_change) {
        const mpColor = d.user_mp_change > 0 ? '#58a6ff' : '#f85149';
        const mpSign = d.user_mp_change > 0 ? '+' : '';
        tradeHtml += `<div style="font-size:11px;color:${mpColor};margin-top:2px;">👤 ${uName} 💧 MP${mpSign}${d.user_mp_change}</div>`;
      }

      // 死亡
      let deathHtml = '';
      if (d.character_died) {
        deathHtml = `<div style="padding:8px;background:#2d0d0d;border:1px solid #f85149;border-radius:6px;margin-top:6px;">
          <div style="color:#f85149;font-weight:bold;">☠️ 角色阵亡</div>
          <div style="font-size:12px;color:#8b949e;">${this._replaceYou(d.death_description || '')}</div>
        </div>`;
      }

      if (!content) {
        content = `
          <div style="color:#c9d1d9;font-size:13px;font-weight:600;">${actionLabel}</div>
          ${d.narrative ? `<div style="font-size:12px;color:#8b949e;line-height:1.5;margin-top:2px;">${this._replaceYou(d.narrative)}</div>` : ''}
          ${combatHtml}${rewardHtml}${levelHtml}${dropHtml}${tradeHtml}${deathHtml}`;
      }
    }
    else if (type === 'move') {
      content = `<div style="color:#3fb950;">🗺️ 从 ${d.from} 前往 ${d.to}</div>
        <div style="font-size:11px;color:#8b949e;">危险等级：${'★'.repeat(d.danger_level || 1)}</div>`;
    }
    else if (type === 'npc_interact') {
      content = `<div style="color:#d29922;">💬 与 ${d.npc_name} 交互（${d.interaction}）</div>
        ${d.message ? `<div style="font-size:12px;color:#8b949e;margin-top:2px;">${this._replaceYou(d.message)}</div>` : ''}`;
    }
    else if (type === 'life_skill') {
      content = `<div style="color:#c9d1d9;font-size:13px;font-weight:600;">${d.skill || '生活技能'}</div>
        <div style="font-size:12px;color:#8b949e;line-height:1.5;margin-top:2px;">${this._replaceYou(d.action || '')}</div>
        ${d.detail ? `<div style="font-size:11px;color:#484f58;margin-top:4px;display:flex;flex-wrap:wrap;gap:3px 10px;">${Object.entries(d.detail).map(([k, v]) => {
          const str = String(v);
          // 短值（评价/数量等）做成小标签，长文本（评语/效果）整行显示
          const isLong = str.length > 12;
          return isLong
            ? `<div style="flex:1 1 100%;color:#8b949e;line-height:1.5;">${k}：${this._replaceYou(str)}</div>`
            : `<span style="color:#8b949e;">${k}：<span style="color:#c9d1d9;">${this._replaceYou(str)}</span></span>`;
        }).join('')}</div>` : ''}`;
    }

    return `
      <div style="padding:10px 12px;margin-bottom:8px;background:#161b22;border-radius:8px;border-left:3px solid ${cfg.color};">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
          <span style="font-size:12px;color:${cfg.color};">${cfg.icon} ${cfg.label}</span>
          <span style="font-size:10px;color:#484f58;">第${day}天 ${time}</span>
        </div>
        ${content}
      </div>
    `;
  },

  // ── 死亡名人堂 ──────────────────────────────────────

  async showHall() {
    try {
      const resp = await fetch('/api/death-mode/hall');
      const data = await resp.json();
      const hall = data.hall || [];

      const overlay = document.createElement('div');
      overlay.id = 'death-hall-overlay';
      overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.85);z-index:9999;display:flex;align-items:center;justify-content:center;';

      overlay.innerHTML = `
        <div style="background:#0d1117;border:1px solid #30363d;border-radius:16px;padding:32px;max-width:560px;width:90%;max-height:80vh;overflow-y:auto;color:#c9d1d9;">
          <h2 style="margin:0 0 8px;color:#f85149;">⚰️ 死亡名人堂</h2>
          <p style="color:#8b949e;font-size:13px;margin:0 0 24px;">那些在冒险中倒下的勇者们...</p>
          ${hall.length === 0 ? '<div style="text-align:center;padding:40px;color:#8b949e;">还没有勇者阵亡</div>' :
            hall.slice().reverse().map(h => `
              <div style="padding:12px;background:#161b22;border:1px solid #30363d;border-radius:8px;margin-bottom:8px;">
                <div style="display:flex;justify-content:space-between;align-items:center;">
                  <div>
                    <span style="font-size:20px;">${h.class_icon||'⚔️'}</span>
                    <span style="font-weight:bold;color:#c9d1d9;margin-left:4px;">${h.name}</span>
                    <span style="font-size:12px;color:#8b949e;margin-left:8px;">${h.class_name} Lv.${h.level}</span>
                  </div>
                  <div style="font-size:11px;color:#8b949e;">${h.died_at?.split('T')[0]||''}</div>
                </div>
                <div style="font-size:12px;color:#8b949e;margin-top:4px;">生存${h.play_time_days}天 · 击杀${h.kill_count} · 死因：${h.death_cause}</div>
                <div style="font-size:12px;color:#c9d1d9;margin-top:4px;font-style:italic;">${h.death_description||''}</div>
              </div>
            `).join('')
          }
          <div style="display:flex;gap:12px;margin-top:24px;">
            <button id="dh-close" style="flex:1;padding:10px;background:#21262d;border:1px solid #30363d;border-radius:8px;color:#c9d1d9;cursor:pointer;font-size:14px;">关闭</button>
            <button id="dh-restart" style="flex:1;padding:10px;background:#da3633;border:none;border-radius:8px;color:white;cursor:pointer;font-size:14px;font-weight:bold;">创建新角色</button>
          </div>
        </div>
      `;

      document.body.appendChild(overlay);
      overlay.querySelector('#dh-close').addEventListener('click', () => overlay.remove());
      overlay.querySelector('#dh-restart').addEventListener('click', () => { overlay.remove(); this.showCreatePanel(); });
    } catch (e) { alert('加载名人堂失败: ' + e.message); }
  },

  // ── 背包交互 ──────────────────────────────────────

  async _equipFromInv(itemName, target) {
    try {
      const resp = await fetch('/api/death-mode/equip-shared', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_name: itemName, target: target }),
      });
      const data = await resp.json();
      if (data.error) { alert(data.message || '穿戴失败'); return; }
      this._renderStatusPanel();
    } catch (e) { alert('穿戴失败: ' + e.message); }
  },

  async _sellFromInv(itemName, price) {
    if (!confirm(`出售 ${itemName} 获得 ${price} 金币？`)) return;
    try {
      const resp = await fetch('/api/death-mode/sell-shared', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_name: itemName }),
      });
      const data = await resp.json();
      if (data.error) { alert(data.message || '出售失败'); return; }
      this._renderStatusPanel();
    } catch (e) { alert('出售失败: ' + e.message); }
  },

  async _unequip(itemName, target) {
    try {
      const resp = await fetch('/api/death-mode/unequip-shared', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_name: itemName, target: target }),
      });
      const data = await resp.json();
      if (data.error) { alert(data.message || '卸下失败'); return; }
      this._renderStatusPanel();
    } catch (e) { alert('卸下失败: ' + e.message); }
  },

  // ── 装备槽位渲染 ──────────────────────────────────

  _getItemSlotIcon(item) {
    const slotIcons = { main_hand: '🗡️', off_hand: '🛡️', ranged: '🏹', outfit: '👕' };
    const slot = item.slot || this._guessItemSlot(item);
    return slotIcons[slot] || '📦';
  },

  _guessItemSlot(item) {
    if (item.type === 'outfit') return 'outfit';
    const subtype = item.subtype || 'one_handed';
    const slotMap = { one_handed: 'main_hand', two_handed: 'main_hand', ranged: 'ranged', wand: 'ranged', shield: 'off_hand', off_hand: 'off_hand' };
    return slotMap[subtype] || 'main_hand';
  },

  _renderEquipmentSlots(character, owner) {
    const equipment = character.equipment || [];
    // 4个槽位定义
    const slots = [
      { id: 'main_hand', label: '主手', icon: '🗡️', empty: '无武器' },
      { id: 'off_hand', label: '副手', icon: '🛡️', empty: '无' },
      { id: 'ranged', label: '远程', icon: '🏹', empty: '无' },
      { id: 'outfit', label: '穿着', icon: '👕', empty: '无' },
    ];

    // 按槽位查找装备
    function getBySlot(id) {
      for (const eq of equipment) {
        const slot = eq.slot || 'main_hand';
        if (slot === id) return eq;
      }
      return null;
    }

    return slots.map(slot => {
      const eq = getBySlot(slot.id);
      if (!eq) {
        return `<div style="font-size:10px;color:#484f58;display:flex;align-items:center;gap:4px;margin-bottom:2px;padding:2px 4px;background:#0d1117;border-radius:3px;border:1px dashed #21262d;">
          <span>${slot.icon}</span>
          <span>${slot.label}：${slot.empty}</span>
        </div>`;
      }
      // 属性描述
      let bonusText = '';
      if (eq.bonus) {
        const dt = eq.damage_type || 'physical';
        const bonusLabel = dt === 'magic' ? '法' : dt === 'ranged' ? '远' : dt === 'defense' ? '防' : '攻';
        bonusText += `${bonusLabel}+${eq.bonus}`;
      }
      if (eq.stat_bonus) {
        const sb = eq.stat_bonus;
        const statLabels = {strength:'力',agility:'敏',intelligence:'智',vitality:'体',luck:'运'};
        const sbParts = Object.entries(sb).map(([k,v]) => `${statLabels[k]||k}+${v}`);
        if (sbParts.length > 0) bonusText += (bonusText ? ' ' : '') + sbParts.join(' ');
      }
      const bonusHtml = bonusText ? `<span style="font-size:8px;color:#3fb950;margin-left:3px;">${bonusText}</span>` : '';
      // 重量提示
      let weightHtml = '';
      if (eq.weight) {
        const str = character.stats?.strength || 5;
        const overload = str < eq.weight;
        weightHtml = `<span style="font-size:8px;color:${overload ? '#f85149' : '#484f58'};margin-left:2px;">⚖️${eq.weight}</span>`;
      }
      const subtypeText = eq.subtype ? (eq.subtype === 'one_handed' ? '单手' : eq.subtype === 'two_handed' ? '双手' : eq.subtype === 'ranged' ? '弓' : eq.subtype === 'wand' ? '法杖' : eq.subtype === 'shield' ? '盾牌' : eq.subtype === 'off_hand' ? '副手' : '') : '';
      return `<div style="font-size:10px;color:${eq.color || '#c9d1d9'};display:flex;justify-content:space-between;align-items:center;margin-bottom:2px;padding:2px 4px;background:#161b22;border-radius:3px;border:1px solid #21262d;">
        <span style="display:flex;align-items:center;gap:3px;min-width:0;overflow:hidden;">
          <span>${slot.icon}</span>
          <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${eq.name}</span>
          <span style="font-size:8px;color:#484f58;">${subtypeText}</span>
          ${bonusHtml}
          ${weightHtml}
        </span>
        <button onclick="DeathModeUI._unequip('${eq.name}','${owner}')" style="font-size:8px;padding:1px 3px;background:#21262d;border:1px solid #30363d;border-radius:2px;color:#8b949e;cursor:pointer;flex-shrink:0;">卸下</button>
      </div>`;
    }).join('');
  },

  // ── 地图可视化 ──────────────────────────────────────

  _renderMap(state) {
    const md = state.map_display;
    if (!md || !md.current) return '';

    const current = md.current;
    const gridSize = md.grid_size || 10;

    // 是否可移动（非战斗、非地下城）
    const canMove = !state.in_combat && !state.in_dungeon;

    // 8方向 → 3x3 grid 位置
    const dirMap = {
      '西北': '0,0', '北': '0,1', '东北': '0,2',
      '西': '1,0', '中': '1,1', '东': '1,2',
      '西南': '2,0', '南': '2,1', '东南': '2,2',
    };

    // 构建3x3网格
    const grid = {};
    for (let r = 0; r < 3; r++) {
      for (let c = 0; c < 3; c++) {
        grid[`${r},${c}`] = null;
      }
    }
    grid['1,1'] = { type: 'center', name: current.name };

    // 填入相邻区域（含空白格子、对角线）
    for (const adj of md.adjacent) {
      const pos = dirMap[adj.direction];
      if (pos) {
        const isBlank = !adj.region_id;
        grid[pos] = {
          type: isBlank ? 'blank' : 'adjacent',
          direction: adj.direction,
          name: adj.name,
          explored: adj.explored,
          danger: adj.danger_level,
          regionType: adj.region_type,
          regionId: adj.region_id,
          canMoveDir: adj.can_move !== false,
        };
      }
    }

    // 方向标签箭头
    const dirArrow = { '北': '↑', '东北': '↗', '东': '→', '东南': '↘', '南': '↓', '西南': '↙', '西': '←', '西北': '↖' };

    // 危险色
    function dangerColor(d) {
      if (d >= 4) return '#f85149';
      if (d >= 3) return '#d29922';
      if (d >= 2) return '#58a6ff';
      return '#3fb950';
    }

    // 区域类型图标
    function regionIcon(type) {
      const icons = { town: '🏘️', wild: '🌲', dungeon: '🕳️', boss_lair: '👑', secret: '✨', unknown: '❓' };
      return icons[type] || '📍';
    }

    let cells = '';
    for (let r = 0; r < 3; r++) {
      for (let c = 0; c < 3; c++) {
        const cell = grid[`${r},${c}`];
        if (!cell) {
          cells += `<div style="flex:1 0 0;aspect-ratio:1;display:flex;align-items:center;justify-content:center;font-size:8px;color:#21262d;">·</div>`;
          continue;
        }
        if (cell.type === 'center') {
          cells += `<div style="flex:1 0 0;aspect-ratio:1;display:flex;flex-direction:column;align-items:center;justify-content:center;background:#1a3a1a;border-radius:6px;border:1px solid #3fb950;">
            <span style="font-size:14px;">📍</span>
            <span style="font-size:7px;color:#3fb950;font-weight:bold;text-align:center;line-height:1.2;max-width:100%;word-break:break-all;">${cell.name}</span>
          </div>`;
        } else if (!cell.canMoveDir) {
          // 对角线方向（显示但不可直接到达）
          const arrow = dirArrow[cell.direction] || '?';
          const color = cell.explored ? dangerColor(cell.danger) : '#484f58';
          const icon = cell.explored ? regionIcon(cell.regionType) : '🌫️';
          const name = cell.explored ? cell.name : (cell.type === 'blank' ? '未探索' : '未知');
          cells += `<div style="flex:1 0 0;aspect-ratio:1;display:flex;flex-direction:column;align-items:center;justify-content:center;border-radius:4px;background:#0d1117;border:1px solid #21262d;opacity:0.5;">
            <span style="font-size:7px;color:#484f58;">${arrow}</span>
            <span style="font-size:12px;margin:1px 0;opacity:0.6;">${icon}</span>
            <span style="font-size:6px;color:#484f58;text-align:center;line-height:1.1;max-width:100%;word-break:break-all;padding:0 1px;">${name}</span>
          </div>`;
        } else if (cell.type === 'blank') {
          // 空白格子（可前往探索）
          if (canMove) {
            cells += `<div onclick="DeathModeUI.moveByDirection('${cell.direction}')" style="flex:1 0 0;aspect-ratio:1;display:flex;flex-direction:column;align-items:center;justify-content:center;border-radius:4px;background:#0d1117;border:1px dashed #30363d;cursor:pointer;" onmouseover="this.style.background='#161b22';" onmouseout="this.style.background='#0d1117';">
              <span style="font-size:8px;color:#58a6ff;font-weight:bold;">${dirArrow[cell.direction]} ${cell.direction}</span>
              <span style="font-size:14px;margin:1px 0;">🌫️</span>
              <span style="font-size:6px;color:#484f58;text-align:center;">可探索</span>
            </div>`;
          } else {
            cells += `<div style="flex:1 0 0;aspect-ratio:1;display:flex;flex-direction:column;align-items:center;justify-content:center;border-radius:4px;background:#0d1117;border:1px dashed #30363d;opacity:0.4;">
              <span style="font-size:8px;color:#58a6ff;font-weight:bold;">${dirArrow[cell.direction]} ${cell.direction}</span>
              <span style="font-size:14px;margin:1px 0;">🌫️</span>
              <span style="font-size:6px;color:#484f58;text-align:center;">🔒</span>
            </div>`;
          }
        } else {
          // 已有区域（可移动）
          const arrow = dirArrow[cell.direction] || '?';
          const color = cell.explored ? dangerColor(cell.danger) : '#484f58';
          const icon = cell.explored ? regionIcon(cell.regionType) : '❓';
          const name = cell.explored ? cell.name : '未知';
          if (canMove) {
            cells += `<div onclick="DeathModeUI.moveByDirection('${cell.direction}')" style="flex:1 0 0;aspect-ratio:1;display:flex;flex-direction:column;align-items:center;justify-content:center;border-radius:4px;background:${cell.explored ? '#161b22' : '#0d1117'};border:1px solid ${cell.explored ? '#21262d' : '#161b22'};cursor:pointer;" onmouseover="this.style.borderColor='#58a6ff';" onmouseout="this.style.borderColor='${cell.explored ? '#21262d' : '#161b22'}';">
              <span style="font-size:8px;color:${color};font-weight:bold;">${arrow} ${cell.direction}</span>
              <span style="font-size:14px;margin:1px 0;">${icon}</span>
              <span style="font-size:7px;color:${color};text-align:center;line-height:1.2;max-width:100%;word-break:break-all;padding:0 1px;">${name}</span>
            </div>`;
          } else {
            cells += `<div style="flex:1 0 0;aspect-ratio:1;display:flex;flex-direction:column;align-items:center;justify-content:center;border-radius:4px;background:${cell.explored ? '#161b22' : '#0d1117'};border:1px solid ${cell.explored ? '#21262d' : '#161b22'};opacity:0.4;">
              <span style="font-size:8px;color:${color};font-weight:bold;">${arrow} ${cell.direction}</span>
              <span style="font-size:14px;margin:1px 0;">${icon}</span>
              <span style="font-size:7px;color:${color};text-align:center;line-height:1.2;max-width:100%;word-break:break-all;padding:0 1px;">🔒</span>
            </div>`;
          }
        }
      }
    }

    // 坐标显示
    const coord = `(${current.x},${current.y})`;
    const moveHint = canMove ? '点击相邻区域移动' : '🔒 战斗/地下城中无法移动';

    return `
      <div style="margin-top:10px;padding-top:10px;border-top:1px dashed #30363d;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">
          <span style="font-size:10px;color:#58a6ff;">🗺️ 地图 ${coord}</span>
          <span onclick="DeathModeUI.showFullMap()" style="font-size:8px;color:#58a6ff;cursor:pointer;text-decoration:underline;">🌐 全图</span>
        </div>
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:2px;width:100%;">
          ${cells}
        </div>
        <div style="font-size:7px;color:#484f58;text-align:center;margin-top:4px;">
          ${current.name} · 危险度${'★'.repeat(current.danger_level) || '安全'}<br>${moveHint}
        </div>
      </div>`;
  },

  async showFullMap() {
    // 从 API 获取最新数据，确保地图信息是最新的
    let md = this._state?.map_display;
    try {
      const resp = await fetch('/api/death-mode/state');
      const freshState = await resp.json();
      if (freshState.active && freshState.map_display) {
        md = freshState.map_display;
        this._state = freshState; // 同步缓存
      }
    } catch (e) {
      // 使用已有缓存
    }
    if (!md || !md.current) return;

    const gridSize = md.grid_size || 10;
    const allRegions = md.all_regions || [];
    const current = md.current;

    // 构建坐标→区域映射
    const regionMap = {};
    for (const r of allRegions) {
      regionMap[`${r.x},${r.y}`] = r;
    }

    // 区域类型图标
    function regionIcon(type) {
      const icons = { town: '🏘️', wild: '🌲', dungeon: '🕳️', boss_lair: '👑', secret: '✨', unknown: '❓' };
      return icons[type] || '📍';
    }

    // 危险色
    function dangerColor(d) {
      if (d >= 4) return '#f85149';
      if (d >= 3) return '#d29922';
      if (d >= 2) return '#58a6ff';
      return '#3fb950';
    }

    // 全图始终显示完整 gridSize×gridSize 网格
    let minX = 0, maxX = gridSize - 1, minY = 0, maxY = gridSize - 1;

    // 生成网格HTML
    let gridHtml = '';
    const cellSize = 40;
    for (let y = minY; y <= maxY; y++) {
      for (let x = minX; x <= maxX; x++) {
        const r = regionMap[`${x},${y}`];
        const isCurrent = current.x === x && current.y === y;
        if (isCurrent) {
          gridHtml += `<div style="width:${cellSize}px;height:${cellSize}px;display:flex;flex-direction:column;align-items:center;justify-content:center;background:#1a3a1a;border-radius:4px;border:2px solid #3fb950;">
            <span style="font-size:16px;">📍</span>
            <span style="font-size:7px;color:#3fb950;font-weight:bold;text-align:center;max-width:36px;word-break:break-all;">${current.name}</span>
          </div>`;
        } else if (r) {
          if (r.explored) {
            // 已探索：显示图标+名称+危险色边框
            const color = dangerColor(r.danger_level);
            const icon = regionIcon(r.region_type);
            gridHtml += `<div style="width:${cellSize}px;height:${cellSize}px;display:flex;flex-direction:column;align-items:center;justify-content:center;background:#161b22;border-radius:4px;border:1px solid ${color}40;">
              <span style="font-size:14px;">${icon}</span>
              <span style="font-size:6px;color:${color};text-align:center;max-width:36px;word-break:break-all;line-height:1.1;">${r.name}</span>
            </div>`;
          } else {
            // 未探索（已知存在但未去过）：显示❓+暗色
            gridHtml += `<div style="width:${cellSize}px;height:${cellSize}px;display:flex;flex-direction:column;align-items:center;justify-content:center;background:#0d1117;border-radius:4px;border:1px dashed #30363d;opacity:0.6;">
              <span style="font-size:14px;">❓</span>
              <span style="font-size:6px;color:#484f58;text-align:center;">未知</span>
            </div>`;
          }
        } else {
          gridHtml += `<div style="width:${cellSize}px;height:${cellSize}px;display:flex;align-items:center;justify-content:center;background:#0d1117;border-radius:4px;border:1px solid #161b22;">
            <span style="font-size:8px;color:#21262d;">·</span>
          </div>`;
        }
      }
    }

    const gridCols = maxX - minX + 1;

    // 创建或更新弹窗
    let overlay = document.getElementById('fullmap-overlay');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'fullmap-overlay';
      overlay.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.8);z-index:9999;display:flex;align-items:center;justify-content:center;';
      overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
      document.body.appendChild(overlay);
    }

    overlay.innerHTML = `
      <div style="background:#0d1117;border:1px solid #30363d;border-radius:12px;padding:16px;max-width:90vw;max-height:90vh;overflow:auto;position:relative;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
          <span style="font-size:14px;color:#58a6ff;">🗺️ 全地图 (${gridSize}×${gridSize})</span>
          <span onclick="document.getElementById('fullmap-overlay').remove()" style="font-size:18px;color:#8b949e;cursor:pointer;">✕</span>
        </div>
        <div style="display:grid;grid-template-columns:repeat(${gridCols},auto);gap:2px;justify-content:center;">
          ${gridHtml}
        </div>
        <div style="font-size:8px;color:#484f58;margin-top:8px;text-align:center;">
          📍当前位置 · ${current.name} (${current.x},${current.y})
        </div>
        <div style="font-size:7px;color:#484f58;margin-top:4px;text-align:center;display:flex;gap:8px;justify-content:center;flex-wrap:wrap;">
          <span>📍 当前</span>
          <span>🏘️🌲🕳️ 已探索</span>
          <span>❓ 已知未探索</span>
          <span>· 未发现</span>
        </div>
      </div>`;
  },

  async moveByDirection(direction) {
    try {
      const resp = await fetch('/api/death-mode/move-direction', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({direction: direction}),
      });
      const data = await resp.json();
      if (data.error) {
        alert(data.message || data.error);
        return;
      }
      await this._renderStatusPanel();
    } catch(e) { console.error('move direction:', e); }
  },

  // ── 地下城探索 UI ──────────────────────────────────

  _renderDungeon(state) {
    const dg = state.dungeon;
    if (!dg) return '';
    const room = dg.current_room;
    if (!room) return '';

    const adjacentHtml = (dg.adjacent_rooms || []).map(r => {
      const icon = r.is_boss ? '👑' : (r.visited ? '🚪' : '❓');
      const status = r.cleared ? '✅' : '';
      const name = r.visited ? r.name : '未知';
      return `<button onclick="DeathModeUI.moveToDungeonRoom('${r.room_id}')"
        style="display:flex;flex-direction:column;align-items:center;padding:6px 8px;background:#161b22;border:1px solid #30363d;border-radius:6px;cursor:pointer;color:#c9d1d9;font-size:9px;min-width:60px;flex:1;">
        <span style="font-size:16px;">${icon}</span>
        <span style="margin-top:2px;text-align:center;">${name}</span>
        ${status}
      </button>`;
    }).join('');

    const enemiesHtml = room.has_enemies ? `
      <div style="margin-top:6px;padding:4px 6px;background:#2a1515;border-radius:4px;border:1px solid #f85149;">
        <div style="font-size:9px;color:#f85149;">⚠️ ${room.enemy_count}个敌人</div>
      </div>` : '';
    const hazardsHtml = room.has_hazards ? `
      <div style="margin-top:4px;padding:4px 6px;background:#2a2015;border-radius:4px;border:1px solid #d29922;">
        <div style="font-size:9px;color:#d29922;">⚠️ 暗藏机关</div>
      </div>` : '';
    const lootHtml = room.has_loot ? `
      <div style="margin-top:4px;padding:4px 6px;background:#15201a;border-radius:4px;border:1px solid #3fb950;">
        <div style="font-size:9px;color:#3fb950;">💰 有战利品</div>
      </div>` : '';
    const bossBadge = room.is_boss ? '<span style="color:#f85149;font-size:9px;">👑 BOSS</span>' : '';
    const clearedBadge = dg.boss_defeated ? '<span style="color:#3fb950;font-size:9px;">✅ 通关</span>' : '';

    return `
      <div style="margin-top:10px;padding-top:10px;border-top:1px dashed #30363d;">
        <div style="font-size:10px;color:#d29922;margin-bottom:4px;text-align:center;">🕳️ ${dg.dungeon_name || '地下城'}</div>
        ${dg.faction_ecology ? `<div style="font-size:8px;color:#8b949e;text-align:center;margin-bottom:4px;font-style:italic;">${dg.faction_ecology}</div>` : ''}
        <div style="font-size:8px;color:#484f58;text-align:center;margin-bottom:6px;">已探索 ${dg.visited_count}/${dg.total_rooms} ${clearedBadge}</div>
        <div style="padding:6px;background:#161b22;border-radius:6px;border:1px solid #30363d;">
          <div style="font-size:10px;color:#58a6ff;font-weight:bold;margin-bottom:2px;">📍 ${room.name} ${bossBadge}</div>
          <div style="font-size:8px;color:#8b949e;line-height:1.4;">${room.description || ''}</div>
          ${enemiesHtml}${hazardsHtml}${lootHtml}
        </div>
        ${adjacentHtml ? `
          <div style="margin-top:6px;">
            <div style="font-size:8px;color:#484f58;margin-bottom:3px;">可达房间：</div>
            <div style="display:flex;gap:4px;flex-wrap:wrap;">${adjacentHtml}</div>
          </div>` : ''}
        <div style="margin-top:6px;text-align:center;">
          <button onclick="DeathModeUI.exitDungeon()" style="padding:3px 10px;background:#21262d;border:1px solid #30363d;border-radius:4px;color:#8b949e;cursor:pointer;font-size:9px;">← 返回地图</button>
        </div>
      </div>`;
  },

  async moveToDungeonRoom(roomId) {
    try {
      const resp = await fetch('/api/death-mode/dungeon-move', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({room_id: roomId}),
      });
      const data = await resp.json();
      if (data.error) { alert(data.message || data.error); return; }
      await this._renderStatusPanel();
    } catch(e) { console.error('dungeon move:', e); }
  },

  async exitDungeon() {
    try {
      await fetch('/api/death-mode/dungeon-exit', {method:'POST'});
      await this._renderStatusPanel();
    } catch(e) { console.error('dungeon exit:', e); }
  },

  // ── 队友 UI ──────────────────────────────────────

  _renderParty(state) {
    const members = state.party_members || [];
    const memberHtml = members.map(m => {
      const hpPct = m.max_hp > 0 ? Math.round(m.hp / m.max_hp * 100) : 0;
      const hpColor = hpPct > 50 ? '#3fb950' : hpPct > 25 ? '#d29922' : '#f85149';
      const alive = m.is_alive !== false;
      return `
        <div style="padding:4px 6px;background:#161b22;border-radius:4px;border:1px solid #30363d;${alive?'':'opacity:0.5;'}">
          <div style="font-size:9px;color:#c9d1d9;">${m.class_icon||'🧑'} ${m.name} <span style="color:#8b949e;font-size:8px;">Lv${m.level} ${m.class_name}</span>${alive?'':' <span style="color:#f85149;">倒下</span>'}</div>
          <div style="font-size:7px;color:${hpColor};">HP ${m.hp}/${m.max_hp} (${hpPct}%)</div>
          <div style="height:3px;background:#0d1117;border-radius:2px;margin-top:1px;">
            <div style="height:3px;background:${hpColor};border-radius:2px;width:${hpPct}%;"></div>
          </div>
          <div style="font-size:7px;color:#58a6ff;">MP ${m.mp}/${m.max_mp}</div>
        </div>`;
    }).join('');
    return `
      <div style="margin-top:8px;padding-top:6px;border-top:1px dashed #30363d;">
        <div style="font-size:9px;color:#3fb950;margin-bottom:4px;">👥 队友 (${members.length}/3)</div>
        ${members.length ? `<div style="display:flex;flex-direction:column;gap:4px;">${memberHtml}</div>` : '<div style="font-size:8px;color:#484f58;text-align:center;padding:4px;">暂无队友</div>'}
        ${members.length < 3 ? `<div style="margin-top:4px;text-align:center;">
          <button onclick="DeathModeUI.showRecruitPanel()" style="padding:2px 8px;background:#21262d;border:1px solid #30363d;border-radius:4px;color:#58a6ff;cursor:pointer;font-size:8px;">+ 招募队友</button>
        </div>` : ''}
      </div>`;
  },

  async showRecruitPanel() {
    try {
      const resp = await fetch('/api/death-mode/recruit-options');
      const data = await resp.json();
      if (data.error) { alert(data.message || data.error); return; }
      const options = data.options || [];

      const overlay = document.createElement('div');
      overlay.id = 'recruit-panel';
      overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.8);z-index:9999;display:flex;align-items:center;justify-content:center;';
      overlay.innerHTML = `
        <div style="background:#0d1117;border:1px solid #30363d;border-radius:12px;padding:24px;max-width:480px;width:90%;color:#c9d1d9;">
          <h3 style="margin:0 0 16px;color:#3fb950;font-size:18px;">招募队友 (${data.current_count}/${data.max_count})</h3>
          <div style="display:flex;flex-direction:column;gap:8px;">
            ${options.map(o => `
              <div class="recruit-card" data-id="${o.member_id}" style="display:flex;align-items:center;gap:10px;padding:10px;background:#161b22;border:2px solid #30363d;border-radius:8px;cursor:pointer;">
                <span style="font-size:28px;">${o.class_icon||'🧑'}</span>
                <div style="flex:1;">
                  <div style="font-weight:bold;color:#c9d1d9;font-size:13px;">${o.name}</div>
                  <div style="font-size:11px;color:#8b949e;">Lv${o.level} ${o.class_name}</div>
                  <div style="font-size:10px;color:#58a6ff;">HP:${o.max_hp} MP:${o.max_mp}</div>
                </div>
                <button onclick="DeathModeUI.recruitMember('${o.member_id}')" style="padding:4px 12px;background:#238636;border:none;border-radius:6px;color:white;cursor:pointer;font-size:11px;">招募</button>
              </div>
            `).join('')}
          </div>
          <button onclick="document.getElementById('recruit-panel').remove()" style="width:100%;margin-top:12px;padding:8px;background:#21262d;border:1px solid #30363d;border-radius:8px;color:#c9d1d9;cursor:pointer;">关闭</button>
        </div>`;
      document.body.appendChild(overlay);
      // 缓存options供招募使用
      this._recruitOptions = options;
    } catch(e) { console.error('recruit panel:', e); }
  },

  async recruitMember(memberId) {
    const option = (this._recruitOptions || []).find(o => o.member_id === memberId);
    if (!option) return;
    try {
      const resp = await fetch('/api/death-mode/recruit', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({member: option}),
      });
      const data = await resp.json();
      if (data.error) { alert(data.message || data.error); return; }
      const panel = document.getElementById('recruit-panel');
      if (panel) panel.remove();
      await this._renderStatusPanel();
    } catch(e) { console.error('recruit:', e); }
  },

  // ── 技能管理 ──────────────────────────────────────

  async showSkillPanel(who) {
    try {
      const whoLabel = who === 'user' ? '我' : 'AI';
      const whoColor = who === 'user' ? '#58a6ff' : '#3fb950';

      // 移除旧面板
      const old = document.getElementById('dm-skill-panel');
      if (old) old.remove();

      const overlay = document.createElement('div');
      overlay.id = 'dm-skill-panel';
      overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.8);z-index:9999;display:flex;align-items:center;justify-content:center;';

      overlay.innerHTML = `
        <div style="background:#0d1117;border:1px solid #30363d;border-radius:16px;padding:20px;max-width:700px;width:92%;max-height:85vh;overflow-y:auto;color:#c9d1d9;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
            <h3 style="margin:0;color:${whoColor};font-size:16px;">⚔️ 技能管理（${whoLabel}）</h3>
            <button onclick="this.closest('#dm-skill-panel').remove()" style="padding:4px 10px;background:#21262d;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;cursor:pointer;font-size:12px;">✕ 关闭</button>
          </div>

          <div id="dm-skill-content" style="text-align:center;padding:40px;color:#8b949e;">加载中...</div>
        </div>
      `;
      document.body.appendChild(overlay);
      await this._renderSkillContent(who);
    } catch (e) {
      const content = document.getElementById('dm-skill-content');
      if (content) content.innerHTML = `<div style="color:#f85149;font-size:12px;">加载失败：${e.message}</div>`;
    }
  },

  async _renderSkillContent(who) {
    const container = document.getElementById('dm-skill-content');
    if (!container) return;

    const whoLabel = who === 'user' ? '我' : 'AI';

    try {
      // 获取技能数据
      const [learnResp, awakeningResp, stateResp] = await Promise.all([
        fetch(`/api/death-mode/learnable-skills?who=${who}`),
        fetch(`/api/death-mode/awakening-skills?who=${who}`),
        fetch('/api/death-mode/state'),
      ]);

      const learnData = await learnResp.json();
      const awakeningData = await awakeningResp.json();
      const stateData = await stateResp.json();

      const char = who === 'user' ? (stateData.user_character || {}) : (stateData.character || {});
      const learnedSkills = char.skills || [];
      // 批量获取已学技能的中文名
      const skillNameCache = {};
      await Promise.all(learnedSkills.map(async sid => {
        try {
          const r = await fetch(`/api/death-mode/skill-info?skill_id=${encodeURIComponent(sid)}`);
          if (r.ok) {
            const d = await r.json();
            if (d && d.name) skillNameCache[sid] = d;
          }
        } catch(e) {}
      }));
      const currentSkills = learnedSkills.map(sid => {
        const info = skillNameCache[sid];
        if (info) return { ...info, is_learned: true };
        return { id: sid, name: sid, is_learned: true, req_level: 1, mp_cost: 0, type: 'unknown', description: '' };
      });

      const skillCount = learnData.skill_count || 0;
      const maxSkills = learnData.max_skills || 10;
      const remainingSlots = learnData.remaining_slots || 0;
      const skillPoints = learnData.skill_points || 0;
      const allSkills = learnData.learnable_skills || [];
      const learnable = allSkills.filter(item => {
        // 只显示可学的（未学过的）
        return item.skill && !learnedSkills.includes(item.skill.id);
      });

      // 觉醒技能
      const awakeningSlots = awakeningData.slots || [];
      const totalAwakeningSlots = awakeningData.total_slots || 3;

      // 属性点
      const statPoints = char.stat_points || 0;
      const stats = char.stats || {};
      const statNames = {'strength': '力量', 'agility': '敏捷', 'intelligence': '智力', 'vitality': '体质', 'luck': '运气'};
      const statIcons = {'strength': '💪', 'agility': '🏃', 'intelligence': '🧠', 'vitality': '❤️', 'luck': '🍀'};

      // 生成HTML
      let html = `
        <div style="margin-bottom:12px;padding:8px;background:#161b22;border-radius:8px;border:1px solid #30363d;">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
            <span style="font-size:12px;color:#c9d1d9;">技能槽位</span>
            <span style="font-size:12px;color:${skillCount >= maxSkills ? '#f85149' : '#3fb950'};">
              ${skillCount} / ${maxSkills}
            </span>
          </div>
          <div style="height:4px;background:#21262d;border-radius:2px;overflow:hidden;">
            <div style="height:100%;width:${maxSkills > 0 ? (skillCount/maxSkills*100) : 0}%;background:${skillCount >= maxSkills ? '#f85149' : '#3fb950'};transition:width 0.3s;"></div>
          </div>
          <div style="font-size:10px;color:#8b949e;margin-top:4px;">
            剩余可学 ${remainingSlots} 个 · 觉醒 ${totalAwakeningSlots} 个槽位
            <span style="font-size:9px;color:#484f58;margin-left:4px;">（可跨职业学习任意技能）</span>
          </div>
          <div style="font-size:11px;color:${skillPoints > 0 ? '#3fb950' : '#f85149'};margin-top:6px;font-weight:600;">
            📚 技能学习点：${skillPoints}
            <span style="font-size:9px;color:#8b949e;font-weight:normal;">（每升2级获得1个，学习技能时消耗1个）</span>
          </div>
        </div>
      `;

      // ── 属性点分配 ──
      html += `<div style="margin-bottom:12px;padding:10px;background:#161b22;border-radius:8px;border:1px solid ${statPoints > 0 ? '#d29922' : '#30363d'};">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <span style="font-size:12px;color:#d29922;font-weight:600;">⚡ 属性点</span>
          <span style="font-size:13px;color:${statPoints > 0 ? '#3fb950' : '#8b949e'};font-weight:bold;">可用 ${statPoints} 点</span>
        </div>
        <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:4px;margin-bottom:8px;">`;
      for (const [key, name] of Object.entries(statNames)) {
        html += `<div style="text-align:center;padding:6px 2px;background:#0d1117;border:1px solid #30363d;border-radius:6px;">
          <div style="font-size:14px;">${statIcons[key]}</div>
          <div style="font-size:10px;color:#8b949e;">${name}</div>
          <div style="font-size:14px;color:#c9d1d9;font-weight:bold;" id="dm-stat-${key}">${stats[key] || 0}</div>
        </div>`;
      }
      html += `</div>`;
      if (statPoints > 0) {
        html += `<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:4px;margin-bottom:8px;">`;
        for (const [key, name] of Object.entries(statNames)) {
          html += `<div style="text-align:center;">
            <button onclick="DeathModeUI._allocStat('${key}',1,'${who}')" style="width:100%;padding:3px;background:#1a2a1a;border:1px solid #d29922;border-radius:4px;color:#d29922;cursor:pointer;font-size:11px;">+1</button>
          </div>`;
        }
        html += `</div>`;
        html += `<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:4px;">
          <div></div>
          <div></div>
          <button onclick="DeathModeUI._allocStat('all',5,'${who}')" style="padding:3px;background:#2d2d0d;border:1px solid #d29922;border-radius:4px;color:#d29922;cursor:pointer;font-size:10px;grid-column:span 1;">全+5</button>
          <div></div>
          <div></div>
        </div>`;
      }
      html += `</div>`;

      // ── 职业被动技能 ──
      let passive = null;
      if (char.class_id) {
        try {
          const passiveResp = await fetch(`/api/death-mode/passive-skill?who=${who}`);
          if (passiveResp.ok) passive = await passiveResp.json();
        } catch(e) {}
      }
      if (passive && passive.name) {
        html += `<div style="margin-bottom:12px;padding:8px;background:#1a1a2d;border:1px solid #58a6ff;border-radius:8px;">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
            <span style="font-size:14px;">🛡️</span>
            <span style="font-size:12px;color:#58a6ff;font-weight:600;">${passive.name}</span>
            <span style="font-size:9px;color:#8b949e;background:#161b22;padding:1px 6px;border-radius:3px;">被动</span>
          </div>
          <div style="font-size:10px;color:#8b949e;">${passive.description}</div>
        </div>`;
      }

      // ── 已学技能 ──
      html += `<div style="margin-bottom:12px;">
        <div style="font-size:12px;color:#58a6ff;margin-bottom:6px;font-weight:600;">📖 已学技能（${currentSkills.length}个）</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:4px;">`;
      for (const skill of currentSkills) {
        const typeColor = skill.type === 'magic' ? '#d29922' : skill.type === 'heal' ? '#3fb950' : skill.type === 'buff' ? '#58a6ff' : '#c9d1d9';
        html += `<div style="padding:6px;background:#0d1117;border:1px solid #30363d;border-radius:6px;font-size:11px;">
          <div style="font-weight:bold;color:#c9d1d9;">${skill.name || skill.id}</div>
          <div style="font-size:9px;color:#8b949e;margin-top:2px;">
            <span style="color:${typeColor};">${skill.type}</span>
            · MP ${skill.mp_cost}
            · Lv.${skill.req_level}
          </div>
          <div style="font-size:9px;color:#484f58;margin-top:1px;">${skill.description || ''}</div>
        </div>`;
      }
      html += `</div></div>`;

      // ── 可学技能 ──
      if (remainingSlots > 0 && learnable.length > 0) {
        const canLearn = skillPoints > 0;
        html += `<div style="margin-bottom:12px;">
          <div style="font-size:12px;color:#d29922;margin-bottom:6px;font-weight:600;">📚 可学习技能（${learnable.length}个）${canLearn ? '' : '<span style="color:#f85149;font-size:10px;margin-left:8px;">⚠️ 技能点不足，升级获得</span>'}</div>
          <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:4px;">`;
        for (const item of learnable) {
          const skill = item.skill;
          const typeColor = skill.type === 'magic' ? '#d29922' : skill.type === 'heal' ? '#3fb950' : skill.type === 'buff' ? '#58a6ff' : '#c9d1d9';
          const hasReq = Object.keys(skill.req_stats || {}).length > 0;
          const reqText = hasReq ? Object.entries(skill.req_stats).map(([k,v]) => `${k}:${v}`).join(' ') : '';
          const btnStyle = canLearn
            ? `onclick="DeathModeUI._learnSkill('${skill.id}','${who}')" style="flex-shrink:0;padding:3px 8px;background:#1a3a1a;border:1px solid #3fb950;border-radius:4px;color:#3fb950;cursor:pointer;font-size:10px;margin-left:4px;"`
            : `disabled style="flex-shrink:0;padding:3px 8px;background:#21262d;border:1px solid #30363d;border-radius:4px;color:#484f58;cursor:not-allowed;font-size:10px;margin-left:4px;"`;
          html += `<div style="padding:6px;background:#161b22;border:1px solid #30363d;border-radius:6px;font-size:11px;${canLearn ? '' : 'opacity:0.6;'}">
            <div style="display:flex;justify-content:space-between;align-items:start;">
              <div style="flex:1;min-width:0;">
                <div style="font-weight:bold;color:#c9d1d9;">${item.class_icon} ${skill.name}</div>
                <div style="font-size:9px;color:#8b949e;margin-top:2px;">
                  <span style="color:${typeColor};">${skill.type}</span>
                  · MP ${skill.mp_cost}
                  · Lv.${skill.req_level}
                  ${item.source ? `· ${item.source}` : ''}
                </div>
                <div style="font-size:9px;color:#484f58;margin-top:1px;">${skill.description || ''}</div>
                ${reqText ? `<div style="font-size:8px;color:#d29922;margin-top:1px;">需求: ${reqText}</div>` : ''}
              </div>
              <button ${btnStyle}>${canLearn ? '学习' : '🔒'}</button>
            </div>
          </div>`;
        }
        html += `</div></div>`;
      } else if (remainingSlots <= 0) {
        html += `<div style="padding:12px;background:#2d0d0d;border:1px solid #f85149;border-radius:8px;text-align:center;margin-bottom:12px;">
          <div style="color:#f85149;font-size:12px;">⚠️ 技能槽位已满</div>
          <div style="color:#8b949e;font-size:10px;margin-top:2px;">已达到最大技能数（${maxSkills}个），无法学习新技能</div>
        </div>`;
      } else {
        html += `<div style="padding:12px;background:#161b22;border:1px solid #30363d;border-radius:8px;text-align:center;margin-bottom:12px;">
          <div style="color:#8b949e;font-size:12px;">暂无更多可学习技能</div>
        </div>`;
      }

      // ── 觉醒技能 ──
      html += `<div style="margin-bottom:8px;">
        <div style="font-size:12px;color:#d29922;margin-bottom:6px;font-weight:600;">💡 觉醒技能（${totalAwakeningSlots}个槽位）</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:4px;">`;
      for (const slot of awakeningSlots) {
        const reqLevel = slot.req_level || 40;
        const unlocked = slot.unlocked !== false;
        if (slot.is_empty) {
          if (unlocked) {
            html += `<div style="padding:8px;background:#0d1117;border:1px dashed #30363d;border-radius:6px;text-align:center;">
              <div style="font-size:10px;color:#484f58;">槽位 ${slot.slot_index + 1}</div>
              <div style="font-size:9px;color:#484f58;margin:4px 0;">空</div>
              <button onclick="DeathModeUI._showAwakeningForm(${slot.slot_index},'${who}')" style="padding:3px 8px;background:#1a2a3a;border:1px solid #58a6ff;border-radius:4px;color:#58a6ff;cursor:pointer;font-size:10px;">创建</button>
            </div>`;
          } else {
            html += `<div style="padding:8px;background:#0d1117;border:1px solid #30363d;border-radius:6px;text-align:center;opacity:0.6;">
              <div style="font-size:10px;color:#484f58;">槽位 ${slot.slot_index + 1}</div>
              <div style="font-size:9px;color:#f85149;margin:4px 0;">🔒 需Lv.${reqLevel}</div>
            </div>`;
          }
        } else {
          const sk = slot.skill;
          const typeColor = sk.type === 'magic' ? '#d29922' : sk.type === 'heal' ? '#3fb950' : sk.type === 'buff' ? '#58a6ff' : '#c9d1d9';
          html += `<div style="padding:8px;background:#161b22;border:1px solid #d29922;border-radius:6px;">
            <div style="font-size:11px;font-weight:bold;color:#d29922;">${sk.name}</div>
            <div style="font-size:9px;color:#8b949e;margin-top:2px;">
              <span style="color:${typeColor};">${sk.type}</span>
              · MP ${sk.mp_cost}
            </div>
            <div style="font-size:9px;color:#484f58;margin-top:1px;">${sk.description || ''}</div>
            <button onclick="DeathModeUI._showAwakeningForm(${slot.slot_index},'${who}')" style="margin-top:4px;padding:2px 6px;background:#2d2d0d;border:1px solid #d29922;border-radius:4px;color:#d29922;cursor:pointer;font-size:9px;">编辑</button>
          </div>`;
        }
      }
      html += `</div></div>`;

      container.innerHTML = html;
    } catch (e) {
      container.innerHTML = `<div style="color:#f85149;font-size:12px;">加载失败: ${e.message}</div>`;
    }
  },

  async _allocStat(stat, amount, who) {
    const allocations = {};
    if (stat === 'all') {
      allocations.strength = amount;
      allocations.agility = amount;
      allocations.intelligence = amount;
      allocations.vitality = amount;
      allocations.luck = amount;
    } else {
      allocations[stat] = amount;
    }
    try {
      const resp = await fetch('/api/death-mode/allocate-stats', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ who, allocations }),
      });
      if (!resp.ok) {
        const err = await resp.json();
        alert('分配失败: ' + (err.detail || err.message || '未知错误'));
        return;
      }
      // 刷新面板
      this._renderSkillContent(who);
      // 刷新主界面
      if (typeof this.refresh === 'function') this.refresh();
    } catch (e) {
      alert('分配失败: ' + e.message);
    }
  },

  async _learnSkill(skillId, who) {
    try {
      const resp = await fetch('/api/death-mode/learn-skill', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ skill_id: skillId, who: who }),
      });
      if (!resp.ok) {
        const err = await resp.json();
        alert('学习失败: ' + (err.detail || err.message || '未知错误'));
        return;
      }
      const data = await resp.json();
      alert(`技能学习成功！\n剩余技能学习点：${data.skill_points}`);
      this._renderSkillContent(who);
    } catch (e) {
      alert('学习失败: ' + e.message);
    }
  },

  _showAwakeningForm(slotIndex, who) {
    const whoLabel = who === 'user' ? '我' : 'AI';
    const overlay = document.createElement('div');
    overlay.id = 'dm-awakening-form';
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.85);z-index:9999;display:flex;align-items:center;justify-content:center;';

    overlay.innerHTML = `
      <div style="background:#0d1117;border:1px solid #d29922;border-radius:16px;padding:24px;max-width:500px;width:90%;color:#c9d1d9;">
        <h3 style="margin:0 0 16px;color:#d29922;font-size:16px;">💡 觉醒技能 - 槽位${slotIndex + 1}（${whoLabel}）</h3>
        <div style="margin-bottom:12px;">
          <label style="display:block;font-size:11px;color:#8b949e;margin-bottom:4px;">技能名称</label>
          <input id="aw-name" type="text" placeholder="觉醒技能的名称" style="width:100%;padding:8px 12px;background:#161b22;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:14px;box-sizing:border-box;">
        </div>
        <div style="margin-bottom:12px;">
          <label style="display:block;font-size:11px;color:#8b949e;margin-bottom:4px;">技能类型</label>
          <select id="aw-type" style="width:100%;padding:8px 12px;background:#161b22;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:14px;box-sizing:border-box;">
            <option value="physical">物理</option>
            <option value="magic">魔法</option>
            <option value="heal">治疗</option>
            <option value="buff">增益</option>
            <option value="utility">特殊</option>
          </select>
        </div>
        <div style="margin-bottom:12px;">
          <label style="display:block;font-size:11px;color:#8b949e;margin-bottom:4px;">MP消耗</label>
          <input id="aw-mp" type="number" value="10" min="0" style="width:100%;padding:8px 12px;background:#161b22;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:14px;box-sizing:border-box;">
        </div>
        <div style="margin-bottom:12px;">
          <label style="display:block;font-size:11px;color:#8b949e;margin-bottom:4px;">冷却回合（0=无冷却）</label>
          <input id="aw-cd" type="number" value="0" min="0" style="width:100%;padding:8px 12px;background:#161b22;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:14px;box-sizing:border-box;">
        </div>
        <div style="margin-bottom:12px;">
          <label style="display:block;font-size:11px;color:#8b949e;margin-bottom:4px;">技能描述</label>
          <textarea id="aw-desc" rows="2" placeholder="描述技能效果..." style="width:100%;padding:8px 12px;background:#161b22;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;font-size:13px;box-sizing:border-box;resize:vertical;"></textarea>
        </div>
        <div style="margin-bottom:16px;padding:12px;background:#161b22;border-radius:8px;border:1px solid #30363d;">
          <div style="font-size:11px;color:#58a6ff;margin-bottom:6px;font-weight:600;">⚙️ 效果配置</div>
          <div style="font-size:10px;color:#8b949e;margin-bottom:6px;">选择效果类型和数值（支持多个效果）</div>
          <div id="aw-effects">
            <div class="aw-effect-row" style="display:flex;gap:6px;margin-bottom:4px;align-items:center;">
              <select class="aw-effect-type" style="flex:1;padding:6px;background:#0d1117;border:1px solid #30363d;border-radius:4px;color:#c9d1d9;font-size:11px;">
                <option value="damage">伤害</option>
                <option value="heal">治疗</option>
                <option value="dot">持续伤害</option>
                <option value="hot">持续治疗</option>
                <option value="buff_stat">属性增益</option>
                <option value="debuff_stat">属性减益</option>
                <option value="shield">护盾</option>
                <option value="stun">眩晕</option>
                <option value="slow">减速</option>
              </select>
              <select class="aw-effect-target" style="width:80px;padding:6px;background:#0d1117;border:1px solid #30363d;border-radius:4px;color:#c9d1d9;font-size:11px;">
                <option value="single_enemy">单体敌</option>
                <option value="all_enemies">全体敌</option>
                <option value="self">自身</option>
                <option value="single_ally">单体友</option>
                <option value="all_allies">全体友</option>
              </select>
              <input class="aw-effect-value" type="number" value="1.5" step="0.1" style="width:60px;padding:6px;background:#0d1117;border:1px solid #30363d;border-radius:4px;color:#c9d1d9;font-size:11px;text-align:center;">
              <span style="font-size:9px;color:#484f58;">倍率</span>
              <button onclick="this.parentElement.remove()" style="padding:4px;background:#2d0d0d;border:1px solid #f85149;border-radius:4px;color:#f85149;cursor:pointer;font-size:9px;">✕</button>
            </div>
          </div>
          <button onclick="DeathModeUI._addEffectRow()" style="padding:4px 10px;background:#1a2a3a;border:1px solid #58a6ff;border-radius:4px;color:#58a6ff;cursor:pointer;font-size:10px;">+ 添加效果</button>
        </div>
        <div id="aw-error" style="color:#f85149;font-size:12px;margin-bottom:12px;display:none;"></div>
        <div style="display:flex;gap:12px;">
          <button onclick="this.closest('#dm-awakening-form').remove()" style="flex:1;padding:10px;background:#21262d;border:1px solid #30363d;border-radius:8px;color:#c9d1d9;cursor:pointer;font-size:14px;">取消</button>
          <button onclick="DeathModeUI._saveAwakeningSkill(${slotIndex},'${who}')" style="flex:1;padding:10px;background:#d29922;border:none;border-radius:8px;color:white;cursor:pointer;font-size:14px;font-weight:bold;">保存觉醒技能</button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);
  },

  _addEffectRow() {
    const container = document.getElementById('aw-effects');
    if (!container) return;
    const row = document.createElement('div');
    row.className = 'aw-effect-row';
    row.style.cssText = 'display:flex;gap:6px;margin-bottom:4px;align-items:center;';
    row.innerHTML = `
      <select class="aw-effect-type" style="flex:1;padding:6px;background:#0d1117;border:1px solid #30363d;border-radius:4px;color:#c9d1d9;font-size:11px;">
        <option value="damage">伤害</option>
        <option value="heal">治疗</option>
        <option value="dot">持续伤害</option>
        <option value="hot">持续治疗</option>
        <option value="buff_stat">属性增益</option>
        <option value="debuff_stat">属性减益</option>
        <option value="shield">护盾</option>
        <option value="stun">眩晕</option>
        <option value="slow">减速</option>
      </select>
      <select class="aw-effect-target" style="width:80px;padding:6px;background:#0d1117;border:1px solid #30363d;border-radius:4px;color:#c9d1d9;font-size:11px;">
        <option value="single_enemy">单体敌</option>
        <option value="all_enemies">全体敌</option>
        <option value="self">自身</option>
        <option value="single_ally">单体友</option>
        <option value="all_allies">全体友</option>
      </select>
      <input class="aw-effect-value" type="number" value="1.0" step="0.1" style="width:60px;padding:6px;background:#0d1117;border:1px solid #30363d;border-radius:4px;color:#c9d1d9;font-size:11px;text-align:center;">
      <span style="font-size:9px;color:#484f58;">倍率</span>
      <button onclick="this.parentElement.remove()" style="padding:4px;background:#2d0d0d;border:1px solid #f85149;border-radius:4px;color:#f85149;cursor:pointer;font-size:9px;">✕</button>
    `;
    container.appendChild(row);
  },

  async _saveAwakeningSkill(slotIndex, who) {
    const overlay = document.getElementById('dm-awakening-form');
    if (!overlay) return;

    const name = overlay.querySelector('#aw-name').value.trim();
    const type = overlay.querySelector('#aw-type').value;
    const mpCost = parseInt(overlay.querySelector('#aw-mp').value) || 10;
    const cooldown = parseInt(overlay.querySelector('#aw-cd').value) || 0;
    const description = overlay.querySelector('#aw-desc').value.trim();

    const errEl = overlay.querySelector('#aw-error');
    if (!name) { errEl.textContent = '请输入技能名称'; errEl.style.display = 'block'; return; }

    // 收集效果
    const effectRows = overlay.querySelectorAll('.aw-effect-row');
    const effects = [];
    for (const row of effectRows) {
      const etype = row.querySelector('.aw-effect-type').value;
      const target = row.querySelector('.aw-effect-target').value;
      const value = parseFloat(row.querySelector('.aw-effect-value').value) || 1.0;
      effects.push({ type: etype, target: target, value: value });
    }

    if (effects.length === 0) {
      errEl.textContent = '至少需要一个效果'; errEl.style.display = 'block'; return;
    }

    errEl.style.display = 'none';

    try {
      const resp = await fetch('/api/death-mode/set-awakening', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          who: who,
          slot_index: slotIndex,
          name: name,
          type: type,
          mp_cost: mpCost,
          cooldown: cooldown,
          effects: effects,
          description: description,
        }),
      });

      if (!resp.ok) {
        const err = await resp.json();
        alert('保存失败: ' + (err.detail || err.message || '未知错误'));
        return;
      }

      alert('觉醒技能「' + name + '」保存成功！');
      overlay.remove();
      this._renderSkillContent(who);
    } catch (e) {
      alert('保存失败: ' + e.message);
    }
  },

  // ── 任务系统 ──────────────────────────────────────

  async showQuestPanel() {
    const old = document.getElementById('dm-quest-panel');
    if (old) old.remove();

    const overlay = document.createElement('div');
    overlay.id = 'dm-quest-panel';
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.8);z-index:9999;display:flex;align-items:center;justify-content:center;';
    overlay.innerHTML = `
      <div style="background:#0d1117;border:1px solid #a371f7;border-radius:16px;padding:20px;max-width:700px;width:92%;max-height:85vh;overflow-y:auto;color:#c9d1d9;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
          <h3 style="margin:0;color:#a371f7;font-size:16px;">📜 任务面板</h3>
          <button onclick="this.closest('#dm-quest-panel').remove()" style="padding:4px 10px;background:#21262d;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;cursor:pointer;font-size:12px;">✕ 关闭</button>
        </div>
        <div id="dm-quest-content" style="text-align:center;color:#8b949e;font-size:12px;">加载中...</div>
      </div>
    `;
    document.body.appendChild(overlay);

    try {
      const [activeResp, availableResp, seriesResp] = await Promise.all([
        fetch('/api/death-mode/quests/active'),
        fetch('/api/death-mode/quests/available?who=ai'),
        fetch('/api/death-mode/quests/series'),
      ]);
      const activeData = await activeResp.json();
      const availableData = await availableResp.json();
      const seriesData = await seriesResp.json();

      const active = activeData.active_quests || [];
      const available = availableData.available_quests || [];
      const series = seriesData.series || [];
      const completedIds = activeData.completed_ids || [];

      let html = '';

      // 系列任务总览
      if (series.length > 0) {
        html += `<div style="margin-bottom:14px;padding:10px;background:#161b22;border:1px solid #30363d;border-radius:8px;">
          <div style="font-size:12px;color:#a371f7;font-weight:600;margin-bottom:8px;">📖 系列任务</div>`;
        for (const s of series) {
          const pct = s.total_quests > 0 ? (s.completed_quests / s.total_quests * 100) : 0;
          html += `<div style="margin-bottom:8px;">
            <div style="display:flex;justify-content:space-between;font-size:11px;color:#c9d1d9;">
              <span>${s.title}</span>
              <span style="color:#8b949e;">${s.completed_quests}/${s.total_quests}</span>
            </div>
            <div style="font-size:10px;color:#8b949e;margin:2px 0;">${s.description}</div>
            <div style="height:3px;background:#21262d;border-radius:2px;overflow:hidden;">
              <div style="height:100%;width:${pct}%;background:#a371f7;"></div>
            </div>
          </div>`;
        }
        html += `</div>`;
      }

      // 进行中任务
      html += `<div style="margin-bottom:14px;">
        <div style="font-size:12px;color:#3fb950;font-weight:600;margin-bottom:6px;">▶ 进行中任务（${active.length}）</div>`;
      if (active.length === 0) {
        html += `<div style="padding:10px;background:#161b22;border:1px dashed #30363d;border-radius:8px;text-align:center;color:#8b949e;font-size:11px;">暂无进行中任务，去任务板接一个吧</div>`;
      } else {
        for (const q of active) {
          const objectives = (q.objectives || []).map(o => {
            const pct = o.count > 0 ? Math.min(100, o.progress / o.count * 100) : 0;
            const done = o.progress >= o.count;
            return `<div style="margin-top:4px;">
              <div style="display:flex;justify-content:space-between;font-size:10px;color:${done ? '#3fb950' : '#c9d1d9'};">
                <span>${o.type === 'kill' ? '击杀' : o.type === 'collect' ? '收集' : o.type === 'visit_location' ? '到达' : '对话'}: ${o.target_keyword}</span>
                <span>${o.progress}/${o.count} ${done ? '✓' : ''}</span>
              </div>
              <div style="height:3px;background:#21262d;border-radius:2px;overflow:hidden;margin-top:2px;">
                <div style="height:100%;width:${pct}%;background:${done ? '#3fb950' : '#58a6ff'};"></div>
              </div>
            </div>`;
          }).join('');
          const allDone = (q.objectives || []).every(o => o.progress >= o.count);
          html += `<div style="padding:10px;background:#0d1117;border:1px solid ${allDone ? '#3fb950' : '#30363d'};border-radius:8px;margin-bottom:6px;">
            <div style="font-size:12px;font-weight:bold;color:#c9d1d9;">${q.title}${allDone ? ' <span style="color:#3fb950;font-size:10px;">✓ 可交付</span>' : ''}</div>
            <div style="font-size:10px;color:#8b949e;margin:3px 0;">${q.description || ''}</div>
            ${objectives}
            <div style="font-size:9px;color:#d29922;margin-top:4px;">奖励：经验${(q.rewards||{}).exp||0} · 金币${(q.rewards||{}).gold||0}${(q.rewards||{}).items ? ' · 物品' : ''}</div>
            <div style="margin-top:6px;display:flex;gap:6px;">
              ${allDone ? `<button onclick="DeathModeUI._turnInQuest('${q.id}')" style="flex:1;padding:4px 12px;background:#1a3a1a;border:1px solid #3fb950;border-radius:4px;color:#3fb950;cursor:pointer;font-size:11px;">交付任务</button>` : ''}
              ${!allDone ? `<button onclick="DeathModeUI._abandonQuest('${q.id}')" style="flex:1;padding:4px 12px;background:#3a1a1a;border:1px solid #f85149;border-radius:4px;color:#f85149;cursor:pointer;font-size:11px;">放弃任务</button>` : ''}
            </div>
          </div>`;
        }
      }
      html += `</div>`;

      // 可接任务
      html += `<div style="margin-bottom:14px;">
        <div style="font-size:12px;color:#d29922;font-weight:600;margin-bottom:6px;">📋 可接任务（${available.length}）</div>`;
      if (available.length === 0) {
        html += `<div style="padding:10px;background:#161b22;border:1px dashed #30363d;border-radius:8px;text-align:center;color:#8b949e;font-size:11px;">暂无可接任务（继续探索世界，或关注酒馆新闻）</div>`;
      } else {
        for (const q of available) {
          html += `<div style="padding:10px;background:#161b22;border:1px solid #30363d;border-radius:8px;margin-bottom:6px;">
            <div style="display:flex;justify-content:space-between;align-items:start;">
              <div style="flex:1;min-width:0;">
                <div style="font-size:12px;font-weight:bold;color:#c9d1d9;">${q.title}</div>
                <div style="font-size:10px;color:#8b949e;margin:3px 0;">${q.description || ''}</div>
                <div style="font-size:9px;color:#58a6ff;">发布人：${q.quest_giver || '未知'} ${q.location_hint ? '· ' + q.location_hint : ''}</div>
                <div style="font-size:9px;color:#d29922;margin-top:2px;">奖励：经验${(q.rewards||{}).exp||0} · 金币${(q.rewards||{}).gold||0}</div>
              </div>
              <button onclick="DeathModeUI._acceptQuest('${q.id}','ai')" style="flex-shrink:0;padding:4px 10px;background:#3a2d0d;border:1px solid #d29922;border-radius:4px;color:#d29922;cursor:pointer;font-size:10px;margin-left:6px;">接受</button>
            </div>
          </div>`;
        }
      }
      html += `</div>`;

      if (completedIds.length > 0) {
        html += `<div style="font-size:10px;color:#484f58;text-align:center;">已完成 ${completedIds.length} 个任务</div>`;
      }

      document.getElementById('dm-quest-content').innerHTML = html;
    } catch (e) {
      document.getElementById('dm-quest-content').innerHTML = `<div style="color:#f85149;font-size:12px;">加载失败: ${e.message}</div>`;
    }
  },

  async _acceptQuest(questId, who) {
    try {
      const resp = await fetch('/api/death-mode/quests/accept', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ quest_id: questId, who: who }),
      });
      if (!resp.ok) {
        const err = await resp.json();
        alert('接受失败: ' + (err.detail || err.message || '未知错误'));
        return;
      }
      const data = await resp.json();
      alert(data.message);
      this.showQuestPanel();
      this.refresh();
    } catch (e) {
      alert('接受失败: ' + e.message);
    }
  },

  async _turnInQuest(questId) {
    try {
      const resp = await fetch('/api/death-mode/quests/turn-in', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ quest_id: questId, who: 'ai' }),
      });
      if (!resp.ok) {
        const err = await resp.json();
        alert('交付失败: ' + (err.detail || err.message || '未知错误'));
        return;
      }
      const data = await resp.json();
      alert(data.message);
      this.showQuestPanel();
      this.refresh();
    } catch (e) {
      alert('交付失败: ' + e.message);
    }
  },

  async _abandonQuest(questId) {
    if (!confirm('确定放弃这个任务吗？')) return;
    try {
      const resp = await fetch('/api/death-mode/quests/abandon', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ quest_id: questId }),
      });
      if (!resp.ok) {
        const err = await resp.json();
        alert('放弃失败: ' + (err.detail || err.message || '未知错误'));
        return;
      }
      const data = await resp.json();
      alert(data.message);
      this.showQuestPanel();
      this.refresh();
    } catch (e) {
      alert('放弃失败: ' + e.message);
    }
  },

  // ── 世界新闻 ──────────────────────────────────────

  async showNewsPanel() {
    const old = document.getElementById('dm-news-panel');
    if (old) old.remove();

    const overlay = document.createElement('div');
    overlay.id = 'dm-news-panel';
    overlay.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.8);z-index:9999;display:flex;align-items:center;justify-content:center;';
    overlay.innerHTML = `
      <div style="background:#0d1117;border:1px solid #d29922;border-radius:16px;padding:20px;max-width:650px;width:92%;max-height:85vh;overflow-y:auto;color:#c9d1d9;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
          <h3 style="margin:0;color:#d29922;font-size:16px;">📰 冒险者酒馆 · 世界新闻</h3>
          <button onclick="this.closest('#dm-news-panel').remove()" style="padding:4px 10px;background:#21262d;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;cursor:pointer;font-size:12px;">✕ 关闭</button>
        </div>
        <div id="dm-news-content" style="text-align:center;color:#8b949e;font-size:12px;">加载中...</div>
      </div>
    `;
    document.body.appendChild(overlay);

    try {
      const resp = await fetch('/api/death-mode/world-news?limit=20');
      const data = await resp.json();
      const news = data.news || [];
      const playDays = data.play_days || 1;

      let html = `<div style="font-size:11px;color:#8b949e;margin-bottom:12px;padding:8px;background:#161b22;border-radius:8px;">
        📅 当前世界日：第 <span style="color:#d29922;font-weight:bold;">${playDays}</span> 天
        ${data.unread_count > 0 ? `<span style="color:#f85149;margin-left:8px;">${data.unread_count} 条未读</span>` : ''}
        <button onclick="DeathModeUI._markAllNewsRead()" style="margin-left:8px;padding:2px 8px;background:#21262d;border:1px solid #30363d;border-radius:4px;color:#c9d1d9;cursor:pointer;font-size:10px;">全部已读</button>
      </div>`;

      if (news.length === 0) {
        html += `<div style="padding:20px;text-align:center;color:#8b949e;font-size:12px;">
          暂无新闻。世界仍在运转中...<br>
          <span style="font-size:10px;color:#484f58;">每过7天会有新消息</span>
        </div>`;
      } else {
        for (const n of news) {
          const readFlag = n.read ? '' : '<span style="color:#f85149;font-size:9px;margin-left:4px;">●</span>';
          html += `<div style="padding:10px;background:#161b22;border:1px solid ${n.read ? '#30363d' : '#d29922'};border-radius:8px;margin-bottom:8px;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
              <span style="font-size:12px;color:#d29922;font-weight:600;">${n.title}${readFlag}</span>
              <span style="font-size:9px;color:#8b949e;">第${n.day}天</span>
            </div>
            <div style="font-size:11px;color:#c9d1d9;line-height:1.5;">${n.news}</div>
            ${n.unlock_quests && n.unlock_quests.length > 0 ? `<div style="font-size:9px;color:#a371f7;margin-top:4px;">🔓 解锁新任务</div>` : ''}
          </div>`;
        }
      }

      document.getElementById('dm-news-content').innerHTML = html;
    } catch (e) {
      document.getElementById('dm-news-content').innerHTML = `<div style="color:#f85149;font-size:12px;">加载失败: ${e.message}</div>`;
    }
  },

  async _markAllNewsRead() {
    try {
      await fetch('/api/death-mode/world-news/mark-read', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      this.showNewsPanel();
      this.refresh();
    } catch (e) {
      alert('标记失败: ' + e.message);
    }
  },

  // ── 刷新主界面 ──────────────────────────────────────

  refresh() {
    this._renderStatusPanel();
    this._loadAndRenderLog();
  },
};

// 暴露到全局
window.DeathModeUI = DeathModeUI;
