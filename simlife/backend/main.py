"""
SimLife FastAPI 后端入口
端口 8769
"""
import json
import sys
import os
import random
import webbrowser
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── 路径 ──────────────────────────────────────────────
SIMLIFE_DIR = Path(__file__).parent.parent
DATA_DIR = SIMLIFE_DIR / "data"
FRONTEND_DIR = SIMLIFE_DIR / "frontend"

sys.path.insert(0, str(SIMLIFE_DIR.parent))

from simlife.backend.character import (
    CharacterCard, WorldState, LogEntry, SceneEnum, SCENE_LABELS
)
from simlife.backend.world_engine import (
    get_current_scene, get_day_seed, get_time_period_label, catchup_world_state,
    _get_current_travel_destination,
)
from simlife.backend.event_engine import (
    load_event_library, load_scheduled_events, save_scheduled_events,
    load_event_history, record_triggered_event,
    check_daily_micro_events, check_random_events, check_scheduled_events,
    apply_event_consequences, add_scheduled_events
)
from simlife.backend.mood_engine import calculate_mood, get_mood_tone
from simlife.backend.npc_engine import load_npc_cards, get_active_npcs
from simlife.backend.agidpa_reader import AGIDPAReader
from simlife.backend.weather import WeatherService
from simlife.backend.world_engine import get_holiday_info, get_festive_log_entry
from simlife.backend.birthday_engine import (
    check_birthdays_today, get_birthday_mood,
)
from simlife.backend.life_arc_engine import LifeArc

# ── 故事NPC卡司（非现代世界） ────────────────────────────────
STORY_CAST_FILE = DATA_DIR / "story_cast.json"
STORY_ARCHIVE_DIR = DATA_DIR / "story_archive"

# ── 剧情存档 ─────────────────────────────────────────────
def _archive_yesterday_story(world_state, old_date: str):
    """将昨天的剧情存档到 story_archive/YYYY-MM-DD.json"""
    if not _is_non_modern_world():
        return
    if not old_date:
        return
    STORY_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = STORY_ARCHIVE_DIR / f"{old_date}.json"

    # 提取 day_plan（含展开的剧情）
    plan_data = []
    if world_state.day_plan:
        for node in world_state.day_plan:
            plan_data.append({
                "time": node.get("time", ""),
                "scene": node.get("scene", ""),
                "label": node.get("label", ""),
                "activity": node.get("activity", ""),
                "mood_delta": node.get("mood_delta", 0),
                "expanded": node.get("expanded", ""),
            })

    # 提取日志
    log_data = []
    for entry in world_state.today_log:
        log_data.append({"time": entry.time, "event": entry.event})

    archive = {
        "date": old_date,
        "mood": world_state.mood,
        "day_plan": plan_data,
        "today_log": log_data,
    }
    try:
        with open(archive_path, "w", encoding="utf-8") as f:
            json.dump(archive, f, ensure_ascii=False, indent=2)
        print(f"[SimLife] 剧情已存档: {old_date}")
    except Exception as e:
        print(f"[SimLife] 存档失败: {e}")


def _load_archive(date_str: str) -> dict:
    """读取指定日期的剧情存档"""
    path = STORY_ARCHIVE_DIR / f"{date_str}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _list_archives() -> list:
    """列出所有存档日期"""
    if not STORY_ARCHIVE_DIR.exists():
        return []
    archives = []
    for f in sorted(STORY_ARCHIVE_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            archives.append({
                "date": f.stem,
                "mood": data.get("mood", 0),
                "node_count": len(data.get("day_plan", [])),
                "summary": _extract_archive_summary(data),
            })
        except Exception:
            pass
    return archives


def _extract_archive_summary(data: dict) -> str:
    """从存档中提取一句话摘要"""
    logs = data.get("today_log", [])
    plan = data.get("day_plan", [])
    # 优先用最后一条剧情展开的摘要
    for node in reversed(plan):
        expanded = node.get("expanded", "")
        if expanded:
            return expanded[:60] + "…"
    # 回退到日志最后一条
    if logs:
        return logs[-1].get("event", "")[:60] + "…"
    return ""


def _get_recent_story_context(days: int = 7) -> str:
    """读取最近 N 天的剧情存档，格式化为连续的剧情摘要"""
    archives = _list_archives()
    if not archives:
        return ""
    recent = archives[-days:]
    lines = ["【近期剧情回顾】"]
    for a in recent:
        date = a["date"]
        data = _load_archive(date)
        if not data:
            continue
        # 提取关键节点
        key_events = []
        for node in data.get("day_plan", []):
            label = node.get("label", "")
            expanded = node.get("expanded", "")
            if expanded:
                key_events.append(f"  [{node['time']}] {label}：{expanded[:80]}…")
            elif label:
                key_events.append(f"  [{node['time']}] {label}")
        lines.append(f"\n{date}（心情{data.get('mood', 0)}/100）：")
        lines.extend(key_events[:6])  # 最多6个节点
    lines.append("\n以上是已发生的剧情，生成新的一天时请保持故事连续性。")
    return "\n".join(lines)


def _load_story_cast() -> list:
    if STORY_CAST_FILE.exists():
        try:
            with open(STORY_CAST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_story_cast(cast: list):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(STORY_CAST_FILE, "w", encoding="utf-8") as f:
        json.dump(cast, f, ensure_ascii=False, indent=2)

# ── 全局状态 ───────────────────────────────────────────
character_card: Optional[CharacterCard] = None
world_state: Optional[WorldState] = None
agidpa_reader: Optional[AGIDPAReader] = None
weather_service: Optional[WeatherService] = None
last_tick_scene: Optional[str] = None
last_tick_time: float = 0  # 上次 tick 时间戳，用于节流
current_world_id: str = "modern"  # 当前世界观
TICK_THROTTLE_SECONDS = 60  # tick 节流间隔（秒）

# ── App ───────────────────────────────────────────────
app = FastAPI(title="SimLife", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件（前端）
FRONTEND_DIR.mkdir(parents=True, exist_ok=True)


def _load_config() -> dict:
    config_path = DATA_DIR / "simlife_config.json"
    if config_path.exists():
        try:
            content = config_path.read_text(encoding="utf-8").strip()
            if content:
                return json.loads(content)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _load_character_card() -> Optional[CharacterCard]:
    path = DATA_DIR / "character_card.json"
    if path.exists():
        try:
            content = path.read_text(encoding="utf-8").strip()
            if content:
                data = json.loads(content)
                return CharacterCard(**data)
        except (json.JSONDecodeError, KeyError, TypeError, OSError) as e:
            print(f"[SimLife] character_card.json 损坏: {e}")
    return None


def _save_character_card(card: CharacterCard):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "character_card.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(card.model_dump(), f, ensure_ascii=False, indent=2)


def _load_world_state() -> WorldState:
    path = DATA_DIR / "world_state.json"
    if path.exists():
        try:
            content = path.read_text(encoding="utf-8").strip()
            if content:
                data = json.loads(content)
                return WorldState(**data)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"[SimLife] world_state.json 损坏，重新初始化: {e}")
    return WorldState()


def _save_world_state(state: WorldState):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "world_state.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state.model_dump(), f, ensure_ascii=False, indent=2)


def _get_work_style_safe() -> str:
    """安全获取工作模式字符串"""
    if not character_card:
        return "office"
    ws = getattr(character_card.basic, "work_style", "office") or "office"
    return ws


def _is_non_modern_world() -> bool:
    """检查当前是否为非现代世界"""
    try:
        from simlife.worlds.world_manager import get_current_world_id
        global current_world_id
        current_world_id = get_current_world_id()
        return current_world_id != "modern"
    except Exception:
        return False


# ── 异世界场景→背景图映射 ──
_FANTASY_BG_KEYWORDS = [
    (["城镇", "集市", "广场", "街道", "商铺", "小镇", "市场"], "town_square"),
    (["酒馆", "旅馆", "旅店", "客栈", "休息"], "tavern"),
    (["森林", "树林", "丛林", "密林", "精灵"], "forest"),
    (["城堡", "宫殿", "王城", "皇宫", "大厅"], "castle"),
    (["学院", "魔法", "塔", "图书馆", "研究"], "magic_academy"),
    (["地下", "地牢", "副本", "洞窟", "矿坑", "迷宫"], "dungeon"),
    (["营地", "扎营", "篝火", "野营", "露营"], "night_camp"),
    (["湖", "河", "溪", "水边", "泉"], "lakeside"),
    (["山", "峡谷", "关隘", "山道", "高地"], "mountain_pass"),
    (["神殿", "祠堂", "祭坛", "圣", "遗迹", "古"], "shrine"),
    (["草原", "平原", "田野", "牧场", "旷野"], "plains"),
]


def _map_fantasy_bg(scene_name: str) -> str:
    """将异世界场景名（中文）映射到通用背景图文件名（不含扩展名）"""
    if not scene_name:
        return "town_square"
    for keywords, bg_name in _FANTASY_BG_KEYWORDS:
        for kw in keywords:
            if kw in scene_name:
                return bg_name
    # 默认：城镇广场
    return "town_square"


def _get_death_mode_state() -> Optional[dict]:
    """获取死亡模式状态（供 UI 面板展示）"""
    try:
        from simlife.backend.death_mode import DeathModeEngine
        engine = DeathModeEngine()
        dm_state = engine.get_game_state()
        if not dm_state.get("active"):
            return None
        # 附加用户角色状态
        user_profile = _load_user_profile()
        dm_state["user_character"] = {
            "name": user_profile.get("name", "用户"),
            "class_id": user_profile.get("class_id", ""),
            "class_name": user_profile.get("class_name", ""),
            "level": user_profile.get("level", 1),
            "hp": user_profile.get("hp", 0),
            "max_hp": user_profile.get("max_hp", 0),
            "mp": user_profile.get("mp", 0),
            "max_mp": user_profile.get("max_mp", 0),
            "stats": user_profile.get("stats", {}),
            "skills": user_profile.get("skills", []),
            "gold": user_profile.get("gold", 0),
            "experience": user_profile.get("experience", 0),
            "exp_to_next": user_profile.get("exp_to_next", 100),
        }
        return dm_state
    except Exception:
        return None


def _get_arc_summary() -> Optional[dict]:
    """获取当前主线的摘要信息，供 API 返回"""
    try:
        from simlife.backend.life_arc_engine import load_life_arc
        arc = load_life_arc()
        if not arc:
            return None
        return {
            "title": arc.title,
            "description": arc.description,
            "main_goal": arc.main_goal,
            "antagonist": arc.antagonist,
            "antagonist_motivation": arc.antagonist_motivation,
            "threat_level": arc.threat_level,
            "progress_percent": arc.progress_percent,
            "current_stage": arc.current_stage.name if arc.current_stage else None,
            "current_stage_desc": arc.current_stage.description if arc.current_stage else None,
            "current_stage_goal": arc.current_stage.goal if arc.current_stage else None,
            "current_stage_type": arc.current_stage.stage_type if arc.current_stage else None,
            "current_sub_goals": arc.current_stage.sub_goals if arc.current_stage else [],
            "unresolved_threads": arc.unresolved_threads,
            "consequences": arc.consequences,
            "stages_completed": arc.stages_completed,
            "total_stages": arc.total_stages,
            "days_elapsed": arc.days_elapsed,
            "duration_days": arc.duration_days,
            "stages": [
                {"name": s.name, "status": s.status, "duration_days": s.duration_days, "stage_type": s.stage_type, "goal": s.goal}
                for s in arc.stages
            ],
        }
    except Exception:
        return None


def _tick_non_modern():
    """非现代世界的 tick：人生大纲模式
    - 主线（LifeArc）：月级别目标，分阶段推进
    - 每天：根据当前主线阶段生成计划
    - 每次 tick：按时间推进计划节点
    - 非现代世界不使用 event_library / npc_cards / scheduled_events / weather
    """
    global character_card, world_state, last_tick_scene, current_world_id

    if not character_card or not world_state:
        return

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    current_time = now.strftime("%H:%M")

    # ── 主线管理 ──
    from simlife.backend.life_arc_engine import (
        load_life_arc, save_life_arc, advance_arc, get_stage_hint,
        archive_life_arc,
    )

    arc = load_life_arc()

    # 没有主线或主线已完成 → 生成新的（带前情提要）
    if not arc or arc.completed:
        prev_arc = None
        if arc:
            prev_arc = arc.to_dict()  # 传递完整数据（含反派/后果/伏笔）
            archive_life_arc(arc)
            print(f"[SimLife] 主线「{arc.title}」已完成，已归档")
        try:
            from simlife.backend.generator import generate_life_arc
            arc_data = generate_life_arc(character_card.model_dump(), previous_arc=prev_arc)
            arc = LifeArc(arc_data)
            save_life_arc(arc)
            print(f"[SimLife] 新主线「{arc.title}」（威胁{arc.threat_level}/5，{arc.total_stages}阶段，{arc.duration_days}天，对手：{arc.antagonist}）")

            # 新主线开始 → 刷新卡司（保留老NPC + 加入新反派阵营）
            try:
                from simlife.backend.generator import generate_story_cast
                old_cast = _load_story_cast()
                new_cast = generate_story_cast(
                    character_card.model_dump(),
                    arc=arc.to_dict(),
                    existing_cast=old_cast,
                )
                _save_story_cast(new_cast)
                cast_names = [c["name"] for c in new_cast]
                print(f"[SimLife] 卡司已刷新：{'、'.join(cast_names)}")
            except Exception as e:
                print(f"[SimLife] 卡司刷新失败: {e}")

        except Exception as e:
            print(f"[SimLife] 主线生成失败: {e}")
            arc = None

    # 推进主线阶段（基于天数自动推进）
    arc_hint = ""
    if arc:
        changed = advance_arc(arc)
        if changed:
            save_life_arc(arc)
            if arc.completed:
                stage_name = "全部完成"
            else:
                stage_name = arc.current_stage.name if arc.current_stage else "?"
            print(f"[SimLife] 主线推进 → {stage_name}")
        arc_hint = get_stage_hint(arc)

    # ── NPC卡司管理 ──
    story_cast = _load_story_cast()
    if not story_cast:
        try:
            from simlife.backend.generator import generate_story_cast
            story_cast = generate_story_cast(character_card.model_dump())
            _save_story_cast(story_cast)
            cast_names = [c["name"] for c in story_cast]
            print(f"[SimLife] 已生成NPC卡司：{'、'.join(cast_names)}")
        except Exception as e:
            print(f"[SimLife] NPC卡司生成失败: {e}")
            story_cast = []

    # ── 新的一天：生成全天计划 ──
    if world_state.today_date != today or not world_state.day_plan:
        old_date = world_state.today_date
        world_state.today_date = today
        world_state.day_plan_progress = 0

        # 存档昨天的剧情
        _archive_yesterday_story(world_state, old_date)
        # 读取近期剧情回顾（用于注入 prompt）
        recent_story = _get_recent_story_context(days=3)

        yesterday_summary = ""
        if world_state.today_log:
            yesterday_summary = "；".join([l.event for l in world_state.today_log[-5:]])

        world_state.today_log = []
        world_state.today_events_triggered = []

        try:
            from simlife.backend.generator import generate_day_plan
            plan = generate_day_plan(
                character_card.model_dump(),
                mood=world_state.mood,
                yesterday_summary=yesterday_summary,
                arc_hint=arc_hint,
                cast=story_cast,
                recent_story_context=recent_story,  # 传入近期剧情回顾
            )
            world_state.day_plan = plan
            print(f"[SimLife] 已生成全天计划（{len(plan)} 个节点）")
        except Exception as e:
            print(f"[SimLife] 全天计划生成失败: {e}")
            world_state.day_plan = []

    # ── 推进计划节点 ──
    plan = world_state.day_plan or []
    if not plan:
        world_state.last_updated = now.isoformat()
        _save_world_state(world_state)
        return

    # 用户在场景中时冻结推进
    user_in_scene = False
    try:
        profile = _load_user_profile()
        if profile.get("entered"):
            user_in_scene = True
    except Exception:
        pass

    if user_in_scene:
        world_state.last_updated = now.isoformat()
        _save_world_state(world_state)
        return

    # 推进计划节点：按原始逻辑，节点有固有 HH:MM 时间分布，直接按时间推进
    progress = world_state.day_plan_progress
    new_progress = progress

    for i in range(progress, len(plan)):
        node = plan[i]
        node_time = node.get("time", "23:59")
        if current_time >= node_time:
            label = node.get("label", "")
            activity = node.get("activity", "")
            mood_delta = node.get("mood_delta", 0)
            new_scene = node.get("scene", "日常")

            if new_scene != world_state.current_scene or label:
                world_state.today_log.append(LogEntry(time=node_time, event=f"→ {label}"))

            # 自动生成 200-500 字详细剧情，失败则回退到简短 activity
            if not node.get("expanded"):
                try:
                    from simlife.backend.generator import expand_node
                    prev_nodes_list = plan[max(0, i - 3):i]
                    text = expand_node(
                        character_card.model_dump(),
                        node,
                        cast=story_cast,
                        arc_context=arc_hint,
                        prev_nodes=prev_nodes_list,
                    )
                    node["expanded"] = text
                except Exception as e:
                    print(f"[SimLife] 节点展开失败: {e}")

            expanded_text = node.get("expanded", "")
            if expanded_text:
                world_state.today_log.append(LogEntry(time=node_time, event=expanded_text))
            elif activity:
                world_state.today_log.append(LogEntry(time=node_time, event=activity))

            world_state.current_scene = new_scene
            world_state.current_activity = expanded_text or activity
            mood_delta = node.get("mood_delta", 0)
            world_state.mood = max(0, min(100, world_state.mood + mood_delta))
            last_tick_scene = world_state.current_scene

            new_progress = i + 1
        else:
            break

    if new_progress != progress:
        world_state.day_plan_progress = new_progress

    # 限制日志数量
    if len(world_state.today_log) > 50:
        world_state.today_log = world_state.today_log[-50:]

    world_state.last_updated = now.isoformat()
    _save_world_state(world_state)


def _tick():
    """核心时钟：计算当前场景、检查事件、更新状态"""
    global character_card, world_state, agidpa_reader, last_tick_scene, last_tick_time

    if not character_card or not world_state:
        return

    # 节流：60秒内不重复执行
    import time as _time
    now_ts = _time.time()
    if now_ts - last_tick_time < TICK_THROTTLE_SECONDS:
        return
    last_tick_time = now_ts

    # 非现代世界走 LLM 路径
    if _is_non_modern_world():
        _tick_non_modern()
        return

    # ── 以下为现代世界逻辑（原有）──

    # ── 检查用户是否在场景中（冻结场景推进） ──
    user_in_scene = False
    try:
        profile = _load_user_profile()
        if profile.get("entered"):
            user_in_scene = True
    except Exception:
        pass

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    char_bd = character_card.basic.birth_date if character_card.basic.birth_date else ""

    # 新的一天，重置
    if world_state.today_date != today:
        world_state.today_date = today
        world_state.today_log = []
        world_state.today_events_triggered = []
        world_state.next_random_event_at = None  # 新的一天重置，下一次触发自动重新计时
        # 继承前一天加班的疲劳
        if world_state.current_scene == "OVERTIME":
            world_state.sleep_mood_penalty = -5
        else:
            world_state.sleep_mood_penalty = 0

        # 新的一天注入节日日志（第一条）
        festive_log = get_festive_log_entry(now)
        if festive_log:
            world_state.today_log.append(LogEntry(
                time="09:00", event=festive_log
            ))

        # 新的一天检查生日
        birthday_results = check_birthdays_today(char_bd, load_npc_cards())
        for br in birthday_results:
            world_state.today_log.append(LogEntry(
                time="09:00", event=br["log"]
            ))

    # 离线补算（用户在场景中跳过，避免角色凭空移动）
    if not user_in_scene:
        last_updated = datetime.fromisoformat(world_state.last_updated) if world_state.last_updated else None
        if last_updated and (now - last_updated).total_seconds() > 300:
            world_state, catchup_logs = catchup_world_state(world_state, character_card, now)
            last_tick_scene = world_state.current_scene

    # ── 用户在场景中：冻结场景切换和事件触发，只更新心情 ──
    if user_in_scene:
        scene = SceneEnum(world_state.current_scene)
        label = SCENE_LABELS.get(scene, world_state.current_scene)

        # 心情计算（仍然响应天气、节假日、用户交互等）
        is_weekend = now.weekday() >= 5
        mood_deltas = []
        for eid in world_state.today_events_triggered:
            hist = load_event_history()
            for h in hist:
                if h.get("id") == eid:
                    mood_deltas.append(h.get("mood_delta", 0))
                    break

        interaction_hours = None
        task_len = 0
        if agidpa_reader and agidpa_reader.is_available():
            if agidpa_reader.recent_interaction_within_hours(3):
                interaction_hours = 0.1
            else:
                interaction_hours = None
            task_len = agidpa_reader.get_task_queue_length()

        weather_mood_delta = 0
        if weather_service:
            weather_mood_delta = weather_service.get_mood_delta()

        holiday_mood_delta = 0
        from simlife.backend.holiday_calendar import get_holiday_mood_delta
        holiday_mood_delta = get_holiday_mood_delta(now.date())

        birthday_mood_delta = get_birthday_mood(char_bd) if char_bd else 0
        if birthday_mood_delta == 0:
            for npc in load_npc_cards():
                npc_bd = npc.get("birth_date", "")
                npc_mood = get_birthday_mood(npc_bd)
                if npc_mood > 0:
                    birthday_mood_delta += npc_mood // 3

        mood_deltas.append(weather_mood_delta)
        mood_deltas.append(holiday_mood_delta)
        mood_deltas.append(birthday_mood_delta)

        world_state.mood = calculate_mood(
            scene=scene.value,
            current_hour=now.hour,
            is_weekend=is_weekend,
            today_events_mood_delta=mood_deltas,
            recent_interaction_hours=interaction_hours,
            task_queue_length=task_len,
            sleep_penalty=world_state.sleep_mood_penalty,
        )

        # 激活 NPC（当前场景）
        active = get_active_npcs(scene.value, world_state.today_events_triggered)
        world_state.active_npcs = [n.get("id", "") for n in active]

        if len(world_state.today_log) > 50:
            world_state.today_log = world_state.today_log[-50:]

        world_state.last_updated = now.isoformat()
        _save_world_state(world_state)
        return

    # ── 正常推进（用户不在场景中） ──

    # 事件覆盖（今日已触发事件的后果）
    event_overrides = {}
    for evt_id in world_state.today_events_triggered:
        consequence = apply_event_consequences(evt_id, 0)
        event_overrides.update(consequence.get("schedule_overrides", {}))

    # 计算场景（传入天气服务）
    day_seed = get_day_seed(now)
    scene, label = get_current_scene(
        character_card, now, day_seed,
        event_overrides or None,
        weather_service=weather_service,
    )

    # 场景变化
    scene_changed = scene.value != world_state.current_scene
    if scene_changed:
        world_state.current_scene = scene.value
        time_str = now.strftime("%H:%M")
        if last_tick_scene:
            old_label = SCENE_LABELS.get(SceneEnum(last_tick_scene), last_tick_scene)
            world_state.today_log.append(LogEntry(
                time=time_str, event=f"→ {label}"
            ))

        # 生成 activity 描述
        try:
            from simlife.backend.generator import generate_activity_description
            events_summary = "; ".join([l.event for l in world_state.today_log[-5:]])
            activity = generate_activity_description(
                character_card.model_dump(),
                scene.value, label,
                events_summary,
                world_state.mood
            )
            world_state.current_activity = activity
        except Exception as e:
            print(f"[SimLife] Activity生成失败: {e}")
            world_state.current_activity = f"在{label}"

        last_tick_scene = scene.value

    # 检查微事件（每 5 分钟检查一次，不再仅限场景变化或整15分钟）
    if scene_changed or (now.minute % 5 == 0):
        micro = check_daily_micro_events(
            character_card.model_dump(),
            scene.value,
            day_seed,
            world_state.today_events_triggered
        )
        if micro and micro["id"] not in world_state.today_events_triggered:
            world_state.today_events_triggered.append(micro["id"])
            record_triggered_event(micro)
            world_state.today_log.append(LogEntry(
                time=now.strftime("%H:%M"),
                event=micro["label"]
            ))

    # 检查随机事件（受 2-4 小时随机间隔控制）
    import time as _time2
    import random as _random_evt

    next_at = world_state.next_random_event_at
    if next_at is None:
        # 新的一天：设置首次触发时间为 2-4 小时后
        world_state.next_random_event_at = _time2.time() + _random_evt.uniform(7200, 14400)
    elif _time2.time() >= next_at:
        rand_evt = check_random_events(
            character_card.model_dump(),
            scene.value,
            day_seed,
            world_state.today_events_triggered,
            now,
        )
        if rand_evt and rand_evt["id"] not in world_state.today_events_triggered:
            world_state.today_events_triggered.append(rand_evt["id"])
            # 设置下一次触发时间为 2-4 小时后
            world_state.next_random_event_at = _time2.time() + _random_evt.uniform(7200, 14400)
            record_triggered_event(rand_evt)
            world_state.today_log.append(LogEntry(
                time=now.strftime("%H:%M"),
                event=rand_evt["label"]
            ))

    # 检查排期事件
    scheduled = load_scheduled_events()
    triggered, remaining = check_scheduled_events(scheduled, now)
    for evt in triggered:
        if evt["id"] not in world_state.today_events_triggered:
            world_state.today_events_triggered.append(evt["id"])
            record_triggered_event(evt)
            world_state.today_log.append(LogEntry(
                time=now.strftime("%H:%M"),
                event=evt["label"]
            ))
    if triggered:
        save_scheduled_events(remaining)

    # 计算心情（加入天气 + 节假日修正）
    is_weekend = now.weekday() >= 5
    mood_deltas = []
    for eid in world_state.today_events_triggered:
        hist = load_event_history()
        for h in hist:
            if h.get("id") == eid:
                mood_deltas.append(h.get("mood_delta", 0))
                break

    # 旅行心情加成
    from simlife.backend.character import WorkStyle
    travel_dest = None
    _ws = _get_work_style_safe()
    if _ws == "travel" and character_card:
        travel_dest = _get_current_travel_destination(character_card, now.date())
        if travel_dest:
            mood_deltas.append(travel_dest.get("mood_bonus", 15))

    interaction_hours = None
    task_len = 0
    if agidpa_reader and agidpa_reader.is_available():
        if agidpa_reader.recent_interaction_within_hours(3):
            interaction_hours = 0.1
        else:
            interaction_hours = None
        task_len = agidpa_reader.get_task_queue_length()

    # 天气心情修正
    weather_mood_delta = 0
    if weather_service:
        weather_mood_delta = weather_service.get_mood_delta()

    # 节假日心情修正
    holiday_mood_delta = 0
    from simlife.backend.holiday_calendar import get_holiday_mood_delta
    holiday_mood_delta = get_holiday_mood_delta(now.date())

    # 生日心情修正
    birthday_mood_delta = get_birthday_mood(char_bd) if char_bd else 0
    if birthday_mood_delta == 0:
        # 检查NPC生日
        for npc in load_npc_cards():
            npc_bd = npc.get("birth_date", "")
            npc_mood = get_birthday_mood(npc_bd)
            if npc_mood > 0:
                birthday_mood_delta += npc_mood // 3  # NPC生日对主角心情影响较小

    mood_deltas.append(weather_mood_delta)
    mood_deltas.append(holiday_mood_delta)
    mood_deltas.append(birthday_mood_delta)

    world_state.mood = calculate_mood(
        scene=scene.value,
        current_hour=now.hour,
        is_weekend=is_weekend,
        today_events_mood_delta=mood_deltas,
        recent_interaction_hours=interaction_hours,
        task_queue_length=task_len,
        sleep_penalty=world_state.sleep_mood_penalty,
    )

    # 激活 NPC
    active = get_active_npcs(scene.value, world_state.today_events_triggered)
    world_state.active_npcs = [n.get("id", "") for n in active]

    # 限制日志数量
    if len(world_state.today_log) > 50:
        world_state.today_log = world_state.today_log[-50:]

    # 保存
    world_state.last_updated = now.isoformat()
    _save_world_state(world_state)


# ── API 路由 ──────────────────────────────────────────

@app.get("/api/world/state")
def api_world_state():
    _tick()
    if not world_state:
        return {"error": "世界未初始化"}

    # 天气信息
    weather_data = {"label": "多云", "emoji": "⛅", "temp": ""}
    if _is_non_modern_world():
        # 非现代世界：用世界观的地点和气候，不调用真实天气 API
        try:
            ws = load_world_setting(current_world_id) if current_world_id != "modern" else None
            if ws:
                regions = ws.get("geography", {}).get("regions", [])
                location_name = regions[0].get("name", "") if regions else ws.get("world_name", "")
                climate = regions[0].get("climate", "") if regions else ""
                weather_data = {
                    "label": climate or "晴朗",
                    "emoji": "",
                    "temp": "",
                    "location": location_name,
                }
        except Exception:
            pass
    elif weather_service:
        w = weather_service.get_weather()
        weather_data = {
            "label": w.get("label", "多云"),
            "emoji": w.get("emoji", "⛅"),
            "temp": w.get("temp", ""),
            "text": w.get("text", ""),
        }

    # 节假日信息
    holiday_info = get_holiday_info()

    # 生日信息
    birthday_info = None
    char_bd = character_card.basic.birth_date if character_card.basic.birth_date else ""
    if char_bd:
        from simlife.backend.birthday_engine import get_birthday_mood
        if get_birthday_mood(char_bd) > 0:
            birthday_info = {
                "is_self": True,
                "zodiac": character_card.basic.zodiac or "",
            }
    # 即将到来的生日
    from simlife.backend.birthday_engine import get_upcoming_birthdays
    upcoming_birthdays = get_upcoming_birthdays(char_bd, load_npc_cards(), days=14)

    # 旅行信息
    travel_info = None
    if character_card and _get_work_style_safe() == "travel":
        travel_dest = _get_current_travel_destination(character_card, datetime.now().date())
        if travel_dest:
            travel_info = travel_dest

    # 用户入驻状态
    user_profile = _load_user_profile()

    # 世界观信息
    world_info = None
    if _is_non_modern_world():
        try:
            from simlife.worlds.world_manager import load_world_setting
            ws = load_world_setting(current_world_id)
            if ws:
                world_info = {
                    "world_id": current_world_id,
                    "world_name": ws.get("world_name", ""),
                    "world_type": ws.get("world_type", ""),
                }
        except Exception:
            pass

    # NPC卡司（非现代世界）
    story_cast = _load_story_cast() if _is_non_modern_world() else []

    # 场景标签
    if _is_non_modern_world():
        # 非现代世界：场景名由 LLM 生成，直接使用
        scene_label = world_state.current_scene
    else:
        try:
            scene_label = SCENE_LABELS.get(
                SceneEnum(world_state.current_scene), world_state.current_scene
            )
        except ValueError:
            scene_label = world_state.current_scene

    # 日志
    # 现代世界返回全部日志，异世界只返回已推进的节点日志
    if _is_non_modern_world():
        # 异世界模式：日志已由 _tick_non_modern 填充到 today_log
        latest_log = [
            {"time": l.time, "event": l.event}
            for l in world_state.today_log[-20:]
        ]
    else:
        latest_log = [
            {"time": l.time, "event": l.event}
            for l in world_state.today_log[-20:]
        ]

    # 背景图提示（异世界场景→通用背景映射）
    bg_hint = None
    if _is_non_modern_world():
        bg_hint = _map_fantasy_bg(world_state.current_scene or "")

    return {
        "scene": world_state.current_scene,
        "scene_label": scene_label,
        "activity": world_state.current_activity,
        "mood": world_state.mood,
        "active_npcs": world_state.active_npcs,
        "today_date": world_state.today_date,
        "time_label": get_time_period_label(),
        "latest_log": latest_log,
        "weather": weather_data,
        "holiday": holiday_info,
        "birthday": birthday_info,
        "upcoming_birthdays": upcoming_birthdays,
        "travel": travel_info,
        "world": world_info,
        "is_story_mode": _is_non_modern_world(),
        "bg_hint": bg_hint,
        "story_cast": story_cast if _is_non_modern_world() else None,
        "day_plan": (world_state.day_plan if _is_non_modern_world() else None),
        "day_plan_progress": world_state.day_plan_progress if _is_non_modern_world() else None,
        "life_arc": _get_arc_summary() if _is_non_modern_world() else None,
        "user": {
            "entered": user_profile.get("entered", False),
            "name": user_profile.get("name", ""),
            "relation": user_profile.get("relation", ""),
        },
        "death_mode": _get_death_mode_state(),
    }


@app.get("/api/character")
def api_get_character():
    if not character_card:
        return {"initialized": False}
    return {"initialized": True, "card": character_card.model_dump()}


@app.post("/api/character")
def api_set_character(data: dict):
    global character_card
    try:
        character_card = CharacterCard(**data)
        _save_character_card(character_card)
        # 初始化世界状态
        global world_state
        world_state = WorldState(
            last_updated=datetime.now().isoformat(),
            today_date=datetime.now().strftime("%Y-%m-%d"),
            current_scene="HOME_EVENING",
            current_activity="刚设置好，在看看新家",
        )
        _save_world_state(world_state)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/api/setup/generate")
def api_setup_generate(data: dict):
    """首次设置：根据锚点生成人物卡"""
    global character_card

    try:
        from simlife.backend.generator import generate_character_card, generate_npc_cards

        anchor = data.get("anchor", {})
        card_data = generate_character_card(anchor)
        if not card_data:
            raise HTTPException(500, "人物卡生成失败")

        character_card = CharacterCard(**card_data)
        _save_character_card(character_card)

        # 非现代世界：生成NPC卡司（而非现代NPC卡）
        if _is_non_modern_world():
            try:
                from simlife.backend.generator import generate_story_cast
                story_cast = generate_story_cast(character_card.model_dump())
                _save_story_cast(story_cast)
                cast_names = [c["name"] for c in story_cast]
                print(f"[SimLife] 已生成NPC卡司：{'、'.join(cast_names)}")
            except Exception as e:
                print(f"[SimLife] NPC卡司生成失败: {e}")
        else:
            # 现代世界：生成社交NPC
            npc_data = generate_npc_cards(card_data)
            if npc_data:
                from simlife.backend.npc_engine import save_npc_cards
                save_npc_cards(npc_data)

        # 初始化世界状态
        global world_state
        now = datetime.now()
        if _is_non_modern_world():
            # 非现代世界：用世界观地点作为初始场景
            ws = None
            try:
                from simlife.worlds.world_manager import load_world_setting
                ws = load_world_setting(current_world_id)
            except Exception:
                pass
            init_scene = "住处"
            init_activity = "新的一天开始了"
            if ws:
                regions = ws.get("geography", {}).get("regions", [])
                if regions:
                    init_scene = regions[0].get("name", "住处")
                init_activity = f"在「{ws.get('world_name', '')}」中开始了新的旅程"
            world_state = WorldState(
                last_updated=now.isoformat(),
                current_scene=init_scene,
                current_activity=init_activity,
                today_date=now.strftime("%Y-%m-%d"),
            )
        else:
            scene, label = get_current_scene(character_card, now)
            world_state = WorldState(
                last_updated=now.isoformat(),
                current_scene=scene.value,
                current_activity=f"世界开始了，{label}",
                today_date=now.strftime("%Y-%m-%d"),
            )
        _save_world_state(world_state)

        return {"status": "ok", "card": character_card.model_dump()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"生成失败: {e}")


@app.get("/api/npcs")
def api_get_npcs():
    if _is_non_modern_world():
        return {"npcs": _load_story_cast()}
    return {"npcs": load_npc_cards()}


@app.get("/api/story/cast")
def api_get_story_cast():
    """获取剧情NPC卡司（非现代世界）"""
    return {"cast": _load_story_cast()}


@app.post("/api/story/expand/{node_index}")
def api_expand_node(node_index: int):
    """展开某个 day_plan 节点为小说段落"""
    if not world_state or not world_state.day_plan:
        raise HTTPException(400, "没有日计划数据")
    if node_index < 0 or node_index >= len(world_state.day_plan):
        raise HTTPException(400, "节点索引无效")

    plan = world_state.day_plan
    node = plan[node_index]

    # 如果已经展开过，直接返回缓存
    if node.get("expanded"):
        return {"text": node["expanded"]}

    # 只展开已到达或已过去的节点
    if node_index > world_state.day_plan_progress:
        raise HTTPException(400, "该节点尚未到达")

    try:
        from simlife.backend.generator import expand_node
        cast = _load_story_cast()
        arc_hint = ""
        arc = load_life_arc()
        if arc:
            from simlife.backend.life_arc_engine import get_stage_hint
            arc_hint = get_stage_hint(arc)

        # 前面节点作为上文衔接
        prev_nodes = [plan[i] for i in range(max(0, node_index - 2), node_index)]

        text = expand_node(
            character_card.model_dump(),
            node,
            cast=cast,
            arc_context=arc_hint,
            prev_nodes=prev_nodes,
        )

        # 缓存到 day_plan
        world_state.day_plan[node_index]["expanded"] = text
        _save_world_state(world_state)

        return {"text": text}
    except Exception as e:
        raise HTTPException(500, f"展开失败: {e}")


@app.get("/api/events/history")
def api_event_history():
    return {"history": load_event_history()[-30:]}


@app.get("/api/events/scheduled")
def api_scheduled_events():
    return {"scheduled": load_scheduled_events()}


@app.post("/api/reset")
def api_reset():
    """重置 SimLife：删除角色卡、世界状态和用户档案，重新初始化"""
    global character_card, world_state
    try:
        # 删除数据文件
        for f in ["character_card.json", "world_state.json", "user_profile.json",
                   "story_cast.json", "life_arc.json", "life_arc_history.json",
                   "event_history.json", "npc_cards.json", "scheduled_events.json",
                   "weather_cache.json",
                   "death_mode_state.json", "death_mode_state.json.dead", "death_hall.json"]:
            p = DATA_DIR / f
            if p.exists():
                p.unlink()

        character_card = None
        world_state = None

        return {"status": "ok", "message": "已重置，请刷新页面重新设置"}
    except Exception as e:
        raise HTTPException(500, f"重置失败: {e}")


@app.get("/api/status")
def api_status():
    return {
        "initialized": character_card is not None,
        "version": "1.0.0",
    }


# ── 调试 API ──────────────────────────────────────────

@app.post("/api/debug/force-next-day")
def api_debug_force_next_day():
    """调试用：强制将 today_date 设为前一天，下次 tick 会触发新天流程"""
    global world_state
    if not world_state:
        raise HTTPException(400, "世界未初始化")
    from datetime import timedelta
    old = world_state.today_date
    try:
        d = datetime.strptime(old, "%Y-%m-%d") - timedelta(days=1)
        world_state.today_date = d.strftime("%Y-%m-%d")
    except Exception:
        world_state.today_date = "2000-01-01"
    _save_world_state(world_state)
    return {
        "status": "ok",
        "message": f"已重置日期为 {world_state.today_date}，下次请求 /api/world/state 将触发新天流程",
    }


# ── 剧情存档 API ─────────────────────────────────────

@app.get("/api/story/archive")
def api_list_archives():
    """列出所有剧情存档"""
    return {"archives": _list_archives()}


@app.get("/api/story/archive/{date_str}")
def api_get_archive(date_str: str):
    """读取指定日期的剧情存档"""
    data = _load_archive(date_str)
    if not data:
        raise HTTPException(404, f"未找到 {date_str} 的存档")
    return data


# ── 世界观管理 API ─────────────────────────────────

@app.get("/api/worlds")
def api_list_worlds():
    """列出所有可用世界观"""
    from simlife.worlds.world_manager import list_available_worlds, get_current_world_id
    return {
        "worlds": list_available_worlds(),
        "current": get_current_world_id(),
    }


@app.get("/api/worlds/current")
def api_get_current_world():
    """获取当前世界观的完整设定"""
    from simlife.worlds.world_manager import (
        load_world_setting, build_world_context,
        get_current_world_id,
    )
    world_id = get_current_world_id()
    setting = load_world_setting(world_id)
    context = build_world_context(setting) if setting else ""
    return {"world_id": world_id, "setting": setting, "context": context}


@app.post("/api/worlds/switch")
def api_switch_world(data: dict):
    """切换世界观（仅未初始化时可用）"""
    if character_card is not None:
        raise HTTPException(400, "已初始化角色，无法切换世界观")
    world_id = data.get("world_id", "modern")
    from simlife.worlds.world_manager import set_current_world, list_available_worlds
    valid_ids = [w["world_id"] for w in list_available_worlds()]
    if world_id not in valid_ids:
        raise HTTPException(400, f"无效的世界观 ID: {world_id}")
    set_current_world(world_id)
    global current_world_id
    current_world_id = world_id
    return {"status": "ok", "world_id": world_id}


@app.post("/api/worlds/import")
def api_import_world(data: dict):
    """导入自定义世界观设定"""
    setting = data.get("setting")
    if not setting or not isinstance(setting, dict):
        raise HTTPException(400, "缺少 setting 字段")
    world_id = setting.get("world_id", "custom")
    if not world_id or world_id == "modern":
        raise HTTPException(400, "世界观 ID 无效（不能使用 'modern'）")
    from simlife.worlds.world_manager import save_world_setting, set_current_world
    save_world_setting(world_id, setting)
    set_current_world(world_id)
    global current_world_id
    current_world_id = world_id
    return {"status": "ok", "world_id": world_id, "world_name": setting.get("world_name", "")}


@app.post("/api/worlds/generate")
def api_generate_world(data: dict):
    """用 AI 生成一个自定义世界观设定"""
    from simlife.backend.generator import generate_world_setting
    from simlife.worlds.world_manager import save_world_setting, set_current_world

    world_type = data.get("world_type", "fantasy")
    core_theme = data.get("core_theme", "")
    character_role = data.get("character_role_hint", "")

    if not core_theme:
        raise HTTPException(400, "请填写核心主题")

    try:
        setting = generate_world_setting(
            world_type=world_type,
            core_theme=core_theme,
            character_role=character_role,
        )
        if not setting:
            raise HTTPException(500, "AI 生成世界观失败，请检查 API Key 是否配置")

        world_id = setting.get("world_id", "custom")
        save_world_setting(world_id, setting)
        set_current_world(world_id)
        global current_world_id
        current_world_id = world_id
        return {
            "status": "ok",
            "world_id": world_id,
            "world_name": setting.get("world_name", ""),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"生成失败: {e}")


@app.post("/api/worlds/delete")
def api_delete_world(data: dict):
    """删除一个自定义世界观（连同全部区域数据）。删除当前世界后自动切回现代世界。"""
    from simlife.worlds.world_manager import (
        delete_world, set_current_world, list_available_worlds,
    )
    world_id = (data.get("world_id") or "").strip()
    if not world_id:
        raise HTTPException(400, "缺少 world_id 字段")
    if world_id == "modern":
        raise HTTPException(400, "现代世界是默认世界，不能删除")
    if not delete_world(world_id):
        raise HTTPException(400, f"世界观不存在或删除失败: {world_id}")
    global current_world_id
    current_world_id = "modern"
    set_current_world("modern")
    return {
        "status": "ok",
        "world_id": world_id,
        "worlds": list_available_worlds(),
        "current": current_world_id,
    }


@app.get("/api/worlds/template")
def api_get_world_template():
    """获取世界观设定模板（用户用 LLM 生成后导入）"""
    from simlife.worlds.world_manager import WORLD_TEMPLATE
    if WORLD_TEMPLATE.exists():
        with open(WORLD_TEMPLATE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


@app.get("/api/worlds/generate-prompt")
def api_get_world_generate_prompt():
    """获取世界观生成提示词 Markdown（给用户复制到 LLM 生成世界观用）"""
    from simlife.worlds.world_manager import WORLD_GENERATE_PROMPT
    if WORLD_GENERATE_PROMPT.exists():
        return {"content": WORLD_GENERATE_PROMPT.read_text(encoding="utf-8")}
    return {"content": ""}


# ── 死亡模式 API ──────────────────────────────────────

@app.get("/api/death-mode/classes")
def api_death_mode_classes(world_id: str = None):
    """获取可选职业列表（根据世界观类型）"""
    from simlife.backend.death_mode_state import get_available_classes, _get_world_type_from_setting
    from simlife.worlds.world_manager import load_world_setting

    world_setting = None
    if world_id:
        world_setting = load_world_setting(world_id)

    world_type = _get_world_type_from_setting(world_setting) if world_setting else None
    return {"classes": get_available_classes(world_type=world_type, world_setting=world_setting), "world_type": world_type or "fantasy"}


@app.post("/api/death-mode/start")
def api_death_mode_start(data: dict):
    """开始死亡模式新游戏"""
    from simlife.backend.death_mode import DeathModeEngine
    from simlife.worlds.world_manager import load_world_setting

    character_name = data.get("character_name", "").strip()
    class_id = data.get("class_id", "warrior")
    user_class_id = data.get("user_class_id", "warrior")
    user_name = data.get("user_name", "").strip()
    world_id = data.get("world_id", "")
    growth_mode = data.get("growth_mode", "normal")
    custom_stat_points = data.get("custom_stat_points")

    if not character_name:
        raise HTTPException(400, "请填写角色名字")
    if not world_id:
        raise HTTPException(400, "请选择世界观")

    world_setting = load_world_setting(world_id)
    if not world_setting:
        raise HTTPException(400, "世界观设定不存在")

    engine = DeathModeEngine()
    result = engine.start_game(
        character_name=character_name,
        class_id=class_id,
        world_setting=world_setting,
        growth_mode=growth_mode,
        custom_stat_points=custom_stat_points,
        user_class_id=user_class_id,
        user_name=user_name,
    )

    # 同步用户角色能力设定（用户角色使用用户选择的职业）
    user_profile = _load_user_profile()
    from simlife.backend.death_mode_state import get_class_template, _get_world_type_from_setting, _convert_skill_names_to_ids
    world_type = _get_world_type_from_setting(world_setting)
    user_cls = get_class_template(world_type, user_class_id)
    if user_cls:
        user_skill_ids = _convert_skill_names_to_ids(user_cls["starting_skills"], world_type, user_class_id)
        user_profile["class_id"] = user_class_id
        user_profile["class_name"] = user_cls["name"]
        user_profile["stats"] = dict(user_cls["base_stats"])
        user_profile["hp"] = user_cls["base_hp"]
        user_profile["max_hp"] = user_cls["base_hp"]
        user_profile["mp"] = user_cls["base_mp"]
        user_profile["max_mp"] = user_cls["base_mp"]
        user_profile["level"] = 1
        user_profile["skills"] = user_skill_ids
        if user_name:
            user_profile["name"] = user_name
        _save_user_profile(user_profile)

        # 同步到 death_mode_state 的 user_character
        state = engine._load()
        if state:
            state["user_character"] = {
                "name": user_name or user_profile.get("name", "用户"),
                "class_id": user_class_id,
                "class_name": user_cls["name"],
                "class_icon": user_cls.get("icon", "👤"),
                "level": 1,
                "hp": user_cls["base_hp"],
                "max_hp": user_cls["base_hp"],
                "mp": user_cls["base_mp"],
                "max_mp": user_cls["base_mp"],
                "stats": dict(user_cls["base_stats"]),
                "skills": user_skill_ids,
                "awakening_skills": [],
                "equipment": [],
                "experience": 0,
                "exp_to_next": 100,
                "gold": 0,
            }
            # 迁移旧 inventory → shared_inventory
            if not state.get("shared_inventory"):
                old_inv = state.get("character", {}).get("inventory", [])
                state["shared_inventory"] = old_inv
                state["character"]["inventory"] = []  # 清空旧背包，统一用 shared_inventory
            engine._save()

    return result


@app.get("/api/death-mode/state")
def api_death_mode_state():
    """获取死亡模式当前状态（含用户角色状态）"""
    from simlife.backend.death_mode import DeathModeEngine
    engine = DeathModeEngine()
    result = engine.get_game_state()

    # 附加用户角色状态（优先从 death_mode_state 读取）
    uc = result.get("user_character", {})
    if not uc or not uc.get("class_name"):
        # 兼容旧存档：从 user_profile 兜底
        user_profile = _load_user_profile()
        uc = {
            "name": user_profile.get("name", "用户"),
            "class_id": user_profile.get("class_id", ""),
            "class_name": user_profile.get("class_name", ""),
            "level": user_profile.get("level", 1),
            "hp": user_profile.get("hp", 0),
            "max_hp": user_profile.get("max_hp", 0),
            "mp": user_profile.get("mp", 0),
            "max_mp": user_profile.get("max_mp", 0),
            "stats": user_profile.get("stats", {}),
            "skills": user_profile.get("skills", []),
            "equipment": user_profile.get("equipment", []),
            "gold": user_profile.get("gold", 0),
            "experience": user_profile.get("experience", 0),
            "exp_to_next": user_profile.get("exp_to_next", 100),
        }
    result["user_character"] = uc
    # 共享背包
    result["shared_inventory"] = result.get("shared_inventory", [])

    return result


# ══════════════════════════════════════════════════════
# 一键生成场景图（基于当前场景描述，调用本地 ComfyUI）
# ══════════════════════════════════════════════════════

# 场景关键词 → 英文画面主题（仅作为 LLM 失败时的兜底，非主要来源）
_SCENE_IMAGE_KEYWORDS = [
    (["城镇", "集市", "广场", "街道", "商铺", "小镇", "市场", "村庄", "村子"], "a bustling medieval fantasy town square with market stalls and stone buildings"),
    (["酒馆", "旅馆", "旅店", "客栈", "休息", "吧"], "a cozy fantasy tavern interior with wooden tables, warm candlelight and a fireplace"),
    (["森林", "树林", "丛林", "密林", "精灵", "古木"], "a mystical ancient forest with towering trees, glowing fireflies and mossy paths"),
    (["城堡", "宫殿", "王城", "皇宫", "大厅", "城墙"], "a grand fantasy castle with stone towers, banners and epic architecture"),
    (["学院", "魔法", "图书馆", "研究", "塔"], "a magical academy tower filled with floating books, glowing runes and arcane energy"),
    (["地下", "地牢", "副本", "洞窟", "矿坑", "迷宫", "洞穴"], "a dark fantasy dungeon with torches, stone corridors and mysterious shadows"),
    (["营地", "扎营", "篝火", "野营", "露营"], "a night camp with a glowing campfire, tents and a starry sky"),
    (["湖", "河", "溪", "水边", "泉", "瀑布"], "a serene lakeside with clear water, soft reflections and gentle mist"),
    (["山", "峡谷", "关隘", "山道", "高地", "雪山"], "a majestic mountain pass with rocky cliffs, a winding path and dramatic clouds"),
    (["神殿", "祠堂", "祭坛", "遗迹", "古", "圣"], "an ancient temple ruin with stone pillars, moss and a sacred atmosphere"),
    (["草原", "平原", "田野", "牧场", "旷野", "草地"], "a vast grassy plain with wildflowers, rolling hills and open sky"),
    (["沙漠", "沙丘", "戈壁"], "a vast desert with golden sand dunes and a distant oasis"),
    (["雪", "冰", "极地", "冰川"], "a snowy frozen landscape with snow-covered trees and icy mountains"),
    (["海", "港口", "码头", "海滩", "沙滩", "船"], "a coastal harbor with ships, ocean waves and seaside buildings"),
    (["王座", "宴会", "王宫"], "a grand royal throne hall with marble columns, chandeliers and red carpets"),
    (["墓", "坟", "陵"], "an ancient cemetery with gravestones, cypress trees and moonlight"),
    (["庭院", "花园", "花", "玫瑰"], "a beautiful fantasy garden with blooming flowers, fountains and manicured hedges"),
    (["教堂", "礼拜", "修道院"], "a gothic fantasy cathedral interior with stained glass and candlelight"),
    (["桥", "石桥"], "an old stone bridge over a river in fantasy scenery"),
]


def _collect_scene_context(engine, dm_state) -> dict:
    """动态提取场景上下文：当前区域设定 + 最近的行动内容（不硬编码）"""
    ctx = {"region_name": "", "region_desc": "", "region_type": "", "events": []}

    # 1. 当前区域设定（name + description + region_type）
    try:
        if getattr(engine, "world_map", None):
            cur = engine.world_map.get_current_region()
            if cur:
                ctx["region_name"] = (cur.name or "").strip()
                ctx["region_desc"] = (cur.description or "").strip()
                ctx["region_type"] = (cur.region_type or "").strip()
    except Exception:
        pass
    if not ctx["region_name"]:
        # 兜底：从 story 读取当前位置
        story = dm_state.get("story") or {}
        ctx["region_name"] = (story.get("current_location") or "").strip()

    # 2. 最近的行动内容（取最新几条有意义的日志）
    logs = dm_state.get("action_log") or []
    events = []
    for log in reversed(logs):
        d = log.get("data") or {}
        t = log.get("type", "")
        text = ""
        if t == "scene":
            text = d.get("description") or ""
            loc = d.get("location") or ""
            if loc:
                text = f"{text}（位置：{loc}）" if text else f"当前位置：{loc}"
        elif t in ("action", "combat_round"):
            parts = []
            if d.get("action"):
                parts.append(str(d["action"]))
            if d.get("outcome"):
                parts.append(str(d["outcome"]))
            combat = d.get("combat") or {}
            enemy_names = combat.get("enemy_names") or []
            if enemy_names:
                parts.append("与 " + "、".join(enemy_names) + " 战斗")
            if parts:
                text = "；".join(parts)
        elif t == "move":
            if d.get("to"):
                text = f"移动到了{d.get('to')}"
        text = (text or "").strip()
        if text and text not in events:
            events.append(text)
        if len(events) >= 3:
            break
    ctx["events"] = events
    return ctx


def _llm_scene_prompt(ctx: dict) -> str:
    """用 LLM 把「区域设定 + 行动内容」动态转成英文绘图提示词"""
    from simlife.backend.generator import get_llm_client
    llm = get_llm_client()

    lines = []
    if ctx.get("region_name"):
        lines.append(f"当前区域名称：{ctx['region_name']}")
    if ctx.get("region_desc"):
        lines.append(f"区域设定描述：{ctx['region_desc']}")
    if ctx.get("events"):
        lines.append("最近发生的行动：")
        lines.extend(f"- {e}" for e in ctx["events"])
    context_text = "\n".join(lines) or "当前身处一片未知的奇幻大陆。"

    sys_prompt = (
        "你是游戏场景美术设定师。根据游戏当前区域的设定和玩家最近的行动内容，"
        "生成一段用于 Stable Diffusion / ComfyUI 绘图的英文画面提示词。\n"
        "要求：\n"
        "1. 只输出英文，逗号分隔的标签式提示词，不要任何解释文字、编号或引号。\n"
        "2. 画面必须忠实反映区域的地形地貌，并体现最近行动中正在发生的事件（如战斗、探索、互动、生活行为）。\n"
        "3. 奇幻游戏原画风格，强调光影氛围、细节丰富、电影感。\n"
        "4. 若行动涉及战斗，用英文描述敌人/怪物形象；画面中不要出现人类角色。\n"
    )
    try:
        prompt = (llm.generate(f"{sys_prompt}\n\n{context_text}", max_tokens=300, temperature=0.8, thinking=False) or "").strip()
        if prompt:
            return prompt
    except Exception as e:
        print(f"[场景图] LLM 提示词生成失败，退回关键词兜底: {e}")
    return ""


def _scene_to_image_prompt(ctx: dict) -> str:
    """生成英文画面提示词：优先 LLM 动态生成（区域+行动），失败则退回关键词映射"""
    # 1. 优先 LLM 动态生成
    prompt = _llm_scene_prompt(ctx)
    if prompt:
        return prompt

    # 2. 兜底：关键词映射 + 原文（区域设定或最近行动文本）
    scene_desc = ctx.get("region_desc") or ((ctx.get("events") or [""])[0]) or ctx.get("region_name") or ""
    theme = ""
    for keywords, en in _SCENE_IMAGE_KEYWORDS:
        if any(kw in scene_desc for kw in keywords):
            theme = en
            break
    desc_tail = scene_desc[:100].replace("\n", " ")
    if theme:
        return f"{theme}, {desc_tail}, fantasy art style, highly detailed, cinematic lighting, epic atmosphere, masterpiece"
    if desc_tail:
        return f"{desc_tail}, fantasy landscape, highly detailed, cinematic lighting, epic atmosphere, masterpiece"
    return "a mysterious fantasy landscape, epic scenery, highly detailed, cinematic lighting, masterpiece"


@app.post("/api/death-mode/generate-scene-image")
def api_death_mode_generate_scene_image():
    """一键生成当前场景图（提取区域设定+最近行动，动态生成提示词，调用本地 ComfyUI）"""
    try:
        from engine.tools import generate_image_comfy
    except Exception as e:
        return {"ok": False, "error": f"图像生成模块不可用: {e}"}

    # 1. 获取当前游戏状态与场景上下文
    from simlife.backend.death_mode import DeathModeEngine
    engine = DeathModeEngine()
    dm_state = engine.get_game_state()
    if not dm_state.get("active"):
        return {"ok": False, "error": "当前没有进行中的死亡模式游戏"}

    ctx = _collect_scene_context(engine, dm_state)

    # 2. 动态生成英文提示词（区域设定 + 行动内容）
    prompt = _scene_to_image_prompt(ctx)

    # 3. 调用 ComfyUI 生成（纯场景/怪物，无人类角色）
    try:
        result = generate_image_comfy(prompt=prompt, no_human=True, width=1024, height=768)
    except Exception as e:
        return {"ok": False, "error": f"生成失败: {e}"}

    if not result.get("ok"):
        return result

    # 4. 拼接前端可访问的图片 URL
    image_path = result.get("image_path", "")
    if image_path:
        result["image_url"] = "/agi-images/" + os.path.basename(image_path)
    # 附上"本图基于什么生成"的上下文，供前端展示
    result["scene_context"] = {
        "region_name": ctx.get("region_name", ""),
        "region_desc": ctx.get("region_desc", ""),
        "events": ctx.get("events", []),
    }
    return result


# ══════════════════════════════════════════════════════
# 生活技能系统 API（烹饪/锻造/钓鱼）
# ══════════════════════════════════════════════════════

def _life_engine():
    from simlife.backend.death_mode import DeathModeEngine
    engine = DeathModeEngine()
    state = engine._load()
    if not state:
        return None, None
    from simlife.backend.life_skills import ensure_life_state
    ensure_life_state(state)
    return engine, state


@app.get("/api/death-mode/life-skills")
def api_death_mode_life_skills():
    """获取生活技能状态（等级/材料/菜谱/设计图/食物/装备/鱼/商店）"""
    from simlife.backend import life_skills as LS
    engine, state = _life_engine()
    if not state:
        return {"error": "no_game"}
    ls = state["life_state"]
    char = state.get("character", {})
    # 共享背包物品（去重合并）：可拆解 + 判别是否材料可存入
    shared_items = []
    from collections import OrderedDict as _OD
    _sacc = _OD()
    for it in state.get("shared_inventory", []):
        itname = it.get("name", "")
        if not itname:
            continue
        key = itname
        if key not in _sacc:
            rar = it.get("rarity") or it.get("quality") or "common"
            _sacc[key] = {"name": itname, "rarity": rar,
                          "is_material": isinstance(LS.match_material_by_name(itname), dict),
                          "qty": 0}
        qty = it.get("qty", 1)
        try:
            qty = int(qty) or 1
        except Exception:
            qty = 1
        _sacc[key]["qty"] += max(1, qty)
    shared_items = list(_sacc.values())
    # 共享背包里可存入生活材料包的材料（按名称匹配并合并数量）
    shared_materials = []
    for si in shared_items:
        mat = LS.match_material_by_name(si["name"])
        if not mat:
            continue
        shared_materials.append({"id": mat["id"], "name": mat["name"], "icon": mat["icon"],
                                 "type": mat["type"], "qty": si["qty"]})
    overall = max((s.get("level", 1) for s in ls["skills"].values()), default=1)
    fg = ls.get("fish_gear") or {}
    # 当前异世界区域 → 决定可钓到的水域（不同区域不同鱼）
    current_region = None
    region_zone = fg.get("zone", "pond")
    if engine.world_map:
        reg = engine.world_map.get_current_region()
        if reg:
            current_region = {
                "id": reg.region_id, "name": reg.name,
                "region_type": reg.region_type, "danger_level": reg.danger_level,
            }
            region_zone = LS.region_fish_zone(reg.region_type, reg.danger_level)
    return {
        "skills": ls["skills"],
        "inventory": [{**it, "grade": LS.material_grade(it["id"])} for it in ls["inventory"]],
        "recipes_known": ls["recipes_known"],
        "blueprints_known": ls["blueprints_known"],
        "foods": ls["foods"],
        "equipment": ls["equipment"],
        "fish_caught": ls["fish_caught"],
        "fish_dex": LS.get_fish_dex(ls),
        "buffs": ls["buffs"],
        "shop": LS.build_shop(overall),
        "recipes": LS.COOK_RECIPES,
        "blueprints": LS.FORGE_BLUEPRINTS,
        "enchant_materials": LS.enchant_materials(),
        "shared_materials": shared_materials,
        "shared_items": shared_items,
        "fish_table": LS.FISH_TABLE,
        "fish_zones": LS.FISH_ZONES,
        "fish_gear_rod": LS.FISH_RODS,
        "fish_gear_reel": LS.FISH_REELS,
        "fish_gear_line": LS.FISH_LINES,
        "fish_gear_bait": LS.FISH_BAITS,
        "fish_gear_owned": fg.get("owned", []),
        "fish_gear_equipped": fg.get("equipped", {}),
        "fish_zone": region_zone,
        "fish_region": current_region,
        "fish_earnings": fg.get("earnings", 0),
        "gold": char.get("gold", 0),
    }


@app.post("/api/death-mode/life-skills/buy")
def api_death_mode_life_buy(data: dict):
    """商店购买原材料：消耗金币，加入原材料背包"""
    from simlife.backend import life_skills as LS
    engine, state = _life_engine()
    if not state:
        return {"error": "no_game"}
    mat_id = data.get("mat_id", "")
    qty = max(1, int(data.get("qty", 1)))
    mat = LS._find_mat(mat_id)
    if not mat:
        return {"error": "not_found", "message": "材料不存在"}
    char = state["character"]
    gold = char.get("gold", 0)
    cost = mat["price"] * qty
    if gold < cost:
        return {"error": "no_gold", "message": f"金币不足（需要{cost}）"}
    char["gold"] -= cost
    ls = state["life_state"]
    LS.add_materials(ls["inventory"], mat_id, qty, mat["name"], mat["icon"])
    engine._log_action("life_skill", {
        "skill": "采购", "action": f"购买了{qty}个{mat['name']}（-{cost}金币）",
        "detail": {"材料": mat["name"], "数量": qty, "花费": f"-{cost}金币"},
    })
    engine._save()
    return {"success": True, "message": f"购买了{qty}个{mat['name']}（-{cost}金币）",
            "gold": char["gold"], "inventory": ls["inventory"]}


def _life_llm_json(prompt: str, max_tokens: int = 400):
    """调用 LLM 并尽力解析 JSON 对象；失败返回 None（不阻断流程）"""
    import json as _json
    try:
        from simlife.backend.generator import get_llm_client
        llm = get_llm_client()
        resp = llm.generate(prompt, max_tokens=max_tokens, temperature=0.9, thinking=False)
    except Exception:
        return None
    text = (resp or "").strip()
    if "```" in text:
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else text
        if text.startswith("json"):
            text = text[4:].lstrip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        obj = _json.loads(text[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


@app.post("/api/death-mode/life-skills/cook")
def api_death_mode_life_cook(data: dict):
    """烹饪判定：recipe_id（固定菜谱）或自由组合（materials + steps）
    steps_sorted: 用户排序后的步骤索引数组（每位对应预期步骤，值=用户选择的步骤）
    """
    from simlife.backend import life_skills as LS
    engine, state = _life_engine()
    if not state:
        return {"error": "no_game"}
    ls = state["life_state"]
    cooking = ls["skills"]["cooking"]
    recipe_id = data.get("recipe_id")
    free_materials = data.get("materials")  # 自由组合 [[id, qty], ...]
    recipe = LS.get_cook_recipe(recipe_id) if recipe_id else None
    is_free = (not recipe) and bool(free_materials)

    if not recipe and not is_free:
        return {"error": "no_recipe", "message": "请选择菜谱或自由组合材料"}

    # ── 自由烹饪：中餐工序 + LLM 动态生成料理 ──
    if is_free:
        if not LS.has_materials(ls["inventory"], free_materials):
            return {"error": "no_materials", "message": "材料不足，无法自由烹饪"}
        mat_val = LS.material_value(ls["inventory"], free_materials)
        if mat_val < 4:
            return {"error": "too_few", "message": "材料太少，不足以烹饪出像样的料理"}
        # 中餐工序参数
        cut = data.get("cut") or "切块"
        marinade = data.get("marinade") or "不腌"
        marinade_t = data.get("marinade_t") or ""
        method = data.get("method") or "炒"
        duration = data.get("duration") or "中"
        rule_comment = LS.cook_time_hint(method, duration)
        mat_desc = "、".join(
            f"{((LS._find_mat(mid) or {}).get('name') or mid)}×{qty}" for mid, qty in free_materials)
        llm = _life_llm_json(
            f"你是奇幻世界的中餐大厨。玩家用以下食材：{mat_desc}，进行中餐烹饪：\n"
            f"切型「{cut}」、腌制「{marinade}{marinade_t}」、制作手法「{method}」、火候时长「{duration}」。\n"
            f"请判断火候与手法是否匹配（爆炒焯宜急火、煎炸焖烧宜中火、蒸炖烤煮宜慢火），"
            f"并只输出一个JSON对象："
            f"{{\"name\":\"菜名(2-6字)\",\"icon\":\"一个emoji\",\"buff_type\":\"hp或mp或attack或defense\","
            f"\"comment\":\"一句烹饪评语，结合火候时长评点，如\\\"火太大食材糊了，勉强能吃\\\"或\\\"火候正好，色香味俱全\\\"\"}}")
        base = LS.free_dish_base(cooking["level"], mat_val)
        # 食材品质等级加成：取所选食材最高等级，等级越高恢复量越高
        top_grade = max((LS.material_grade(mid) for mid, _ in free_materials), default=1)
        base["value"] = int(base["value"] * (1 + (top_grade - 1) * 0.15))
        if llm and llm.get("name"):
            dish_name = str(llm["name"])[:12]
            icon = str(llm.get("icon") or "🍲")
            buff_type = str(llm.get("buff_type") or "hp")
            if buff_type not in ("hp", "mp", "attack", "defense"):
                buff_type = "hp"
            comment = str(llm.get("comment") or rule_comment)[:80]
        else:
            dish_name, icon, buff_type = "神秘杂烩", "🍲", "hp"
            comment = rule_comment
        # 含附魔/特殊材料 → 更容易出属性类增益
        has_special = any((LS._find_mat(mid) or {}).get("type") == "enchant" for mid, _ in free_materials)
        if has_special and buff_type in ("hp", "mp"):
            buff_type = random.choice(["attack", "defense"])
        buff = {"type": buff_type, "value": base["value"],
                "turns": 0 if buff_type in ("hp", "mp") else 3}
        result_name = dish_name
        result_icon = icon
        result_level = cooking["level"]
        quality_buff = buff
    else:
        # ── 固定菜谱 ──
        if not LS.has_materials(ls["inventory"], recipe["materials"]):
            return {"error": "no_materials", "message": "材料不足，无法烹饪"}
        if cooking["level"] < recipe["level"]:
            return {"error": "low_level", "message": f"烹饪等级不足（需要{recipe['level']}级）"}
        target_steps = recipe["steps"]
        steps_sorted = data.get("steps", [])
        if not steps_sorted or len(steps_sorted) < len(target_steps):
            return {"error": "incomplete", "message": "步骤未完成"}
        result_name = recipe["result"]["name"]
        result_icon = recipe["icon"]
        result_level = recipe["level"]
        quality_buff = dict(recipe["buff"])

    # 品质判定
    if is_free:
        # 自由烹饪：品质由火候与手法匹配度决定，高等级食材可补救火候失误
        quality = LS.cook_quality_by_heat(method, duration)
        if top_grade >= 4 and quality == "bad":
            quality = "normal"
        if top_grade >= 5 and quality == "normal":
            quality = "good"
    else:
        # 固定菜谱：按步骤排序判定
        judgements = []
        for i in range(len(target_steps)):
            input_step = int(steps_sorted[i]) if i < len(steps_sorted) else 0
            judgements.append(LS.judge_step(i, len(target_steps), input_step, cooking["level"]))
        quality = LS.judge_overall(judgements, cooking["level"])

    # 扣除材料
    used_materials = free_materials if is_free else recipe["materials"]
    for mat_id, qty in used_materials:
        LS.remove_materials(ls["inventory"], mat_id, qty)

    # 失败（仅固定菜谱）：返还一半材料，小经验
    is_good = quality in ("perfect", "good")
    if not is_good and not is_free:
        for mat_id, qty in used_materials:
            LS.add_materials(ls["inventory"], mat_id, max(1, qty // 2))
        xp = LS.resource_value("normal")
        lv = LS.add_xp(ls["skills"], "cooking", xp)
        LS.add_item_to_list(ls["foods"], {"name": "焦糊料理", "icon": "🔥", "type": "food",
                                          "buff": {"type": "hp", "value": 5, "turns": 0}}, 1)
        ls["last_activity"] = "烹饪失败，得到一份焦糊料理"
        engine._log_action("life_skill", {
            "skill": "烹饪", "action": "烹饪失败！",
            "detail": {"评价": "失败", "说明": "步骤错误，得到一份焦糊料理（返还部分材料）"},
        })
        engine._save()
        return {"success": False, "quality": quality, "message": "烹饪失败，得到一份焦糊料理（返还部分材料）",
                "xp_gained": xp, "level_up": lv["level_up"], "foods": ls["foods"]}

    # 成功：按品质加成产出
    mult = LS.quality_multiplier(quality)
    buff = dict(quality_buff)
    buff["value"] = int(buff["value"] * mult)
    # 自由烹饪 · 劣质品质：火候失控，产出容易食物中毒的料理（吃了扣血）
    poison = False
    if is_free and quality == "bad":
        poison = True
        buff = {"type": "hp", "value": -max(8, int(buff["value"] * 0.5)), "turns": 0}
    # 自由烹饪 · 完美品质：附带特殊效果（额外持续属性增益）
    special = None
    if is_free and quality == "perfect":
        special = {"type": random.choice(["attack", "defense"]),
                   "value": max(3, int(buff["value"] * 0.3)), "turns": 3, "source": result_name}
    LS.add_item_to_list(ls["foods"], {"name": result_name, "icon": result_icon, "type": "food",
                                      "buff": buff, "level": result_level,
                                      **({"free": True, "desc": (comment if is_free else "")} if is_free else {}),
                                      **({"poison": True} if poison else {}),
                                      **({"special": special} if special else {})}, 1)
    xp = LS.resource_value(quality)
    lv = LS.add_xp(ls["skills"], "cooking", xp)
    if recipe_id and recipe_id not in ls["recipes_known"]:
        ls["recipes_known"].append(recipe_id)
    ls["last_activity"] = f"烹饪成功，得到{result_name}"
    quality_name = {"perfect": "完美", "good": "良好", "normal": "普通", "bad": "劣质"}.get(quality, quality)
    detail = {
        "菜名": result_name,
        "评价": quality_name,
        "回复": f"{buff.get('type','hp')}+{buff.get('value',0)}",
        "评语": comment if is_free else "",
    }
    if special:
        detail["特殊"] = f"附加{special['type']}+{special['value']}（{special['turns']}回合）"
    if poison:
        detail["注意"] = "火候失控，吃了会食物中毒扣血！"
    engine._log_action("life_skill", {
        "skill": "烹饪", "action": f"烹饪出{result_name}",
        "detail": detail,
    })
    engine._save()
    quality_name = {"perfect": "完美", "good": "良好", "normal": "普通", "bad": "劣质"}.get(quality, quality)
    return {"success": True, "quality": quality, "quality_name": quality_name,
            "message": f"烹饪成功！得到{result_name}（{quality_name}品质）",
            "comment": (comment if is_free else ""),
            "special": special, "poison": poison,
            "xp_gained": xp, "level_up": lv["level_up"], "foods": ls["foods"]}


@app.post("/api/death-mode/life-skills/forge")
def api_death_mode_life_forge(data: dict):
    """锻造判定：blueprint_id（设计图/钓鱼装备）或自由组合（materials + steps）
    fishing_gear 设计图产出钓鱼装备；自由组合经 LLM 动态生成装备。
    """
    from simlife.backend import life_skills as LS
    engine, state = _life_engine()
    if not state:
        return {"error": "no_game"}
    ls = state["life_state"]
    forging = ls["skills"]["forging"]
    bp_id = data.get("blueprint_id")
    free_materials = data.get("materials")  # 自由组合 [[id, qty], ...]
    bp = LS.get_forge_blueprint(bp_id) if bp_id else None
    is_free = (not bp) and bool(free_materials)

    if not bp and not is_free:
        return {"error": "no_blueprint", "message": "请选择设计图或自由组合材料"}

    # ── 目标步骤与材料 ──
    if is_free:
        if not LS.has_materials(ls["inventory"], free_materials):
            return {"error": "no_materials", "message": "材料不足，无法锻造"}
        mat_val = LS.material_value(ls["inventory"], free_materials)
        if mat_val < 8:
            return {"error": "too_few", "message": "材料太少，不足以锻造成型"}
        target_steps = ["选材", "加热", "锻打", "淬火", "成型"]
        used_materials = free_materials
    else:
        if not LS.has_materials(ls["inventory"], bp["materials"]):
            return {"error": "no_materials", "message": "材料不足，无法锻造"}
        if forging["level"] < bp["level"]:
            return {"error": "low_level", "message": f"锻造等级不足（需要{bp['level']}级）"}
        target_steps = bp["steps"]
        used_materials = bp["materials"]

    steps_sorted = data.get("steps", [])
    if not steps_sorted or len(steps_sorted) < len(target_steps):
        return {"error": "incomplete", "message": "步骤未完成"}

    judgements = []
    for i in range(len(target_steps)):
        input_step = int(steps_sorted[i]) if i < len(steps_sorted) else 0
        judgements.append(LS.judge_step(i, len(target_steps), input_step, forging["level"]))
    quality = LS.judge_overall(judgements, forging["level"])

    for mat_id, qty in used_materials:
        LS.remove_materials(ls["inventory"], mat_id, qty)

    if quality == "fail":
        for mat_id, qty in used_materials:
            LS.add_materials(ls["inventory"], mat_id, max(1, qty // 2))
        xp = LS.resource_value("normal")
        lv = LS.add_xp(ls["skills"], "forging", xp)
        ls["last_activity"] = "锻造失败，金属报废"
        engine._log_action("life_skill", {
            "skill": "锻造", "action": "锻造失败！",
            "detail": {"评价": "失败", "说明": "步骤错误，金属报废（返还部分材料）"},
        })
        engine._save()
        return {"success": False, "quality": quality, "message": "锻造失败，金属报废（返还部分材料）",
                "xp_gained": xp, "level_up": lv["level_up"]}

    mult = LS.quality_multiplier(quality)
    xp = LS.resource_value(quality)
    lv = LS.add_xp(ls["skills"], "forging", xp)

    # ── 钓鱼装备设计图：产出钓鱼装备 ──
    if bp and bp.get("fishing_gear"):
        fg_info = bp["fishing_gear"]
        LS.forge_fishing_gear(ls, fg_info["slot"], fg_info["gear_id"])
        ls["last_activity"] = f"锻造成功，打造了{bp['name']}"
        quality_name = {"perfect": "完美", "good": "良好", "normal": "普通"}.get(quality, quality)
        engine._log_action("life_skill", {
            "skill": "锻造", "action": f"打造出{bp['name']}",
            "detail": {"装备": bp["name"], "评价": quality_name,
                       "部位": bp["fishing_gear"]["slot"], "用途": "钓鱼装备"},
        })
        engine._save()
        quality_name = {"perfect": "完美", "good": "良好", "normal": "普通"}.get(quality, quality)
        return {"success": True, "quality": quality, "quality_name": quality_name,
                "message": f"锻造成功！打造出{bp['icon']} {bp['name']}（{quality_name}品质），已加入钓鱼装备",
                "xp_gained": xp, "level_up": lv["level_up"],
                "fish_gear_owned": ls.setdefault("fish_gear", {}).get("owned", [])}

    # ── 自由组合：LLM 动态生成装备 ──
    if is_free:
        mat_val = LS.material_value(ls["inventory"], used_materials)
        mat_desc = "、".join(
            f"{((LS._find_mat(mid) or {}).get('name') or mid)}×{qty}" for mid, qty in used_materials)
        llm = _life_llm_json(
            f"你是奇幻世界的锻造大师。玩家用以下材料自由锻造一件装备：{mat_desc}\n"
            f"请只输出一个JSON对象：{{\"name\":\"装备名(2-6字)\",\"icon\":\"一个emoji\",\"item_type\":\"weapon或outfit\",\"damage_type\":\"physical或magic或defense\",\"desc\":\"一句话\"}}")
        base = LS.free_gear_base(forging["level"], mat_val)
        if llm and llm.get("name"):
            result_name = str(llm["name"])[:12]
            result_icon = str(llm.get("icon") or "⚔️")
            item_type = str(llm.get("item_type") or "weapon")
            if item_type not in ("weapon", "outfit"):
                item_type = "weapon"
            damage_type = str(llm.get("damage_type") or "physical")
            if damage_type not in ("physical", "magic", "defense"):
                damage_type = "physical"
        else:
            result_name = "无名兵刃"
            result_icon, item_type, damage_type = "⚔️", "weapon", "physical"
        result = {"name": result_name, "icon": result_icon, "type": item_type,
                  "damage_type": damage_type, "bonus": max(1, int(base["bonus"] * mult)),
                  "free": True, "desc": llm.get("desc", "") if llm else ""}
        rarity_map = {"perfect": "传说", "good": "史诗", "normal": "稀有"}
        result["rarity_name"] = rarity_map.get(quality, "稀有")
        LS.add_item_to_list(ls["equipment"], result, 1)
        ls["last_activity"] = f"锻造成功，得到{result_name}"
        rarity_name = rarity_map.get(quality, "稀有")
        bonus_str = f"{result.get('bonus',0)}"
        engine._log_action("life_skill", {
            "skill": "锻造", "action": f"锻造出{result_name}",
            "detail": {"装备": result_name, "评价": rarity_name,
                       "属性": f"{result.get('type','weapon')}·{result.get('damage_type','physical')}",
                       "加成": f"+{bonus_str}"},
        })
        engine._save()
        quality_name = rarity_map.get(quality, quality)
        return {"success": True, "quality": quality, "quality_name": quality_name,
                "message": f"锻造成功！得到{result['icon']} {result_name}（{quality_name}品质）",
                "xp_gained": xp, "level_up": lv["level_up"], "equipment": ls["equipment"]}

    # ── 固定设计图（武器/防具） ──
    result = dict(bp["result"])
    result["bonus"] = max(1, int(result["bonus"] * mult))
    rarity_map = {"perfect": "传说", "good": "史诗", "normal": "稀有"}
    result["rarity_name"] = rarity_map.get(quality, "稀有")
    LS.add_item_to_list(ls["equipment"], result, 1)
    if bp_id and bp_id not in ls["blueprints_known"]:
        ls["blueprints_known"].append(bp_id)
    ls["last_activity"] = f"锻造成功，得到{result['name']}"
    rarity_name = rarity_map.get(quality, "稀有")
    engine._log_action("life_skill", {
        "skill": "锻造", "action": f"锻造出{result['name']}",
        "detail": {"装备": result["name"], "评价": rarity_name,
                   "属性": result.get("damage_type", "physical"),
                   "加成": f"+{result.get('bonus',0)}"},
    })
    engine._save()
    quality_name = rarity_map.get(quality, quality)
    return {"success": True, "quality": quality, "quality_name": quality_name,
            "message": f"锻造成功！得到{result['name']}（{quality_name}品质）",
            "xp_gained": xp, "level_up": lv["level_up"], "equipment": ls["equipment"]}


@app.post("/api/death-mode/life-skills/enchant")
def api_death_mode_life_enchant(data: dict):
    """附魔：为已锻造装备/钓鱼装备附加属性（消耗附魔材料）
    data: {"item_name": 装备名, "materials": [[id, qty], ...]}
    """
    from simlife.backend import life_skills as LS
    engine, state = _life_engine()
    if not state:
        return {"error": "no_game"}
    ls = state["life_state"]
    name = data.get("item_name", "")
    materials = data.get("materials", [])
    if not materials:
        return {"error": "no_materials", "message": "请选择附魔材料"}
    if not LS.has_materials(ls["inventory"], materials):
        return {"error": "no_materials", "message": "附魔材料不足"}
    # 查找装备（锻造装备 / 钓鱼装备 / 打怪爆的共享背包装备）
    item = next((e for e in ls["equipment"] if e["name"] == name and e.get("qty", 0) > 0), None)
    target = "equipment"
    if not item:
        item = next((f for f in ls["fish_caught"] if f["name"] == name), None)
        target = "fish_caught"
    shared_enchant_idx = None
    if not item:
        shared = state.get("shared_inventory") or []
        shared_enchant_idx = next((i for i, it in enumerate(shared) if it.get("name") == name), None)
        if shared_enchant_idx is not None:
            item = shared[shared_enchant_idx]
            target = "shared_inventory"
    if not item:
        return {"error": "not_found", "message": "没有这件可附魔的物品"}
    if item.get("enchant"):
        return {"error": "enchanted", "message": "该物品已附魔，无法重复附魔"}
    if item.get("effect"):
        return {"error": "enchanted", "message": "该装备自带特殊特效，无法再附魔"}

    mat_val = LS.material_value(ls["inventory"], materials)
    # 从附魔材料提取特效（特殊机制，非仅加数值）
    effects = LS.pick_enchant_effects(materials)
    # LLM 生成附魔效果
    mat_desc = "、".join(
        f"{((LS._find_mat(mid) or {}).get('name') or mid)}×{qty}" for mid, qty in materials)
    llm = _life_llm_json(
        f"你是奇幻世界的附魔师。为装备「{name}」使用材料（{mat_desc}）附魔。\n"
        f"请只输出一个JSON对象：{{\"name\":\"附魔名(2-6字)\",\"stat_type\":\"attack或defense或hp或mp\",\"stat_value\":整数,range 5-40,\"desc\":\"一句话\"}}")
    if llm and llm.get("stat_type") in ("attack", "defense", "hp", "mp"):
        stat_type = llm["stat_type"]
        stat_value = max(3, min(60, int(llm.get("stat_value") or mat_val // 4)))
        enchant_name = str(llm.get("name") or "古老附魔")[:12]
    else:
        stat_type = "attack"
        stat_value = max(3, mat_val // 4)
        enchant_name = "淬火封印"
    # 材料价值越高 → 附魔越强（上限保护）
    stat_value = int(stat_value * (1 + mat_val / 200.0))
    stat_value = min(80, stat_value)

    # 扣除材料
    for mid, qty in materials:
        LS.remove_materials(ls["inventory"], mid, qty)

    if target == "equipment":
        LS.apply_enchant(item, stat_type, stat_value, enchant_name, effects=effects)
    else:
        # 钓鱼装备附魔：记录在 fish 上（供钓鱼属性参考），暂仅存字段
        ench = {"name": enchant_name, "stat_type": stat_type, "stat_value": stat_value}
        if effects:
            ench["effects"] = effects
        item["enchant"] = ench

    ls["last_activity"] = f"为{name}附魔成功：{enchant_name}"
    stat_label = {"attack": "攻击", "defense": "防御", "hp": "生命", "mp": "魔法"}.get(stat_type, stat_type)
    effect_desc = "、".join(eff.get("name", "") for eff in effects) if effects else "无"
    engine._log_action("life_skill", {
        "skill": "附魔", "action": f"为{name}附魔「{enchant_name}」",
        "detail": {"装备": name, "附魔": enchant_name,
                   "效果": f"{stat_label}+{stat_value}", "特效": effect_desc},
    })
    engine._save()
    stat_name = {"attack": "攻击", "defense": "防御", "hp": "生命", "mp": "法力"}.get(stat_type, stat_type)
    msg = f"附魔成功！{name}获得「{enchant_name}」：{stat_name}+{stat_value}"
    if effects:
        msg += "；特效：" + "、".join(eff.get("name", "") for eff in effects)
    return {"success": True, "message": msg,
            "equipment": ls["equipment"], "fish_caught": ls["fish_caught"],
            "inventory": ls["inventory"], "shared_inventory": state.get("shared_inventory") or []}


@app.post("/api/death-mode/life-skills/fish")
def api_death_mode_life_fish(data: dict):
    """钓鱼结算：客户端(实景小游戏)已完成搏斗，提交捕获结果。
    zone: 水域id  fish_id: 捕获的鱼id  weight: 体重kg  quality: 完美/良好/普通
    """
    from simlife.backend import life_skills as LS
    engine, state = _life_engine()
    if not state:
        return {"error": "no_game"}
    ls = state["life_state"]
    fishing = ls["skills"]["fishing"]
    zone = data.get("zone", "pond")
    # 当前区域决定水域：若玩家位于异世界区域，强制使用该区域对应的水域
    region_name = ""
    if engine.world_map:
        reg = engine.world_map.get_current_region()
        if reg:
            region_name = reg.name
            zone = LS.region_fish_zone(reg.region_type, reg.danger_level)
    fish_id = data.get("fish_id", "")
    weight = float(data.get("weight", 1))
    quality = data.get("quality", "normal")

    # 校验水域
    z = LS.get_zone(zone)
    if not z:
        return {"error": "no_zone", "message": "水域不存在"}
    if not LS.zone_unlocked(zone, (ls.get("fish_gear") or {}).get("earnings", 0)):
        return {"error": "locked_zone", "message": f"该水域尚未解锁（需累计收益{z['need']}）"}
    # 校验鱼属于该水域
    fish = LS.get_fish(fish_id)
    if not fish or zone not in fish["zones"]:
        return {"error": "no_fish", "message": "该水域没有这种鱼"}

    # 消耗一份鱼饵（装备背包里的鱼饵材料）
    baits = [it for it in ls["inventory"] if it.get("type") == "bait"]
    if baits:
        LS.remove_materials(ls["inventory"], baits[0]["id"], 1)

    # 体重有效范围
    weight = max(fish["min"], min(fish["max"], weight))
    value = max(1, int(fish["value"] * weight))
    energy = max(1, int(fish["energy"] * weight))
    mult = {"perfect": 1.5, "good": 1.2, "normal": 1.0}.get(quality, 1.0)
    value = max(1, int(value * mult))
    energy = max(1, int(energy * mult))

    # 入账：鱼获 + 累计收益 + 经验
    LS.add_item_to_list(ls["fish_caught"], {
        "name": fish["name"], "icon": fish["icon"], "family": fish["family"],
        "rarity": fish["rarity"], "weight": weight, "value": value, "energy": energy,
    }, 1)
    new_record = LS.mark_fish_dex(ls, fish_id, weight)  # 收集图鉴点亮并返回是否刷新最大重量纪录
    fg = ls.setdefault("fish_gear", {})
    fg["earnings"] = fg.get("earnings", 0) + value
    # 钓到的鱼直接作为独立食材进背包（按鱼种区分，可自由烹饪出对应料理）
    LS.add_materials(ls["inventory"], f"fish_{fish_id}", 1, fish["name"], fish["icon"])
    xp = LS.resource_value(quality) + LS.fish_rarity_weight(fish)
    lv = LS.add_xp(ls["skills"], "fishing", xp)
    ls["last_activity"] = f"钓到了{fish['name']}({weight}kg)"

    # 记录到行动日志，供 A 层/AI 角色读取
    quality_name = {"perfect": "完美", "good": "良好", "normal": "普通"}.get(quality, quality)
    engine._log_action("life_skill", {
        "skill": "钓鱼",
        "action": f"在{region_name}钓到了{fish['name']}",
        "detail": {"鱼": fish["name"], "体重": f"{weight}kg", "评价": quality_name,
                   "价值": f"{value}金币", "地点": region_name, "水域": zone},
    })
    engine._save()

    quality_name = {"perfect": "完美", "good": "良好", "normal": "普通"}.get(quality, quality)
    return {"success": True, "quality": quality, "quality_name": quality_name,
            "message": f"钓到了{fish['name']}（{weight}kg·{quality_name}）！价值{value}金币",
            "fish": {"name": fish["name"], "icon": fish["icon"], "rarity": fish["rarity"],
                     "family": fish["family"], "weight": weight, "value": value, "energy": energy},
            "new_record": bool(new_record), "best": ls["fish_dex"].get(fish_id, {}).get("best"),
            "xp_gained": xp, "level_up": lv["level_up"], "fish_caught": ls["fish_caught"]}


@app.post("/api/death-mode/life-skills/fish-buy-gear")
def api_death_mode_life_fish_buy_gear(data: dict):
    """购买钓鱼装备（杆/轮/线/饵）"""
    from simlife.backend import life_skills as LS
    engine, state = _life_engine()
    if not state:
        return {"error": "no_game"}
    gear_id = data.get("gear_id", "")
    ls = state["life_state"]
    char = state["character"]
    r = LS.buy_fish_gear(ls, gear_id, char.get("gold", 0))
    if not r["success"]:
        return {"error": "buy_fail", "message": r["msg"]}
    char["gold"] = r["gold"]
    engine._log_action("life_skill", {
        "skill": "采购", "action": r["msg"],
        "detail": {"装备": r["msg"]},
    })
    engine._save()
    return {"success": True, "message": r["msg"], "gold": char["gold"],
            "fish_gear_owned": ls["fish_gear"]["owned"]}


@app.post("/api/death-mode/life-skills/fish-equip")
def api_death_mode_life_fish_equip(data: dict):
    """穿戴钓鱼装备"""
    from simlife.backend import life_skills as LS
    engine, state = _life_engine()
    if not state:
        return {"error": "no_game"}
    gear_id = data.get("gear_id", "")
    ls = state["life_state"]
    r = LS.equip_fish_gear(ls, gear_id)
    if not r["success"]:
        return {"error": "equip_fail", "message": r["msg"]}
    engine._log_action("life_skill", {
        "skill": "钓鱼", "action": r["msg"],
        "detail": {"装备": r["msg"]},
    })
    engine._save()
    return {"success": True, "message": r["msg"], "fish_gear_equipped": ls["fish_gear"]["equipped"]}


@app.post("/api/death-mode/life-skills/fish-damage")
def api_death_mode_life_fish_damage(data: dict):
    """钓鱼装备损坏（断线/爆杆）：从已拥有中移除对应装备，需重新购买"""
    from simlife.backend import life_skills as LS
    engine, state = _life_engine()
    if not state:
        return {"error": "no_game"}
    slot = data.get("slot", "")
    ls = state["life_state"]
    r = LS.damage_fish_gear(ls, slot)
    if not r["broken"]:
        return {"success": True, "broken": False, "message": r["msg"]}
    engine._log_action("life_skill", {
        "skill": "钓鱼", "action": f"钓鱼时{r['name']}损坏需更换",
        "detail": {"装备": r["name"], "状态": "已损坏，需重新购买"},
    })
    engine._save()
    return {"success": True, "broken": True, "message": r["msg"],
            "fish_gear_owned": ls["fish_gear"]["owned"],
            "fish_gear_equipped": ls["fish_gear"]["equipped"]}


@app.post("/api/death-mode/life-skills/fish-set-zone")
def api_death_mode_life_fish_set_zone(data: dict):
    """切换到指定水域"""
    from simlife.backend import life_skills as LS
    engine, state = _life_engine()
    if not state:
        return {"error": "no_game"}
    zone = data.get("zone", "")
    ls = state["life_state"]
    fg = ls.setdefault("fish_gear", {})
    if not LS.zone_unlocked(zone, fg.get("earnings", 0)):
        return {"error": "locked_zone", "message": "该水域尚未解锁"}
    fg["zone"] = zone
    zone_name = LS.get_zone(zone)["name"]
    engine._log_action("life_skill", {
        "skill": "钓鱼", "action": f"前往{zone_name}垂钓",
        "detail": {"水域": zone_name},
    })
    engine._save()
    return {"success": True, "message": f"已切换到{zone_name}", "fish_zone": zone}


@app.post("/api/death-mode/life-skills/eat")
def api_death_mode_life_eat(data: dict):
    """食用食物/鱼：获得增益或回复 HP/MP
    target: ai / user / both（一起食用，两人分食同一份，各获 80% 效果）
    """
    from simlife.backend import life_skills as LS
    engine, state = _life_engine()
    if not state:
        return {"error": "no_game"}
    target = data.get("target", "ai")  # ai / user / both
    name = data.get("name", "")
    ls = state["life_state"]

    # 确定食用对象列表
    if target == "both":
        ai_char = state["character"]
        user_char = state.get("user_character")
        if not user_char:
            return {"error": "no_target", "message": "用户角色不存在，无法一起食用"}
        targets = [("ai", ai_char), ("user", user_char)]
    else:
        char = state["character"] if target == "ai" else state.get("user_character")
        if not char:
            return {"error": "no_target", "message": "目标角色不存在"}
        targets = [(target, char)]

    # 从食物或鱼中查找
    item = next((f for f in ls["foods"] if f["name"] == name), None)
    source = "foods"
    if not item:
        item = next((f for f in ls["fish_caught"] if f["name"] == name), None)
        source = "fish_caught"
    if not item:
        return {"error": "not_found", "message": "没有这种食物"}
    if item.get("qty", 0) <= 0:
        return {"error": "empty", "message": "数量不足"}

    # 一起食用：同一份两人分食，各获 80% 效果
    scale = 0.8 if target == "both" else 1.0

    # 扣除一份
    item["qty"] -= 1
    if item["qty"] <= 0:
        ls[source].remove(item)

    msgs = []
    for role, char in targets:
        buff = item.get("buff") or {}
        msg = f"食用了{name}。"
        # HP/MP 回复
        if buff.get("type") == "hp" and buff.get("value", 0) < 0:
            # 劣质料理：食物中毒，扣血（分食按比例）
            dmg = int(round(-buff["value"] * scale))
            char["hp"] = max(0, char.get("hp", 0) - dmg)
            msg += f" 🦠食材不佳中毒，损失{dmg}点HP！"
        elif buff.get("type") == "hp":
            heal = int(round(buff.get("value", 0) * scale))
            char["hp"] = min(char.get("max_hp", char["hp"]), char.get("hp", 0) + heal)
            msg += f" 回复{heal}点HP"
        elif buff.get("type") == "mp":
            heal = int(round(buff.get("value", 0) * scale))
            char["mp"] = min(char.get("max_mp", char["mp"]), char.get("mp", 0) + heal)
            msg += f" 回复{heal}点MP"
        # 临时增益（攻击/防御 持续回合）
        elif buff.get("type") in ("attack", "defense"):
            turns = buff.get("turns", 3)
            val = int(round(buff["value"] * scale))
            # role 标记增益属主（ai/user），供战斗前按角色分配
            ls["buffs"].append({"type": buff["type"], "value": val, "turns": turns, "source": name, "target": role})
            msg += f" 获得{val}点{'攻击' if buff['type']=='attack' else '防御'}增益（{turns}回合）"
        # 鱼类能量
        elif item.get("energy"):
            eng = int(round(item.get("energy", 0) * scale))
            char["hp"] = min(char.get("max_hp", char["hp"]), char.get("hp", 0) + eng)
            msg += f" 回复{eng}点HP"

        # 完美品质特殊效果：额外持续属性增益
        special = item.get("special")
        if special:
            sp = dict(special)
            sp["value"] = int(round(sp.get("value", 0) * scale))
            sp["target"] = role  # 特殊效果同样记录属主
            ls["buffs"].append(sp)
            msg += f" ✨特殊效果：获得{sp['value']}点{'攻击' if sp['type'] == 'attack' else '防御'}增益（{sp['turns']}回合）"

        char["hp"] = max(0, char["hp"])
        actor = "AI角色" if role == "ai" else "玩家"
        msgs.append(f"{actor}：{msg}")
        engine._log_action("life_skill", {
            "skill": "饮食", "action": f"{actor}食用了{name}",
            "detail": {"对象": actor, "食物": name, "效果": msg},
        })

    msg_all = "、".join(msgs)
    engine._save()
    return {"success": True, "message": msg_all, "hp": state["character"].get("hp"), "mp": state["character"].get("mp"),
            "buffs": ls["buffs"], "foods": ls["foods"], "fish_caught": ls["fish_caught"]}


@app.post("/api/death-mode/life-skills/equip-item")
def api_death_mode_life_equip_item(data: dict):
    """把锻造装备放入共享背包（可装备）"""
    from simlife.backend import life_skills as LS
    engine, state = _life_engine()
    if not state:
        return {"error": "no_game"}
    name = data.get("name", "")
    ls = state["life_state"]
    item = next((e for e in ls["equipment"] if e["name"] == name), None)
    if not item:
        return {"error": "not_found", "message": "没有这种锻造装备"}
    if item.get("qty", 0) <= 0:
        return {"error": "empty", "message": "数量不足"}
    item["qty"] -= 1
    if item["qty"] <= 0:
        ls["equipment"].remove(item)
    # 加入共享背包，附带装备属性（含附魔加成）
    stat_bonus = dict(item.get("stat_bonus") or {})
    if item.get("enchant"):
        eh = item["enchant"]
        stat_bonus[eh.get("stat_type", "attack")] = stat_bonus.get(eh.get("stat_type", "attack"), 0) + eh.get("stat_value", 0)
    eq_item = {
        "name": item["name"], "rarity": "epic", "rarity_name": item.get("rarity_name", "稀有"),
        "type": item.get("type", "weapon"), "bonus": item.get("bonus", 0),
        "damage_type": item.get("damage_type", "physical"),
        "stat_bonus": stat_bonus, "level_req": 1, "sell_price": item.get("bonus", 0) * 3,
        "icon": item.get("icon", "⚔️"),
    }
    if item.get("enchant"):
        eq_item["enchant"] = item["enchant"]
    state.setdefault("shared_inventory", []).append(eq_item)
    engine._log_action("life_skill", {
        "skill": "锻造", "action": f"将{item['name']}打造并放入共享背包",
        "detail": {"装备": item["name"], "状态": "已放入共享背包"},
    })
    engine._save()
    return {"success": True, "message": f"已将{item['name']}放入共享背包", "equipment": ls["equipment"]}


@app.post("/api/death-mode/life-skills/dismantle")
def api_death_mode_life_dismantle(data: dict):
    """拆解共享背包里的物品为生活材料（万物皆可锻造）。

    body: {"name": 物品名}。
    普通品质 → 算法按类型/稀有度折算基础材料（确定性）；
    高稀(epic/legendary/紫/橙) → 调 LLM 生成可含预设之外的特殊材料。
    产物进生活材料包，原物品从共享背包移除。
    """
    from simlife.backend import life_skills as LS
    engine, state = _life_engine()
    if not state:
        return {"error": "no_game"}
    name = (data.get("name") or "").strip()
    ls = state["life_state"]
    shared = state.get("shared_inventory") or []
    idx = next((i for i, it in enumerate(shared) if it.get("name") == name), None)
    if idx is None:
        return {"error": "not_found", "message": "共享背包里没有该物品"}
    item = shared[idx]
    rar = str(item.get("rarity") or "") or str(item.get("quality") or "")
    is_rare = rar.lower() in ("epic", "legendary") or rar in ("史诗", "传说", "紫", "橙")

    if is_rare:
        # 高稀有：LLM 生成特色材料（可含预设之外），并限制 1-3 种防失控
        llm = _life_llm_json(
            f"你是炼金拆解师。把高稀有物品「{item.get('name')}」拆解成锻造/附魔材料。\n"
            f"只输出JSON：{{\"materials\":[{{\"id\":\"唯一id\",\"name\":\"材料名(2-6字)\","
            f"\"icon\":\"一个emoji\",\"qty\":整数1-8}}]}},材料1-3种，id用英文字母，"
            f"可创造预设之外的新奇稀有材料。", max_tokens=300)
        mats = []
        for m in (llm or {}).get("materials", [])[:3]:
            mid = str(m.get("id") or "")[:24]
            if not mid:
                continue
            try:
                q = max(1, min(8, int(m.get("qty") or 1)))
            except Exception:
                q = 1
            mats.append({"id": mid, "name": str(m.get("name") or mid)[:10],
                         "icon": str(m.get("icon") or "⚗️")[:4], "qty": q,
                         "type": "rare"})
        if not mats:
            mats = LS.dismantle_basic(item)
    else:
        mats = LS.dismantle_basic(item)

    # 移出共享背包（同名单次拆一件）
    shared.pop(idx)
    # 产物进生活材料包
    for m in mats:
        LS.add_materials(ls["inventory"], m["id"], m["qty"], m.get("name", m["id"]), m.get("icon", "❔"))
    prod_desc = "、".join(f"{m.get('name', m['id'])}×{m['qty']}" for m in mats)
    ls["last_activity"] = f"拆解{item.get('name')}获得{prod_desc}"
    engine._log_action("life_skill", {
        "skill": "拆解", "action": f"拆解{item.get('name')}",
        "detail": {"物品": item.get("name"), "获得": prod_desc,
                   "方式": "炼金拆解" if is_rare else "工坊拆解"},
    })
    engine._save()
    return {"success": True, "message": f"拆解成功！获得{prod_desc}",
            "yields": mats, "inventory": ls["inventory"],
            "shared_inventory": shared}


@app.post("/api/death-mode/life-skills/transfer-material")
def api_death_mode_life_transfer_material(data: dict):
    """把共享背包里的生活材料存入生活材料包（当作便捷仓库中转）。

    body: {"name": "材料名"}。按名称匹配 RAW_MATERIALS，匹配成功的所有同名
    共享物品全部转出并累加到 life_state.inventory。
    """
    from simlife.backend import life_skills as LS
    engine, state = _life_engine()
    if not state:
        return {"error": "no_game"}
    name = (data.get("name") or "").strip()
    ls = state["life_state"]
    shared = state.get("shared_inventory") or []
    mat = LS.match_material_by_name(name)
    if not mat:
        return {"error": "not_material", "message": "这不是生活材料，无法存入"}
    # 收集所有同名共享物品并转出
    total = 0
    kept = []
    for it in shared:
        if it.get("name") == name:
            qty = it.get("qty", 1)
            try:
                qty = int(qty) or 1
            except Exception:
                qty = 1
            total += max(1, qty)
        else:
            kept.append(it)
    if total <= 0:
        return {"error": "not_found", "message": "共享背包里没有该材料"}
    state["shared_inventory"] = kept
    LS.add_materials(ls["inventory"], mat["id"], total, mat["name"], mat["icon"])
    engine._log_action("life_skill", {
        "skill": "仓库", "action": f"将共享背包中的{mat['name']}×{total}存入生活材料包",
        "detail": {"材料": mat["name"], "数量": total},
    })
    engine._save()
    return {"success": True, "message": f"已存入{mat['name']}×{total}",
            "inventory": ls["inventory"]}


@app.post("/api/death-mode/life-skills/sell-fish")
def api_death_mode_life_sell_fish(data: dict):
    """出售鱼获换成金币"""
    from simlife.backend import life_skills as LS
    engine, state = _life_engine()
    if not state:
        return {"error": "no_game"}
    name = data.get("name", "")
    ls = state["life_state"]
    item = next((f for f in ls["fish_caught"] if f["name"] == name), None)
    if not item:
        return {"error": "not_found", "message": "没有这种鱼"}
    if item.get("qty", 0) <= 0:
        return {"error": "empty", "message": "数量不足"}
    item["qty"] -= 1
    if item["qty"] <= 0:
        ls["fish_caught"].remove(item)
    price = item.get("price", 5)
    state["character"]["gold"] = state["character"].get("gold", 0) + price
    engine._log_action("life_skill", {
        "skill": "交易", "action": f"出售{name}获得{price}金币",
        "detail": {"鱼": name, "金币": f"+{price}"},
    })
    engine._save()
    return {"success": True, "message": f"出售{name}获得{price}金币",
            "gold": state["character"]["gold"], "fish_caught": ls["fish_caught"]}


@app.post("/api/death-mode/scene")
def api_death_mode_scene():
    """生成新场景"""
    from simlife.backend.death_mode import DeathModeEngine
    engine = DeathModeEngine()
    result = engine.start_scene()
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@app.post("/api/death-mode/action")
def api_death_mode_action(data: dict):
    """处理用户行动"""
    from simlife.backend.death_mode import DeathModeEngine
    engine = DeathModeEngine()
    choice_id = data.get("choice_id")
    free_action = data.get("free_action")
    sender = data.get("sender", "user")
    result = engine.process_choice(choice_id=choice_id, free_action=free_action, sender=sender)
    if "error" in result:
        raise HTTPException(400, result["error"])
    return result


@app.post("/api/death-mode/transition-chapter")
def api_death_mode_transition_chapter(data: dict = None):
    """网页端"新篇章"按钮：手动触发章节衔接
    - 结局已达成（pending_transition=True）：正常衔接，生成完整结局叙事
    - force=True：即使结局未达成也可主动衔接，生成"未完篇章"叙事
    会生成800字章节总结、新章节开场叙事、新隐藏结局，耗时较长（可能30-60秒）。
    """
    from simlife.backend.death_mode import DeathModeEngine
    force = bool((data or {}).get("force", False))
    engine = DeathModeEngine()
    result = engine.trigger_chapter_transition(force=force)
    if "error" in result:
        raise HTTPException(400, result.get("message", result["error"]))
    return result


@app.get("/api/death-mode/hall")
def api_death_mode_hall():
    """获取死亡名人堂"""
    from simlife.backend.death_mode import DeathModeEngine
    engine = DeathModeEngine()
    return {"hall": engine.get_hall()}


@app.get("/api/death-mode/map")
def api_death_mode_map():
    """获取当前地图信息"""
    from simlife.backend.death_mode import DeathModeEngine
    engine = DeathModeEngine()
    return engine.get_map_info()


@app.post("/api/death-mode/move")
def api_death_mode_move(data: dict):
    """移动到指定区域"""
    from simlife.backend.death_mode import DeathModeEngine
    engine = DeathModeEngine()
    target_id = data.get("region_id", "")
    return engine.move_to_region(target_id)


@app.post("/api/death-mode/move-direction")
def api_death_mode_move_direction(data: dict):
    """按方向移动（北/南/东/西，支持空白格子生成）"""
    from simlife.backend.death_mode import DeathModeEngine
    engine = DeathModeEngine()
    direction = data.get("direction", "")
    return engine.move_by_direction_api(direction)


# ── 地下城API ──
@app.post("/api/death-mode/dungeon-move")
def api_death_mode_dungeon_move(data: dict):
    """在地下城内移动到相邻房间"""
    from simlife.backend.death_mode import DeathModeEngine
    engine = DeathModeEngine()
    return engine.move_to_dungeon_room(data.get("room_id", ""))


@app.post("/api/death-mode/dungeon-exit")
def api_death_mode_dungeon_exit():
    """退出地下城"""
    from simlife.backend.death_mode import DeathModeEngine
    engine = DeathModeEngine()
    return engine.exit_dungeon()


@app.get("/api/death-mode/dungeon-info")
def api_death_mode_dungeon_info():
    """获取当前地下城信息"""
    from simlife.backend.death_mode import DeathModeEngine
    engine = DeathModeEngine()
    return engine.get_dungeon_info()


# ── 队友系统API ──
@app.get("/api/death-mode/recruit-options")
def api_death_mode_recruit_options():
    """获取可招募的队友列表"""
    from simlife.backend.death_mode import DeathModeEngine
    engine = DeathModeEngine()
    return engine.get_recruit_options()


@app.post("/api/death-mode/recruit")
def api_death_mode_recruit(data: dict):
    """招募一个队友"""
    from simlife.backend.death_mode import DeathModeEngine
    engine = DeathModeEngine()
    return engine.recruit_member(data.get("member", {}))


@app.post("/api/death-mode/dismiss")
def api_death_mode_dismiss(data: dict):
    """解散一个队友"""
    from simlife.backend.death_mode import DeathModeEngine
    engine = DeathModeEngine()
    return engine.dismiss_member(data.get("member_id", ""))


@app.post("/api/death-mode/npc-interact")
def api_death_mode_npc_interact(data: dict):
    """与NPC交互"""
    from simlife.backend.death_mode import DeathModeEngine
    engine = DeathModeEngine()
    npc_name = data.get("npc_name", "")
    interaction = data.get("type", "talk")
    return engine.interact_npc(npc_name, interaction)


@app.get("/api/death-mode/npc-deaths")
def api_death_mode_npc_deaths():
    """获取NPC死亡记录"""
    from simlife.backend.death_mode import DeathModeEngine
    engine = DeathModeEngine()
    return {"records": engine.get_npc_death_records()}


@app.get("/api/death-mode/equipment")
def api_death_mode_equipment():
    """获取当前装备和背包"""
    from simlife.backend.death_mode import DeathModeEngine
    from simlife.backend.equipment_system import EquipmentSystem
    engine = DeathModeEngine()
    state = engine._load()
    if not state:
        return {"error": "no_game"}
    char = state.get("character", {})
    return {
        "equipment": char.get("equipment", []),
        "inventory": char.get("inventory", []),
        "equipment_summary": EquipmentSystem.get_equipment_summary(char),
        "inventory_summary": EquipmentSystem.get_inventory_summary(char),
        "gold": char.get("gold", 0),
    }


@app.post("/api/death-mode/equip-shared")
def api_death_mode_equip_shared(data: dict):
    """从共享背包穿戴装备到指定角色（target: 'ai' / 'user'）"""
    from simlife.backend.death_mode import DeathModeEngine
    from simlife.backend.equipment_system import EquipmentSystem
    engine = DeathModeEngine()
    state = engine._load()
    if not state:
        return {"error": "no_game"}
    item_name = data.get("item_name", "")
    target = data.get("target", "ai")
    shared_inv = state.get("shared_inventory", [])
    # 查找物品
    found = None
    for item in shared_inv:
        if item.get("name") == item_name or item_name in item.get("name", ""):
            found = item
            break
    if not found:
        return {"error": "item_not_found", "message": f"背包中没有{item_name}"}
    # 确定目标角色
    char = state["character"] if target == "ai" else state.get("user_character")
    if not char or not char.get("class_name"):
        return {"error": "no_target", "message": "用户角色数据不存在，请重新创建游戏"}
    # 穿戴
    result = EquipmentSystem.equip_item(char, found)
    # 从共享背包移除
    state["shared_inventory"] = [i for i in shared_inv if i is not found]
    # 被替换的旧装备放回共享背包
    old_inv = char.get("inventory", [])
    if old_inv:
        state["shared_inventory"].extend(old_inv)
        char["inventory"] = []
    engine._save()
    return result


@app.post("/api/death-mode/sell-shared")
def api_death_mode_sell_shared(data: dict):
    """从共享背包出售装备"""
    from simlife.backend.death_mode import DeathModeEngine
    engine = DeathModeEngine()
    state = engine._load()
    if not state:
        return {"error": "no_game"}
    item_name = data.get("item_name", "")
    shared_inv = state.get("shared_inventory", [])
    found = None
    for item in shared_inv:
        if item.get("name") == item_name or item_name in item.get("name", ""):
            found = item
            break
    if not found:
        return {"error": "item_not_found", "message": f"背包中没有{item_name}"}
    sell_price = found.get("sell_price", 5)
    state["shared_inventory"] = [i for i in shared_inv if i is not found]
    state["character"]["gold"] = state["character"].get("gold", 0) + sell_price
    engine._save()
    return {"success": True, "sold": found.get("name", item_name), "gold": sell_price}


@app.post("/api/death-mode/unequip-shared")
def api_death_mode_unequip_shared(data: dict):
    """卸下已穿戴的装备到共享背包（target: 'ai' / 'user'）"""
    from simlife.backend.death_mode import DeathModeEngine
    from simlife.backend.equipment_system import EquipmentSystem
    engine = DeathModeEngine()
    state = engine._load()
    if not state:
        return {"error": "no_game"}
    item_name = data.get("item_name", "")
    target = data.get("target", "ai")
    char = state["character"] if target == "ai" else state.get("user_character")
    if not char or not char.get("class_name"):
        return {"error": "no_target", "message": "用户角色数据不存在，请重新创建游戏"}
    result = EquipmentSystem.unequip_item(char, item_name)
    if result.get("success"):
        # 卸下的装备放回共享背包
        old_inv = char.get("inventory", [])
        if old_inv:
            state.setdefault("shared_inventory", []).extend(old_inv)
            char["inventory"] = []
        engine._save()
    return result


@app.get("/api/death-mode/log")
def api_death_mode_log(limit: int = 50, offset: int = 0):
    """获取行动日志（网页端展示用）"""
    from simlife.backend.death_mode import DeathModeEngine
    engine = DeathModeEngine()
    return engine.get_action_log(limit=limit, offset=offset)


# ── 技能系统 API ─────────────────────────────────────


@app.get("/api/death-mode/learnable-skills")
def api_death_mode_learnable_skills(who: str = "ai"):
    """
    获取所有可学习的技能（跨职业自由选择）
    who: "ai" 或 "user"
    """
    from simlife.backend.death_mode import DeathModeEngine
    from simlife.backend.skill_system import SkillSystem

    engine = DeathModeEngine()
    state = engine._load()
    if not state:
        raise HTTPException(400, "游戏未开始")

    world_type = state.get("world_type", "fantasy")
    who = who.strip().lower()

    if who == "user":
        character = state.get("user_character", {})
    else:
        character = state.get("character", {})

    if not character or not character.get("class_name"):
        raise HTTPException(400, "角色未初始化")

    level = character.get("level", 1)
    stats = character.get("stats", {})
    known_skills = character.get("skills", [])

    # 获取所有可学技能
    learnable = SkillSystem.get_all_learnable_skills(
        world_type, level, stats, known_skills
    )

    # 获取剩余技能槽位
    from simlife.backend.skill_system import MAX_SKILLS
    normal_skills_count = len([sid for sid in known_skills if not sid.startswith("awakening_")])
    remaining_slots = MAX_SKILLS - normal_skills_count

    return {
        "learnable_skills": [
            {
                "skill": _skill_with_power(item["skill"], character),
                "source": item["source"],
                "source_class_id": item["source_class_id"],
                "class_icon": item["class_icon"],
            }
            for item in learnable
        ],
        "known_skills": known_skills,
        "skill_count": normal_skills_count,
        "max_skills": MAX_SKILLS,
        "remaining_slots": remaining_slots,
        "skill_points": character.get("skill_points", 0),
    }


@app.post("/api/death-mode/learn-skill")
def api_death_mode_learn_skill(data: dict):
    """
    学习技能
    data: {"skill_id": "war_heavy_strike", "who": "ai"}
    who: "ai" 或 "user"
    """
    from simlife.backend.death_mode import DeathModeEngine
    from simlife.backend.skill_system import SkillSystem, MAX_SKILLS

    skill_id = data.get("skill_id", "").strip()
    who = data.get("who", "ai").strip().lower()

    if not skill_id:
        raise HTTPException(400, "请指定要学习的技能ID")

    engine = DeathModeEngine()
    state = engine._load()
    if not state:
        raise HTTPException(400, "游戏未开始")

    if who == "user":
        character = state.get("user_character", {})
    else:
        character = state.get("character", {})

    if not character or not character.get("class_name"):
        raise HTTPException(400, "角色未初始化")

    # 检查技能是否存在
    skill = SkillSystem.get_skill(skill_id)
    if not skill:
        raise HTTPException(400, f"技能不存在: {skill_id}")

    # 检查是否已学习
    if skill_id in character.get("skills", []):
        raise HTTPException(400, f"已学习技能「{skill.name}」")

    # 检查技能槽位
    normal_skills = [sid for sid in character.get("skills", []) if not sid.startswith("awakening_")]
    if len(normal_skills) >= MAX_SKILLS:
        raise HTTPException(400, f"技能已达上限（{MAX_SKILLS}个）")

    # 检查技能学习点（每升2级获得1个技能点）
    skill_points = character.get("skill_points", 0)
    if skill_points <= 0:
        raise HTTPException(400, "技能学习点不足（每升2级获得1个技能点）")

    # 检查等级需求
    level = character.get("level", 1)
    if skill.req_level > level:
        raise HTTPException(400, f"需要等级{skill.req_level}，当前等级{level}")

    # 检查属性需求
    stats = character.get("stats", {})
    for stat, val in skill.req_stats.items():
        if stats.get(stat, 0) < val:
            raise HTTPException(400, f"需要{stat}≥{val}，当前{stats.get(stat, 0)}")

    # 学习技能（消耗1个技能点）
    character.setdefault("skills", []).append(skill_id)
    character["skill_points"] = skill_points - 1
    engine._save()

    return {
        "success": True,
        "skill_name": skill.name,
        "skill_id": skill_id,
        "skill_count": len([s for s in character.get("skills", []) if not s.startswith("awakening_")]),
        "max_skills": MAX_SKILLS,
        "skill_points": character["skill_points"],
        "message": f"学习了技能「{skill.name}」",
    }


@app.post("/api/death-mode/allocate-stats")
def api_death_mode_allocate_stats(data: dict):
    """分配属性点 data: {"who": "ai"/"user", "allocations": {"strength": 1, ...}}"""
    from simlife.backend.death_mode import DeathModeEngine
    from simlife.backend.growth_system import GrowthSystem

    who = data.get("who", "ai").strip().lower()
    allocations = data.get("allocations", {})

    engine = DeathModeEngine()
    state = engine._load()
    if not state:
        raise HTTPException(400, "游戏未开始")

    if who == "user":
        character = state.get("user_character", {})
    else:
        character = state.get("character", {})

    if not character or not character.get("class_name"):
        raise HTTPException(400, "角色未初始化")

    success, msg = GrowthSystem.allocate_stat_points(character, allocations)
    if not success:
        raise HTTPException(400, msg)

    engine._save()
    return {
        "success": True,
        "message": msg,
        "stat_points": character.get("stat_points", 0),
        "stats": character.get("stats", {}),
    }


@app.get("/api/death-mode/passive-skill")
def api_death_mode_passive_skill(who: str = "ai"):
    """获取角色职业被动技能"""
    from simlife.backend.death_mode import DeathModeEngine
    from simlife.backend.skill_system import SkillSystem

    engine = DeathModeEngine()
    state = engine._load()
    if not state:
        raise HTTPException(400, "游戏未开始")

    world_type = state.get("world_type", "fantasy")
    who = who.strip().lower()

    if who == "user":
        character = state.get("user_character", {})
    else:
        character = state.get("character", {})

    if not character or not character.get("class_name"):
        raise HTTPException(400, "角色未初始化")

    passive = SkillSystem.get_passive_skill(world_type, character.get("class_id", ""))
    if not passive:
        return {"name": "", "description": ""}
    return passive


def _skill_with_power(skill, character=None):
    """给 Skill 对象附加 power_text 数值参考（返回新 dict，不改原对象）"""
    from simlife.backend.skill_system import build_skill_power_text
    d = skill.to_dict()
    try:
        d["power_text"] = build_skill_power_text(skill, character)
    except Exception:
        d["power_text"] = build_skill_power_text(skill)
    if not d.get("power_text"):
        d["power_text"] = build_skill_power_text(skill)
    return d


@app.get("/api/death-mode/skill-info")
def api_death_mode_skill_info(skill_id: str = "", who: str = "ai"):
    """获取技能信息 by ID（可附数值参考 power_text，需指定 who 拿对应角色属性）"""
    from simlife.backend.skill_system import SkillSystem, build_skill_power_text
    from simlife.backend.death_mode import DeathModeEngine
    if not skill_id:
        return {"error": "no_skill_id"}
    skill = SkillSystem.get_skill(skill_id)
    if not skill:
        return {"error": "skill_not_found"}
    data = skill.to_dict()
    try:
        state = DeathModeEngine()._load()
        role = None
        if state:
            role = state.get("user_character", {}) if who.strip().lower() == "user" else state.get("character", {})
            role = role or None
        data["power_text"] = build_skill_power_text(skill, role)
    except Exception:
        data["power_text"] = _skill_with_power(skill)["power_text"]
    if not data.get("power_text"):
        data["power_text"] = _skill_with_power(skill)["power_text"]
    return data


@app.get("/api/death-mode/awakening-skills")
def api_death_mode_awakening_skills(who: str = "ai"):
    """获取觉醒技能槽位状态"""
    from simlife.backend.death_mode import DeathModeEngine
    from simlife.backend.skill_system import SkillSystem

    engine = DeathModeEngine()
    state = engine._load()
    if not state:
        raise HTTPException(400, "游戏未开始")

    who = who.strip().lower()
    if who == "user":
        character = state.get("user_character", {})
    else:
        character = state.get("character", {})

    if not character or not character.get("class_name"):
        raise HTTPException(400, "角色未初始化")

    slots = SkillSystem.get_awakening_slots(character)

    return {
        "slots": [
            {
                "slot_index": s["slot_index"],
                "is_empty": s["is_empty"],
                "skill": s["skill"].to_dict() if s["skill"] else None,
                "req_level": s["req_level"],
                "unlocked": s["unlocked"],
            }
            for s in slots
        ],
        "total_slots": 3,
        "char_level": character.get("level", 1),
    }


@app.post("/api/death-mode/set-awakening")
def api_death_mode_set_awakening(data: dict):
    """
    设置觉醒技能
    data: {
        "who": "ai",
        "slot_index": 0,
        "name": "觉醒技名",
        "type": "physical",
        "mp_cost": 10,
        "effects": [{"type": "damage", "target": "single_enemy", "value": 2.0}],
        "description": "技能描述",
        "cooldown": 0,
    }
    """
    from simlife.backend.death_mode import DeathModeEngine
    from simlife.backend.skill_system import SkillSystem

    who = data.get("who", "ai").strip().lower()
    slot_index = data.get("slot_index", 0)
    name = data.get("name", "").strip()
    skill_type = data.get("type", "physical")
    mp_cost = data.get("mp_cost", 10)
    effects = data.get("effects", [])
    description = data.get("description", "")
    cooldown = data.get("cooldown", 0)

    if not name:
        raise HTTPException(400, "技能名称不能为空")

    if not effects:
        raise HTTPException(400, "至少需要一个效果")

    engine = DeathModeEngine()
    state = engine._load()
    if not state:
        raise HTTPException(400, "游戏未开始")

    if who == "user":
        character = state.get("user_character", {})
    else:
        character = state.get("character", {})

    if not character or not character.get("class_name"):
        raise HTTPException(400, "角色未初始化")

    skill_data = {
        "name": name,
        "type": skill_type,
        "mp_cost": mp_cost,
        "effects": effects,
        "description": description,
        "cooldown": cooldown,
    }

    success, msg = SkillSystem.set_awakening_skill(character, slot_index, skill_data)
    if not success:
        raise HTTPException(400, msg)

    engine._save()

    return {
        "success": True,
        "message": msg,
        "slot_index": slot_index,
        "skill_name": name,
    }


# ── 用户入驻管理 API ─────────────────────────────────

USER_PROFILE_PATH = DATA_DIR / "user_profile.json"


def _load_user_profile() -> dict:
    """加载用户在世界中的身份信息"""
    if USER_PROFILE_PATH.exists():
        try:
            content = USER_PROFILE_PATH.read_text(encoding="utf-8").strip()
            if content:
                return json.loads(content)
        except (json.JSONDecodeError, OSError):
            pass
    return {"entered": False}


def _save_user_profile(profile: dict):
    """保存用户身份信息"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(USER_PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════
# 任务系统 API
# ═══════════════════════════════════════════════════
@app.get("/api/death-mode/quests/available")
def api_death_mode_available_quests(who: str = "ai"):
    """获取可接任务列表"""
    from simlife.backend.death_mode import DeathModeEngine
    from simlife.backend.quest_system import QuestSystem

    engine = DeathModeEngine()
    state = engine._load()
    if not state:
        raise HTTPException(400, "游戏未开始")

    who = who.strip().lower()
    character = state.get("user_character", {}) if who == "user" else state.get("character", {})
    if not character or not character.get("class_name"):
        raise HTTPException(400, "角色未初始化")

    available = QuestSystem.get_available_quests(state, character)
    offers = QuestSystem.get_available_offers(state)
    # 合并：动态 offers + 预定义任务
    combined = list(offers) + list(available)
    return {
        "available_quests": combined,
        "count": len(combined),
        "dynamic_count": len(offers),
        "predefined_count": len(available),
    }


@app.get("/api/death-mode/quests/active")
def api_death_mode_active_quests():
    """获取进行中任务"""
    from simlife.backend.death_mode import DeathModeEngine
    from simlife.backend.quest_system import QuestSystem

    engine = DeathModeEngine()
    state = engine._load()
    if not state:
        raise HTTPException(400, "游戏未开始")

    active = QuestSystem.get_active_quests(state)
    turned_in = state.get("quests", {}).get("turned_in_ids", [])
    return {
        "active_quests": active,
        "completed_ids": turned_in,
        "count": len(active),
    }


@app.post("/api/death-mode/quests/accept")
def api_death_mode_accept_quest(data: dict):
    """接受任务 data: {"quest_id": "...", "who": "ai"}"""
    from simlife.backend.death_mode import DeathModeEngine
    from simlife.backend.quest_system import QuestSystem

    quest_id = data.get("quest_id", "").strip()
    who = data.get("who", "ai").strip().lower()
    if not quest_id:
        raise HTTPException(400, "请指定任务ID")

    engine = DeathModeEngine()
    state = engine._load()
    if not state:
        raise HTTPException(400, "游戏未开始")

    character = state.get("user_character", {}) if who == "user" else state.get("character", {})
    if not character or not character.get("class_name"):
        raise HTTPException(400, "角色未初始化")

    ok, msg = QuestSystem.accept_quest(state, quest_id, character)
    if not ok:
        raise HTTPException(400, msg)
    engine._save()
    return {"success": True, "message": msg}


@app.post("/api/death-mode/quests/turn-in")
def api_death_mode_turn_in_quest(data: dict):
    """交付任务 data: {"quest_id": "...", "who": "ai"}"""
    from simlife.backend.death_mode import DeathModeEngine
    from simlife.backend.quest_system import QuestSystem
    from simlife.backend.growth_system import GrowthSystem

    quest_id = data.get("quest_id", "").strip()
    who = data.get("who", "ai").strip().lower()
    if not quest_id:
        raise HTTPException(400, "请指定任务ID")

    engine = DeathModeEngine()
    state = engine._load()
    if not state:
        raise HTTPException(400, "游戏未开始")

    character = state.get("user_character", {}) if who == "user" else state.get("character", {})
    if not character or not character.get("class_name"):
        raise HTTPException(400, "角色未初始化")

    ok, msg, rewards = QuestSystem.turn_in_quest(state, quest_id, character)
    if not ok:
        raise HTTPException(400, msg)

    # 任务奖励：经验/金币同时发放给两位同伴（焕灵 + yount），并肩作战共享战果
    exp_gain = rewards.get("exp", 0)
    gold_gain = rewards.get("gold", 0)
    world_type = state.get("world_type", "fantasy")
    growth_mode = state.get("growth_mode", "normal")

    # 两位角色的经验都加（turn_in_quest 内金币只加到 character，这里补另一位角色金币）
    both_chars = []
    _ai = state.get("character", {})
    _user = state.get("user_character", {})
    if _ai and _ai.get("class_name"):
        both_chars.append(_ai)
    if _user and _user.get("class_name"):
        both_chars.append(_user)

    for c in both_chars:
        c["world_type"] = world_type
        # 经验
        if exp_gain > 0:
            GrowthSystem.gain_exp(c, exp_gain, growth_mode)
        # 金币：turn_in_quest 已给传入的 character 加了金币，这里只给"另一位"补
        # 为避免重复，记录已加过的
    if gold_gain > 0:
        # character 已在 turn_in_quest 内获得金币，补发给另一位同伴
        for c in both_chars:
            if c is character:
                continue
            c["gold"] = c.get("gold", 0) + gold_gain

    # 把物品奖励加到共享背包
    if rewards.get("items"):
        shared_inv = state.setdefault("shared_inventory", [])
        for item_def in rewards["items"]:
            shared_inv.append({
                "name": item_def.get("name", "未知物品"),
                "rarity": item_def.get("rarity", "common"),
                "rarity_name": {"common": "普通", "rare": "稀有",
                                "epic": "史诗", "legendary": "传说"}.get(item_def.get("rarity", "common"), "普通"),
                "type": "misc",
                "bonus": 0,
                "stat_bonus": {},
                "level_req": 1,
                "sell_price": 10,
            })

    # 经验奖励说明（用于前端展示两人都获得）
    reward_names = []
    if exp_gain > 0:
        reward_names.append(f"经验+{exp_gain}×2")
    if gold_gain > 0:
        reward_names.append(f"金币+{gold_gain}")
    if rewards.get("items"):
        reward_names.append("物品")
    if reward_names:
        msg += f"（{'，'.join(reward_names)}）"

    engine._save()
    return {"success": True, "message": msg, "rewards": rewards}


@app.post("/api/death-mode/quests/abandon")
def api_death_mode_abandon_quest(data: dict):
    """放弃任务 data: {"quest_id": "..."}"""
    from simlife.backend.death_mode import DeathModeEngine
    from simlife.backend.quest_system import QuestSystem

    quest_id = data.get("quest_id", "").strip()
    if not quest_id:
        raise HTTPException(400, "请指定任务ID")

    engine = DeathModeEngine()
    state = engine._load()
    if not state:
        raise HTTPException(400, "游戏未开始")

    ok, msg = QuestSystem.abandon_quest(state, quest_id)
    if not ok:
        raise HTTPException(400, msg)
    engine._save()
    return {"success": True, "message": msg}


@app.get("/api/death-mode/quests/series")
def api_death_mode_quest_series():
    """获取系列任务总览"""
    from simlife.backend.death_mode import DeathModeEngine
    from simlife.backend.quest_system import QuestSystem

    engine = DeathModeEngine()
    state = engine._load()
    if not state:
        raise HTTPException(400, "游戏未开始")

    world_type = state.get("world_type", "fantasy")
    series = QuestSystem.get_series_overview(state, world_type)
    return {"series": series, "count": len(series)}


# ═══════════════════════════════════════════════════
# 世界新闻 API
# ═══════════════════════════════════════════════════
@app.get("/api/death-mode/world-news")
def api_death_mode_world_news(limit: int = 20):
    """获取冒险者酒馆新闻列表"""
    from simlife.backend.death_mode import DeathModeEngine
    from simlife.backend.world_progress import WorldProgress

    engine = DeathModeEngine()
    state = engine._load()
    if not state:
        raise HTTPException(400, "游戏未开始")

    news = WorldProgress.get_recent_news(state, limit=limit)
    unread = WorldProgress.get_unread_count(state)
    play_days = state.get("play_time_days", 1)
    return {
        "news": news,
        "unread_count": unread,
        "play_days": play_days,
    }


@app.post("/api/death-mode/world-news/mark-read")
def api_death_mode_mark_news_read(data: dict = None):
    """标记新闻已读 data: {"news_id": "..."} 或 {} 全部已读"""
    from simlife.backend.death_mode import DeathModeEngine
    from simlife.backend.world_progress import WorldProgress

    engine = DeathModeEngine()
    state = engine._load()
    if not state:
        raise HTTPException(400, "游戏未开始")

    news_id = (data or {}).get("news_id")
    count = WorldProgress.mark_news_read(state, news_id)
    engine._save()
    return {"success": True, "marked_count": count}


@app.get("/api/user/profile")
def api_get_user_profile():
    """获取用户当前入驻状态和身份"""
    return _load_user_profile()


@app.post("/api/user/profile")
def api_set_user_profile(data: dict):
    """设置用户在世界中的身份信息"""
    profile = _load_user_profile()
    profile["name"] = data.get("name", "") or profile.get("name", "")
    profile["relation"] = data.get("relation", "")
    profile["world_role"] = data.get("world_role", "")

    # 死亡模式能力设定（仅在非现代世界时有效）
    if data.get("class_id"):
        profile["class_id"] = data.get("class_id")
    if data.get("stats"):
        profile["stats"] = data.get("stats")
    if data.get("skills"):
        profile["skills"] = data.get("skills")
    if data.get("hp") is not None:
        profile["hp"] = data.get("hp")
    if data.get("max_hp") is not None:
        profile["max_hp"] = data.get("max_hp")
    if data.get("level") is not None:
        profile["level"] = data.get("level")

    if profile["relation"]:
        _save_user_profile(profile)
    return {"status": "ok", "profile": profile}


@app.post("/api/user/enter")
def api_user_enter():
    """用户进入 SimLife 世界"""
    profile = _load_user_profile()
    if not profile.get("relation"):
        raise HTTPException(400, "请先设置你与角色的关系")
    profile["entered"] = True
    profile["entered_at"] = datetime.now().isoformat()
    _save_user_profile(profile)
    # 记录到世界日志
    if world_state:
        user_name = profile.get("name", "用户")
        relation = profile.get("relation", "")
        world_state.today_log.append(LogEntry(
            time=datetime.now().strftime("%H:%M"),
            event=f"🎂 {user_name}（{relation}）来到了"
        ))
        _save_world_state(world_state)
    return {"status": "ok", "entered": True}


@app.post("/api/user/leave")
def api_user_leave():
    """用户离开 SimLife 世界"""
    profile = _load_user_profile()
    profile["entered"] = False
    profile["entered_at"] = None
    _save_user_profile(profile)
    # 记录到世界日志
    if world_state:
        user_name = profile.get("name", "用户")
        world_state.today_log.append(LogEntry(
            time=datetime.now().strftime("%H:%M"),
            event=f"👋 {user_name}离开了"
        ))
        _save_world_state(world_state)
    return {"status": "ok", "entered": False}


# ── 前端静态文件 ─────────────────────────────────────

@app.get("/")
def serve_index():
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return "<h1>SimLife</h1><p>前端文件未找到，请运行 setup.py</p>"


# 挂载前端静态文件（JS/CSS/图片）
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

# 挂载 AGI 生成的图片目录（供场景图等展示）
try:
    from engine.image_gen import get_image_dir
    _agi_image_dir = str(get_image_dir())
    if os.path.isdir(_agi_image_dir):
        app.mount("/agi-images", StaticFiles(directory=_agi_image_dir), name="agi-images")
except Exception:
    pass

# favicon 路由（避免404）
@app.get("/favicon.ico")
async def favicon():
    from fastapi.responses import Response
    return Response(content=b'', media_type="image/x-icon")


@app.on_event("startup")
def on_startup():
    global character_card, world_state, agidpa_reader, weather_service, current_world_id

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 加载当前世界观 ID
    try:
        from simlife.worlds.world_manager import get_current_world_id as _get_wid
        current_world_id = _get_wid()
        if current_world_id != "modern":
            print(f"[SimLife] 当前世界观: {current_world_id}")
    except Exception:
        pass

    # 加载人物卡
    character_card = _load_character_card()

    # 加载世界状态
    if character_card:
        world_state = _load_world_state()

    # AGI-DPA 读取器
    config = _load_config()
    agidpa_path = config.get("agidpa_data_path", "")
    agidpa_reader = AGIDPAReader(agidpa_path)

    # 天气服务（Open-Meteo 免费 API，无需配置 Key，根据人物卡城市自动定位）
    city = character_card.basic.city if character_card else "上海"
    weather_service = WeatherService(city=city)
    geo = weather_service._geo
    if geo:
        print(f"[SimLife] 天气服务已启用（{city}，{geo[0]:.2f}°N {geo[1]:.2f}°E）")
    else:
        print(f"[SimLife] 天气服务：城市「{city}」未找到坐标，使用季节推断")

    print("[SimLife] 后端启动")
    if character_card:
        print(f"[SimLife] 角色: {character_card.basic.name}")
        h = get_holiday_info()
        if h:
            print(f"[SimLife] 今天: {h['label']}（{h['type']}）")
        _tick()
    else:
        print("[SimLife] 未初始化，请访问设置页面")

    # ── 后台定时 tick 线程（不依赖前端轮询，每 3 分钟自动推进一次）──
    def _background_tick_loop():
        while True:
            try:
                import time
                time.sleep(180)  # 每 3 分钟
                _tick()
            except Exception as e:
                print(f"[SimLife] 后台tick出错: {e}")

    _bg_thread = threading.Thread(target=_background_tick_loop, daemon=True)
    _bg_thread.start()
    print("[SimLife] 后台定时 tick 已启动（每 3 分钟）")


def run_server(port: int = 87659, open_browser: bool = True):
    """启动服务器"""
    import uvicorn

    def _open():
        import time
        time.sleep(1.5)
        webbrowser.open(f"http://127.0.0.1:{port}")

    if open_browser:
        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SimLife 后端")
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    run_server(port=args.port, open_browser=not args.no_browser)
