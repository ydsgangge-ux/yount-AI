/**
 * SimLife UI 管理 v2
 */

const UI = {
  $city: null,
  $weekday: null,
  $time: null,
  $weather: null,
  $moodEmoji: null,
  $moodBar: null,
  $moodValue: null,
  $activityText: null,
  $sceneTag: null,
  $logList: null,
  $setupOverlay: null,
  $mainUi: null,
  $userOverlay: null,
  $userEnterBtn: null,
  _userProfile: null,

  _worlds: [],
  _selectedWorldId: 'modern',

  init() {
    this.$city = document.getElementById('disp-city');
    this.$weekday = document.getElementById('disp-weekday');
    this.$time = document.getElementById('disp-time');
    this.$weather = document.getElementById('disp-weather');
    this.$moodEmoji = document.getElementById('mood-emoji');
    this.$moodBar = document.getElementById('mood-bar');
    this.$moodValue = document.getElementById('mood-value');
    this.$activityText = document.getElementById('activity-text');
    this.$sceneTag = document.getElementById('scene-tag');
    this.$logList = document.getElementById('log-list');
    this.$setupOverlay = document.getElementById('setup-overlay');
    this.$mainUi = document.getElementById('main-ui');
    this.$userOverlay = document.getElementById('user-overlay');
    this.$userEnterBtn = document.getElementById('user-enter-btn');

    // 启动时加载用户入驻状态 + 世界观列表
    this._loadUserProfile();
    this._loadWorlds();
  },

  async _loadWorlds() {
    try {
      const resp = await fetch('/api/worlds');
      if (resp.ok) {
        const data = await resp.json();
        this._worlds = data.worlds || [];
        this._selectedWorldId = data.current || 'modern';
        this._refreshWorldSelector();
      }
    } catch (e) { /* 忽略 */ }
  },

  _refreshWorldSelector() {
    const sel = document.getElementById('inp-world');
    if (!sel) return;
    // 清空并重建选项
    const currentValue = sel.value;
    sel.innerHTML = '<option value="modern">🏢 现代都市（默认）</option>';
    for (const w of this._worlds) {
      if (w.world_id === 'modern') continue;
      const opt = document.createElement('option');
      opt.value = w.world_id;
      const typeEmoji = { fantasy: '🗡️', modern_power: '⚡', scifi: '🚀', xianxia: '⛩️', post_apocalyptic: '☢️', custom: '🌈' };
      opt.textContent = (typeEmoji[w.world_type] || '🌍') + ' ' + w.world_name;
      sel.appendChild(opt);
    }
    sel.innerHTML += '<option value="__ai_generate">🤖 AI 生成自定义世界…</option>';
    sel.innerHTML += '<option value="__import">📋 导入世界观 JSON…</option>';
    sel.value = this._selectedWorldId || 'modern';
    onWorldChange();
  },

  async _loadUserProfile() {
    try {
      const resp = await fetch('/api/user/profile');
      if (resp.ok) {
        this._userProfile = await resp.json();
        this._updateEnterButton();
      }
    } catch (e) { /* 忽略 */ }
  },

  _updateEnterButton() {
    if (!this.$userEnterBtn || !this._userProfile) return;
    const entered = this._userProfile.entered;
    const name = this._userProfile.name || '你';
    const relation = this._userProfile.relation || '';

    if (entered) {
      this.$userEnterBtn.className = 'entered';
      this.$userEnterBtn.innerHTML = '<span id="user-status-dot" class="active"></span>' + name + '（' + relation + '）在场';
    } else if (relation) {
      this.$userEnterBtn.className = '';
      this.$userEnterBtn.innerHTML = '🏠 进入世界';
    } else {
      this.$userEnterBtn.className = '';
      this.$userEnterBtn.innerHTML = '👤 设置我的身份';
    }
  },

  showSetup() {
    this.$setupOverlay.style.display = 'flex';
    this.$mainUi.style.display = 'none';
  },

  hideSetup() {
    this.$setupOverlay.style.display = 'none';
    this.$mainUi.style.display = 'flex';
  },

  updateTopBar(data) {
    if (data.city) this.$city.textContent = data.city;
    if (data.weekday) this.$weekday.textContent = data.weekday;
    if (data.time) this.$time.textContent = data.time;
    if (data.weather) this.$weather.textContent = data.weather;
  },

  updateMood(mood) {
    const pct = Math.max(0, Math.min(100, mood));
    this.$moodBar.style.width = pct + '%';

    let color;
    if (pct >= 70) color = 'var(--mood-good)';
    else if (pct >= 40) color = 'var(--mood-mid)';
    else color = 'var(--mood-bad)';
    this.$moodBar.style.background = color;

    let emoji;
    if (pct >= 85) emoji = '😄';
    else if (pct >= 70) emoji = '😊';
    else if (pct >= 55) emoji = '🙂';
    else if (pct >= 40) emoji = '😐';
    else if (pct >= 25) emoji = '😔';
    else emoji = '😢';
    this.$moodEmoji.textContent = emoji;

    if (this.$moodValue) this.$moodValue.textContent = pct;
  },

  updateActivity(text, sceneLabel) {
    this.$activityText.textContent = text || '';
    if (this.$sceneTag && sceneLabel) {
      this.$sceneTag.textContent = sceneLabel;
    }
  },

  updateLogs(logs) {
    if (!logs || logs.length === 0) return;

    // 用 JSON 序列化比较，避免日志条数达到上限后无法追加
    const currentHtml = this.$logList.innerHTML;
    const newHtml = logs.map(log =>
      `<div class="log-item"><span class="log-time">${log.time}</span><span class="log-event">${log.event}</span></div>`
    ).join('');
    if (newHtml === currentHtml) return;

    this.$logList.innerHTML = newHtml;

    const panel = document.getElementById('log-panel');
    panel.scrollTop = panel.scrollHeight;
  },

  clearLogs() {
    this.$logList.innerHTML = '';
  },

  setSetupStatus(text) {
    document.getElementById('setup-status').textContent = text;
  },

  setGenerateButton(enabled) {
    document.getElementById('btn-generate').disabled = !enabled;
  },
};

// 暴露全局函数
function skipSetup() {
  UI.hideSetup();
}

function toggleAllLogs() {
  // TODO: 展开全部日志的弹窗
}

async function generateWorld() {
  const anchor = {
    character_name: document.getElementById('inp-name').value.trim(),
    city: document.getElementById('inp-city').value,
    occupation_hint: document.getElementById('inp-occupation').value.trim(),
    age: parseInt(document.getElementById('inp-age').value) || 24,
    personality_word: document.getElementById('inp-personality').value.trim(),
  };

  if (!anchor.character_name) {
    UI.setSetupStatus('请填写角色名字');
    return;
  }

  UI.setSetupStatus('正在生成人物卡和世界... AI 可能耗时 10-30 秒');
  UI.setGenerateButton(false);

  try {
    const resp = await fetch('/api/setup/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ anchor }),
    });

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || '生成失败');
    }

    const data = await resp.json();
    UI.setSetupStatus('✅ 世界生成完成！');

    setTimeout(() => {
      UI.hideSetup();
      if (typeof Game !== 'undefined') {
        Game.onCharacterReady(data.card);
      }
    }, 800);

  } catch (e) {
    UI.setSetupStatus('❌ ' + e.message);
    UI.setGenerateButton(true);
  }
}

/* ── 设置菜单 ── */

function toggleSettingsMenu() {
  const menu = document.getElementById('settings-menu');
  menu.classList.toggle('show');
  if (menu.classList.contains('show')) {
    setTimeout(() => {
      document.addEventListener('click', _closeSettingsOnOutsideClick);
    }, 0);
  }
}

function _closeSettingsOnOutsideClick(e) {
  const menu = document.getElementById('settings-menu');
  const btn = document.getElementById('settings-btn');
  if (!menu.contains(e.target) && !btn.contains(e.target)) {
    menu.classList.remove('show');
    document.removeEventListener('click', _closeSettingsOnOutsideClick);
  }
}

function openSetupForReinit() {
  document.getElementById('settings-menu').classList.remove('show');
  if (!confirm('重新初始化会删除当前角色和世界，确定要重新开始吗？')) return;
  fetch('/api/reset', { method: 'POST' })
    .then(r => r.json())
    .then(() => { location.reload(); })
    .catch(e => { alert('重置失败：' + e.message); });
}

function openUserPanelFromMenu() {
  document.getElementById('settings-menu').classList.remove('show');
  const overlay = document.getElementById('user-overlay');
  if (overlay.style.display === 'flex') {
    closeUserPanel();
    return;
  }
  if (UI._userProfile) {
    document.getElementById('inp-user-name').value = UI._userProfile.name || '';
    document.getElementById('inp-user-relation').value = UI._userProfile.relation || '';
    document.getElementById('inp-user-role').value = UI._userProfile.world_role || '';
  }
  const hasRelation = UI._userProfile && UI._userProfile.relation;
  const btnEnter = document.getElementById('btn-user-enter');
  const btnLeave = document.getElementById('btn-user-leave');
  if (UI._userProfile && UI._userProfile.entered) {
    btnEnter.textContent = '✨ 保存修改';
    btnLeave.style.display = '';
  } else {
    btnEnter.textContent = hasRelation ? '✨ 进入世界' : '✨ 保存并进入';
    btnLeave.style.display = 'none';
  }
  overlay.style.display = 'flex';
}

function doResetSimLife() {
  document.getElementById('settings-menu').classList.remove('show');
  if (!confirm('这将清空 SimLife 的所有数据（角色、世界、NPC、用户身份），确定吗？')) return;
  fetch('/api/reset', { method: 'POST' })
    .then(r => r.json())
    .then(() => { location.reload(); })
    .catch(e => { alert('重置失败：' + e.message); });
}

/* ── 用户入驻管理 ── */

function toggleUserPanel() {
  const overlay = document.getElementById('user-overlay');
  if (overlay.style.display === 'flex') {
    closeUserPanel();
    return;
  }

  // 已入驻状态：打开面板可修改身份或离开
  // （不再直接执行离开，让用户在面板里选择）
  
  // 填充已有信息
  if (UI._userProfile) {
    document.getElementById('inp-user-name').value = UI._userProfile.name || '';
    document.getElementById('inp-user-relation').value = UI._userProfile.relation || '';
    document.getElementById('inp-user-role').value = UI._userProfile.world_role || '';
  }

  const hasRelation = UI._userProfile && UI._userProfile.relation;
  const btnEnter = document.getElementById('btn-user-enter');
  const btnLeave = document.getElementById('btn-user-leave');

  if (UI._userProfile && UI._userProfile.entered) {
    btnEnter.textContent = '✨ 保存修改';
    btnLeave.style.display = '';
  } else {
    btnEnter.textContent = hasRelation ? '✨ 进入世界' : '✨ 保存并进入';
    btnLeave.style.display = 'none';
  }

  overlay.style.display = 'flex';
}

function closeUserPanel() {
  document.getElementById('user-overlay').style.display = 'none';
}

async function doUserEnter() {
  const name = document.getElementById('inp-user-name').value.trim();
  const relation = document.getElementById('inp-user-relation').value.trim();
  const worldRole = document.getElementById('inp-user-role').value.trim();

  if (!relation) {
    alert('请填写你和角色的关系');
    return;
  }

  try {
    // 先保存身份信息
    await fetch('/api/user/profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, relation, world_role: worldRole }),
    });

    // 再进入世界
    const resp = await fetch('/api/user/enter', { method: 'POST' });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || '进入失败');
    }

    UI._userProfile = { name, relation, world_role: worldRole, entered: true };
    UI._updateEnterButton();
    closeUserPanel();

  } catch (e) {
    alert('操作失败：' + e.message);
  }
}

async function doUserLeave() {
  if (!confirm('确定要离开 SimLife 世界吗？')) return;

  try {
    const resp = await fetch('/api/user/leave', { method: 'POST' });
    if (resp.ok && UI._userProfile) {
      UI._userProfile.entered = false;
      UI._updateEnterButton();
    }
  } catch (e) {
    alert('操作失败：' + e.message);
  }
}

/* ── 世界观管理 ── */

function onWorldChange() {
  const sel = document.getElementById('inp-world');
  const val = sel.value;

  const modernFields = document.getElementById('modern-fields');
  const cwFields = document.getElementById('custom-world-fields');
  const aiPanel = document.getElementById('ai-gen-world-panel');
  const importPanel = document.getElementById('import-world-panel');
  const infoBar = document.getElementById('world-info-bar');

  // 默认全部隐藏
  modernFields.style.display = 'none';
  cwFields.style.display = 'none';
  aiPanel.style.display = 'none';
  importPanel.style.display = 'none';
  infoBar.style.display = 'none';

  if (val === 'modern') {
    modernFields.style.display = '';
  } else if (val === '__ai_generate') {
    aiPanel.style.display = '';
    cwFields.style.display = '';
  } else if (val === '__import') {
    importPanel.style.display = '';
    cwFields.style.display = '';
  } else {
    // 已有的自定义世界观
    cwFields.style.display = '';
    // 显示世界观摘要
    const world = UI._worlds.find(w => w.world_id === val);
    if (world) {
      infoBar.style.display = '';
      const typeNames = { fantasy: '奇幻魔法', modern_power: '现世超武', scifi: '科幻未来', xianxia: '仙侠修真', post_apocalyptic: '末世废土', custom: '自定义' };
      infoBar.textContent = '🌍 ' + world.world_name + '  |  类型：' + (typeNames[world.world_type] || world.world_type);
    }
  }

  // 同步名字字段
  const nameModern = document.getElementById('inp-name');
  const nameCw = document.getElementById('inp-name-cw');
  if (nameModern && nameCw) {
    if (val === 'modern') {
      nameCw.value = nameModern.value;
    } else {
      nameModern.value = nameCw.value;
    }
  }

  // 死亡模式按钮：仅在选中已生成的非现代世界观时显示
  const dmBtn = document.getElementById('btn-death-mode-setup');
  if (dmBtn) {
    if (val && val !== 'modern' && val !== '__ai_generate' && val !== '__import') {
      dmBtn.style.display = '';
    } else {
      dmBtn.style.display = 'none';
    }
  }
}

async function doSwitchWorld(worldId) {
  try {
    const resp = await fetch('/api/worlds/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ world_id: worldId }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || '切换失败');
    }
    UI._selectedWorldId = worldId;
    UI.setSetupStatus('✅ 已切换到 ' + worldId);
  } catch (e) {
    UI.setSetupStatus('❌ ' + e.message);
  }
}

async function doAIGenerateWorld() {
  const worldType = document.getElementById('inp-ai-world-type').value;
  const theme = document.getElementById('inp-ai-world-theme').value.trim();
  const role = document.getElementById('inp-ai-world-role').value.trim();

  if (!theme) {
    UI.setSetupStatus('请至少填写「核心主题」');
    return;
  }

  UI.setSetupStatus('🧙 AI 正在生成世界观设定… 这可能需要 30-60 秒');
  const btn = document.querySelector('#ai-gen-world-panel button');
  btn.disabled = true;
  btn.textContent = '⏳ 生成中…';

  try {
    const resp = await fetch('/api/worlds/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        world_type: worldType,
        core_theme: theme,
        character_role_hint: role,
      }),
    });

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || '生成失败');
    }

    const data = await resp.json();
    UI.setSetupStatus('✅ 世界观「' + (data.world_name || data.world_id) + '」生成成功！');

    // 刷新列表并选中
    UI._selectedWorldId = data.world_id;
    await UI._loadWorlds();

  } catch (e) {
    UI.setSetupStatus('❌ ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = '🧙 AI 生成世界观设定（约 30-60 秒）';
  }
}

// 下载世界观模板 JSON
async function doDownloadWorldTemplate() {
  try {
    const resp = await fetch('/api/worlds/template');
    if (!resp.ok) throw new Error('获取模板失败');
    const data = await resp.json();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'world_setting_template.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    UI.setSetupStatus('✅ 模板已下载，用 LLM 填充后导入');
  } catch (e) {
    UI.setSetupStatus('❌ 下载模板失败：' + e.message);
  }
}

// 下载世界观生成提示词 Markdown
async function doDownloadWorldPrompt() {
  try {
    const resp = await fetch('/api/worlds/generate-prompt');
    if (!resp.ok) throw new Error('获取提示词失败');
    const data = await resp.json();
    const content = data.content || '';
    if (!content) {
      UI.setSetupStatus('❌ 提示词文件不存在');
      return;
    }
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'generate_world_prompt.md';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    UI.setSetupStatus('✅ 生成提示词已下载，复制到任意 LLM 即可生成世界观');
  } catch (e) {
    UI.setSetupStatus('❌ 下载提示词失败：' + e.message);
  }
}

// 上传 JSON 文件，自动填入文本框
function onWorldFileSelected(input) {
  const file = input.files && input.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (e) => {
    const ta = document.getElementById('inp-import-json');
    if (ta) {
      ta.value = e.target.result;
      UI.setSetupStatus('📂 已载入 ' + file.name + '，确认无误后点击「导入并使用」');
    }
  };
  reader.onerror = () => UI.setSetupStatus('❌ 读取文件失败');
  reader.readAsText(file, 'utf-8');
  // 重置 input，允许再次选择同一文件
  input.value = '';
}

async function doImportWorld() {
  const jsonStr = document.getElementById('inp-import-json').value.trim();
  if (!jsonStr) {
    UI.setSetupStatus('请粘贴世界观 JSON 或从文件导入');
    return;
  }

  let setting;
  try {
    setting = JSON.parse(jsonStr);
  } catch (e) {
    UI.setSetupStatus('❌ JSON 格式错误：' + e.message);
    return;
  }

  UI.setSetupStatus('正在导入…');

  try {
    const resp = await fetch('/api/worlds/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ setting }),
    });

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || '导入失败');
    }

    const data = await resp.json();
    UI.setSetupStatus('✅ 世界观「' + (data.world_name || data.world_id) + '」导入成功！');

    UI._selectedWorldId = data.world_id;
    await UI._loadWorlds();

  } catch (e) {
    UI.setSetupStatus('❌ ' + e.message);
  }
}

// 改写 generateWorld 以支持非现代世界
const _originalGenerateWorld = generateWorld;
window.generateWorld = async function() {
  const sel = document.getElementById('inp-world');
  const isModern = sel.value === 'modern';

  // 如果选了现代世界，确保切换回去（之前可能选了异世界）
  if (isModern) {
    await doSwitchWorld('modern');
  }
  // 如果选了自定义世界观但未实际切换
  else if (sel.value !== '__ai_generate' && sel.value !== '__import') {
    await doSwitchWorld(sel.value);
  }

  const anchor = {
    character_name: isModern
      ? document.getElementById('inp-name').value.trim()
      : document.getElementById('inp-name-cw').value.trim(),
    city: isModern ? document.getElementById('inp-city').value : '',
    occupation_hint: isModern
      ? document.getElementById('inp-occupation').value.trim()
      : document.getElementById('inp-occupation-cw').value.trim(),
    age: parseInt(isModern
      ? document.getElementById('inp-age').value
      : document.getElementById('inp-age-cw').value) || 24,
    personality_word: isModern
      ? document.getElementById('inp-personality').value.trim()
      : document.getElementById('inp-personality-cw').value.trim(),
  };

  if (!anchor.character_name) {
    UI.setSetupStatus('请填写角色名字');
    return;
  }

  UI.setSetupStatus('正在生成人物卡和世界... AI 可能耗时 10-30 秒');
  UI.setGenerateButton(false);

  try {
    const resp = await fetch('/api/setup/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ anchor }),
    });

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || '生成失败');
    }

    const data = await resp.json();
    UI.setSetupStatus('✅ 世界生成完成！');

    setTimeout(() => {
      UI.hideSetup();
      if (typeof Game !== 'undefined') {
        Game.onCharacterReady(data.card);
      }
    }, 800);

  } catch (e) {
    UI.setSetupStatus('❌ ' + e.message);
    UI.setGenerateButton(true);
  }
};

// ── 剧情存档 ─────────────────────────────────────────
function openStoryArchive() {
  document.getElementById('settings-menu').classList.remove('show');
  const overlay = document.getElementById('archive-overlay');
  overlay.style.display = 'flex';
  loadArchiveList();
}

function openDeathMode() {
  document.getElementById('settings-menu').classList.remove('show');
  if (window.DeathModeUI) {
    // 检查是否有进行中的游戏
    fetch('/api/death-mode/state')
      .then(r => r.json())
      .then(data => {
        if (data.active && data.is_alive) {
          DeathModeUI._state = data;
          DeathModeUI.showGamePanel();
        } else {
          DeathModeUI.showCreatePanel();
        }
      })
      .catch(() => {
        DeathModeUI.showCreatePanel();
      });
  }
}

function enterDeathModeSetup() {
  // 从setup-overlay进入死亡模式设定
  if (window.DeathModeUI) {
    DeathModeUI.showCreatePanel();
  }
}

function closeStoryArchive() {
  document.getElementById('archive-overlay').style.display = 'none';
}

async function loadArchiveList() {
  const listEl = document.getElementById('archive-list');
  listEl.innerHTML = '加载中…';
  try {
    const resp = await fetch('/api/story/archive');
    const data = await resp.json();
    const archives = data.archives || [];
    if (archives.length === 0) {
      listEl.innerHTML = '<div style="padding:40px 0;color:#8899aa;">暂无存档，异世界模式运行一天后会自动生成</div>';
      return;
    }
    let html = '';
    for (const a of archives) {
      html += `<div class="archive-item" onclick="loadArchiveDay('${a.date}')"
        style="cursor:pointer;padding:12px 14px;margin-bottom:8px;background:rgba(0,0,0,0.2);border:1px solid rgba(255,255,255,0.05);border-radius:10px;transition:background 0.2s;"
        onmouseover="this.style.background='rgba(255,255,255,0.08)'"
        onmouseout="this.style.background='rgba(0,0,0,0.2)'">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <span style="color:#e0e0e0;font-weight:bold;">📅 ${a.date}</span>
          <span style="font-size:12px;color:#8899aa;">${a.node_count} 个节点 · 心情 ${a.mood}/100</span>
        </div>
        <div style="font-size:12px;color:#8899aa;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${a.summary || '暂无记录'}</div>
      </div>`;
    }
    listEl.innerHTML = html;
  } catch (e) {
    listEl.innerHTML = `<div style="padding:40px 0;color:#e94560;">加载失败：${e.message}</div>`;
  }
}

async function loadArchiveDay(dateStr) {
  const listEl = document.getElementById('archive-list');
  listEl.innerHTML = '加载中…';
  try {
    const resp = await fetch(`/api/story/archive/${dateStr}`);
    const data = await resp.json();
    let html = `<div style="margin-bottom:12px;">
      <button onclick="loadArchiveList()" style="background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.08);color:#8899aa;padding:6px 14px;border-radius:6px;cursor:pointer;font-size:12px;">← 返回列表</button>
      <span style="color:#e0e0e0;font-weight:bold;font-size:15px;margin-left:10px;">📅 ${dateStr}</span>
    </div>`;
    // 日志
    const logs = data.today_log || [];
    if (logs.length > 0) {
      html += '<div style="margin-bottom:12px;"><div style="font-size:12px;color:#8899aa;margin-bottom:6px;">📋 日志</div>';
      for (const log of logs) {
        html += `<div style="padding:4px 0;font-size:13px;color:#e0e0e0;border-bottom:1px solid rgba(255,255,255,0.03);">
          <span style="color:#e94560;opacity:0.7;width:42px;display:inline-block;">${log.time || ''}</span>
          ${log.event || ''}
        </div>`;
      }
      html += '</div>';
    }
    // 剧情节点
    const plan = data.day_plan || [];
    if (plan.length > 0) {
      html += '<div style="font-size:12px;color:#8899aa;margin-bottom:6px;">📖 剧情节点</div>';
      for (const node of plan) {
        html += `<div style="padding:10px 12px;margin-bottom:6px;background:rgba(0,0,0,0.2);border:1px solid rgba(255,255,255,0.05);border-radius:8px;">
          <div style="display:flex;gap:10px;align-items:center;margin-bottom:4px;">
            <span style="color:#e94560;font-size:12px;font-weight:bold;">${node.time || ''}</span>
            <span style="color:#4ecca3;font-size:12px;">${node.label || ''}</span>
            <span style="color:#8899aa;font-size:11px;">${node.scene || ''}</span>
          </div>`;
        if (node.expanded) {
          html += `<div style="font-size:13px;color:#e0e0e0;line-height:1.6;padding:6px 0;">${node.expanded}</div>`;
        } else if (node.activity) {
          html += `<div style="font-size:12px;color:#8899aa;">${node.activity}</div>`;
        }
        html += '</div>';
      }
    }
    listEl.innerHTML = html;
  } catch (e) {
    listEl.innerHTML = `<div style="padding:40px 0;color:#e94560;">加载失败：${e.message}</div>`;
  }
}
