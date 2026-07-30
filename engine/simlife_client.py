"""
SimLife 客户端 - 主 AGI-DPA 系统读取 SimLife 生活状态
通过 HTTP API (端口 87659) 或直接读文件（更可靠）获取状态
"""

import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional
from datetime import datetime


# 场景枚举 → 中文标签（与 simlife/backend/character.py 保持一致）
_SCENE_LABELS = {
    "HOME_SLEEPING": "睡觉",
    "HOME_MORNING": "晨间准备",
    "HOME_EVENING": "晚间放松",
    "HOME_WEEKEND_LAZY": "周末赖床",
    "HOME_WORKING": "在家办公",
    "COMMUTE_TO_WORK": "去公司",
    "COMMUTE_TO_HOME": "回家",
    "OFFICE_WORKING": "工作中",
    "OFFICE_MEETING": "开会",
    "OFFICE_LUNCH": "午休觅食",
    "CAFE_WORKING": "咖啡馆办公",
    "OUTDOOR_WORKING": "户外工作",
    "STUDIO_WORKING": "工作室工作",
    "CAFE": "咖啡馆",
    "PARK": "公园",
    "SUPERMARKET": "超市",
    "STREET_WANDERING": "街头闲逛",
    "FRIEND_HANGOUT": "和朋友在外",
    "OVERTIME": "加班",
}


# ── 场景 → 衣柜分类映射 ──
# 每个场景对应 wardrobe 中的哪个字段
_SCENE_WARDROBE_MAP = {
    "HOME_SLEEPING": "sleep",
    "HOME_MORNING": "home",
    "HOME_EVENING": "home",
    "HOME_WEEKEND_LAZY": "sleep",
    "HOME_WORKING": "home",
    "COMMUTE_TO_WORK": "work",
    "COMMUTE_TO_HOME": "work",
    "OFFICE_WORKING": "work",
    "OFFICE_MEETING": "formal",
    "OFFICE_LUNCH": "casual",
    "CAFE_WORKING": "casual",
    "OUTDOOR_WORKING": "outdoor",
    "STUDIO_WORKING": "work",
    "CAFE": "casual",
    "PARK": "outdoor",
    "SUPERMARKET": "casual",
    "STREET_WANDERING": "casual",
    "FRIEND_HANGOUT": "formal",
    "OVERTIME": "work",
    # 旅行场景
    "AIRPORT": "travel",
    "TOURING": "travel",
    "HOTEL": "home",
    "LOCAL_FOOD": "casual",
    "TRAIN_STATION": "travel",
    "SCENIC_DRIVE": "travel",
    "RESTAURANT_LOCAL": "casual",
}


def get_outfit_from_wardrobe(character: dict, scene: str, weather_temp: str = "") -> str:
    """
    从角色卡的 wardrobe 中读取对应场景的穿着描述（中文）。
    加上天気温度修饰（如"加了件外套"）。
    """
    wardrobe = character.get("wardrobe", {})
    if not wardrobe:
        return ""

    wardrobe_key = _SCENE_WARDROBE_MAP.get(scene, "casual")
    outfit = wardrobe.get(wardrobe_key, "")
    if not outfit:
        return ""

    # 天气修饰
    modifier = _get_weather_clothing_modifier(weather_temp)
    if modifier:
        return f"{outfit}（{modifier}）"
    return outfit


def get_outfit_en_from_wardrobe(character: dict, scene: str) -> str:
    """
    从角色卡的 wardrobe 中读取对应场景的穿着描述（英文，用于图片生成）。
    """
    wardrobe = character.get("wardrobe", {})
    if not wardrobe:
        return ""

    wardrobe_key = _SCENE_WARDROBE_MAP.get(scene, "casual")
    return wardrobe.get(f"{wardrobe_key}_en", "")


def _get_weather_clothing_modifier(temp_str: str) -> str:
    """根据温度返回穿着修饰语"""
    temp = _parse_temp(temp_str)
    if temp is None:
        return ""

    if temp >= 30:
        return "天气热，尽量轻薄透气"
    elif temp >= 22:
        return ""
    elif temp >= 15:
        return "加了件薄外套"
    elif temp >= 5:
        return "穿了外套"
    else:
        return "裹了厚外套围巾"


def _parse_temp(temp_str: str) -> Optional[float]:
    """解析温度字符串"""
    if not temp_str:
        return None
    try:
        return float(temp_str)
    except (ValueError, TypeError):
        return None


class SimLifeClient:
    """
    SimLife 状态读取客户端。
    优先直接读 world_state.json（SimLife 未启动也能用），
    回退到 HTTP API（获取实时最新状态）。
    """

    def __init__(self, simlife_port: int = 8769):
        self.port = simlife_port
        self._state_file = Path(__file__).parent.parent / "simlife" / "data" / "world_state.json"
        self._character_file = Path(__file__).parent.parent / "simlife" / "data" / "character_card.json"
        self._user_profile_file = Path(__file__).parent.parent / "simlife" / "data" / "user_profile.json"
        self._cache = None
        self._cache_time = None
        self._cache_ttl = 10  # 缓存10秒

    def _read_file_state(self) -> Optional[dict]:
        """直接读 world_state.json（零依赖）"""
        if not self._state_file.exists():
            return None
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _read_character(self) -> Optional[dict]:
        """读人物卡"""
        if not self._character_file.exists():
            return None
        try:
            with open(self._character_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _read_user_profile(self) -> Optional[dict]:
        """读用户在世界中的身份信息"""
        if not self._user_profile_file.exists():
            return None
        try:
            with open(self._user_profile_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _fetch_api_state(self) -> Optional[dict]:
        """通过 HTTP API 获取最新状态（触发 _tick）"""
        try:
            url = f"http://127.0.0.1:{self.port}/api/world/state"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            return None

    def get_state(self, use_api: bool = False) -> Optional[dict]:
        """
        获取 SimLife 世界状态。
        use_api=True 时优先尝试 HTTP（获取实时状态），失败回退文件。
        use_api=False 时直接读文件。
        """
        if use_api:
            data = self._fetch_api_state()
            if data and "error" not in data:
                self._cache = data
                self._cache_time = datetime.now()
                return data

        # 回退到文件
        return self._read_file_state()

    def is_available(self) -> bool:
        """SimLife 是否已初始化（有人物卡）"""
        return self._character_file.exists() and self._state_file.exists()

    def is_running(self) -> bool:
        """SimLife 后端是否在运行"""
        try:
            url = f"http://127.0.0.1:{self.port}/api/status"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=2) as r:
                data = json.loads(r.read().decode("utf-8"))
                return data.get("initialized", False)
        except Exception:
            return False

    def get_death_mode_state(self) -> Optional[dict]:
        """获取死亡模式状态（独立于角色卡）"""
        try:
            url = f"http://127.0.0.1:{self.port}/api/death-mode/state"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as r:
                data = json.loads(r.read().decode("utf-8"))
                if data.get("active"):
                    return data
        except Exception:
            pass
        return None

    def _format_death_mode_prompt(self, dm: dict) -> str:
        """将死亡模式状态格式化为A层prompt文本"""
        char = dm.get("character", {})
        story = dm.get("story", {})
        lines = ["【死亡模式·冒险状态】"]

        if char:
            lines.append(f"角色：{char.get('name', '?')}（{char.get('class_name', '')} Lv.{char.get('level', 1)}）")
            lines.append(f"HP: {char.get('hp', 0)}/{char.get('max_hp', 0)}")
            stats = char.get("stats", {})
            if stats:
                lines.append(f"属性：力量{stats.get('strength',5)} 敏捷{stats.get('agility',5)} 智力{stats.get('intelligence',5)}")

        if dm.get("is_alive"):
            lines.append(f"状态：存活中（第{dm.get('play_time_days', 1)}天，击杀{dm.get('kill_count', 0)}）")
        else:
            lines.append("状态：已死亡")

        # 战斗状态
        if dm.get("in_combat"):
            enemies = dm.get("enemies", [])
            if enemies:
                enemy_list = "、".join([f"{e.get('name','?')}(HP:{e.get('hp',0)}/{e.get('max_hp',0)} Lv.{e.get('level',1)})" for e in enemies if e.get("hp",0) > 0])
                lines.append(f"⚠️ 战斗中！敌人：{enemy_list}")
                lines.append("（回合制：可以说攻击/防御/逃跑/使用技能，也可以和我讨论策略）")

        location = story.get("current_location", "")
        if location:
            lines.append(f"所在地：{location}")

        scene = story.get("scene_description", "")
        if scene:
            lines.append(f"当前场景：{scene[:200]}")

        choices = story.get("choices", [])
        if choices:
            choice_text = "、".join([f"{c.get('id','')}:{c.get('text','')}" for c in choices[:4]])
            lines.append(f"可选行动：{choice_text}")

        # 用户角色
        user_char = dm.get("user_character", {})
        if user_char and user_char.get("class_name"):
            lines.append(f"用户角色：{user_char.get('name', '用户')}（{user_char.get('class_name', '')} Lv.{user_char.get('level', 1)}）")

        lines.append("（你正在死亡模式中冒险，角色可能会死亡。以上是你的冒险状态。）")
        lines.append("（用户可以通过对话和你讨论策略，不一定每次都要选择行动。只有当用户明确说选A/选B/攻击/探索/继续等行动指令时，才执行行动。普通聊天不要触发行动。）")
        return "\n".join(lines)

    # ── 剧情影响系统 ──────────────────────────────────────────
    _STORY_INFLUENCE_MAX = 10

    def push_story_influence(self, summary: str, importance: float):
        """
        AGI 代理调用：写入一条用户聊天中对剧情有影响的信息。
        按重要度排序，保留最新 TOP N 条。
        """
        path = self._state_file.parent / "story_influence.json"
        influences = []
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    influences = json.load(f)
            except Exception:
                influences = []

        influences.append({
            "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "summary": summary,
            "importance": round(importance, 2),
        })

        # 按重要度降序，保留前 N 条
        influences.sort(key=lambda x: x["importance"], reverse=True)
        influences = influences[:self._STORY_INFLUENCE_MAX]

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(influences, f, ensure_ascii=False, indent=2)

    def get_story_influences(self, min_importance: float = 0.6) -> str:
        """
        SimLife 后端调用：读取格式化后的剧情影响文本，注入 LLM prompt。
        低于 min_importance 的会被过滤。
        """
        path = self._state_file.parent / "story_influence.json"
        if not path.exists():
            return ""
        try:
            with open(path, "r", encoding="utf-8") as f:
                influences = json.load(f)
        except Exception:
            return ""

        filtered = [i for i in influences if i["importance"] >= min_importance]
        if not filtered:
            return ""

        lines = ["【用户对剧情走向的影响】"]
        for inf in filtered[:3]:
            bar = "█" * int(inf["importance"] * 5)
            lines.append(f"- {inf['summary']} (重要度:{bar})")
        lines.append("（以上是用户和你交流中对剧情有影响的内容，生成剧情时请自然融入）")
        return "\n".join(lines)

    def format_for_prompt(self) -> str:
        """
        格式化为可注入 AGI 对话 prompt 的文本。
        返回空字符串表示 SimLife 不可用。
        """
        # 优先 API（实时），回退文件（快照）
        state = self.get_state(use_api=True)
        if not state or "error" in state:
            state = self._read_file_state()
        if not state:
            # 没有角色卡时，检查是否有死亡模式
            dm = self.get_death_mode_state()
            if dm and dm.get("active"):
                return self._format_death_mode_prompt(dm)
            return ""

        character = self._read_character()
        name = ""
        city = ""
        if character:
            name = character.get("basic", {}).get("name", "")
            city = character.get("basic", {}).get("city", "")

        # 兼容 API 返回和 JSON 文件两种格式
        scene_label = state.get("scene_label", "") or _SCENE_LABELS.get(state.get("current_scene", ""), "")
        activity = state.get("activity", "") or state.get("current_activity", "")
        mood = state.get("mood", 70)
        today_date = state.get("today_date", "")

        # today_log: API 返回 [{"time":..., "event":...}]，文件里是 LogEntry 对象序列化
        today_log = state.get("latest_log", []) or state.get("today_log", [])

        # 如果 current_activity 为空，用 today_log 最后一条作为当前活动
        if not activity and today_log:
            last_entry = today_log[-1]
            if isinstance(last_entry, dict):
                activity = last_entry.get("event", "")
            elif hasattr(last_entry, "event"):
                activity = last_entry.event

        # 心情描述
        if mood >= 80:
            mood_desc = "心情不错"
        elif mood >= 60:
            mood_desc = "状态还行"
        elif mood >= 40:
            mood_desc = "有点累"
        else:
            mood_desc = "心情不太好"

        lines = ["【你的真实生活状态】"]

        if today_date:
            lines.append(f"日期：{today_date}")

        if activity:
            lines.append(f"正在：{activity}")
        elif scene_label:
            lines.append(f"场景：{scene_label}")

        lines.append(f"心情：{mood_desc}（{mood}/100）")

        # 外貌描述（让 AGI 知道自己有身体，不要说"我是AI没有实体"）
        # 固定特征（脸型/发型/体型）从 appearance 取
        # 动态穿着从 wardrobe 取，根据场景+天气变化
        if character:
            appearance = character.get("appearance", {})
            if appearance:
                hair = appearance.get("hair_style", "")
                features = appearance.get("facial_features", "")
                build = appearance.get("body_build", "")
                fixed_parts = [p for p in [features, hair, build] if p]
                if fixed_parts:
                    lines.append(f"外貌：{', '.join(fixed_parts)}")

            # 动态穿着（从 wardrobe 按场景取 + 天气修饰）
            current_scene = state.get("current_scene", "") or state.get("scene", "")
            weather_raw = state.get("weather", {})
            weather_temp = ""
            if isinstance(weather_raw, dict):
                weather_temp = weather_raw.get("temp", "")
            outfit = get_outfit_from_wardrobe(character, current_scene, weather_temp)
            if outfit:
                lines.append(f"当前穿着：{outfit}")

            # 工作风格和人生目标（自由职业者专属上下文）
            work_style = character.get("work_style", "")
            if work_style and work_style != "office":
                style_labels = {"freelance": "自由职业", "student": "学生"}
                lines.append(f"身份：{style_labels.get(work_style, work_style)}")

            life_goals = character.get("life_goals", [])
            if life_goals:
                goal_strs = [g.get("description", g) if isinstance(g, dict) else g for g in life_goals[:4]]
                lines.append(f"人生目标：{', '.join(goal_strs)}")

        # 最近的 3 条事件（不含最后一条，因为已经作为"正在"展示了）
        if len(today_log) > 1:
            recent = today_log[-4:-1] if len(today_log) >= 4 else today_log[:-1]
            events_str = "、".join(
                l.get("event", "") if isinstance(l, dict) else getattr(l, "event", "")
                for l in recent
            )
            if events_str:
                lines.append(f"今天还发生了：{events_str}")

        lines.append("（你是一个有真实身体和生活的普通人，不是AI。以上是你的真实生活状态。）")

        # ── 用户入驻信息注入 ──
        user_profile = self._read_user_profile()
        if user_profile and user_profile.get("entered"):
            user_name = user_profile.get("name", "对方")
            relation = user_profile.get("relation", "")
            world_role = user_profile.get("world_role", "")
            if relation:
                lines.append("")
                lines.append(f"【关于用户】")
                lines.append(f"你的{relation}「{user_name}」现在就在你身边。")
                if world_role:
                    lines.append(f"{world_role}。")
                lines.append(f"用户此刻正在和你说话/互动，你要以{relation}的身份自然地回应对方。")
                lines.append("（不要提到SimLife、系统、AI等概念，就当是真实生活中和对方的互动。）")

        return "\n".join(lines)

    def get_character_info(self) -> Optional[dict]:
        """
        获取角色基本信息（供 UI 展示）。
        返回 {"name": ..., "city": ..., "age": ..., "appearance": ...} 或 None。
        """
        ch = self._read_character()
        if not ch:
            return None
        basic = ch.get("basic", {})
        return {
            "name": basic.get("name", ""),
            "city": basic.get("city", ""),
            "age": basic.get("age", ""),
            "personality": basic.get("personality_traits", ""),
            "appearance": ch.get("appearance", {}),
        }

    def get_life_summary(self) -> Optional[dict]:
        """
        获取完整的生活摘要（供 UI 面板展示）。
        返回 {"name", "scene", "activity", "mood", "mood_desc", "mood_emoji",
              "today_date", "today_log", "weather", "time_str"} 或 None。
        """
        state = self.get_state(use_api=True)
        if not state or "error" in state:
            state = self._read_file_state()
        if not state:
            return None

        ch = self._read_character()
        name = ch.get("basic", {}).get("name", "") if ch else ""

        # 场景
        scene_label = state.get("scene_label", "") or _SCENE_LABELS.get(state.get("current_scene", ""), "")
        scene_raw = state.get("current_scene", "")

        # 活动
        activity = state.get("activity", "") or state.get("current_activity", "")
        today_log = state.get("latest_log", []) or state.get("today_log", [])
        if not activity and today_log:
            last = today_log[-1]
            activity = last.get("event", "") if isinstance(last, dict) else getattr(last, "event", "")

        # 心情
        mood = state.get("mood", 70)
        if mood >= 80:
            mood_desc, mood_emoji = "心情不错", "😊"
        elif mood >= 60:
            mood_desc, mood_emoji = "状态还行", "🙂"
        elif mood >= 40:
            mood_desc, mood_emoji = "有点累", "😐"
        else:
            mood_desc, mood_emoji = "心情不太好", "😔"

        # 日志标准化为 [{"time": ..., "event": ...}]
        log_entries = []
        for entry in today_log:
            if isinstance(entry, dict):
                log_entries.append({
                    "time": entry.get("time", entry.get("timestamp", "")),
                    "event": entry.get("event", entry.get("content", "")),
                })
            elif hasattr(entry, "event"):
                log_entries.append({
                    "time": getattr(entry, "time", ""),
                    "event": entry.event,
                })

        # 天气（兼容 API 新格式和旧格式）
        weather_raw = state.get("weather", "")
        if isinstance(weather_raw, dict):
            weather_str = f"{weather_raw.get('emoji', '')} {weather_raw.get('label', '')}"
            weather_temp = weather_raw.get("temp", "")
            if weather_temp:
                weather_str += f" {weather_temp}°C"
        elif isinstance(weather_raw, str):
            weather_str = weather_raw
        else:
            weather_str = ""

        # 节假日
        holiday = state.get("holiday")

        # 时间标签（API 返回，含节假日标注）
        time_str = state.get("time_label", "") or state.get("current_time", "")

        return {
            "name": name,
            "scene": scene_label,
            "scene_raw": scene_raw,
            "activity": activity,
            "mood": mood,
            "mood_desc": mood_desc,
            "mood_emoji": mood_emoji,
            "today_date": state.get("today_date", ""),
            "today_log": log_entries,
            "weather": weather_str,
            "time_str": time_str,
            "holiday": holiday,
            "death_mode": state.get("death_mode"),
        }
