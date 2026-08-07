"""
Party Agent — 队友系统

核心设计（参考 Party_Agent_设计文档.txt）：
- 队友是系统角色和用户角色之外的额外队伍成员
- 只负责"队友该做什么决策、说什么话"，不负责判定世界真相
- 决策用规则引擎（不调LLM），台词只在关键节点触发（省token）
- 观测视图过滤：队友只能看到已发现的信息，隐藏字段不进入上下文

数据流：
  Party Agent 输出结构化决策 → CombatSystem 执行数值计算 → 返回结果

成本控制：
- 决策：规则引擎化（人格倾向加权 + 局势输入 → 输出动作），不调LLM
- 台词：只在关键节点触发（战斗开始/击杀/濒死/Boss战/踩陷阱/胜利）
"""
import random
from typing import Dict, List, Optional


# ============================================================
# 队友数据结构
# ============================================================

class PartyMember:
    """一个队友"""

    def __init__(self, member_id: str, name: str, class_id: str, class_name: str,
                 class_icon: str = "🧑", level: int = 1,
                 hp: int = 100, max_hp: int = 100,
                 mp: int = 30, max_mp: int = 30,
                 stats: Dict = None, skills: List[str] = None,
                 relation: int = 50):
        self.member_id = member_id
        self.name = name
        self.class_id = class_id
        self.class_name = class_name
        self.class_icon = class_icon
        self.level = level
        self.hp = hp
        self.max_hp = max_hp
        self.mp = mp
        self.max_mp = max_mp
        self.stats = stats or {"strength": 5, "agility": 5, "intelligence": 5, "vitality": 5, "luck": 5}
        self.skills = skills or []
        self.relation = relation  # 与用户好感度 0-100
        self.is_alive = True
        self.passive_effects = []

    def to_dict(self) -> Dict:
        return {
            "member_id": self.member_id,
            "name": self.name,
            "class_id": self.class_id,
            "class_name": self.class_name,
            "class_icon": self.class_icon,
            "level": self.level,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "mp": self.mp,
            "max_mp": self.max_mp,
            "stats": self.stats,
            "skills": self.skills,
            "relation": self.relation,
            "is_alive": self.is_alive,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "PartyMember":
        m = cls(
            member_id=d.get("member_id", ""),
            name=d.get("name", "队友"),
            class_id=d.get("class_id", ""),
            class_name=d.get("class_name", ""),
            class_icon=d.get("class_icon", "🧑"),
            level=d.get("level", 1),
            hp=d.get("hp", 100),
            max_hp=d.get("max_hp", 100),
            mp=d.get("mp", 30),
            max_mp=d.get("max_mp", 30),
            stats=d.get("stats", {}),
            skills=d.get("skills", []),
            relation=d.get("relation", 50),
        )
        m.is_alive = d.get("is_alive", True)
        return m

    def to_combat_entity(self) -> Dict:
        """转换为战斗系统可用的实体格式（与character/user_character格式一致）"""
        return {
            "name": self.name,
            "class_name": self.class_name,
            "class_id": self.class_id,
            "level": self.level,
            "hp": self.hp,
            "max_hp": self.max_hp,
            "mp": self.mp,
            "max_mp": self.max_mp,
            "stats": self.stats,
            "skills": self.skills,
            "passive_effects": self.passive_effects,
            "is_party_member": True,
            "member_id": self.member_id,
        }


# ============================================================
# Party Agent — 决策引擎 + 台词生成
# ============================================================

class PartyAgent:
    """队友决策引擎和台词生成"""

    MAX_PARTY_SIZE = 3  # 最多3个额外队友

    # ── 决策规则引擎（不调LLM）──

    @staticmethod
    def decide_action(member: PartyMember, observation: Dict,
                      enemies: List[Dict], allies: List[Dict],
                      world_type: str = "fantasy") -> Dict:
        """规则引擎决策：输入观测视图+状态，输出结构化动作

        返回格式：
        {
            "action": "attack|defend|skill",
            "target_index": 0,          # 攻击哪个敌人
            "skill_id": "war_heavy_strike",  # 使用哪个技能（action=skill时）
            "reason_tag": "low_hp_defend"    # 供内部记录
        }
        """
        hp_pct = member.hp / member.max_hp if member.max_hp > 0 else 0
        mp = member.mp

        # 规则1：HP < 25% → 优先防御
        if hp_pct < 0.25:
            return {
                "action": "defend",
                "target_index": 0,
                "skill_id": None,
                "reason_tag": "low_hp_defend",
            }

        # 筛选存活敌人
        alive_enemies = [(i, e) for i, e in enumerate(enemies) if e.get("hp", 0) > 0]
        if not alive_enemies:
            return {"action": "defend", "target_index": 0, "skill_id": None, "reason_tag": "no_enemies"}

        # 规则2：有伤害技能且MP足够 → 使用技能（优先选倍率最高的）
        from simlife.backend.skill_system import SkillSystem
        usable_skills = []
        for sid in member.skills:
            sk = SkillSystem.get_skill(sid)
            if sk and sk.type in ("physical", "magic") and sk.mp_cost <= mp:
                dmg_mult = sk.effects[0].value if sk.effects else 1.0
                usable_skills.append((sk, dmg_mult))

        # Boss战优先用技能
        has_boss = any(e.get("type") == "boss" for _, e in alive_enemies)
        if usable_skills and (has_boss or random.random() < 0.5):
            # 选倍率最高的技能
            usable_skills.sort(key=lambda x: x[1], reverse=True)
            sk = usable_skills[0][0]

            # 目标选择：Boss战优先打Boss，否则打最弱的
            target_idx = PartyAgent._select_target(alive_enemies, has_boss)

            return {
                "action": "skill",
                "target_index": target_idx,
                "skill_id": sk.id,
                "is_magic": sk.type == "magic",
                "skill_mult": sk.effects[0].value if sk.effects else 1.0,
                "reason_tag": "use_skill_boss" if has_boss else "use_skill",
            }

        # 规则3：普通攻击 → 优先攻击最弱敌人
        target_idx = PartyAgent._select_target(alive_enemies, has_boss)
        return {
            "action": "attack",
            "target_index": target_idx,
            "skill_id": None,
            "reason_tag": "normal_attack",
        }

    @staticmethod
    def _select_target(alive_enemies: List, has_boss: bool) -> int:
        """选择攻击目标：Boss战优先Boss，否则打最弱的"""
        if has_boss:
            for idx, e in alive_enemies:
                if e.get("type") == "boss":
                    return idx
        # 打HP最低的敌人
        weakest = min(alive_enemies, key=lambda x: x[1].get("hp", 999))
        return weakest[0]

    # ── 扫荡模式决策（简化版，不调LLM）──

    @staticmethod
    def decide_sweep_action(member: PartyMember, enemies: List[Dict]) -> Optional[Dict]:
        """扫荡模式下的队友决策（简化版）

        返回 cmd_override 格式（与 death_mode._quick_combat 兼容）：
        {"party_member_X_is_magic": bool, "party_member_X_skill_mult": float, "party_member_X_skill": str}
        或 None（普通攻击）
        """
        if not member.is_alive or member.hp <= 0:
            return None

        from simlife.backend.skill_system import SkillSystem
        mp = member.mp
        usable = []
        for sid in member.skills:
            sk = SkillSystem.get_skill(sid)
            if sk and sk.type in ("physical", "magic") and sk.mp_cost <= mp:
                usable.append(sk)

        if not usable:
            return None

        sk = random.choice(usable)
        member.mp -= sk.mp_cost
        return {
            f"party_member_{member.member_id}_is_magic": sk.type == "magic",
            f"party_member_{member.member_id}_skill_mult": sk.effects[0].value if sk.effects else 1.0,
            f"party_member_{member.member_id}_skill": sk.id,
        }

    # ── 台词生成（关键节点才调LLM）──

    # 固定模板台词（不调LLM，省token）
    DIALOGUE_TEMPLATES = {
        "combat_start": [
            "小心点！",
            "交给我吧！",
            "一起上！",
            "别大意！",
        ],
        "kill_enemy": [
            "解决一个！",
            "干得漂亮！",
            "下一个是谁？",
        ],
        "low_hp": [
            "我...撑不住了...",
            "需要治疗！",
            "危险！",
        ],
        "victory": [
            "赢了！",
            "辛苦了！",
            "终于结束了。",
        ],
        "hazard": [
            "小心机关！",
            "有陷阱！",
            "当心脚下！",
        ],
        "boss_start": [
            "这是Boss！全力以赴！",
            "大家注意，强敌来了！",
            "别留手，上！",
        ],
    }

    @staticmethod
    def generate_dialogue(member: PartyMember, trigger: str,
                           context: Dict = None, llm_client=None) -> Optional[str]:
        """生成队友台词

        trigger: combat_start / kill_enemy / low_hp / victory / hazard / boss_start
        优先用固定模板（省token），关键节点可选调LLM
        """
        templates = PartyAgent.DIALOGUE_TEMPLATES.get(trigger, [])
        if not templates:
            return None

        # 90%用固定模板，10%调LLM生成个性化台词（省token）
        if random.random() < 0.9 or not llm_client:
            return random.choice(templates)

        # LLM生成个性化台词
        try:
            context = context or {}
            enemy_name = context.get("enemy_name", "敌人")
            prompt = f"""你是队友"{member.name}"（职业：{member.class_name}），在战斗中触发了一个台词节点。
触发场景：{trigger}
当前情况：{context.get('situation', '战斗中')}

请用1句话说一句符合你职业和性格的台词。要简短自然，不超过20字。只返回台词文本。"""

            response = llm_client.generate(prompt, max_tokens=50, temperature=0.9, thinking=False)
            return response.strip().strip('"').strip('"').strip('"')
        except Exception:
            return random.choice(templates)

    # ── 队友招募 ──

    # 可招募的队友模板（按世界类型）
    RECRUIT_TEMPLATES = {
        "fantasy": [
            {"name": "老兵卡尔", "class_id": "warrior", "class_name": "战士", "icon": "⚔️",
             "stats": {"strength": 12, "agility": 6, "intelligence": 4, "vitality": 10, "luck": 5}},
            {"name": "游侠艾拉", "class_id": "rogue", "class_name": "盗贼", "icon": "🏹",
             "stats": {"strength": 7, "agility": 12, "intelligence": 6, "vitality": 6, "luck": 8}},
            {"name": "法师琳达", "class_id": "mage", "class_name": "法师", "icon": "🔮",
             "stats": {"strength": 3, "agility": 6, "intelligence": 14, "vitality": 4, "luck": 7}},
            {"name": "牧师汤姆", "class_id": "cleric", "class_name": "牧师", "icon": "✨",
             "stats": {"strength": 5, "agility": 5, "intelligence": 10, "vitality": 8, "luck": 6}},
        ],
        "xianxia": [
            {"name": "剑修陈风", "class_id": "sword immortal", "class_name": "剑修", "icon": "🗡️",
             "stats": {"strength": 13, "agility": 8, "intelligence": 7, "vitality": 9, "luck": 5}},
            {"name": "丹师苏婉", "class_id": "alchemist", "class_name": "丹师", "icon": "💊",
             "stats": {"strength": 4, "agility": 6, "intelligence": 13, "vitality": 7, "luck": 8}},
            {"name": "体修铁牛", "class_id": "body cultivator", "class_name": "体修", "icon": "💪",
             "stats": {"strength": 15, "agility": 5, "intelligence": 3, "vitality": 12, "luck": 4}},
        ],
        "wuxia": [
            {"name": "剑客柳风", "class_id": "swordsman", "class_name": "剑客", "icon": "🗡️",
             "stats": {"strength": 13, "agility": 10, "intelligence": 5, "vitality": 8, "luck": 6}},
            {"name": "拳师铁山", "class_id": "boxer", "class_name": "拳师", "icon": "👊",
             "stats": {"strength": 14, "agility": 7, "intelligence": 4, "vitality": 11, "luck": 5}},
            {"name": "医者素心", "class_id": "doctor", "class_name": "医者", "icon": "💊",
             "stats": {"strength": 4, "agility": 7, "intelligence": 12, "vitality": 8, "luck": 10}},
        ],
        "post_apocalyptic": [
            {"name": "老兵雷克斯", "class_id": "soldier", "class_name": "士兵", "icon": "🔫",
             "stats": {"strength": 10, "agility": 8, "intelligence": 6, "vitality": 10, "luck": 6}},
            {"name": "医生艾米", "class_id": "medic", "class_name": "医疗兵", "icon": "⚕️",
             "stats": {"strength": 5, "agility": 7, "intelligence": 12, "vitality": 7, "luck": 7}},
            {"name": "工程师泰克", "class_id": "engineer", "class_name": "工程师", "icon": "🔧",
             "stats": {"strength": 7, "agility": 6, "intelligence": 11, "vitality": 8, "luck": 6}},
        ],
        "modern_power": [
            {"name": "格斗家阿龙", "class_id": "fighter", "class_name": "格斗家", "icon": "👊",
             "stats": {"strength": 12, "agility": 9, "intelligence": 5, "vitality": 9, "luck": 6}},
            {"name": "异能者小雪", "class_id": "esper", "class_name": "异能者", "icon": "🧊",
             "stats": {"strength": 4, "agility": 8, "intelligence": 13, "vitality": 5, "luck": 8}},
            {"name": "侦探老陈", "class_id": "detective", "class_name": "侦探", "icon": "🔍",
             "stats": {"strength": 7, "agility": 9, "intelligence": 10, "vitality": 7, "luck": 9}},
        ],
        "scifi": [
            {"name": "机甲师Z", "class_id": "mech pilot", "class_name": "机甲师", "icon": "🤖",
             "stats": {"strength": 11, "agility": 7, "intelligence": 8, "vitality": 10, "luck": 5}},
            {"name": "黑客诺娃", "class_id": "hacker", "class_name": "黑客", "icon": "💻",
             "stats": {"strength": 3, "agility": 9, "intelligence": 14, "vitality": 5, "luck": 8}},
            {"name": "生化人K9", "class_id": "cyborg", "class_name": "生化人", "icon": "🦾",
             "stats": {"strength": 10, "agility": 10, "intelligence": 6, "vitality": 10, "luck": 5}},
        ],
    }

    @staticmethod
    def generate_recruit_options(world_type: str, char_level: int, count: int = 3) -> List[Dict]:
        """生成可招募的队友选项

        返回可供玩家选择的队友列表（未招募状态）
        """
        templates = PartyAgent.RECRUIT_TEMPLATES.get(
            world_type, PartyAgent.RECRUIT_TEMPLATES["fantasy"]
        )
        selected = random.sample(templates, min(count, len(templates)))

        options = []
        for i, t in enumerate(selected):
            # 队友等级比玩家低1-3级
            member_level = max(1, char_level - random.randint(1, 3))
            # HP/MP按等级计算
            base_hp = 80 + member_level * 20
            base_mp = 20 + member_level * 10

            member = PartyMember(
                member_id=f"pm_{random.randint(1000, 9999)}",
                name=t["name"],
                class_id=t["class_id"],
                class_name=t["class_name"],
                class_icon=t.get("icon", "🧑"),
                level=member_level,
                hp=base_hp,
                max_hp=base_hp,
                mp=base_mp,
                max_mp=base_mp,
                stats=t["stats"].copy(),
                skills=[],  # 招募后根据职业分配技能
                relation=random.randint(40, 60),
            )
            options.append(member.to_dict())

        return options

    @staticmethod
    def recruit_member(member_dict: Dict, world_type: str = "fantasy") -> PartyMember:
        """将招募选项转换为队友实例，并分配初始技能"""
        member = PartyMember.from_dict(member_dict)

        # 根据职业分配1-2个初始技能
        from simlife.backend.skill_system import SkillSystem
        class_skills = SkillSystem.get_skills_by_level(world_type, member.class_id, member.level)
        if class_skills:
            pick_count = min(2, len(class_skills))
            member.skills = [s.id for s in random.sample(class_skills, pick_count)]

        return member

    # ── 观测视图 ──

    @staticmethod
    def get_observation(member: PartyMember, dungeon=None) -> Dict:
        """获取队友的观测视图

        如果在地下城中，从Dungeon获取过滤后的视图。
        否则返回基础战斗信息。
        """
        if dungeon:
            return dungeon.get_observation_view(f"party_{member.member_id}")
        return {"in_dungeon": False}
