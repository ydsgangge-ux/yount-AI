"""
人生主线引擎 — 非现代世界的月度目标系统

核心逻辑：
- 根据世界观设定 + 角色信息，LLM 自动推算一个月级别的主线任务
- 主线分为多个阶段（stage），每个阶段持续数天
- 每天的计划围绕当前阶段生成，推进叙事连续性
- 主线完成后自动归档，生成新的主线
"""
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List

DATA_DIR = Path(__file__).parent.parent / "data"


# ── 数据结构 ──────────────────────────────────────────

class ArcStage:
    """主线的一个阶段"""
    def __init__(self, data: dict = None):
        data = data or {}
        self.name: str = data.get("name", "")
        self.description: str = data.get("description", "")
        self.goal: str = data.get("goal", "")  # 本阶段要达成的具体目标
        self.stage_type: str = data.get("stage_type", "exploration")  # travel/preparation/exploration/conflict/climax/social/resolution
        self.duration_days: int = data.get("duration_days", 5)
        self.status: str = data.get("status", "pending")  # pending / active / completed
        self.key_events: List[str] = data.get("key_events", [])
        self.sub_goals: List[str] = data.get("sub_goals", [])  # 子目标（2-4个）

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "goal": self.goal,
            "stage_type": self.stage_type,
            "duration_days": self.duration_days,
            "status": self.status,
            "key_events": self.key_events,
            "sub_goals": self.sub_goals,
        }


class LifeArc:
    """人生主线"""
    def __init__(self, data: dict = None):
        data = data or {}
        self.arc_id: str = data.get("arc_id", f"arc_{uuid.uuid4().hex[:8]}")
        self.title: str = data.get("title", "")
        self.description: str = data.get("description", "")
        self.main_goal: str = data.get("main_goal", "")
        self.antagonist: str = data.get("antagonist", "")  # 反派/对抗力量描述
        self.antagonist_motivation: str = data.get("antagonist_motivation", "")  # 反派动机
        self.threat_level: int = data.get("threat_level", 1)  # 威胁等级 1-5，逐弧递增
        self.duration_days: int = data.get("duration_days", 30)
        self.start_date: str = data.get("start_date", datetime.now().strftime("%Y-%m-%d"))
        self.current_stage_index: int = data.get("current_stage_index", 0)
        self.stages: List[ArcStage] = [ArcStage(s) for s in data.get("stages", [])]
        self.unresolved_threads: List[str] = data.get("unresolved_threads", [])  # 未解决的伏笔
        self.consequences: str = data.get("consequences", "")  # 主线完成后的后果描述
        self.completed: bool = data.get("completed", False)

    @property
    def current_stage(self) -> Optional[ArcStage]:
        if 0 <= self.current_stage_index < len(self.stages):
            return self.stages[self.current_stage_index]
        return None

    @property
    def days_elapsed(self) -> int:
        try:
            start = datetime.strptime(self.start_date, "%Y-%m-%d")
            return (datetime.now() - start).days
        except Exception:
            return 0

    @property
    def stages_completed(self) -> int:
        return sum(1 for s in self.stages if s.status == "completed")

    @property
    def total_stages(self) -> int:
        return len(self.stages)

    @property
    def progress_percent(self) -> int:
        if not self.stages:
            return 0
        return int(self.stages_completed / self.total_stages * 100)

    def to_dict(self) -> dict:
        return {
            "arc_id": self.arc_id,
            "title": self.title,
            "description": self.description,
            "main_goal": self.main_goal,
            "antagonist": self.antagonist,
            "antagonist_motivation": self.antagonist_motivation,
            "threat_level": self.threat_level,
            "duration_days": self.duration_days,
            "start_date": self.start_date,
            "current_stage_index": self.current_stage_index,
            "stages": [s.to_dict() for s in self.stages],
            "unresolved_threads": self.unresolved_threads,
            "consequences": self.consequences,
            "completed": self.completed,
        }


# ── 持久化 ────────────────────────────────────────────

ARC_FILE = DATA_DIR / "life_arc.json"
ARC_HISTORY_FILE = DATA_DIR / "life_arc_history.json"


def load_life_arc() -> Optional[LifeArc]:
    """加载当前主线"""
    if ARC_FILE.exists():
        try:
            with open(ARC_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if data and not data.get("completed", False):
                return LifeArc(data)
        except Exception:
            pass
    return None


def save_life_arc(arc: LifeArc):
    """保存当前主线"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(ARC_FILE, "w", encoding="utf-8") as f:
        json.dump(arc.to_dict(), f, ensure_ascii=False, indent=2)


def archive_life_arc(arc: LifeArc):
    """归档已完成的主线"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    history = []
    if ARC_HISTORY_FILE.exists():
        try:
            with open(ARC_HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except Exception:
            pass
    history.append(arc.to_dict())
    # 只保留最近 10 条
    history = history[-10:]
    with open(ARC_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


# ── 推进逻辑 ────────────────────────────────────────────

def advance_arc(arc: LifeArc) -> bool:
    """
    推进主线阶段。
    根据当前阶段持续天数和已过天数判断是否该推进到下一阶段。
    返回 True 表示有推进，False 表示无变化。
    """
    if arc.completed:
        return False

    stage = arc.current_stage
    if not stage:
        arc.completed = True
        save_life_arc(arc)
        return True

    # 计算当前阶段已过天数（相对于主线开始日期）
    # 每个阶段的起始天 = 前面所有阶段的 duration_days 之和
    stage_start_day = sum(s.duration_days for s in arc.stages[:arc.current_stage_index])
    days_in_stage = arc.days_elapsed - stage_start_day

    if days_in_stage >= stage.duration_days:
        # 当前阶段完成
        stage.status = "completed"

        # 推进到下一阶段
        if arc.current_stage_index + 1 < len(arc.stages):
            arc.current_stage_index += 1
            arc.current_stage.status = "active"
            save_life_arc(arc)
            return True
        else:
            # 所有阶段完成，主线结束
            arc.completed = True
            save_life_arc(arc)
            return True

    return False


def get_stage_hint(arc: LifeArc) -> str:
    """获取当前阶段的提示文本，用于注入到 day_plan 的 prompt 中"""
    stage = arc.current_stage
    if not stage:
        return ""

    elapsed_in_stage = 0
    stage_start_day = sum(s.duration_days for s in arc.stages[:arc.current_stage_index])
    elapsed_in_stage = max(0, arc.days_elapsed - stage_start_day)
    remaining = max(0, stage.duration_days - elapsed_in_stage)

    # 阶段类型→节奏引导
    pacing_map = {
        "travel": "本阶段以赶路为主，节奏偏慢。大部分时间在旅途上，可以安排沿途见闻、露营、偶遇等。不需要每天都有大事发生",
        "preparation": "本阶段以准备为主，节奏中等。安排收集情报、采购装备、修炼提升等活动，为后续做铺垫",
        "exploration": "本阶段以探索为主，节奏中等偏快。安排调查、发现线索、解开谜题等，逐步揭示信息",
        "social": "本阶段以社交为主，节奏偏慢。安排与NPC交流、建立关系、参与当地活动等，注重角色互动",
        "conflict": "本阶段以冲突为主，节奏偏快。安排对抗、危机、战斗等紧张事件，但也要有喘息的空间",
        "climax": "本阶段是主线高潮，节奏最快。安排关键决战、重大抉择、转折等，是整个主线最紧张的部分",
        "resolution": "本阶段是收尾，节奏偏慢。安排处理后果、休整、总结、为未来埋下种子等",
    }
    pacing = pacing_map.get(stage.stage_type, "活动应围绕当前阶段目标展开，体现推进感")

    hints = []
    hints.append(f"【主线】{arc.title}")
    if arc.description:
        hints.append(f"主线目标：{arc.description}")
    if arc.antagonist:
        hints.append(f"对抗力量：{arc.antagonist}")
        if arc.antagonist_motivation:
            hints.append(f"对方动机：{arc.antagonist_motivation}")
        hints.append(f"威胁等级：{arc.threat_level}/5")
    hints.append(f"【当前阶段】第{arc.current_stage_index + 1}/{arc.total_stages}阶段：{stage.name}（{stage.stage_type}）")
    if stage.goal:
        hints.append(f"阶段目标：{stage.goal}")
    if stage.description:
        hints.append(f"阶段描述：{stage.description}")
    if stage.sub_goals:
        hints.append(f"子目标（今天可以推进其中1-2个）：")
        for i, sg in enumerate(stage.sub_goals, 1):
            hints.append(f"  {i}. {sg}")
    if stage.key_events:
        hints.append(f"可能发生的事：{'、'.join(stage.key_events[:5])}")
    hints.append(f"本阶段已过{elapsed_in_stage}天，还剩约{remaining}天")
    hints.append(f"节奏指导：{pacing}")

    return "\n".join(hints)
