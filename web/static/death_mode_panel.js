/* ── 死亡模式面板（18766网页端）──
 * 跨端口调用 8769 的 /api/death-mode/* 接口
 * 显示状态 + 行动日志 + 发起行动
 */

const DeathModePanel = {
  // 8769 服务基础URL（8769只监听127.0.0.1，必须用本机回环地址）
  API_BASE: 'http://127.0.0.1:8769',

  _timer: null,
  _lastLogCount: -1,
  _userName: '用户',
  _sending: false,

  // 切换到死亡模式视图
  show() {
    document.getElementById('chatMessages').style.display = 'none';
    document.querySelector('.input-area').style.display = 'none';
    document.getElementById('welcomeScreen')?.remove();
    const view = document.getElementById('deathModeView');
    view.classList.add('active');
    document.getElementById('chatTitle').textContent = '死亡模式';
    this._startAutoRefresh();
    this.refreshAll();
  },

  // 切换回聊天视图
  hide() {
    document.getElementById('deathModeView').classList.remove('active');
    document.getElementById('chatMessages').style.display = '';
    document.querySelector('.input-area').style.display = '';
    this._stopAutoRefresh();
  },

  _startAutoRefresh() {
    this._stopAutoRefresh();
    this._timer = setInterval(() => this.refreshAll(), 5000);
  },

  _stopAutoRefresh() {
    if (this._timer) { clearInterval(this._timer); this._timer = null; }
  },

  async refreshAll() {
    await Promise.all([this._renderStatus(), this._renderLog()]);
  },

  // ── 状态栏渲染 ──
  async _renderStatus() {
    const bar = document.getElementById('dmStatusBar');
    if (!bar) return;
    try {
      const resp = await fetch(`${this.API_BASE}/api/death-mode/state`);
      const state = await resp.json();

      // 顶栏元信息
      const metaEl = document.getElementById('dmTopbarMeta');
      if (state.active) {
        const day = state.play_time_days || 1;
        const loc = state.story?.current_location || '未知';
        if (metaEl) metaEl.innerHTML = `第${day}天 · 📍${loc}<span class="dm-refresh-dot"></span>`;
      } else {
        if (metaEl) metaEl.innerHTML = '未开始<span class="dm-refresh-dot" style="background:#999;"></span>';
        bar.innerHTML = `<div class="dm-no-game">暂无进行中的死亡模式游戏<div class="dm-no-game-hint">请在主程序（桌面宠物/8769网页）中创建角色开始冒险</div></div>`;
        return;
      }

      const char = state.character || {};
      const uc = state.user_character || {};
      if (uc.name) this._userName = uc.name;

      // AI 角色卡片
      const charCard = this._renderCharCard(char, '🤖', false);

      // 用户角色卡片
      let ucCard = '';
      if (uc && uc.class_name) {
        ucCard = this._renderCharCard(uc, '👤', true);
      }

      // 敌人卡片（战斗中）
      let enemyCard = '';
      if (state.in_combat && state.enemies?.length) {
        const alive = state.enemies.filter(e => e.hp > 0);
        if (alive.length > 0) {
          enemyCard = `<div class="dm-enemies-card">
            <div style="font-weight:600;color:#dc2626;margin-bottom:4px;">⚔️ 战斗中</div>
            ${alive.map(e => `<div class="dm-enemy-item">
              <span>${e.name || '?'}</span>
              <span class="dm-enemy-hp">HP ${e.hp}/${e.max_hp || e.hp}</span>
            </div>`).join('')}
          </div>`;
        }
      }

      bar.innerHTML = charCard + ucCard + enemyCard;
    } catch (e) {
      bar.innerHTML = `<div class="dm-no-game" style="color:#dc2626;">无法连接死亡模式服务（8769）<div class="dm-no-game-hint">请确认主程序已启动</div></div>`;
    }
  },

  _renderCharCard(c, icon, isUser) {
    if (!c || !c.class_name) return '';
    const hpPct = c.max_hp > 0 ? (c.hp / c.max_hp * 100) : 0;
    const mpPct = c.max_mp > 0 ? (c.mp / c.max_mp * 100) : 0;
    const expPct = c.exp_to_next > 0 ? ((c.experience || 0) / c.exp_to_next * 100) : 0;
    const hpColor = hpPct > 60 ? '#16a34a' : hpPct > 30 ? '#d97706' : '#dc2626';
    const dead = c.hp <= 0;
    return `<div class="dm-char-card${dead ? ' dead' : ''}">
      <div class="dm-char-name">${icon} ${c.name || '?'} <span class="dm-char-class">${c.class_name || ''} Lv.${c.level || 1}${dead ? ' · 已倒下' : ''}</span></div>
      <div class="dm-bar-row"><span style="color:#dc2626;">HP</span><span>${c.hp || 0}/${c.max_hp || 0}</span></div>
      <div class="dm-bar"><div class="dm-bar-fill" style="width:${hpPct}%;background:${hpColor};"></div></div>
      <div class="dm-bar-row"><span style="color:#2563eb;">MP</span><span>${c.mp || 0}/${c.max_mp || 0}</span></div>
      <div class="dm-bar"><div class="dm-bar-fill" style="width:${mpPct}%;background:#2563eb;"></div></div>
      <div class="dm-bar-row"><span style="color:#d97706;">EXP</span><span>${c.experience || 0}/${c.exp_to_next || 100}</span></div>
      <div class="dm-bar"><div class="dm-bar-fill" style="width:${expPct}%;background:#d97706;"></div></div>
      ${c.gold !== undefined ? `<div style="font-size:10px;color:var(--text-muted);margin-top:4px;">💰 ${c.gold}</div>` : ''}
    </div>`;
  },

  // ── 日志渲染 ──
  async _renderLog() {
    const container = document.getElementById('dmLogArea');
    if (!container) return;
    try {
      const resp = await fetch(`${this.API_BASE}/api/death-mode/log?limit=100`);
      const data = await resp.json();
      if (data.error) {
        container.innerHTML = `<div class="dm-log-empty">暂无游戏</div>`;
        return;
      }
      const logs = data.logs || [];
      if (logs.length === this._lastLogCount && container.children.length > 0) return;
      this._lastLogCount = logs.length;

      if (logs.length === 0) {
        container.innerHTML = `<div class="dm-log-empty">📜 还没有行动记录<br><span style="font-size:11px;">在下方输入框发起行动</span></div>`;
        return;
      }

      container.innerHTML = logs.map(log => this._renderLogEntry(log)).join('');
      container.scrollTop = 0;
    } catch (e) {
      container.innerHTML = `<div class="dm-log-empty" style="color:#dc2626;">加载日志失败</div>`;
    }
  },

  _renderLogEntry(log) {
    const type = log.type || 'action';
    const d = log.data || {};
    const time = log.time ? new Date(log.time).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '';
    const day = log.day || 1;

    // 类型样式
    let cls = 'dm-log-action';
    if (type === 'game_start') cls = 'dm-log-victory';
    else if (d.combat?.victory) cls = 'dm-log-victory';
    else if (d.combat) cls = 'dm-log-combat';

    let html = `<div class="dm-log-entry ${cls}">`;

    // 头部：天数 + 时间
    html += `<div class="dm-log-header"><span class="dm-log-day">第${day}天</span><span class="dm-log-time">${time}</span></div>`;

    // 行动文本
    if (d.action) {
      html += `<div class="dm-log-action-text">🎯 ${this._replaceYou(d.action)}</div>`;
    }

    // 游戏开始
    if (type === 'game_start') {
      html += `<div class="dm-log-narrative" style="color:#2563eb;font-weight:600;">⚔️ ${d.character_name || '?'} 开始了冒险！</div>`;
      html += `<div style="font-size:11px;color:var(--text-muted);">职业：${d.class_name || ''} · 世界：${d.world_name || ''}</div>`;
    }
    // 场景
    else if (type === 'scene') {
      if (d.description) html += `<div class="dm-log-narrative">${this._replaceYou(d.description)}</div>`;
      if (d.location) html += `<div style="font-size:11px;color:var(--text-muted);margin-top:4px;">📍 ${d.location}</div>`;
    }
    // 行动
    else if (type === 'action') {
      // 叙事
      if (d.narrative) html += `<div class="dm-log-narrative">${this._replaceYou(d.narrative)}</div>`;
      else if (d.description) html += `<div class="dm-log-narrative">${this._replaceYou(d.description)}</div>`;

      // 战斗结果
      if (d.combat) {
        if (d.combat.victory) {
          html += `<div style="color:#16a34a;font-size:12px;font-weight:600;margin-top:4px;">⚔️ 胜利！${d.combat.enemy_names?.length ? '击败 ' + d.combat.enemy_names.join('、') : ''}</div>`;
        }
        if (d.combat.combat_log?.length) {
          const lines = d.combat.combat_log.map(l => `<div class="dm-log-combat-line">${this._replaceYou(l)}</div>`).join('');
          html += `<div class="dm-log-combat-box">${lines}</div>`;
        }
      }

      // 奖励
      if (d.exp_gained || d.gold_gained) {
        html += `<div class="dm-log-rewards">`;
        if (d.exp_gained) html += `经验+${d.exp_gained} `;
        if (d.gold_gained) html += `金币+${d.gold_gained}`;
        html += `</div>`;
      }

      // 升级
      if (d.leveled_up) {
        html += `<div class="dm-log-levelup">🎉 升级到 Lv.${d.new_level}！</div>`;
      }

      // 装备掉落
      if (d.drops?.length) {
        html += `<div class="dm-log-drops">${d.drops.map(drop => `🎁 ${drop.name}（${drop.rarity_name || '普通'}）`).join(' ')}</div>`;
      }

      // HP/MP 变化
      if (d.hp_change || d.mp_change || d.user_hp_change || d.user_mp_change) {
        html += `<div style="font-size:11px;color:var(--text-muted);margin-top:2px;">`;
        if (d.hp_change) html += `💧 HP${d.hp_change > 0 ? '+' : ''}${d.hp_change} `;
        if (d.mp_change) html += `💧 MP${d.mp_change > 0 ? '+' : ''}${d.mp_change} `;
        if (d.user_hp_change) html += `👤 HP${d.user_hp_change > 0 ? '+' : ''}${d.user_hp_change} `;
        if (d.user_mp_change) html += `👤 MP${d.user_mp_change > 0 ? '+' : ''}${d.user_mp_change}`;
        html += `</div>`;
      }

      // 购买/花费
      if (d.gold_spent) {
        html += `<div style="font-size:11px;color:#dc2626;margin-top:2px;">💰 花费 ${d.gold_spent} 金币</div>`;
      }
      if (d.items_to_backpack?.length) {
        html += `<div class="dm-log-drops">📦 获得 ${d.items_to_backpack.join('、')}</div>`;
      }
    }

    html += `</div>`;
    return html;
  },

  _replaceYou(text) {
    if (!text) return text;
    const name = this._userName || '用户';
    return text
      .replace(/你们/g, name + '们')
      .replace(/你/g, name);
  },

  // ── 发起行动 ──
  async sendAction() {
    const input = document.getElementById('dmActionInput');
    const btn = document.getElementById('dmSendBtn');
    const text = input.value.trim();
    if (!text || this._sending) return;

    this._sending = true;
    input.disabled = true;
    btn.disabled = true;
    btn.textContent = '行动中...';

    try {
      const resp = await fetch(`${this.API_BASE}/api/death-mode/action`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ free_action: text, sender: 'user' }),
      });
      const result = await resp.json();

      if (result.error) {
        alert('行动失败：' + (result.error || '未知错误'));
      }

      // 立即刷新
      await this.refreshAll();

      // 死亡处理
      if (result.death_pending) {
        const who = result.death_who === 'user' ? this._userName : (result.character?.name || 'AI角色');
        if (result.last_words) {
          alert(`💀 ${who} 已倒下\n\n遗言：${result.last_words}\n\n回复"继续"独自冒险，或"结束"存入名人堂`);
        } else {
          alert(`💀 ${who} 已倒下\n\n回复"继续"独自冒险，或"结束"存入名人堂`);
        }
      }
    } catch (e) {
      alert('无法连接死亡模式服务（8769），请确认主程序已启动');
    } finally {
      this._sending = false;
      input.disabled = false;
      btn.disabled = false;
      btn.textContent = '发起行动';
      input.value = '';
      input.focus();
    }
  },

  // 输入框回车发送
  onKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      this.sendAction();
    }
  },
};
