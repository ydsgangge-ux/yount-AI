"""
世界推进系统：按 play_time_days 每 7 天推进一次世界事件
- 生成"冒险者酒馆新闻"写到 state["world_news"]
- 新闻可以解锁任务（联动 quest_system）
- 节奏温和：一周一条，不激进
"""
from typing import Dict, List, Optional, Tuple
import copy


# ─────────────────────────────────────────────
# 世界事件时间线（按世界类型分组）
# day_threshold: 达到该天数时触发
# ─────────────────────────────────────────────
WORLD_TIMELINE = {
    "fantasy": [
        {
            "day_threshold": 7,
            "id": "we_fantasy_1",
            "title": "酒馆传闻：Mage Council 的新发现",
            "news": "酒馆老板说，Mage Council 在 Silvamagica 发现了一处远古封印，正在招募志愿者协助研究。",
            "unlock_quests": [],
        },
        {
            "day_threshold": 14,
            "id": "we_fantasy_2",
            "title": "前线消息：Dark Guild 蠢蠢欲动",
            "news": "Liberation Army 斥候报告，Dark Guild 在 Tenebralis 边境集结，疑似图谋不轨。",
            "unlock_quests": ["q_fantasy_dark_scout"],
        },
        {
            "day_threshold": 21,
            "id": "we_fantasy_3",
            "title": "冒险者协会公告：第一层BOSS攻略战",
            "news": "Liberation Army 公开招募勇者挑战 Luminous Sanctum 的 Boss，承诺给予重赏。",
            "unlock_quests": ["q_fantasy_floor1_boss"],
        },
        {
            "day_threshold": 30,
            "id": "we_fantasy_4",
            "title": "城镇流言：神秘旅人抵达",
            "news": "一位戴着兜帽的神秘旅人入驻酒馆，据说他知晓 Sage 之塔的秘密。",
            "unlock_quests": [],
        },
        {
            "day_threshold": 45,
            "id": "we_fantasy_5",
            "title": "Mage Council 警告：第六层封印松动",
            "news": "Mage Council 发布警告，第六层封印出现裂痕，需要更多冒险者协助。",
            "unlock_quests": [],
        },
        {
            "day_threshold": 60,
            "id": "we_fantasy_6",
            "title": "前线急报：Dark Guild 大规模袭击",
            "news": "Dark Guild 突袭 Ironport，多处建筑被毁，多名玩家重伤。",
            "unlock_quests": ["q_fantasy_dark_strike"],
        },
    ],
    "cultivation": [
        {
            "day_threshold": 7,
            "id": "we_cult_1",
            "title": "山门外：妖兽异动",
            "news": "外门弟子传言，山外妖兽近期频繁出现，长老们正在寻找清剿之人。",
            "unlock_quests": ["q_cult_spirit_beast"],
        },
        {
            "day_threshold": 14,
            "id": "we_cult_2",
            "title": "丹房消息：灵草短缺",
            "news": "丹房执事抱怨灵草库存告急，正在悬赏采集。",
            "unlock_quests": ["q_cult_spirit_herb"],
        },
        {
            "day_threshold": 21,
            "id": "we_cult_3",
            "title": "内门传召：试炼开启",
            "news": "内门长老宣布试炼塔即将开启，符合条件的外门弟子可报名参试。",
            "unlock_quests": ["q_cult_inner_trial"],
        },
        {
            "day_threshold": 35,
            "id": "we_cult_4",
            "title": "宗门传闻：天劫将至",
            "news": "长老们面色凝重，传闻有高人将渡天劫，全宗戒备。",
            "unlock_quests": [],
        },
    ],
    "apocalypse": [
        {
            "day_threshold": 7,
            "id": "we_apoc_1",
            "title": "避难所广播：物资告急",
            "news": "避难所广播求助，罐头等食物储备已不足三日，急需搜刮。",
            "unlock_quests": ["q_apoc_scavenge"],
        },
        {
            "day_threshold": 14,
            "id": "we_apoc_2",
            "title": "前线警报：尸潮来袭",
            "news": "避难所外围出现尸潮，需要清剿。",
            "unlock_quests": ["q_apoc_clear_zombies"],
        },
        {
            "day_threshold": 28,
            "id": "we_apoc_3",
            "title": "幸存者电台：他方避难所联络",
            "news": "无线电收到另一个避难所的求救信号，但他们似乎隐瞒了什么。",
            "unlock_quests": [],
        },
    ],
}


class WorldProgress:
    """世界推进系统，所有方法 classmethod"""

    @classmethod
    def _ensure_state(cls, state: Dict) -> Dict:
        if "world_news" not in state:
            state["world_news"] = []
        state.setdefault("world_progress_triggered", [])
        return state

    @classmethod
    def check_and_advance(cls, state: Dict) -> Optional[Dict]:
        """
        检查当前 play_time_days，触发尚未触发的世界事件。
        返回最新触发的新闻（如果有），否则 None。
        """
        cls._ensure_state(state)
        world_type = state.get("world_type", "fantasy")
        play_days = state.get("play_time_days", 1)
        timeline = WORLD_TIMELINE.get(world_type, WORLD_TIMELINE["fantasy"])
        triggered = set(state["world_progress_triggered"])

        newly_triggered = None
        for event in timeline:
            if event["id"] in triggered:
                continue
            if play_days >= event["day_threshold"]:
                # 触发事件
                news_entry = {
                    "id": event["id"],
                    "day": play_days,
                    "title": event["title"],
                    "news": event["news"],
                    "unlock_quests": event.get("unlock_quests", []),
                    "read": False,
                }
                state["world_news"].append(news_entry)
                state["world_progress_triggered"].append(event["id"])
                newly_triggered = news_entry
                # 解锁任务：实际是改变任务可见性，但因为 QuestSystem.get_available_quests
                # 本身就会过滤已交付/进行中的任务，所以"解锁"主要是等级+前置的判断
                # 这里不需要额外操作，quest 系统会自然处理
        return newly_triggered

    @classmethod
    def get_recent_news(cls, state: Dict, limit: int = 10) -> List[Dict]:
        """获取最近 N 条新闻（默认未读优先）"""
        cls._ensure_state(state)
        news = state["world_news"]
        # 按 day 倒序
        sorted_news = sorted(news, key=lambda x: x.get("day", 0), reverse=True)
        return sorted_news[:limit]

    @classmethod
    def get_unread_count(cls, state: Dict) -> int:
        cls._ensure_state(state)
        return sum(1 for n in state["world_news"] if not n.get("read", False))

    @classmethod
    def mark_news_read(cls, state: Dict, news_id: str = None) -> int:
        """标记新闻为已读。news_id=None 表示全部。返回标记条数"""
        cls._ensure_state(state)
        count = 0
        for n in state["world_news"]:
            if news_id is None or n.get("id") == news_id:
                if not n.get("read", False):
                    n["read"] = True
                    count += 1
        return count

    @classmethod
    def get_current_events_summary(cls, state: Dict) -> str:
        """生成简短的世界事件摘要，供 story_agent prompt 使用"""
        cls._ensure_state(state)
        recent = state["world_news"][-3:]  # 最近3条
        if not recent:
            return ""
        lines = []
        for n in recent:
            lines.append(f"· [{n.get('day', '?')}日] {n.get('title', '')}: {n.get('news', '')[:80]}")
        return "近期世界动态：\n" + "\n".join(lines)
