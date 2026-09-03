"""
死亡模式状态管理
独立于原有 SimLife 系统，不影响现代/异世界模式
"""
import json
import os
import time
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any

# 延迟导入，避免循环依赖
def _life_skill_init() -> Dict:
    from simlife.backend import life_skills
    return life_skills.init_life_state()


DATA_DIR = Path(__file__).parent.parent / "data"
STATE_FILE = DATA_DIR / "death_mode_state.json"
HALL_FILE = DATA_DIR / "death_hall.json"

# 存档读写线程锁：8769 服务的同步 handler 运行在 uvicorn 线程池，
# 多个请求可并行调用 save_state，无锁并发 open("w") 会导致文件被交错拼接损坏。
_STATE_LOCK = threading.Lock()

# ── 自动备份配置（仿 engine/db_guard.py 思路）──────────
MAX_STATE_BACKUPS = 5           # 最多保留几份存档备份（轮转删除旧份）
BACKUP_INTERVAL_SECONDS = 600   # 距上次备份超过该秒数才创建新备份（限频，避免每次写都备份）

_last_backup_time = 0.0         # 受 _STATE_LOCK 保护


# ── 职业模板（按世界类型分组）──────────────────────────

# 属性统一为：strength(力量/体术) agility(敏捷/身法) intelligence(智力/悟性) vitality(体质/根骨) luck(运气/机缘)

CLASS_TEMPLATES = {
    # ── 奇幻魔法 ──
    "fantasy": {
        "warrior": {"name": "战士", "icon": "⚔️", "description": "近战物理输出，高生命值和防御力", "base_stats": {"strength": 15, "agility": 8, "intelligence": 5, "vitality": 15, "luck": 5}, "base_hp": 150, "base_mp": 20, "starting_skills": ["重击", "格挡"]},
        "mage": {"name": "法师", "icon": "🔮", "description": "远程魔法输出，高魔力但生命值低", "base_stats": {"strength": 5, "agility": 8, "intelligence": 18, "vitality": 6, "luck": 8}, "base_hp": 70, "base_mp": 100, "starting_skills": ["火球术", "魔法护盾"]},
        "rogue": {"name": "盗贼", "icon": "🗡️", "description": "高敏捷，擅长暴击和闪避", "base_stats": {"strength": 10, "agility": 16, "intelligence": 8, "vitality": 8, "luck": 10}, "base_hp": 100, "base_mp": 40, "starting_skills": ["偷袭", "闪避"]},
        "archer": {"name": "弓箭手", "icon": "🏹", "description": "远程物理输出，平衡型", "base_stats": {"strength": 12, "agility": 14, "intelligence": 8, "vitality": 10, "luck": 7}, "base_hp": 110, "base_mp": 35, "starting_skills": ["精准射击", "快速移动"]},
        "cleric": {"name": "牧师", "icon": "✨", "description": "治疗和辅助，生存能力强", "base_stats": {"strength": 7, "agility": 7, "intelligence": 14, "vitality": 12, "luck": 8}, "base_hp": 120, "base_mp": 80, "starting_skills": ["治愈术", "祝福"]},
    },
    # ── 仙侠修真 ──
    "xianxia": {
        "sword_cultivator": {"name": "剑修", "icon": "🗡️", "description": "以剑入道，攻击凌厉，剑意破万法", "base_stats": {"strength": 14, "agility": 14, "intelligence": 10, "vitality": 10, "luck": 7}, "base_hp": 120, "base_mp": 60, "starting_skills": ["御剑术", "剑气斩"]},
        "body_cultivator": {"name": "体修", "icon": "💪", "description": "炼体成圣，肉身不灭，近战无敌", "base_stats": {"strength": 18, "agility": 6, "intelligence": 5, "vitality": 16, "luck": 5}, "base_hp": 180, "base_mp": 20, "starting_skills": ["金刚拳", "铜皮铁骨"]},
        "pill_cultivator": {"name": "丹修", "icon": "⚗️", "description": "炼丹入道，丹药辅助，续航极强", "base_stats": {"strength": 6, "agility": 8, "intelligence": 16, "vitality": 10, "luck": 12}, "base_hp": 90, "base_mp": 90, "starting_skills": ["回春丹", "毒丹术"]},
        "talisman_cultivator": {"name": "符修", "icon": "📜", "description": "符箓之道，攻守兼备，变化多端", "base_stats": {"strength": 7, "agility": 10, "intelligence": 15, "vitality": 8, "luck": 12}, "base_hp": 85, "base_mp": 85, "starting_skills": ["雷符", "护身符"]},
        "soul_cultivator": {"name": "魂修", "icon": "👻", "description": "修炼神魂，精神攻击，诡异莫测", "base_stats": {"strength": 5, "agility": 10, "intelligence": 18, "vitality": 6, "luck": 10}, "base_hp": 75, "base_mp": 110, "starting_skills": ["神识刺", "摄魂术"]},
    },
    # ── 武侠江湖 ──
    "wuxia": {
        "swordsman": {"name": "剑客", "icon": "🗡️", "description": "剑法精湛，攻击凌厉，以快制胜", "base_stats": {"strength": 15, "agility": 13, "intelligence": 6, "vitality": 10, "luck": 8}, "base_hp": 120, "base_mp": 40, "starting_skills": ["剑法·劈刺", "剑气"]},
        "boxer": {"name": "拳师", "icon": "👊", "description": "拳掌功夫，内外兼修，近战王者", "base_stats": {"strength": 16, "agility": 10, "intelligence": 5, "vitality": 12, "luck": 5}, "base_hp": 150, "base_mp": 30, "starting_skills": ["铁拳", "擒拿手"]},
        "assassin": {"name": "刺客", "icon": "🗡️", "description": "暗器百发百中，轻功来去如风", "base_stats": {"strength": 8, "agility": 18, "intelligence": 8, "vitality": 8, "luck": 10}, "base_hp": 90, "base_mp": 50, "starting_skills": ["飞镖", "轻功"]},
        "doctor": {"name": "医者", "icon": "💊", "description": "悬壶济世，精通医毒，救人亦能伤敌", "base_stats": {"strength": 5, "agility": 8, "intelligence": 14, "vitality": 10, "luck": 12}, "base_hp": 100, "base_mp": 70, "starting_skills": ["金针术", "药粉"]},
        "scholar": {"name": "文人", "icon": "🎵", "description": "琴棋书画皆可杀人，内力深厚", "base_stats": {"strength": 6, "agility": 10, "intelligence": 16, "vitality": 8, "luck": 10}, "base_hp": 85, "base_mp": 80, "starting_skills": ["琴音攻击", "内力护体"]},
    },
    # ── 末世废土 ──
    "post_apocalyptic": {
        "esper": {"name": "异能者", "icon": "⚡", "description": "觉醒超能力，远程能量攻击", "base_stats": {"strength": 8, "agility": 10, "intelligence": 16, "vitality": 8, "luck": 8}, "base_hp": 90, "base_mp": 90, "starting_skills": ["念动力", "能量护盾"]},
        "scavenger": {"name": "拾荒者", "icon": "🎒", "description": "废土生存专家，资源利用大师", "base_stats": {"strength": 12, "agility": 14, "intelligence": 8, "vitality": 12, "luck": 10}, "base_hp": 120, "base_mp": 30, "starting_skills": ["废土搜刮", "陷阱制作"]},
        "mechanic": {"name": "机械师", "icon": "🔧", "description": "改造机械，科技战力", "base_stats": {"strength": 10, "agility": 8, "intelligence": 15, "vitality": 10, "luck": 7}, "base_hp": 100, "base_mp": 60, "starting_skills": ["无人机召唤", "电磁脉冲"]},
        "mutant": {"name": "变异者", "icon": "🧬", "description": "基因变异，肉体强化", "base_stats": {"strength": 16, "agility": 10, "intelligence": 6, "vitality": 14, "luck": 5}, "base_hp": 160, "base_mp": 25, "starting_skills": ["利爪撕裂", "再生"]},
        "survivor": {"name": "生存者", "icon": "🛡️", "description": "全能型废土生存者，均衡发展", "base_stats": {"strength": 10, "agility": 10, "intelligence": 10, "vitality": 12, "luck": 10}, "base_hp": 115, "base_mp": 45, "starting_skills": ["急救术", "战术撤退"]},
    },
    # ── 现世超武 ──
    "modern_power": {
        "martial_artist": {"name": "武道者", "icon": "👊", "description": "古武术传人，内力深厚", "base_stats": {"strength": 15, "agility": 12, "intelligence": 8, "vitality": 13, "luck": 6}, "base_hp": 140, "base_mp": 50, "starting_skills": ["崩拳", "气功罩"]},
        "awakened": {"name": "觉醒者", "icon": "🌀", "description": "异能觉醒，能力多变", "base_stats": {"strength": 8, "agility": 12, "intelligence": 14, "vitality": 8, "luck": 10}, "base_hp": 95, "base_mp": 85, "starting_skills": ["念动力", "感知强化"]},
        "ancient_inheritor": {"name": "古武传人", "icon": "🗡️", "description": "传承古老武学，招式精妙", "base_stats": {"strength": 13, "agility": 15, "intelligence": 8, "vitality": 10, "luck": 8}, "base_hp": 110, "base_mp": 45, "starting_skills": ["连环掌", "轻功"]},
        "dark_ability": {"name": "暗能力者", "icon": "🌑", "description": "隐秘能力，暗影操控", "base_stats": {"strength": 10, "agility": 14, "intelligence": 12, "vitality": 7, "luck": 10}, "base_hp": 90, "base_mp": 70, "starting_skills": ["暗影潜行", "影刃"]},
        "enhancer": {"name": "强化者", "icon": "💎", "description": "身体全方位强化，无短板", "base_stats": {"strength": 12, "agility": 12, "intelligence": 8, "vitality": 14, "luck": 6}, "base_hp": 130, "base_mp": 40, "starting_skills": ["力量强化", "速度强化"]},
    },
    # ── 科幻未来 ──
    "scifi": {
        "mecha_pilot": {"name": "机甲师", "icon": "🤖", "description": "驾驶战斗机甲，火力强大", "base_stats": {"strength": 14, "agility": 8, "intelligence": 12, "vitality": 14, "luck": 6}, "base_hp": 160, "base_mp": 40, "starting_skills": ["导弹齐射", "能量护盾"]},
        "nano_soldier": {"name": "纳米战士", "icon": "🔬", "description": "纳米改造身体，自适应战斗", "base_stats": {"strength": 13, "agility": 13, "intelligence": 10, "vitality": 12, "luck": 7}, "base_hp": 130, "base_mp": 55, "starting_skills": ["纳米修复", "形态变化"]},
        "hacker": {"name": "黑客", "icon": "💻", "description": "信息战专家，远程干扰控制", "base_stats": {"strength": 5, "agility": 10, "intelligence": 18, "vitality": 7, "luck": 10}, "base_hp": 80, "base_mp": 100, "starting_skills": ["系统入侵", "电磁干扰"]},
        "gene_modified": {"name": "基因改造者", "icon": "🧬", "description": "基因编辑强化，超越人类极限", "base_stats": {"strength": 15, "agility": 12, "intelligence": 8, "vitality": 13, "luck": 6}, "base_hp": 145, "base_mp": 35, "starting_skills": ["基因爆发", "快速再生"]},
        "energy_manipulator": {"name": "能量操控者", "icon": "⚡", "description": "操控纯能量，攻防一体", "base_stats": {"strength": 7, "agility": 10, "intelligence": 16, "vitality": 8, "luck": 9}, "base_hp": 85, "base_mp": 95, "starting_skills": ["能量弹", "能量壁"]},
    },
}


def _get_world_type_from_setting(world_setting: Dict) -> str:
    """从世界设定中推断世界类型"""
    if not world_setting:
        return "fantasy"
    wtype = world_setting.get("world_type", "fantasy")
    # 直接匹配
    if wtype in CLASS_TEMPLATES:
        return wtype
    # 模糊匹配
    if "xianxia" in wtype or "仙" in str(world_setting.get("world_name", "")):
        return "xianxia"
    if "wuxia" in wtype or "武" in str(world_setting.get("world_name", "")) or "江湖" in str(world_setting.get("world_name", "")):
        return "wuxia"
    if "apocal" in wtype or "末" in str(world_setting.get("world_name", "")):
        return "post_apocalyptic"
    if "modern" in wtype or "超" in str(world_setting.get("world_name", "")):
        return "modern_power"
    if "sci" in wtype:
        return "scifi"
    return "fantasy"


def get_available_classes(world_type: str = None, world_setting: Dict = None) -> List[Dict]:
    """获取可选职业列表（根据世界类型）"""
    if world_type is None and world_setting:
        world_type = _get_world_type_from_setting(world_setting)
    if world_type is None:
        world_type = "fantasy"

    classes = CLASS_TEMPLATES.get(world_type, CLASS_TEMPLATES["fantasy"])
    return [
        {
            "id": k,
            "name": v["name"],
            "icon": v["icon"],
            "description": v["description"],
            "base_stats": v["base_stats"],
            "base_hp": v["base_hp"],
            "base_mp": v["base_mp"],
            "starting_skills": v["starting_skills"],
        }
        for k, v in classes.items()
    ]


def get_class_template(world_type: str, class_id: str) -> Optional[Dict]:
    """获取特定职业模板"""
    classes = CLASS_TEMPLATES.get(world_type, CLASS_TEMPLATES["fantasy"])
    return classes.get(class_id)


# ── 状态结构 ──────────────────────────────────────────

def _convert_skill_names_to_ids(skill_names: list, world_type: str, class_id: str) -> list:
    """将技能名称列表转换为技能ID列表（支持精确匹配和模糊匹配）"""
    from simlife.backend.skill_system import SkillSystem
    ids = []
    for name in skill_names:
        # 先从职业技能中精确匹配
        class_skills = SkillSystem.get_class_skills(world_type, class_id)
        found = False
        for s in class_skills:
            if s.name == name:
                ids.append(s.id)
                found = True
                break
        if found:
            continue
        # 模糊匹配：职业技能名包含输入名称
        for s in class_skills:
            if name in s.name or s.name in name:
                ids.append(s.id)
                found = True
                break
        if found:
            continue
        # 通用技能中匹配
        skill = SkillSystem.get_skill_by_name(name)
        if skill:
            ids.append(skill.id)
            continue
        # 回退到通用Lv.1技能
        common = SkillSystem.get_skill_by_name("防御")
        if common:
            ids.append(common.id)
    return ids


def create_initial_state(
    character_name: str,
    class_id: str,
    world_setting: Dict,
    growth_mode: str = "normal",
    custom_stat_points: Optional[Dict] = None,
    user_class_id: str = "",
    user_name: str = "",
) -> Dict:
    """创建死亡模式初始状态"""
    world_type = _get_world_type_from_setting(world_setting)
    cls = get_class_template(world_type, class_id)
    if not cls:
        # 回退到奇幻战士
        cls = CLASS_TEMPLATES["fantasy"]["warrior"]

    stats = dict(cls["base_stats"])
    # 自由分配点数（初始5点）
    remaining_points = 5
    if custom_stat_points:
        for k, v in custom_stat_points.items():
            if k in stats and v > 0 and remaining_points >= v:
                stats[k] += v
                remaining_points -= v

    # 初始化用户角色
    user_cls = get_class_template(world_type, user_class_id) if user_class_id else None
    if user_cls:
        user_character = {
            "name": user_name or "用户",
            "class_id": user_class_id,
            "class_name": user_cls["name"],
            "class_icon": user_cls.get("icon", "👤"),
            "level": 1,
            "hp": user_cls["base_hp"],
            "max_hp": user_cls["base_hp"],
            "mp": user_cls["base_mp"],
            "max_mp": user_cls["base_mp"],
            "stats": dict(user_cls["base_stats"]),
            "skills": _convert_skill_names_to_ids(user_cls["starting_skills"], world_type, user_class_id),
            "equipment": [],
            "experience": 0,
            "exp_to_next": 100,
            "gold": 0,
            "awakening_skills": [],
        }
    else:
        user_character = {
            "name": user_name or "用户",
            "class_id": "",
            "class_name": "",
            "class_icon": "👤",
            "level": 1, "hp": 0, "max_hp": 0, "mp": 0, "max_mp": 0,
            "stats": {"strength": 5, "agility": 5, "intelligence": 5, "vitality": 5, "luck": 5},
            "skills": [], "equipment": [], "experience": 0, "exp_to_next": 100, "gold": 0,
            "awakening_skills": [],
        }

    return {
        "mode": "death_mode",
        "character": {
            "name": character_name,
            "class_id": class_id,
            "class_name": cls["name"],
            "class_icon": cls["icon"],
            "level": 1,
            "hp": cls["base_hp"],
            "max_hp": cls["base_hp"],
            "mp": cls["base_mp"],
            "max_mp": cls["base_mp"],
            "stats": stats,
            "skills": _convert_skill_names_to_ids(cls["starting_skills"], world_type, class_id),
            "awakening_skills": [],
            "equipment": [],
            "inventory": [],
            "experience": 0,
            "exp_to_next": 100,
            "gold": 50,
        },
        "world_setting": world_setting,
        "world_type": world_type,
        "growth_mode": growth_mode,  # "fast" (爽文) / "normal" (平衡) / "slow" (慢热)
        "story": {
            "current_chapter": 1,
            "current_scene_id": None,
            "scene_description": "",
            "choices": [],
            "history": [],
            "pending_action": None,
            "unresolved_hooks": [],  # 未解决的剧情钩子（LLM 必须承接）
        },
        "spotted_enemies": [],  # 叙事中提到的敌人，战斗时优先使用
        "enemy": None,  # 当前遭遇的敌人信息（兼容旧版）
        "enemies": [],  # 当前遭遇的敌人列表（支持一群怪）
        "in_combat": False,  # 是否在战斗中
        "environment": {},  # 死亡模式独立环境状态(昼夜/天气/内外室)，由 DeathModeEnvironment 填充
        "is_alive": True,
        "death_cause": None,
        "play_time_days": 1,
        "start_time": datetime.now().isoformat(),  # 游戏开始时间（天数按实际时间计算）
        "kill_count": 0,
        "created_at": datetime.now().isoformat(),
        "defeated_enemies": [],  # 已击败的敌人名列表（防止LLM反复复活）
        # ── 任务系统 ──
        "quests": {
            "active": [],            # 已接进行中的任务实例
            "available_offers": [],  # LLM 动态生成的任务委托（未接受）
            "turned_in_ids": [],     # 已交付的任务 id
            "failed_ids": [],        # 失败的任务 id
            "series_progress": {},   # series_id -> 当前已完成到第几个
            "dynamic_series": {},   # series_id -> {title, description}（LLM 生成的系列信息）
        },
        # ── 世界推进 ──
        "world_news": [],              # 冒险者酒馆新闻列表
        "world_progress_triggered": [],  # 已触发的世界事件 id
        # ── 共享背包 ──
        "shared_inventory": [],  # 两角色共享的背包（装备穿戴后从此取出）
        # ── 生活技能系统 ──
        "life_state": _life_skill_init(),  # 烹饪/锻造/钓鱼 生活技能状态
        # ── 用户角色（与AI角色并列） ──
        "user_character": user_character,
        # ── 地图与NPC系统 ──
        "world_map": {},      # WorldMap.to_dict() 序列化
        "npc_system": {},     # NPCSystem.to_dict() 序列化
        "npc_death_records": [],  # NPC死亡记录（冗余存储，方便快速查询）
        # ── 行动日志 ──
        "action_log": [],     # 所有行动记录，网页端用
    }


# ── 持久化 ────────────────────────────────────────────

def save_state(state: Dict):
    """保存死亡模式状态（线程安全 + 原子写：先写临时文件再替换，避免写一半崩溃/并发拼接损坏存档）"""
    with _STATE_LOCK:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_FILE)
        # 限频自动备份一份快照（可回滚的保险）
        _maybe_backup_state(state)


def load_state() -> Optional[Dict]:
    """加载死亡模式状态；若存档损坏则尝试从最近备份自动恢复"""
    with _STATE_LOCK:
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if data and data.get("is_alive"):
                    return data
            except Exception:
                pass
            # 存档损坏（或被判定无游戏）：尝试从最近备份自愈
            recovered = _recover_state_from_backup()
            if recovered:
                return recovered
    return None


def _backup_files() -> List[Path]:
    """按时间倒序返回所有存档备份文件"""
    return sorted(
        DATA_DIR.glob("death_mode_state.bak.*.json"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )


def _maybe_backup_state(state: Dict):
    """限频创建存档备份（须在 _STATE_LOCK 内调用），防止频繁写导致大量小文件"""
    global _last_backup_time
    now = time.time()
    if now - _last_backup_time < BACKUP_INTERVAL_SECONDS:
        return
    _last_backup_time = now
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        bak = DATA_DIR / f"death_mode_state.bak.{timestamp}.json"
        with open(bak, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        _rotate_state_backups()
    except Exception:
        pass


def _rotate_state_backups(max_backups: int = MAX_STATE_BACKUPS):
    """轮转存档备份：保留最近 N 份，删除旧的"""
    for p in _backup_files()[max_backups:]:
        try:
            p.unlink()
        except OSError:
            pass


def _recover_state_from_backup() -> Optional[Dict]:
    """从最近的合法备份恢复存档（损坏自愈），成功则写回正式存档并返回状态"""
    for bak in _backup_files():
        try:
            with open(bak, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data and data.get("is_alive"):
                tmp = STATE_FILE.with_suffix(".json.tmp")
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, STATE_FILE)
                print(f"[death_mode] ⚠ 存档损坏，已自动从备份恢复: {bak.name}")
                return data
        except Exception:
            continue
    return None


def clear_state():
    """清除死亡模式状态（角色死亡后）"""
    with _STATE_LOCK:
        if STATE_FILE.exists():
            try:
                STATE_FILE.rename(STATE_FILE.with_suffix(".json.dead"))
            except Exception:
                pass


def save_to_hall(state: Dict, death_cause: str, death_description: str):
    """将死亡角色保存到名人堂"""
    with _STATE_LOCK:
        hall = []
        if HALL_FILE.exists():
            try:
                with open(HALL_FILE, "r", encoding="utf-8") as f:
                    hall = json.load(f)
            except Exception:
                pass

        char = state.get("character", {})
        hall.append({
            "name": char.get("name", "无名"),
            "class_name": char.get("class_name", ""),
            "class_icon": char.get("class_icon", ""),
            "level": char.get("level", 1),
            "kill_count": state.get("kill_count", 0),
            "play_time_days": state.get("play_time_days", 0),
            "death_cause": death_cause,
            "death_description": death_description[:500],
            "died_at": datetime.now().isoformat(),
        })

        # 只保留最近 50 条
        hall = hall[-50:]
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = HALL_FILE.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(hall, f, ensure_ascii=False, indent=2)
        os.replace(tmp, HALL_FILE)


def load_hall() -> List[Dict]:
    """加载死亡名人堂"""
    if HALL_FILE.exists():
        try:
            with open(HALL_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []
