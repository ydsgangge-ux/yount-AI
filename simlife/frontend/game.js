/**
 * SimLife 主循环 v2
 */

const API_BASE = '';

const Game = {
  renderer: null,
  currentScene: '',
  character: null,
  npcCards: [],
  initialized: false,
  pollInterval: null,
  _activeNpcIds: [],
  _storySelectedIdx: -1,   // 剧情面板当前选中的节点索引（-1 表示跟随当前进度）
  _storyExpanded: {},      // 缓存节点展开文本：{idx: text}
  _storyLoading: {},       // 正在加载的节点

  async init() {
    UI.init();

    // 初始化死亡模式（检查是否有进行中的游戏）
    if (window.DeathModeUI) {
      DeathModeUI.init();
    }

    const canvas = document.getElementById('game-canvas');
    const charCanvas = document.getElementById('char-canvas');
    this.renderer = new Renderer(canvas, charCanvas);

    try {
      const resp = await fetch(API_BASE + '/api/character');
      const data = await resp.json();

      if (data.initialized) {
        this.character = data.card;
        this.initialized = true;
        UI.hideSetup();
        this.startLoop();
      } else {
        UI.showSetup();
      }
    } catch (e) {
      console.error('Failed to check status:', e);
      UI.showSetup();
    }
  },

  onCharacterReady(card) {
    this.character = card;
    this.initialized = true;
    this.startLoop();
  },

  startLoop() {
    this.render();
    this.poll();
    this.pollInterval = setInterval(() => this.poll(), 60000);
  },

  render() {
    if (!this.character) {
      requestAnimationFrame(() => this.render());
      return;
    }

    const pixel = this.character.pixel_appearance || {};
    const mainChar = {
      gender: pixel.gender || 'female',
      hairColor: pixel.hair_color || '#4A3728',
      outfitColor: pixel.default_outfit_color || '#F5F0E8',
    };

    const activeNpcs = [];
    if (this.npcCards) {
      this._activeNpcIds.forEach(id => {
        const npc = this.npcCards.find(n => n.id === id);
        if (npc) {
          activeNpcs.push({
            variant: npc.pixel_variant ?
              parseInt(npc.pixel_variant.replace(/\D/g, '')) || 0 : 0,
          });
        }
      });
    }

    const bgCount = this._getBgNpcCount(this.currentScene);

    this.renderer.drawScene(
      this.currentScene || 'HOME_EVENING',
      mainChar,
      activeNpcs,
      bgCount,
      this._isStoryMode || false,
      this._bgHint || null
    );

    requestAnimationFrame(() => this.render());
  },

  async poll() {
    if (!this.initialized) return;

    try {
      const resp = await fetch(API_BASE + '/api/world/state');
      const state = await resp.json();

      if (state.error) return;

      const sceneChanged = state.scene !== this.currentScene;
      const isStoryMode = state.is_story_mode || false;
      this._isStoryMode = isStoryMode;
      this._bgHint = state.bg_hint || null;

      const now = new Date();
      const weekdays = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
      UI.updateTopBar({
        city: isStoryMode ? (state.world?.world_name || '') : (this.character?.basic?.city || ''),
        weekday: weekdays[now.getDay()],
        time: now.toTimeString().slice(0, 5),
        weather: isStoryMode ? '' : (state.weather || '⛅'),
      });
      UI.updateMood(state.mood);
      UI.updateActivity(state.activity, state.scene_label || '');

      // 现代模式：显示日志；异世界模式：日志由 day_plan 面板承载
      if (state.latest_log && !isStoryMode) {
        UI.updateLogs(state.latest_log);
      }

      // 世界观信息同步
      if (state.world && state.world.world_name) {
        let worldEl = document.getElementById('world-tag');
        if (!worldEl) {
          worldEl = document.createElement('div');
          worldEl.id = 'world-tag';
          worldEl.style.cssText = 'position:absolute;top:8px;right:8px;background:rgba(139,92,246,0.8);color:#fff;padding:3px 10px;border-radius:12px;font-size:11px;z-index:10;';
          const container = document.getElementById('game-canvas')?.parentElement;
          if (container) container.style.position = 'relative', container.appendChild(worldEl);
        }
        worldEl.textContent = state.world.world_name;
      }

      // 隐藏非现代世界不相关的UI元素
      this._applyStoryModeUI(isStoryMode);

      // 主线进度展示（非现代世界）— 插入到 day-plan-panel 之前
      if (state.life_arc) {
        let arcEl = document.getElementById('life-arc-panel');
        const storyPanel = document.getElementById('story-panel');
        const planElRef = document.getElementById('day-plan-panel');
        if (!arcEl) {
          arcEl = document.createElement('div');
          arcEl.id = 'life-arc-panel';
          arcEl.style.cssText = 'flex-shrink:0;padding:6px 10px;background:rgba(0,0,0,0.35);border-radius:8px;font-size:11px;line-height:1.6;margin-bottom:6px;';
          if (storyPanel && planElRef) storyPanel.insertBefore(arcEl, planElRef);
          else if (storyPanel) storyPanel.appendChild(arcEl);
        }
        const arc = state.life_arc;
        const pct = arc.progress_percent || 0;
        let html = `<div style="color:#f59e0b;margin-bottom:4px;font-size:12px;">${arc.title}</div>`;
        html += `<div style="background:#333;border-radius:4px;height:6px;margin-bottom:6px;"><div style="background:#f59e0b;border-radius:4px;height:6px;width:${pct}%;transition:width 0.3s;"></div></div>`;
        if (arc.current_stage) {
          html += `<div style="color:#ccc;margin-bottom:4px;">当前：${arc.current_stage}</div>`;
        }
        if (arc.stages && arc.stages.length > 0) {
          html += '<div style="display:flex;flex-wrap:wrap;gap:6px;">';
          arc.stages.forEach(s => {
            const color = s.status === 'completed' ? '#22c55e' : s.status === 'active' ? '#f59e0b' : '#555';
            const marker = s.status === 'completed' ? '✓' : s.status === 'active' ? '▶' : '○';
            html += `<span style="color:${color};white-space:nowrap;">${marker} ${s.name}</span>`;
          });
          html += '</div>';
        }
        arcEl.innerHTML = html;
      }

      // 当天剧情（非现代世界）— 进度条 + 正文
      if (state.day_plan && state.day_plan.length > 0 && isStoryMode) {
        this._renderStoryPanel(state);
      }
      if (state.weather && this.renderer && !isStoryMode) {
        const wMap = { 'rainy': 'rainy', 'heavy_rain': 'heavy_rain', 'snow': 'snow', 'cloudy': 'cloudy', 'sunny': 'cloudy' };
        this.renderer.setWeather(wMap[state.weather] || 'cloudy');
      }

      if (sceneChanged && this.currentScene) {
        this.renderer.startFade(() => {
          this.currentScene = state.scene;
        });
      } else {
        this.currentScene = state.scene;
      }

      this._activeNpcIds = state.active_npcs || [];

      // 同步用户入驻状态
      if (state.user) {
        UI._userProfile = {
          ...UI._userProfile,
          entered: state.user.entered,
          name: state.user.name || UI._userProfile?.name || '',
          relation: state.user.relation || UI._userProfile?.relation || '',
        };
        UI._updateEnterButton();

        // 冻结指示器
        const freezeEl = document.getElementById('freeze-indicator');
        if (freezeEl) {
          if (state.user && state.user.entered) {
            freezeEl.classList.add('show');
          } else {
            freezeEl.classList.remove('show');
          }
        }
      }

    } catch (e) {
      console.error('Poll error:', e);
    }
  },

  _applyStoryModeUI(isStoryMode) {
    // 隐藏/显示非相关UI元素
    const weatherEl = document.getElementById('disp-weather');
    if (weatherEl) weatherEl.style.display = isStoryMode ? 'none' : '';

    // 异世界模式：隐藏日志面板（内容由 story-panel 承载）
    const logPanel = document.getElementById('log-panel');
    if (logPanel) logPanel.style.display = isStoryMode ? 'none' : '';

    // 异世界模式：显示故事面板容器
    const storyPanel = document.getElementById('story-panel');
    if (storyPanel) storyPanel.classList.toggle('show', !!isStoryMode);

    // 异世界模式：game-area 收缩到内容高度，把空间让给 story-panel
    const gameArea = document.getElementById('game-area');
    if (gameArea) {
      if (isStoryMode) {
        gameArea.style.flex = '0 0 auto';
        gameArea.style.padding = '8px 0';
      } else {
        gameArea.style.flex = '1';
        gameArea.style.padding = '';
      }
    }
  },

  // ── 剧情面板渲染（异世界模式） ──────────────────────
  _renderStoryPanel(state) {
    const plan = state.day_plan || [];
    const progress = state.day_plan_progress || 0;
    const cast = state.story_cast || [];
    const total = plan.length;

    // 同步缓存后端已经展开过的节点
    plan.forEach((node, idx) => {
      if (node && node.expanded && !this._storyExpanded[idx]) {
        this._storyExpanded[idx] = node.expanded;
      }
    });

    // 决定选中节点：-1 或无效时跟随当前进度
    let sel = this._storySelectedIdx;
    if (sel < 0 || sel >= total) sel = progress;
    if (sel > progress) sel = progress;  // 不允许选未来
    if (sel < 0) sel = 0;
    this._storySelectedIdx = sel;

    // ── 进度条 ──
    const planEl = document.getElementById('day-plan-panel');
    if (planEl) {
      let html = `<span style="color:#a78bfa;font-size:11px;margin-right:8px;">今日剧情 ${progress}/${total}</span>`;
      plan.forEach((item, idx) => {
        const isPast = idx < progress;
        const isNow = idx === progress;
        const isFuture = idx > progress;
        const cls = ['plan-node'];
        if (isPast) cls.push('past');
        if (isNow) cls.push('now');
        if (isFuture) cls.push('future');
        if (idx === sel) cls.push('selected');
        const marker = isPast ? '✓' : isNow ? '▶' : '○';
        const label = isFuture ? '？？' : (item.label || item.time || '');
        html += `<span class="${cls.join(' ')}" data-idx="${idx}">${marker} ${item.time || ''} ${label}</span>`;
      });
      planEl.innerHTML = html;
      planEl.querySelectorAll('.plan-node').forEach(el => {
        el.addEventListener('click', (e) => {
          const idx = parseInt(e.currentTarget.dataset.idx, 10);
          if (idx > progress) return;  // 未来节点不可选
          this._storySelectedIdx = idx;
          this._renderStoryContent(state, idx);
          // 更新选中态
          planEl.querySelectorAll('.plan-node').forEach(n => n.classList.remove('selected'));
          e.currentTarget.classList.add('selected');
        });
      });
      // 滚动到当前节点
      const selEl = planEl.querySelector('.plan-node.selected');
      if (selEl) selEl.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' });
    }

    // ── 正文 ──
    this._renderStoryContent(state, sel);
  },

  _renderStoryContent(state, idx) {
    const contentEl = document.getElementById('story-content');
    if (!contentEl) return;
    const plan = state.day_plan || [];
    const progress = state.day_plan_progress || 0;
    const cast = state.story_cast || [];
    const node = plan[idx];
    if (!node) {
      contentEl.innerHTML = '<div class="scn-empty">暂无剧情</div>';
      return;
    }

    // NPC 名字
    let npcName = '';
    if (node.npc && cast.length > 0) {
      const npc = cast.find(c => c.id === node.npc);
      if (npc) npcName = `<span class="scn-npc">💬 ${npc.name}</span>`;
    }

    const head = `<div class="scn-head">
      <span class="scn-time">${node.time || ''}</span>
      <span class="scn-label">${node.label || ''}</span>
      ${npcName}
    </div>`;

    // 已有缓存文本 → 直接显示
    if (this._storyExpanded[idx]) {
      contentEl.innerHTML = head + `<div class="scn-body">${this._escapeHtml(this._storyExpanded[idx])}</div>`;
      contentEl.scrollTop = contentEl.scrollHeight;
      return;
    }

    // 节点尚未到达
    if (idx > progress) {
      contentEl.innerHTML = head + '<div class="scn-empty">该时刻尚未到来…</div>';
      return;
    }

    // 已到达但还没展开 → 异步调用后端展开接口
    if (this._storyLoading[idx]) return;
    this._storyLoading[idx] = true;
    contentEl.innerHTML = head + '<div class="scn-loading">正在展开剧情…</div>';
    fetch(API_BASE + `/api/story/expand/${idx}`, { method: 'POST' })
      .then(r => r.ok ? r.json() : Promise.reject(new Error('展开失败')))
      .then(data => {
        const text = data.text || '';
        this._storyExpanded[idx] = text;
        // 仍选中同一节点时才更新，避免覆盖用户已切换的查看
        if (this._storySelectedIdx === idx) {
          contentEl.innerHTML = head + `<div class="scn-body">${this._escapeHtml(text)}</div>`;
          contentEl.scrollTop = contentEl.scrollHeight;
        }
      })
      .catch(() => {
        if (this._storySelectedIdx === idx) {
          const fallback = node.activity ? `（简略）${node.activity}` : '剧情展开失败，稍后重试。';
          contentEl.innerHTML = head + `<div class="scn-body" style="color:#8899aa;">${this._escapeHtml(fallback)}</div>`;
        }
      })
      .finally(() => { this._storyLoading[idx] = false; });
  },

  _escapeHtml(s) {
    if (!s) return '';
    return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  },

  _getBgNpcCount(scene) {
    const counts = {
      'COMMUTE_TO_WORK': 4,
      'COMMUTE_TO_HOME': 2,
      'OFFICE_WORKING': 1,
      'OFFICE_LUNCH': 3,
      'STREET_WANDERING': 3,
      'CAFE': 1,
      'PARK': 2,
      'SUPERMARKET': 3,
    };
    return counts[scene] || 0;
  },
};

document.addEventListener('DOMContentLoaded', () => {
  Game.init();
});
