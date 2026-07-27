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

  async init() {
    UI.init();

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

      // 主线进度展示（非现代世界）
      if (state.life_arc) {
        let arcEl = document.getElementById('life-arc-panel');
        if (!arcEl) {
          arcEl = document.createElement('div');
          arcEl.id = 'life-arc-panel';
          arcEl.style.cssText = 'margin-top:4px;padding:8px 10px;background:rgba(0,0,0,0.5);border-radius:8px;font-size:11px;line-height:1.7;';
          const storyPanel = document.getElementById('story-panel');
          if (storyPanel) storyPanel.appendChild(arcEl);
        }
        const arc = state.life_arc;
        const pct = arc.progress_percent || 0;
        let html = `<div style="color:#f59e0b;margin-bottom:4px;font-size:12px;">${arc.title}</div>`;
        html += `<div style="background:#333;border-radius:4px;height:6px;margin-bottom:6px;"><div style="background:#f59e0b;border-radius:4px;height:6px;width:${pct}%;transition:width 0.3s;"></div></div>`;
        if (arc.current_stage) {
          html += `<div style="color:#ccc;margin-bottom:4px;">当前：${arc.current_stage}</div>`;
        }
        if (arc.stages && arc.stages.length > 0) {
          arc.stages.forEach(s => {
            const color = s.status === 'completed' ? '#22c55e' : s.status === 'active' ? '#f59e0b' : '#555';
            const marker = s.status === 'completed' ? '✓' : s.status === 'active' ? '▶' : '○';
            html += `<div style="color:${color}">${marker} ${s.name}（${s.duration_days}天）</div>`;
          });
        }
        arcEl.innerHTML = html;
      }

      // 当天大纲展示（非现代世界）— 渐进式，只显示已到达的节点
      if (state.day_plan && state.day_plan.length > 0 && isStoryMode) {
        let planEl = document.getElementById('day-plan-panel');
        if (!planEl) {
          planEl = document.createElement('div');
          planEl.id = 'day-plan-panel';
          planEl.style.cssText = 'margin-top:4px;padding:6px 10px;background:rgba(0,0,0,0.5);border-radius:8px;font-size:11px;line-height:1.6;';
          const storyPanel = document.getElementById('story-panel');
          if (storyPanel) storyPanel.appendChild(planEl);
        }
        const progress = state.day_plan_progress || 0;
        const cast = state.story_cast || [];
        const total = state.day_plan.length;
        let html = '<div style="color:#a78bfa;margin-bottom:4px;">今日剧情 <span style="color:#555;font-size:10px;">' + progress + '/' + total + '</span></div>';
        state.day_plan.forEach((item, idx) => {
          // 只显示已到达的节点，未来的不显示
          if (idx > progress) return;
          const isPast = idx < progress;
          const isNow = idx === progress;
          const color = isPast ? '#666' : '#a78bfa';
          const marker = isPast ? '✓' : '▶';

          // NPC名字
          let npcName = '';
          if (item.npc && cast.length > 0) {
            const npc = cast.find(c => c.id === item.npc);
            if (npc) npcName = ' <span style="color:#f59e0b;">💬' + npc.name + '</span>';
          }

          html += '<div style="color:' + color + '" id="plan-item-' + idx + '">' + marker + ' ' + item.time + ' ' + item.label + npcName + '</div>';
          // 显示简短的activity
          if (item.activity) {
            html += '<div style="color:#555;margin:1px 0 3px 16px;font-size:11px;">' + item.activity + '</div>';
          }
        });
        planEl.innerHTML = html;
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

    // 异世界模式：隐藏日志面板（内容由 day_plan 面板承载）
    const logPanel = document.getElementById('log-panel');
    if (logPanel) logPanel.style.display = isStoryMode ? 'none' : '';

    // 异世界模式：显示故事面板容器
    const storyPanel = document.getElementById('story-panel');
    if (storyPanel) storyPanel.style.display = isStoryMode ? 'block' : 'none';
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
