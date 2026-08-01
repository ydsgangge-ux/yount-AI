"""
成长机制 — 爽文/平衡/慢热三档

技能系统已迁移至 skill_system.py
"""
import random
from typing import Dict, List

from simlife.backend.skill_system import SkillSystem


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

            # 检查新技能解锁（使用 SkillSystem）
            class_id = character.get("class_id", "warrior")
            world_type = character.get("world_type", "fantasy")
            stats = character.get("stats", {})
            known_skills = character.get("skills", [])
            available = SkillSystem.get_available_skills(world_type, class_id,
                                                          character["level"], stats, known_skills)
            for item in available:
                skill = item["skill"]
                if skill.req_level <= character["level"] and skill.id not in known_skills:
                    character["skills"].append(skill.id)
                    result["new_skills"].append({"id": skill.id, "name": skill.name})

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
        stats = character.get("stats", {})
        for k, v in allocations.items():
            if k in stats and v > 0:
                stats[k] += v
        return True

    @staticmethod
    def get_available_skills(world_type: str, class_id: str, current_level: int,
                              stats: Dict, known_skills: List[str]) -> List[Dict]:
        """获取当前可学习的新技能（返回简化信息）"""
        skills = SkillSystem.get_available_skills(world_type, class_id, current_level, stats, known_skills)
        return [item["skill"].to_dict() for item in skills]