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
  _lastLogCount: 0,
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
      fantasy: '奇幻魔法', xianxia: '仙侠修真',
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

      panel.innerHTML = `
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

        ${ucHtml}
      `;

      // ── 渲染怪物信息栏 ──
      this._renderEnemiesPanel(state);
    } catch (e) {}
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

      // 如果没有新日志，不重新渲染
      if (logs.length === this._lastLogCount && container.children.length > 0) return;
      this._lastLogCount = logs.length;

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
      move:         { icon: '🗺️', color: '#3fb950', label: '移动' },
      npc_interact: { icon: '💬', color: '#d29922', label: 'NPC交互' },
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
    else if (type === 'action') {
      const actionLabel = d.action || '未知行动';
      const outcome = d.outcome || '';

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

      content = `
        <div style="color:#c9d1d9;font-size:13px;font-weight:600;">${actionLabel}</div>
        ${d.narrative ? `<div style="font-size:12px;color:#8b949e;line-height:1.5;margin-top:2px;">${this._replaceYou(d.narrative)}</div>` : ''}
        ${combatHtml}${rewardHtml}${levelHtml}${dropHtml}${tradeHtml}${deathHtml}`;
    }
    else if (type === 'move') {
      content = `<div style="color:#3fb950;">🗺️ 从 ${d.from} 前往 ${d.to}</div>
        <div style="font-size:11px;color:#8b949e;">危险等级：${'★'.repeat(d.danger_level || 1)}</div>`;
    }
    else if (type === 'npc_interact') {
      content = `<div style="color:#d29922;">💬 与 ${d.npc_name} 交互（${d.interaction}）</div>
        ${d.message ? `<div style="font-size:12px;color:#8b949e;margin-top:2px;">${this._replaceYou(d.message)}</div>` : ''}`;
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

    // 方向 → 3x3 grid 位置
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

    // 填入相邻区域
    for (const adj of md.adjacent) {
      const pos = dirMap[adj.direction];
      if (pos) {
        grid[pos] = {
          type: 'adjacent',
          direction: adj.direction,
          name: adj.name,
          explored: adj.explored,
          danger: adj.danger_level,
          regionType: adj.region_type,
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
          cells += `<div style="width:33.33%;aspect-ratio:1;display:flex;align-items:center;justify-content:center;font-size:8px;color:#21262d;">.</div>`;
          continue;
        }
        if (cell.type === 'center') {
          cells += `<div style="width:33.33%;aspect-ratio:1;display:flex;flex-direction:column;align-items:center;justify-content:center;background:#1a3a1a;border-radius:6px;border:1px solid #3fb950;">
            <span style="font-size:14px;">📍</span>
            <span style="font-size:7px;color:#3fb950;font-weight:bold;text-align:center;line-height:1.2;max-width:100%;word-break:break-all;">${cell.name}</span>
          </div>`;
        } else {
          const arrow = dirArrow[cell.direction] || '?';
          const color = cell.explored ? dangerColor(cell.danger) : '#484f58';
          const icon = cell.explored ? regionIcon(cell.regionType) : '❓';
          const name = cell.explored ? cell.name : '未知';
          cells += `<div style="width:33.33%;aspect-ratio:1;display:flex;flex-direction:column;align-items:center;justify-content:center;border-radius:4px;background:${cell.explored ? '#161b22' : '#0d1117'};border:1px solid ${cell.explored ? '#21262d' : '#161b22'};">
            <span style="font-size:8px;color:${color};font-weight:bold;">${arrow} ${cell.direction}</span>
            <span style="font-size:14px;margin:1px 0;">${icon}</span>
            <span style="font-size:7px;color:${color};text-align:center;line-height:1.2;max-width:100%;word-break:break-all;padding:0 1px;">${name}</span>
          </div>`;
        }
      }
    }

    return `
      <div style="margin-top:10px;padding-top:10px;border-top:1px dashed #30363d;">
        <div style="font-size:10px;color:#58a6ff;margin-bottom:4px;text-align:center;">🗺️ 地图</div>
        <div style="display:flex;flex-wrap:wrap;width:100%;gap:2px;">
          ${cells}
        </div>
        <div style="font-size:8px;color:#484f58;text-align:center;margin-top:4px;">
          ${current.name} · 危险度${'★'.repeat(current.danger_level) || '安全'}
        </div>
      </div>`;
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
      const name = r.visited ? r.name : '未知房间';
      return `<button onclick="DeathModeUI.moveToDungeonRoom('${r.room_id}')"
        style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:6px 8px;background:#161b22;border:1px solid #30363d;border-radius:6px;cursor:pointer;color:#c9d1d9;font-size:9px;min-width:60px;flex:1;">
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

    const bossBadge = room.is_boss ? '<span style="color:#f85149;font-size:9px;">👑 BOSS房</span>' : '';
    const clearedBadge = dg.boss_defeated ? '<span style="color:#3fb950;font-size:9px;">✅ 已通关</span>' : '';

    return `
      <div style="margin-top:10px;padding-top:10px;border-top:1px dashed #30363d;">
        <div style="font-size:10px;color:#d29922;margin-bottom:4px;text-align:center;">🕳️ ${dg.dungeon_name || '地下城'}</div>
        ${dg.lore ? `<div style="font-size:8px;color:#8b949e;text-align:center;margin-bottom:4px;font-style:italic;">${dg.lore}</div>` : ''}
        <div style="font-size:8px;color:#484f58;text-align:center;margin-bottom:6px;">
          已探索 ${dg.visited_count}/${dg.total_rooms} 个房间 ${clearedBadge}
        </div>
        <div style="padding:6px;background:#161b22;border-radius:6px;border:1px solid #30363d;">
          <div style="font-size:10px;color:#58a6ff;font-weight:bold;margin-bottom:2px;">📍 ${room.name} ${bossBadge}</div>
          <div style="font-size:8px;color:#8b949e;line-height:1.4;">${room.description || ''}</div>
          ${enemiesHtml}
          ${hazardsHtml}
          ${lootHtml}
        </div>
        ${adjacentHtml ? `
          <div style="margin-top:6px;">
            <div style="font-size:8px;color:#484f58;margin-bottom:3px;">可达房间：</div>
            <div style="display:flex;gap:4px;flex-wrap:wrap;">${adjacentHtml}</div>
          </div>` : ''}
        <div style="margin-top:6px;text-align:center;">
          <button onclick="DeathModeUI.exitDungeon()"
            style="padding:3px 10px;background:#21262d;border:1px solid #30363d;border-radius:4px;color:#8b949e;cursor:pointer;font-size:9px;">
            ← 返回区域地图
          </button>
        </div>
      </div>`;
  },

  async moveToDungeonRoom(roomId) {
    try {
      const resp = await fetch('/api/death-mode/dungeon-move', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ room_id: roomId }),
      });
      const data = await resp.json();
      if (data.error) {
        alert(data.message || data.error);
        return;
      }
      await this._renderStatusPanel();
    } catch (e) {
      console.error('dungeon move error:', e);
    }
  },

  async exitDungeon() {
    try {
      await fetch('/api/death-mode/dungeon-exit', { method: 'POST' });
      await this._renderStatusPanel();
    } catch (e) {
      console.error('dungeon exit error:', e);
    }
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
      const learnable = allSkills.filter(item => {
        // 只显示可学的（未学过的）
        return !learnedSkills.includes(item.skill.id);
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
        html += `<div style="margin-bottom:12px;">
          <div style="font-size:12px;color:#d29922;margin-bottom:6px;font-weight:600;">📚 可学习技能（${learnable.length}个）</div>
          <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:4px;">`;
        for (const item of learnable) {
          const skill = item.skill;
          const typeColor = skill.type === 'magic' ? '#d29922' : skill.type === 'heal' ? '#3fb950' : skill.type === 'buff' ? '#58a6ff' : '#c9d1d9';
          const hasReq = Object.keys(skill.req_stats || {}).length > 0;
          const reqText = hasReq ? Object.entries(skill.req_stats).map(([k,v]) => `${k}:${v}`).join(' ') : '';
          html += `<div style="padding:6px;background:#161b22;border:1px solid #30363d;border-radius:6px;font-size:11px;">
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
              <button onclick="DeathModeUI._learnSkill('${skill.id}','${who}')" style="flex-shrink:0;padding:3px 8px;background:#1a3a1a;border:1px solid #3fb950;border-radius:4px;color:#3fb950;cursor:pointer;font-size:10px;margin-left:4px;">学习</button>
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
        if (slot.is_empty) {
          html += `<div style="padding:8px;background:#0d1117;border:1px dashed #30363d;border-radius:6px;text-align:center;">
            <div style="font-size:10px;color:#484f58;">槽位 ${slot.slot_index + 1}</div>
            <div style="font-size:9px;color:#484f58;margin:4px 0;">空</div>
            <button onclick="DeathModeUI._showAwakeningForm(${slot.slot_index},'${who}')" style="padding:3px 8px;background:#1a2a3a;border:1px solid #58a6ff;border-radius:4px;color:#58a6ff;cursor:pointer;font-size:10px;">创建</button>
          </div>`;
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
      alert('技能学习成功！');
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
};

// 暴露到全局
window.DeathModeUI = DeathModeUI;
