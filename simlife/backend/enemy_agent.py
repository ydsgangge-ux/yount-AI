"""
敌人Agent —— 给特殊敌人（精英、BOSS、反派势力）添加智能决策和对话能力
设计原则：
1. 轻量级：不改变现有敌人生成流程，只在战斗时接管
2. 自由度高：从世界观读取势力信息，适应任意世界观
3. 高自由：反派/勇者/任何势力都可以是敌人，取决于用户的行动
"""

import random
from typing import Dict, List, Optional, Tuple

from simlife.backend.skill_system import SkillSystem
from simlife.backend.combat_system import DefenseAction


# 对话触发点
DIALOG_TRIGGERS = [
    "battle_start",    # 战斗开始
    "crisis_low_hp",  # HP < 20%
    "kill_player",     # 击杀玩家队友
    "player_crit",    # 玩家暴击
    "defeat_enemy",   # 击杀精英/BOSS
    "stage_enter",    # 进入二阶段
]


class EnemyAgent:
    """
    包装一个敌人，提供智能决策和对话能力。
    敌人数据仍由 CombatSystem 生成，Agent 只提供决策和对话。
    """

    # 特殊敌人类型（击败后永久屏蔽，不允许LLM重新生成）
    UNIQUE_TYPES = ("elite", "boss")

    @classmethod
    def is_unique_enemy(cls, enemy: Dict) -> bool:
        """判断是否为特殊敌人（精英/Boss）"""
        return enemy.get("type", "normal") in cls.UNIQUE_TYPES

    @staticmethod
    def is_already_defeated(state: Dict, enemy_name: str) -> bool:
        """检查特殊敌人是否已被击败（永久屏蔽）"""
        if not enemy_name:
            return False
        # 规范化名字比较（去连字符、统一空格），与 spotted_enemies 处理保持一致
        import re
        def _normalize(n):
            return re.sub(r'\s+', ' ', n.replace('-', ' ')).strip().lower()
        normalized = _normalize(enemy_name)
        unique_defeated = state.get("defeated_unique_enemies", [])
        return normalized in (_normalize(d) for d in unique_defeated)

    def __init__(self, enemy: Dict, world_setting: Dict = None):
        """
        enemy: 敌人字典（来自 CombatSystem.generate_enemy）
        world_setting: 当前世界观设定，用于读取势力信息
        """
        self.enemy = enemy
        self.name = enemy.get("name", "未知敌人")
        self.level = enemy.get("level", 1)
        self.type = enemy.get("type", "normal")  # normal/elite/boss
        self.faction_name: Optional[str] = None
        self.dialogue_style: str = "default"
        self.skill_set: List[Dict] = []  # 敌人拥有的技能
        self.tactics: Dict = {
            "aggressive": True,
            "focus_tank": True,
            "phase": 1,
            "low_hp_rage": True,
        }
        self.world_setting = world_setting or {}

        # 从世界观分配势力（如果敌人属于某个势力）
        self._assign_faction()
        # 分配技能
        self._assign_skills()

    def _assign_faction(self):
        """从世界观读取势力信息，分配给敌人"""
        factions = self.world_setting.get("factions", [])
        if not factions:
            return

        # 敌人类型对应势力：精英/BOSS更可能属于势力
        if self.type == "normal":
            # 普通怪 20% 概率属于势力
            if random.random() > 0.2:
                return

        # 收集符合等级的势力首领/精英成员
        candidates = []
        for f in factions:
            # 势力首领肯定是BOSS
            if self.type == "boss":
                leader = f.get("leader")
                if leader and isinstance(leader, dict) and leader.get("name"):
                    candidates.append({
                        "name": leader["name"],
                        "type": "boss",
                        "faction": f["name"],
                        "description": leader.get("description", ""),
                    })
            # 精英可能是势力成员
            elif self.type == "elite":
                notable = f.get("notable_members", [])
                for nm in notable:
                    if nm and isinstance(nm, dict) and nm.get("name"):
                        candidates.append({
                            "name": nm["name"],
                            "type": "elite",
                            "faction": f["name"],
                            "description": nm.get("description", ""),
                        })

        if candidates:
            chosen = random.choice(candidates)
            self.name = chosen["name"]
            self.faction_name = chosen["faction"]
            # 根据势力类型确定对话风格：从原势力数据中获取type
            faction_type = "default"
            for f in factions:
                if f.get("name") == chosen["faction"]:
                    faction_type = f.get("type", "other")
                    break
            self._set_dialogue_style(faction_type)

    def _set_dialogue_style(self, faction_type: str):
        """根据势力类型设置对话风格"""
        style_map = {
            "kingdom": "royal:威严傲慢",
            "empire": "imperial:残暴自信",
            "guild": "guild:专业冷酷",
            "dark_guild": "dark:嘲讽冷血",
            "religion": "religious:虔诚狂热",
            "mercenary": "mercenary:务实要钱",
            "academy": "academic:理性轻蔑",
            "evil_cult": "cult:疯狂诡异",
            "monster": "beast:凶猛无智",
            "rebel": "rebel:激昂反抗",
        }
        self.dialogue_style = style_map.get(faction_type, "default")

    def _assign_skills(self):
        """从技能池给敌人分配技能"""
        # 根据敌人类型决定技能数量
        if self.type == "normal":
            # 普通怪没有技能
            self.skill_set = []
            return
        elif self.type == "elite":
            # 精英 1-2个技能
            count = random.randint(1, 2)
        elif self.type == "boss":
            # BOSS 2-3个技能
            count = random.randint(2, 3)
        else:
            count = 1

        self.skill_set = SkillSystem.assign_skills_for_enemy(count, self.level, self.type)

        # 如果是BOSS，一定有一个群体技能
        if self.type == "boss" and not any(s.get("target_type") == "aoe" for s in self.skill_set):
            # 替换最后一个技能为AOE
            aoe_skill = SkillSystem.get_random_aoe_skill(self.level)
            if aoe_skill:
                if self.skill_set:
                    self.skill_set[-1] = aoe_skill
                else:
                    self.skill_set.append(aoe_skill)

    def choose_defense(self) -> DefenseAction:
        """选择防御方式（对玩家攻击进行防御）"""
        stats = self.enemy.get("stats", {})
        intel = stats.get("intelligence", 5)

        choices = [DefenseAction.DODGE, DefenseAction.BLOCK, DefenseAction.NONE]
        if intel > 12:
            choices.append(DefenseAction.PARRY)

        # 根据智力调整概率：高智商更倾向招架
        weights = {
            DefenseAction.DODGE: 3,
            DefenseAction.BLOCK: 3,
            DefenseAction.NONE: 1,
            DefenseAction.PARRY: max(1, int(intel / 3)),
        }

        # 低血量更可能防御
        hp_pct = self.get_hp_percent()
        if hp_pct < 0.3:
            weights[DefenseAction.BLOCK] += 2

        # 加权随机
        total = sum(weights.values())
        r = random.randint(1, total)
        cumulative = 0
        for choice, weight in weights.items():
            cumulative += weight
            if r <= cumulative:
                return choice
        return DefenseAction.BLOCK

    def choose_target(self, available_targets: List[Dict]) -> Dict:
        """选择攻击目标（从可用目标中选）

        available_targets: [{"name": "...", "hp": ..., "max_hp": ..., "is_tank": bool}, ...]
        返回选中的目标 dict
        """
        if not available_targets:
            return available_targets[0] if available_targets else None

        # 战术：优先打低血量 → 然后坦克 → 然后随机
        # 根据势力/类型调整优先级
        targets = sorted(available_targets, key=lambda t: (
            # 低血量优先
            t.get("hp", 0) / (t.get("max_hp", 1) or 1),
            # 坦克后打（如果是凶狠型会先打坦克）
            -1 if t.get("is_tank") and self.tactics["aggressive"] else 1,
            random.random(),
        ))

        return targets[0]

    def get_dialogue(self, trigger: str) -> Optional[str]:
        """根据触发点获取对话（可能返回 None 表示不说话）"""
        # 概率：普通怪不说话，精英说一半，BOSS必说
        if self.type == "normal":
            if random.random() > 0.1:
                return None
        elif self.type == "elite":
            if random.random() > 0.5:
                return None

        templates = self._get_dialogue_templates(trigger)
        if not templates:
            return None
        return random.choice(templates).format(name=self.name, faction=self.faction_name or "")

    def _get_dialogue_templates(self, trigger: str) -> List[str]:
        """根据对话风格和触发点获取模板"""
        # 风格 -> 触发点 -> 模板列表
        style_templates = {
            "royal:威严傲慢": {
                "battle_start": ["蝼蚁也敢挑战本王？", "不知天高地厚的小虫，准备好灭亡了吗？", "你们的勇气值得称赞——可惜，勇气救不了命。"],
                "crisis_low_hp": ["这点伤害……就这点？", "你以为这样就能杀死我吗？可笑。", "你们激怒了我！"],
                "kill_player": ["这就是反抗我的下场。", "下一个是谁？"],
                "player_crit": ["运气不错……但运气不会一直站在你这边。", "哼，侥幸。"],
                "defeat_enemy": "就这点本事也配称为勇者？",
                "stage_enter": ["感受我的真正力量吧！"],
            },
            "dark:嘲讽冷血": {
                "battle_start": ["把钱留下，命留下。", "这趟活的赏金够我花半年了。", "你们还真敢过来啊。"],
                "crisis_low_hp": ["就这点伤害……还不够挠痒。", "可惜，你打错人了。"],
                "kill_player": ["下一个。", "任务完成，收工。"],
                "player_crit": ["运气不错。可惜，下一次你就没这么好运了。"],
                "defeat_enemy": ["垃圾就是垃圾。"],
                "stage_enter": ["现在，让你看看黑暗的真正力量。"],
            },
            "cult:疯狂诡异": {
                "battle_start": ["……赞美……深渊……", "……鲜血……献祭……", "…… join us……"],
                "crisis_low_hp": ["……更深……更深……", "……混沌……吞噬……"],
                "kill_player": ["……灵魂……给了……主人……"],
                "player_crit": ["……有趣……继续……"],
            },
            "mercenary:务实要钱": {
                "battle_start": ["我只要赏金，别挡路。", "拿钱办事，杀人不眨眼。", "规矩我懂，动手吧。"],
                "crisis_low_hp": ["追加赏金我就活下来，不然你得加钱。", "这点伤不影响干活。"],
                "kill_player": ["尾款结清，下一个。"],
            },
            "academic:理性轻蔑": {
                "battle_start": ["你的数据我已经建模完成，胜利毫无悬念。", "统计学上你胜率不足 5%，投降吧。", "理论上你不该出现在这里。"],
                "crisis_low_hp": ["误差在允许范围内，实验继续。", "数据收集完成，结论不变。"],
                "player_crit": ["标准差偏大，样本不足，不足为虑。"],
            },
            "beast:凶猛无智": {
                "battle_start": ["*咆哮*", "*嘶吼*"],
                "crisis_low_hp": ["*愤怒咆哮*"],
            },
            "default": {
                "battle_start": ["[{}]准备受死！", "你的死期到了！", "入侵者，滚出去！"],
                "crisis_low_hp": ["绝不投降！", "我还能战斗！"],
                "kill_player": ["下一个！"],
                "player_crit": ["哼，算你厉害。"],
            },
        }

        # 获取对应风格的模板，没有就用默认
        if self.dialogue_style in style_templates and trigger in style_templates[self.dialogue_style]:
            return style_templates[self.dialogue_style][trigger]
        if trigger in style_templates["default"]:
            return style_templates["default"][trigger]
        return []

    def get_hp_percent(self) -> float:
        """获取当前血量百分比"""
        hp = self.enemy.get("hp", 0)
        max_hp = self.enemy.get("max_hp", 1)
        return hp / max_hp if max_hp > 0 else 1.0

    def is_low_hp(self) -> bool:
        """是否低血量（触发狂暴）"""
        return self.get_hp_percent() < 0.2

    def check_phase_change(self) -> bool:
        """BOSS 是否需要进入下一阶段（HP<50%）"""
        if self.type != "boss":
            return False
        if self.tactics["phase"] == 1 and self.get_hp_percent() < 0.5:
            self.tactics["phase"] = 2
            return True
        return False

    def get_skills(self) -> List[Dict]:
        """获取敌人技能列表"""
        return self.skill_set

    def get_enemy(self) -> Dict:
        """返回原始敌人字典"""
        return self.enemy


def should_use_agent(enemy: Dict) -> bool:
    """判断这个敌人是否需要使用 EnemyAgent"""
    etype = enemy.get("type", "normal")
    # 普通敌人不用，精英/BOSS用
    return etype in ("elite", "boss")


def get_enemy_agent(enemy: Dict, world_setting: Dict) -> Optional[EnemyAgent]:
    """获取敌人 Agent，如果需要则返回实例，否则返回 None"""
    if should_use_agent(enemy):
        return EnemyAgent(enemy, world_setting)
    return None


# ── 特殊敌人唯一性管理 ──
UNIQUE_ENEMY_TYPES = ("elite", "boss")


def is_unique_enemy(enemy: Dict) -> bool:
    """判断是否为特殊敌人（精英/Boss），特殊敌人击败后永久屏蔽"""
    return enemy.get("type", "normal") in UNIQUE_ENEMY_TYPES
