"""
成长机制 — 爽文/平衡/慢热三档
"""
import random
from typing import Dict, List


class GrowthSystem:
    """角色成长系统：经验、升级、技能学习"""

    # 成长模式配置
    GROWTH_CONFIG = {
        "fast": {  # 爽文模式：快速升级，大幅增长
            "exp_multiplier": 1.5,  # 经验获取倍率
            "exp_curve": 1.15,      # 升级经验曲线
            "stat_points_per_level": 5,  # 每级可分配点数
            "hp_growth": 30,
            "mp_growth": 15,
        },
        "normal": {  # 平衡模式
            "exp_multiplier": 1.0,
            "exp_curve": 1.25,
            "stat_points_per_level": 3,
            "hp_growth": 20,
            "mp_growth": 10,
        },
        "slow": {  # 慢热模式：慢速成长，每点都很重要
            "exp_multiplier": 0.7,
            "exp_curve": 1.4,
            "stat_points_per_level": 2,
            "hp_growth": 12,
            "mp_growth": 6,
        },
    }

    # 可学习的技能池（按世界类型 → 职业分组）
    SKILL_POOL = {
        # ── 奇幻魔法 ──
        "fantasy": {
            "warrior": [
                {"name": "旋风斩", "mp_cost": 15, "multiplier": 1.5, "type": "physical", "req_level": 3},
                {"name": "战吼", "mp_cost": 10, "multiplier": 1.0, "type": "buff", "req_level": 5},
                {"name": "盾击", "mp_cost": 12, "multiplier": 1.3, "type": "physical", "req_level": 7},
                {"name": "狂战士", "mp_cost": 25, "multiplier": 2.0, "type": "buff", "req_level": 10},
            ],
            "mage": [
                {"name": "冰冻术", "mp_cost": 15, "multiplier": 1.4, "type": "magic", "req_level": 3},
                {"name": "闪电链", "mp_cost": 20, "multiplier": 1.6, "type": "magic", "req_level": 5},
                {"name": "瞬移", "mp_cost": 15, "multiplier": 0, "type": "utility", "req_level": 7},
                {"name": "陨石术", "mp_cost": 40, "multiplier": 2.5, "type": "magic", "req_level": 10},
            ],
            "rogue": [
                {"name": "毒刃", "mp_cost": 10, "multiplier": 1.2, "type": "physical", "req_level": 3},
                {"name": "影分身", "mp_cost": 20, "multiplier": 1.5, "type": "physical", "req_level": 5},
                {"name": "暗杀", "mp_cost": 25, "multiplier": 2.2, "type": "physical", "req_level": 7},
                {"name": "无形", "mp_cost": 15, "multiplier": 0, "type": "utility", "req_level": 10},
            ],
            "archer": [
                {"name": "连射", "mp_cost": 12, "multiplier": 1.4, "type": "physical", "req_level": 3},
                {"name": "穿透箭", "mp_cost": 18, "multiplier": 1.6, "type": "physical", "req_level": 5},
                {"name": "箭雨", "mp_cost": 30, "multiplier": 1.8, "type": "physical", "req_level": 7},
                {"name": "鹰眼", "mp_cost": 15, "multiplier": 0, "type": "buff", "req_level": 10},
            ],
            "cleric": [
                {"name": "群体治愈", "mp_cost": 25, "multiplier": 0, "type": "heal", "req_level": 3},
                {"name": "圣光术", "mp_cost": 20, "multiplier": 1.5, "type": "magic", "req_level": 5},
                {"name": "复活", "mp_cost": 50, "multiplier": 0, "type": "utility", "req_level": 7},
                {"name": "神圣审判", "mp_cost": 40, "multiplier": 2.3, "type": "magic", "req_level": 10},
            ],
        },
        # ── 仙侠修真 ──
        "xianxia": {
            "sword_cultivator": [
                {"name": "万剑归宗", "mp_cost": 20, "multiplier": 1.6, "type": "physical", "req_level": 3},
                {"name": "剑意凝形", "mp_cost": 15, "multiplier": 1.0, "type": "buff", "req_level": 5},
                {"name": "天外飞仙", "mp_cost": 30, "multiplier": 2.0, "type": "physical", "req_level": 7},
                {"name": "剑道领域", "mp_cost": 40, "multiplier": 2.5, "type": "magic", "req_level": 10},
            ],
            "body_cultivator": [
                {"name": "山岳拳", "mp_cost": 12, "multiplier": 1.5, "type": "physical", "req_level": 3},
                {"name": "不动明王", "mp_cost": 15, "multiplier": 0, "type": "buff", "req_level": 5},
                {"name": "碎地踏", "mp_cost": 20, "multiplier": 1.8, "type": "physical", "req_level": 7},
                {"name": "法天象地", "mp_cost": 40, "multiplier": 2.5, "type": "buff", "req_level": 10},
            ],
            "pill_cultivator": [
                {"name": "爆裂丹", "mp_cost": 15, "multiplier": 1.4, "type": "magic", "req_level": 3},
                {"name": "疗伤丹", "mp_cost": 20, "multiplier": 0, "type": "heal", "req_level": 5},
                {"name": "迷幻丹", "mp_cost": 18, "multiplier": 1.3, "type": "magic", "req_level": 7},
                {"name": "九转金丹", "mp_cost": 45, "multiplier": 2.5, "type": "heal", "req_level": 10},
            ],
            "talisman_cultivator": [
                {"name": "火球符", "mp_cost": 12, "multiplier": 1.4, "type": "magic", "req_level": 3},
                {"name": "封印符", "mp_cost": 20, "multiplier": 1.0, "type": "utility", "req_level": 5},
                {"name": "万符阵", "mp_cost": 30, "multiplier": 1.8, "type": "magic", "req_level": 7},
                {"name": "天符降世", "mp_cost": 40, "multiplier": 2.5, "type": "magic", "req_level": 10},
            ],
            "soul_cultivator": [
                {"name": "魂压", "mp_cost": 15, "multiplier": 1.5, "type": "magic", "req_level": 3},
                {"name": "夺舍", "mp_cost": 25, "multiplier": 1.8, "type": "magic", "req_level": 5},
                {"name": "万魂噬", "mp_cost": 30, "multiplier": 2.0, "type": "magic", "req_level": 7},
                {"name": "元神出窍", "mp_cost": 40, "multiplier": 2.5, "type": "utility", "req_level": 10},
            ],
        },
        # ── 末世废土 ──
        "post_apocalyptic": {
            "esper": [
                {"name": "心灵冲击", "mp_cost": 15, "multiplier": 1.5, "type": "magic", "req_level": 3},
                {"name": "力场护盾", "mp_cost": 20, "multiplier": 0, "type": "buff", "req_level": 5},
                {"name": "精神控制", "mp_cost": 25, "multiplier": 1.8, "type": "magic", "req_level": 7},
                {"name": "超频爆发", "mp_cost": 40, "multiplier": 2.5, "type": "magic", "req_level": 10},
            ],
            "scavenger": [
                {"name": "自制炸弹", "mp_cost": 10, "multiplier": 1.5, "type": "physical", "req_level": 3},
                {"name": "资源回收", "mp_cost": 5, "multiplier": 0, "type": "utility", "req_level": 5},
                {"name": "诱饵装置", "mp_cost": 15, "multiplier": 1.0, "type": "utility", "req_level": 7},
                {"name": "废土之王", "mp_cost": 30, "multiplier": 2.0, "type": "buff", "req_level": 10},
            ],
            "mechanic": [
                {"name": "炮台部署", "mp_cost": 20, "multiplier": 1.4, "type": "physical", "req_level": 3},
                {"name": "护甲修复", "mp_cost": 15, "multiplier": 0, "type": "heal", "req_level": 5},
                {"name": "自爆机器人", "mp_cost": 25, "multiplier": 2.0, "type": "physical", "req_level": 7},
                {"name": "机甲降临", "mp_cost": 45, "multiplier": 2.5, "type": "buff", "req_level": 10},
            ],
            "mutant": [
                {"name": "酸液喷射", "mp_cost": 12, "multiplier": 1.4, "type": "physical", "req_level": 3},
                {"name": "快速再生", "mp_cost": 20, "multiplier": 0, "type": "heal", "req_level": 5},
                {"name": "变异突进", "mp_cost": 18, "multiplier": 1.7, "type": "physical", "req_level": 7},
                {"name": "完全变异", "mp_cost": 40, "multiplier": 2.5, "type": "buff", "req_level": 10},
            ],
            "survivor": [
                {"name": "战术分析", "mp_cost": 10, "multiplier": 1.3, "type": "buff", "req_level": 3},
                {"name": "紧急包扎", "mp_cost": 15, "multiplier": 0, "type": "heal", "req_level": 5},
                {"name": "绝地反击", "mp_cost": 25, "multiplier": 2.0, "type": "physical", "req_level": 7},
                {"name": "生存本能", "mp_cost": 30, "multiplier": 2.0, "type": "buff", "req_level": 10},
            ],
        },
        # ── 现世超武 ──
        "modern_power": {
            "martial_artist": [
                {"name": "连劲崩山", "mp_cost": 15, "multiplier": 1.5, "type": "physical", "req_level": 3},
                {"name": "内力护体", "mp_cost": 20, "multiplier": 0, "type": "buff", "req_level": 5},
                {"name": "寸劲爆发", "mp_cost": 25, "multiplier": 2.0, "type": "physical", "req_level": 7},
                {"name": "武道极致", "mp_cost": 40, "multiplier": 2.5, "type": "buff", "req_level": 10},
            ],
            "awakened": [
                {"name": "能力觉醒", "mp_cost": 15, "multiplier": 1.5, "type": "magic", "req_level": 3},
                {"name": "感知域", "mp_cost": 20, "multiplier": 0, "type": "buff", "req_level": 5},
                {"name": "能力超载", "mp_cost": 30, "multiplier": 2.0, "type": "magic", "req_level": 7},
                {"name": "第二觉醒", "mp_cost": 45, "multiplier": 2.5, "type": "buff", "req_level": 10},
            ],
            "ancient_inheritor": [
                {"name": "连环掌·碎", "mp_cost": 12, "multiplier": 1.4, "type": "physical", "req_level": 3},
                {"name": "轻功·瞬步", "mp_cost": 15, "multiplier": 0, "type": "utility", "req_level": 5},
                {"name": "古武奥义", "mp_cost": 25, "multiplier": 1.8, "type": "physical", "req_level": 7},
                {"name": "传承解放", "mp_cost": 40, "multiplier": 2.5, "type": "physical", "req_level": 10},
            ],
            "dark_ability": [
                {"name": "影袭", "mp_cost": 12, "multiplier": 1.5, "type": "physical", "req_level": 3},
                {"name": "暗域", "mp_cost": 20, "multiplier": 0, "type": "utility", "req_level": 5},
                {"name": "影刃乱舞", "mp_cost": 25, "multiplier": 1.8, "type": "physical", "req_level": 7},
                {"name": "完全暗化", "mp_cost": 40, "multiplier": 2.5, "type": "buff", "req_level": 10},
            ],
            "enhancer": [
                {"name": "全力强化", "mp_cost": 15, "multiplier": 1.4, "type": "physical", "req_level": 3},
                {"name": "感官强化", "mp_cost": 15, "multiplier": 0, "type": "buff", "req_level": 5},
                {"name": "极限突破", "mp_cost": 25, "multiplier": 2.0, "type": "physical", "req_level": 7},
                {"name": "超越极限", "mp_cost": 40, "multiplier": 2.5, "type": "buff", "req_level": 10},
            ],
        },
        # ── 科幻未来 ──
        "scifi": {
            "mecha_pilot": [
                {"name": "激光齐射", "mp_cost": 15, "multiplier": 1.5, "type": "physical", "req_level": 3},
                {"name": "力场过载", "mp_cost": 20, "multiplier": 0, "type": "buff", "req_level": 5},
                {"name": "导弹风暴", "mp_cost": 30, "multiplier": 1.8, "type": "physical", "req_level": 7},
                {"name": "终极合体", "mp_cost": 45, "multiplier": 2.5, "type": "buff", "req_level": 10},
            ],
            "nano_soldier": [
                {"name": "纳米刃", "mp_cost": 12, "multiplier": 1.4, "type": "physical", "req_level": 3},
                {"name": "纳米重组", "mp_cost": 20, "multiplier": 0, "type": "heal", "req_level": 5},
                {"name": "全形态战斗", "mp_cost": 25, "multiplier": 1.8, "type": "physical", "req_level": 7},
                {"name": "纳米风暴", "mp_cost": 40, "multiplier": 2.5, "type": "magic", "req_level": 10},
            ],
            "hacker": [
                {"name": "数据洪流", "mp_cost": 15, "multiplier": 1.5, "type": "magic", "req_level": 3},
                {"name": "防火墙", "mp_cost": 18, "multiplier": 0, "type": "buff", "req_level": 5},
                {"name": "系统崩溃", "mp_cost": 25, "multiplier": 1.8, "type": "magic", "req_level": 7},
                {"name": "AI接管", "mp_cost": 40, "multiplier": 2.5, "type": "buff", "req_level": 10},
            ],
            "gene_modified": [
                {"name": "基因突变", "mp_cost": 15, "multiplier": 1.5, "type": "physical", "req_level": 3},
                {"name": "适应进化", "mp_cost": 20, "multiplier": 0, "type": "buff", "req_level": 5},
                {"name": "超限爆发", "mp_cost": 30, "multiplier": 2.0, "type": "physical", "req_level": 7},
                {"name": "完美形态", "mp_cost": 45, "multiplier": 2.5, "type": "buff", "req_level": 10},
            ],
            "energy_manipulator": [
                {"name": "能量风暴", "mp_cost": 15, "multiplier": 1.5, "type": "magic", "req_level": 3},
                {"name": "能量吸收", "mp_cost": 18, "multiplier": 0, "type": "buff", "req_level": 5},
                {"name": "等离子炮", "mp_cost": 30, "multiplier": 2.0, "type": "magic", "req_level": 7},
                {"name": "纯能量化", "mp_cost": 45, "multiplier": 2.5, "type": "buff", "req_level": 10},
            ],
        },
    }

    @staticmethod
    def get_config(growth_mode: str) -> Dict:
        return GrowthSystem.GROWTH_CONFIG.get(growth_mode, GrowthSystem.GROWTH_CONFIG["normal"])

    @staticmethod
    def gain_exp(character: Dict, base_exp: int, growth_mode: str = "normal") -> Dict:
        """
        获取经验，返回升级信息。
        返回: {"leveled_up": bool, "new_level": int, "stat_points_gained": int, "new_skills": [...]}
        """
        config = GrowthSystem.get_config(growth_mode)
        actual_exp = int(base_exp * config["exp_multiplier"])
        character["experience"] += actual_exp

        result = {
            "leveled_up": False,
            "exp_gained": actual_exp,
            "new_level": character["level"],
            "stat_points_gained": 0,
            "new_skills": [],
        }

        # 检查升级
        while character["experience"] >= character["exp_to_next"]:
            character["experience"] -= character["exp_to_next"]
            character["level"] += 1

            # 更新升级经验需求
            character["exp_to_next"] = int(character["exp_to_next"] * config["exp_curve"])

            # 增加属性
            character["max_hp"] += config["hp_growth"]
            character["hp"] = character["max_hp"]  # 升级回满
            character["max_mp"] += config["mp_growth"]
            character["mp"] = character["max_mp"]

            result["stat_points_gained"] += config["stat_points_per_level"]

            # 检查新技能解锁
            class_id = character.get("class_id", "warrior")
            world_type = character.get("world_type", "fantasy")
            world_skills = GrowthSystem.SKILL_POOL.get(world_type, {})
            skills = world_skills.get(class_id, [])
            known_skills = set(character.get("skills", []))
            for skill in skills:
                if skill["req_level"] <= character["level"] and skill["name"] not in known_skills:
                    character["skills"].append(skill["name"])
                    result["new_skills"].append(skill["name"])

            result["leveled_up"] = True
            result["new_level"] = character["level"]

        return result

    @staticmethod
    def allocate_stat_points(character: Dict, allocations: Dict) -> bool:
        """
        分配属性点。
        allocations: {"strength": 1, "agility": 2, ...}
        返回是否成功。
        """
        # 这里简单实现：直接加到 stats 上
        # 实际使用时需要从 character 中扣除可用点数
        stats = character.get("stats", {})
        for k, v in allocations.items():
            if k in stats and v > 0:
                stats[k] += v
        return True

    @staticmethod
    def get_available_skills(world_type: str, class_id: str, current_level: int, known_skills: List[str]) -> List[Dict]:
        """获取当前可学习的新技能"""
        world_skills = GrowthSystem.SKILL_POOL.get(world_type, {})
        skills = world_skills.get(class_id, [])
        known = set(known_skills)
        return [
            s for s in skills
            if s["req_level"] <= current_level and s["name"] not in known
        ]
