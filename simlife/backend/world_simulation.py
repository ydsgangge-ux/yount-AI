"""
世界模拟引擎 — 自治推进 + 可测量因果结算

设计哲学：把"世界的真相"从 LLM 手里拿回给一个**确定性、可结算**的状态模型。

- 世界的真相只有一个来源：`state["world_sim"]`（冲突弧 + 承诺待办 + 既定事实 + 影响账本）。
- LLM 只是叙事渲染层：每次生成剧情前注入《世界状态·不可更改》约束，它只能照此翻译，不能编造。
- 世界自转：冲突弧（world arcs）按 tick_rate 每天自动演化，不依赖玩家存在。
- 玩家 / AI 行动：只通过 apply_influence 注入影响力，改变冲突弧的斜率与走向，并记入因果账本。
- NPC 承诺：commit_npc 登记 + 到期日，自转时自动推进并执行，NPC 离开场景后不再变卦。

所有改动只落在 state["world_sim"]，不影响现有任何字段。
"""
from typing import Dict, List, Optional


class WorldSimulation:
    """世界模拟引擎。纯数据 + 确定性规则，不调用 LLM。"""

    # ── 每种世界类型的"默认主冲突弧"（世界自己在转的那几根弦）──
    # tick_rate: 每天（每步）数值变化；value 范围 0~100
    # gates: 数值跨过 at 时触发一次"既定事实"，供叙事必须遵守
    DEFAULT_ARCS = {
        "fantasy": [
            {
                "arc_id": "world_darkness",
                "label": "封印沉眠的黑暗",
                "value": 100,              # 100=稳固封印，0=大敌苏醒
                "tick_rate": -2,           # 每天松动 2 点，即便无人干预也在恶化
                "gates": [
                    {"at": 80, "title": "封印初裂", "fact": "远古封印出现第一道裂痕，黑暗中隐隐有声。"},
                    {"at": 50, "title": "暗潮涌动", "fact": "封印过半松动，附近邪祟开始躁动。"},
                    {"at": 20, "title": "大敌将醒", "fact": "封印濒临失效，古老的存在即将苏醒。"},
                ],
            },
            {
                "arc_id": "faction_tension",
                "label": "多方势力暗战",
                "value": 30,
                "tick_rate": 1,
                "gates": [
                    {"at": 60, "title": "对峙升级", "fact": "各势力摩擦升级，边境开始出现冲突。"},
                ],
            },
        ],
        "apocalypse": [
            {
                "arc_id": "world_threat",
                "label": "末日的威胁",
                "value": 100,
                "tick_rate": -1,
                "gates": [
                    {"at": 70, "title": "物资枯竭", "fact": "避难所储备告急，周边变得愈发危险。"},
                    {"at": 40, "title": "尸潮压境", "fact": "外围尸潮逼近，防线吃紧。"},
                ],
            },
        ],
        # 通用兜底
        "default": [
            {
                "arc_id": "world_tide",
                "label": "世界的暗流",
                "value": 100,
                "tick_rate": -1,
                "gates": [
                    {"at": 50, "title": "暗流涌动", "fact": "某种深藏的威胁正在缓慢逼近。"},
                ],
            },
        ],
    }

    # ─────────────────────────────────────────────
    # 状态初始化
    # ─────────────────────────────────────────────
    @classmethod
    def ensure_state(cls, state: Dict) -> Dict:
        """确保 state 中存在 world_sim 结构；为当前世界类型播种默认冲突弧（仅首次）。"""
        if "world_sim" not in state or not isinstance(state.get("world_sim"), dict):
            state["world_sim"] = {}
        ws = state["world_sim"]
        ws.setdefault("arcs", {})
        ws.setdefault("commitments", [])
        ws.setdefault("facts", [])           # 不可更改的既定事实
        ws.setdefault("influence_log", [])   # 因果账本
        # 记录上一次结算的世界天数，供"按天自转"
        ws.setdefault("last_day", int(state.get("play_time_days", 1) or 1))
        # 首次播种默认冲突弧（不覆盖已有）
        if not ws["arcs"]:
            cls._seed_default_arcs(state)
        return ws

    @classmethod
    def _seed_default_arcs(cls, state: Dict) -> None:
        """按世界类型播种默认冲突弧。"""
        ws = state["world_sim"]
        world_type = str(state.get("world_type", "fantasy") or "fantasy").lower()
        template = cls.DEFAULT_ARCS.get(world_type, cls.DEFAULT_ARCS["default"])
        for arc_tpl in template:
            arc = {
                "arc_id": arc_tpl["arc_id"],
                "label": arc_tpl["label"],
                "value": float(arc_tpl["value"]),
                "tick_rate": arc_tpl["tick_rate"],
                "gates": [dict(g) for g in arc_tpl.get("gates", [])],
            }
            # 将 gates 统一初始化 triggered=False，避免结构不一致
            for g in arc["gates"]:
                g.setdefault("triggered", False)
            ws["arcs"][arc["arc_id"]] = arc

    # ─────────────────────────────────────────────
    # 自治推进（按天）
    # ─────────────────────────────────────────────
    @classmethod
    def tick_by_day(cls, state: Dict) -> List[Dict]:
        """世界自转：按 play_time_days 与上次结算的天数差自动推进。
        返回本次推进中新触发的事件（跨过阈值的门 / 完成的承诺），供前端提示。"""
        cls.ensure_state(state)
        ws = state["world_sim"]
        cur_day = int(state.get("play_time_days", 1) or 1)
        last_day = int(ws.get("last_day", cur_day))
        steps = max(0, cur_day - last_day)
        events = []
        if steps > 0:
            cls._advance(state, steps, events)
            ws["last_day"] = cur_day
        return events

    @classmethod
    def _advance(cls, state: Dict, steps: int, events: List[Dict]) -> None:
        """推进 steps 步冲突弧演化 + 承诺待办到期检查（纯数据，无副作用于其他系统）。"""
        ws = state["world_sim"]
        cur_day = int(state.get("play_time_days", 1) or 1)

        # 1) 冲突弧自转：数值变化、跨门触发既定事实
        for arc in ws["arcs"].values():
            arc["value"] = max(0.0, min(100.0, float(arc.get("value", 100)) + float(arc.get("tick_rate", 0)) * steps))
            for gate in arc.get("gates", []):
                if gate.get("triggered"):
                    continue
                # 触发方向：tick_rate>0 表示向上，<0 表示向下
                pos = arc.get("tick_rate", 0) >= 0
                if (pos and arc["value"] >= float(gate["at"])) or (not pos and arc["value"] <= float(gate["at"])):
                    gate["triggered"] = True
                    fact = f"【{arc.get('label', '世界暗流')} · {gate['title']}】{gate['fact']}"
                    if fact not in ws["facts"]:
                        ws["facts"].append(fact)
                    events.append({"type": "gate", "arc": arc.get("label"), "title": gate["title"], "fact": gate["fact"]})

        # 2) 承诺待办到期检查：到期即视为执行（世界照约办事）
        for commit in ws["commitments"]:
            if commit.get("done"):
                continue
            if cur_day >= int(commit.get("deadline_day", cur_day + 999)):
                commit["done"] = True
                commit["done_day"] = cur_day
                fact = f"【承诺兑现】{commit.get('npc', '？')} 兑现了承诺：{commit.get('task', '')}"
                if fact not in ws["facts"]:
                    ws["facts"].append(fact)
                events.append({"type": "commitment_done", "npc": commit.get("npc"), "task": commit.get("task")})

    # ─────────────────────────────────────────────
    # 玩家 / AI 影响力注入（可测量因果）
    # ─────────────────────────────────────────────
    @classmethod
    def apply_influence(cls, state: Dict, effects: List[Dict], by: str = "行动") -> List[str]:
        """玩家/AI 的行动按 effects 结算为对冲突弧的影响。
        effects 形如 [{"arc": "world_darkness", "delta": -15, "note": "击杀渊吼破除第一层封印"}]
        返回被计入影响的弧的说明列表。"""
        cls.ensure_state(state)
        ws = state["world_sim"]
        cur_day = int(state.get("play_time_days", 1) or 1)
        applied = []
        for eff in effects or []:
            if not isinstance(eff, dict):
                continue
            arc = ws["arcs"].get(eff.get("arc", ""))
            if not arc:
                continue
            delta = float(eff.get("delta", 0))
            note = str(eff.get("note", "") or "").strip()
            arc["value"] = max(0.0, min(100.0, float(arc.get("value", 100)) + delta))
            # 记入因果账本
            ws["influence_log"].append({
                "day": cur_day,
                "by": by,
                "arc": arc.get("label"),
                "delta": delta,
                "note": note,
                "ts": _now_ts(),
            })
            applied.append(f"{arc.get('label')}{delta:+g}（{note or by}）")
        # 影响力注入后同样检查跨门（可能一次行动直接越过阈值）
        for arc in ws["arcs"].values():
            for gate in arc.get("gates", []):
                if gate.get("triggered"):
                    continue
                pos = arc.get("tick_rate", 0) >= 0
                if (pos and arc["value"] >= float(gate["at"])) or (not pos and arc["value"] <= float(gate["at"])):
                    gate["triggered"] = True
                    fact = f"【{arc.get('label', '世界暗流')} · {gate['title']}】{gate['fact']}"
                    if fact not in ws["facts"]:
                        ws["facts"].append(fact)
        return applied

    # ─────────────────────────────────────────────
    # NPC 承诺待办
    # ─────────────────────────────────────────────
    @classmethod
    def commit_npc(cls, state: Dict, npc: str, task: str, deadline_day: int = None,
                   note: str = "") -> bool:
        """登记一个 NPC 承诺。deadline_day 缺省为"当前天数 + 3"（自动执行的倒计时）。
        世界自转到期后该承诺自动标记为已兑现，叙事层因此绝不能再让 NPC 变卦。"""
        cls.ensure_state(state)
        if not npc or not task:
            return False
        ws = state["world_sim"]
        cur_day = int(state.get("play_time_days", 1) or 1)
        deadline = deadline_day if deadline_day else cur_day + 3
        commit = {
            "npc": npc,
            "task": task,
            "note": note,
            "deadline_day": max(int(deadline), cur_day),
            "done": False,
            "created_day": cur_day,
        }
        # 去重：同 NPC 同任务不重复登记
        for c in ws["commitments"]:
            if c.get("npc") == npc and c.get("task") == task and not c.get("done"):
                return False
        ws["commitments"].append(commit)
        return True

    @classmethod
    def get_pending_commitments(cls, state: Dict) -> List[Dict]:
        """获取尚未兑现的承诺（供叙事层引用，塑造"NPC 正在办这事"的连续性）。"""
        cls.ensure_state(state)
        cur_day = int(state.get("play_time_days", 1) or 1)
        return [
            c for c in state["world_sim"]["commitments"]
            if not c.get("done") and cur_day < int(c.get("deadline_day", cur_day + 999))
        ]

    # ─────────────────────────────────────────────
    # 叙事注入：《世界状态·不可更改》
    # ─────────────────────────────────────────────
    @classmethod
    def build_world_facts_blob(cls, state: Dict) -> str:
        """渲染一段给叙事 LLM 的强制约束文本：冲突弧当前值 + 既定事实 + 进行中的承诺。
        叙事必须遵守这些状态，绝不能因其"想要"而改变世界真相。"""
        cls.ensure_state(state)
        ws = state["world_sim"]
        cur_day = int(state.get("play_time_days", 1) or 1)
        lines = []

        # 冲突弧（当前"主线程度"）
        arcs = ws.get("arcs", {})
        if arcs:
            lines.append("【世界主冲突弧·当前状态】（角色能感知到的变化幅度，数值是内因不是角色所见）")
            for arc in arcs.values():
                v = float(arc.get("value", 100))
                level = "尚稳" if v > 66 else ("正在恶化" if v > 33 else "已濒临失控")
                lines.append(f" · {arc.get('label', '世界暗流')}：{level}（{v:.0f}/100）")

        # 进行中的 NPC 承诺
        pending = cls.get_pending_commitments(state)
        if pending:
            lines.append("【正在进行中的承诺·必须遵守】这些 NPC 正在按约定办事，叙事中不可让它们无故变卦或消失")
            for c in pending:
                _d = max(0, int(c.get("deadline_day", cur_day)) - cur_day)
                lines.append(f" · {c.get('npc')} 答应了『{c.get('task')}』，还剩约 {_d} 天")

        # 不可更改的既定事实
        if ws.get("facts"):
            lines.append("【世界既定事实·不可更改】以下已成定局，叙事绝不能推翻（例如让已被击杀的敌人复活、让已兑现的承诺消失）")
            for f in ws["facts"][-20:]:
                lines.append(f" · {f}")

        return "\n".join(lines)

    # ─────────────────────────────────────────────
    # 汇总（调试/展示）
    # ─────────────────────────────────────────────
    @classmethod
    def get_summary(cls, state: Dict) -> Dict:
        """返回世界状态摘要，供测试与展示。"""
        cls.ensure_state(state)
        ws = state["world_sim"]
        return {
            "arcs": {
                k: {"label": v.get("label"), "value": round(float(v.get("value", 100)), 1)}
                for k, v in ws.get("arcs", {}).items()
            },
            "pending_commitments": [{"npc": c.get("npc"), "task": c.get("task"),
                                     "deadline_day": c.get("deadline_day")}
                                    for c in cls.get_pending_commitments(state)],
            "facts": list(ws.get("facts", [])[-20:]),
            "influence_count": len(ws.get("influence_log", [])),
        }


def _now_ts() -> str:
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S")