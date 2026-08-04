"""
成长机制 — 爽文/平衡/慢热三档

技能系统已迁移至 skill_system.py
"""
import random
from typing import Dict, List, Tuple

from simlife.backend.skill_system import SkillSystem, MAX_LEVEL


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
            "skill_points_gained": 0,
            "new_skills": [],
        }

        # 检查升级（满级后不再升级）
        while character["experience"] >= character["exp_to_next"] and character["level"] < MAX_LEVEL:
            character["experience"] -= character["exp_to_next"]
            character["level"] += 1

            # 满级后清空经验
            if character["level"] >= MAX_LEVEL:
                character["experience"] = 0
                character["exp_to_next"] = 0
                result["max_level_reached"] = True

            # 更新升级经验需求
            character["exp_to_next"] = int(character["exp_to_next"] * config["exp_curve"])

            # 增加属性
            character["max_hp"] += config["hp_growth"]
            character["hp"] = character["max_hp"]  # 升级回满
            character["max_mp"] += config["mp_growth"]
            character["mp"] = character["max_mp"]

            # 属性点存入角色，由玩家手动分配
            points = config["stat_points_per_level"]
            character["stat_points"] = character.get("stat_points", 0) + points
            result["stat_points_gained"] += points

            # 技能学习点：每升2级获得1个技能点（用于手动学习新技能）
            if character["level"] % 2 == 0:
                character["skill_points"] = character.get("skill_points", 0) + 1
                result["skill_points_gained"] = result.get("skill_points_gained", 0) + 1

            # 检查新技能解锁提示（不自动学习，玩家需手动通过技能面板学习）
            class_id = character.get("class_id", "warrior")
            world_type = character.get("world_type", "fantasy")
            stats = character.get("stats", {})
            known_skills = character.get("skills", [])
            available = SkillSystem.get_available_skills(world_type, class_id,
                                                          character["level"], stats, known_skills)
            for item in available:
                skill = item["skill"]
                if skill.req_level <= character["level"] and skill.id not in known_skills:
                    # 只记录可学的新技能，不自动加入skills列表
                    result["new_skills"].append({"id": skill.id, "name": skill.name, "manual_learn": True})

            result["leveled_up"] = True
            result["new_level"] = character["level"]

        return result

    @staticmethod
    def allocate_stat_points(character: Dict, allocations: Dict) -> Tuple[bool, str]:
        """
        手动分配属性点。
        allocations: {"strength": 1, "agility": 2, ...}
        返回 (是否成功, 消息)。
        """
        valid_stats = {"strength", "agility", "intelligence", "vitality", "luck"}
        total_request = sum(v for v in allocations.values() if v > 0)
        available = character.get("stat_points", 0)

        if total_request <= 0:
            return False, "请至少分配1点"
        if total_request > available:
            return False, f"属性点不足，剩余{available}点"

        stats = character.get("stats", {})
        for k, v in allocations.items():
            if k in valid_stats and k in stats and v > 0:
                stats[k] += v

        character["stat_points"] = available - total_request
        return True, f"成功分配{total_request}点属性"

    @staticmethod
    def get_available_skills(world_type: str, class_id: str, current_level: int,
                              stats: Dict, known_skills: List[str]) -> List[Dict]:
        """获取当前可学习的新技能（返回简化信息）"""
        skills = SkillSystem.get_available_skills(world_type, class_id, current_level, stats, known_skills)
        return [item["skill"].to_dict() for item in skills]