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
        const firstCard = classesContainer.querySelector('.dm-class-card');
        if (firstCard) { firstCard.style.borderColor = '#58a6ff'; selectedClass = firstCard.dataset.id; }
        renderClassCards(userClassesContainer, classes, null, (id) => { selectedUserClass = id; });
        const userCards = userClassesContainer.querySelectorAll('.dm-class-card');
        if (userCards.length > 1) { userCards[1].style.borderColor = '#3fb950'; selectedUserClass = userCards[1].dataset.id; }
        else if (userCards.length > 0) { userCards[0].style.borderColor = '#3fb950'; selectedUserClass = userCards[0].dataset.id; }
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

        <!-- 右侧：行动日志 -->
        <div style="flex:1;display:flex;flex-direction:column;overflow:hidden;">
          <div style="padding:8px 16px;border-bottom:1px solid #21262d;display:flex;align-items:center;justify-content:space-between;">
            <span style="font-size:13px;color:#58a6ff;font-weight:600;">📜 行动记录</span>
            <span id="dm-log-count" style="font-size:11px;color:#484f58;"></span>
          </div>
          <div id="dm-log-container" style="flex:1;overflow-y:auto;padding:12px 16px;">
            <div style="text-align:center;color:#484f58;padding:40px 0;">加载中...</div>
          </div>
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

      // 更新头部
      const headerChar = document.getElementById('dm-header-char');
      if (headerChar) {
        headerChar.textContent = `${char.name || '?'} Lv.${char.level || 1} · HP ${char.hp}/${char.max_hp}`;
      }

      // 装备
      const equipment = char.equipment || [];
      const eqHtml = equipment.length > 0 ? equipment.map(eq => {
        const icon = eq.type === 'weapon' ? '🗡️' : '🛡️';
        return `<div style="font-size:11px;color:${eq.color || '#c9d1d9'};">${icon} ${eq.name}（${eq.rarity_name || '普通'}）</div>`;
      }).join('') : '<div style="font-size:11px;color:#484f58;">无装备</div>';

      // 用户角色
      const uc = state.user_character;
      let ucHtml = '';
      if (uc && uc.class_name) {
        const uHpPct = uc.max_hp > 0 ? (uc.hp / uc.max_hp * 100) : 0;
        const uHpColor = uHpPct > 60 ? '#3fb950' : uHpPct > 30 ? '#d29922' : '#f85149';
        const uStats = uc.stats || {};
        ucHtml = `
          <div style="margin-top:12px;padding-top:12px;border-top:1px dashed #30363d;">
            <div style="font-size:11px;color:#3fb950;margin-bottom:4px;">👤 用户角色</div>
            <div style="font-size:13px;font-weight:bold;color:#c9d1d9;">${uc.name || '用户'}</div>
            <div style="font-size:11px;color:#8b949e;">${uc.class_name || ''} Lv.${uc.level || 1}</div>
            <div style="height:8px;background:#21262d;border-radius:4px;overflow:hidden;margin-top:4px;">
              <div style="height:100%;width:${uHpPct}%;background:${uHpColor};transition:width 0.3s;"></div>
            </div>
            <div style="font-size:10px;color:#8b949e;margin-top:4px;">
              <div>💪${uStats.strength||5} 🏃${uStats.agility||5} 🧠${uStats.intelligence||5} ❤️${uStats.vitality||5} 🍀${uStats.luck||5}</div>
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
          <div style="font-size:10px;color:#58a6ff;margin-bottom:3px;">装备</div>
          ${eqHtml}
        </div>

        <div style="font-size:10px;color:#8b949e;">
          <div>💰 金币: ${char.gold||0}</div>
          <div>📅 第${state.play_time_days||1}天</div>
          <div>⚔️ 击杀: ${state.kill_count||0}</div>
          ${state.in_combat ? '<div style="color:#f85149;">⚠️ 战斗中</div>' : ''}
          ${state.story?.current_location ? `<div>📍 ${state.story.current_location}</div>` : ''}
        </div>

        ${ucHtml}
      `;
    } catch (e) {}
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
      content = `<div style="color:#c9d1d9;font-size:13px;line-height:1.6;">${d.description || ''}</div>
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
          combatHtml = `<div style="padding:6px 8px;background:#161b22;border-radius:4px;margin-top:4px;">
            <div style="font-size:11px;color:#8b949e;">${d.combat.combat_log.slice(0, 3).join('；')}</div>
          </div>`;
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

      // 死亡
      let deathHtml = '';
      if (d.character_died) {
        deathHtml = `<div style="padding:8px;background:#2d0d0d;border:1px solid #f85149;border-radius:6px;margin-top:6px;">
          <div style="color:#f85149;font-weight:bold;">☠️ 角色阵亡</div>
          <div style="font-size:12px;color:#8b949e;">${d.death_description || ''}</div>
        </div>`;
      }

      content = `
        <div style="color:#c9d1d9;font-size:13px;font-weight:600;">${actionLabel}</div>
        ${d.narrative ? `<div style="font-size:12px;color:#8b949e;line-height:1.5;margin-top:2px;">${d.narrative}</div>` : ''}
        ${combatHtml}${rewardHtml}${levelHtml}${dropHtml}${deathHtml}`;
    }
    else if (type === 'move') {
      content = `<div style="color:#3fb950;">🗺️ 从 ${d.from} 前往 ${d.to}</div>
        <div style="font-size:11px;color:#8b949e;">危险等级：${'★'.repeat(d.danger_level || 1)}</div>`;
    }
    else if (type === 'npc_interact') {
      content = `<div style="color:#d29922;">💬 与 ${d.npc_name} 交互（${d.interaction}）</div>
        ${d.message ? `<div style="font-size:12px;color:#8b949e;margin-top:2px;">${d.message}</div>` : ''}`;
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
};

// 暴露到全局
window.DeathModeUI = DeathModeUI;
