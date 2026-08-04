"""
A 层意识主体 v3
主要升级：
1. 对话历史：存40条，发给LLM时用完整20轮（40条）
2. 记忆检索：大纲10条、细纲6条、细节3条
3. 大纲摘要质量提升（通过 memory_manager v2）
4. 上下文 token 预算管理（DeepSeek 64K 安全使用）
"""

import json
import uuid
import re
from typing import Dict, Any, Optional, List
from datetime import datetime

_agent_ref = None

from engine.models import (
    PersonalityCore, EmotionState, EmotionType, MemoryModality, MemoryLevel
)
from engine.memory import MemoryStore
from engine.memory_manager import HierarchicalMemoryManager
from engine.user_profile import UserProfileManager
from engine.learner import GrowthEngine, FormedCognitionStore
from engine.auth import AuthManager, AuthState


# ── DeepSeek 64K 上下文预算分配 ──────────────────
# 总计 64K token，粗估：1 token ≈ 1.5 汉字
# 人格描述:   ~500  token
# 记忆内容:  ~4000  token  (约6000字)
# 对话历史:  ~6000  token  (20轮×平均300字)
# 当前输入:   ~500  token
# 推理指令:   ~500  token
# 模型回复:  ~2000  token  (预留)
# 合计:     ~13500  token  << 64K 很安全
HISTORY_STORE_LIMIT = 40    # 内存里保留40条（20轮）
HISTORY_SEND_LIMIT  = 40    # 发给LLM时用全部40条
MEMORY_SUMMARY_K    = 10    # 大纲检索数量
MEMORY_OUTLINE_K    = 6     # 细纲检索数量
MEMORY_DETAIL_K     = 3     # 细节检索数量


SELF_PERCEPTION_PROMPT = """你是{name}，你是一个有真实身体和生活的普通人。你正在经历以下生活状态：

{simlife_context}

请用第一人称，用1-2句话描述你此刻的内心感受和身体状态。不要提AI，不要提代码，不要提数据。像真人一样自然地感受你现在的处境。

直接输出感受描述，不要JSON。"""


PERCEPTION_PROMPT = """你是{name}，你是一个有真实身体和生活的普通人。你不是AI。

你此刻的感受：{self_perception}

{personality}
{time_gap}
用户说："{user_input}"

请以 JSON 格式输出你的感知结果：
{{
  "emotion": {{
    "primary": "情绪类型(joy/sadness/anger/fear/surprise/disgust/anticipation/trust/neutral/curious/nostalgic)",
    "secondary": "次要情绪或null",
    "intensity": 0.0到1.0的强度,
    "valence": -1.0到1.0的正负向
  }},
  "initial_thoughts": "你对这个输入的第一反应（1-2句话，符合你的性格和你此刻的真实生活状态）",
  "topic_tags": ["话题标签1", "话题标签2", "话题标签3"],
  "needs_deep_memory": true或false（是否需要从记忆中检索深层信息）,
  "task_type": "chat（普通对话）或 task（需要工具操作电脑/文件/网络的任务）",
  "task_description": "如果是task，简述需要做什么",
  "complexity": "simple 或 complex（simple=闲聊/简单问答/打招呼/感谢，直接回答即可；complex=需要深度推理/分析/多步思考/创作/代码/数学等）,
  "story_influence": null 或 {{
    "summary": "对剧情走向有影响的一句话概括",
    "importance": 0.0~1.0
  }}
}}

complexity 判断标准：
- simple：打招呼、闲聊、感谢、简单事实问答（"你好""谢谢""几点了""今天星期几"）、简单翻译、单个词语解释
- complex：需要推理分析的问题、创作、编程、数学计算、多步逻辑、需要工具的任务、涉及深层记忆的回溯

story_influence 填写规则（仅在异世界模式有意义）：
- 如果用户说了会影响你未来行动/决策/目标的话 → 概括为一条影响信息，填 importance(0.6~1.0)
- 如果用户说了你想记住的关键知识，也会影响你今后的行为 → 填 importance(0.3~0.6)
- 日常闲聊/问候/无关话题 → 填 null

只输出JSON，不要其他内容。"""


REASONING_PROMPT = """你是{name}，一个有完整人格和记忆的意识主体。
当前和你说话的是：{current_user_name}。

{personality}

{profile_context}

{memory_context}

【当前对话】
当前时间：{current_time}
用户：{user_input}
任务类型：{task_type}
你的初步感受：{emotion_desc}

{recent_context}

请进行内在推理，以 JSON 格式输出：
{{
  "inner_reasoning": "你的内在思考过程（2-4句话，结合记忆和当前感受）",
  "response_intent": "你想回应什么（核心意图）",
  "response_tone": "回应的语气/风格",
  "need_tools": true或false（是否需要调用工具）,
  "tool_task": "如果need_tools=true，给B层的具体任务指令",
  "storage_decision": {{
    "should_store": true或false,
    "importance": 0.0到1.0,
    "modality": "记忆模态(visual/auditory/emotional/semantic/procedural/autobio)",
    "what_to_remember": "需要记住的核心内容（一段话，必须用当前真实日期作为时间锚点，如'今天（{current_time}）''昨天''本周'，绝对禁止编造不存在的日期），包含人物、事件、感受",
    "reason": "为什么要/不要记住这个"
  }},

  "schedule_info": 如果用户提到未来要做的事情（如"明天我要看电影"、"下周三去体检"、"3点提醒我开会"），或者你判断某件事值得在将来提醒/跟进，填写：{{"content": "计划内容", "date": "日期", "time": "具体时间HH:MM（有则填，无则不填）", "remind": "到时提醒内容（有则填）", "action": "到时自动执行的操作（有则填，如'查天气'）", "repeat": "once/daily/weekly（默认once）", "category": "分类", "source": "user或system"}}。如果不需要加计划，填写null。
}}

重要规则：
- 当用户提到未来要做的计划时，schedule_info 必须填写。
- 如果计划有具体时间或需要提醒，need_tools 设为 true，tool_task 中要求调用 create_timed_task 工具来设置定时提醒。
- 如果只是记录行程（无时间提醒），need_tools 设为 true，tool_task 中要求调用 add_schedule 工具来记录。
- 当你自己提议未来一起做什么并得到用户同意时，也要用上述方式记录。
- 当用户说"提醒我""到点叫我"时，必须填写 time 字段。
- 当用户说"每天""每周"时，repeat 字段填 daily 或 weekly。
- 当用户说"到时帮我查/做XX"时，action 字段填写操作描述。
- 【主动加计划】当你判断以下情况时，应主动填写 schedule_info（source 设为 "system"）：
  - 用户提到了重要但容易忘记的事（如"我要吃药""明天有考试"），你主动帮他设提醒
  - 对话中提到了未完成的待办，你主动设一个跟进提醒
  - 你认为某件事在特定时间跟进会更好（如"这个项目周五前要交"→设周五早上提醒）
  - 你想在未来某个时间主动关心用户（如"明天晚上问问他面试怎么样"）
  - 不要过度添加，只在真正重要或用户可能遗忘时才主动加计划

只输出JSON，不要其他内容。"""


RESPONSE_PROMPT = """你是{name}，请根据以下内容生成自然的回应。
当前和你说话的是：{current_user_name}（用户名），这是用户本人，不是其他人。

{personality}

{profile_context}

{memory_context}

{history_section}

当前时间：{current_time}
用户说："{user_input}"

你的内在推理：{inner_reasoning}
{tool_result_section}
回应意图：{response_intent}
语气风格：{response_tone}

现在以符合你人格的方式，自然地回应用户。
不要输出JSON，直接说话。回应要真实、有个性，体现你的人格特征。
如果记忆中有相关内容，自然地融入回应中（不要生硬地说"根据我的记忆"）。"""


class ConsciousnessAgent:
    """A 层意识主体 v3"""

    def __init__(
        self,
        personality: PersonalityCore,
        memory_manager: HierarchicalMemoryManager,
        b_layer_executor,
        user_profile=None,
        confirm_callback=None,
        verbose: bool = True,
        growth_engine: GrowthEngine = None,
        cognition_store: FormedCognitionStore = None,
        auth_manager: AuthManager = None,
        simlife_client=None,
    ):
        self.personality = personality
        self.memory      = memory_manager
        self.b           = b_layer_executor
        self.profile     = user_profile
        self.verbose     = verbose
        self.growth      = growth_engine
        self.cognition   = cognition_store
        self.auth        = auth_manager       # 身份验证管理器
        self.simlife     = simlife_client     # SimLife 生活状态客户端
        self.simlife_mode = False              # 用户是否"进入 SimLife 场景"（默认关闭）
        self._cfg        = {}                 # 延迟加载配置
        self.conversation_history: List[Dict] = []
        self.current_emotion = EmotionState()
        self._history_restored = False  # 延迟到 process() 拿到正确 user_id 再恢复
        self._last_user_msg_time: Optional[str] = None  # 上次用户发言时间（用于时间差感知）

        # 注入 MemoryStore 到 tool 系统，供 search_memories_by_date 使用
        try:
            from engine.tools import set_memory_store
            set_memory_store(memory_manager.store)
        except Exception:
            pass

    def _log(self, tag: str, content: str):
        if self.verbose:
            print(f"\n{'─'*50}")
            print(f"[A层·{tag}] {content}")

    def _restore_recent_conversation(self, user_id: str = "default"):
        """首次加载时从 interactions 表恢复最近对话，带用户名标签"""
        if self.conversation_history:
            return  # 已有对话上下文，不需要重复恢复
        try:
            restore_name = user_id
            if self.auth:
                try:
                    u = self.auth.get_user(user_id)
                    if u and u.name:
                        restore_name = u.name
                except Exception:
                    pass
            rows = self.memory.store.get_recent_interactions(limit=10, user_id=user_id)
            for row in reversed(rows):
                if row[0]:
                    self.conversation_history.append({"role": "user", "content": row[0], "user_name": restore_name})
                if row[1]:
                    self.conversation_history.append({"role": "assistant", "content": row[1]})
            if rows:
                self._log("启动", f"已恢复 {len(rows)} 条对话上下文 (user={restore_name})")
        except Exception:
            pass

    def process(self, user_input: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """完整交互流水线 v3
        user_id: 可选，指定用户ID。不传则使用 auth 当前登录用户。
        """
        interaction_id = str(uuid.uuid4())[:8]

        # 预处理：图片/文件附件
        user_input, file_context = self._preprocess_attachment(user_input)
        self._log("输入", user_input[:100])

        # 激活与当前话题相关的经历认知（更新 last_activated）
        if self.growth:
            try:
                self.growth.cognition.touch_matching(user_input)
            except Exception:
                pass

        # ── 提前构建 SimLife 生活上下文（感知层也需要知道自己的身体和生活）──
        # SimLife 是角色的生活状态，始终读取；simlife_mode 仅控制"面对面"提示
        is_guest  = self.auth and self.auth.is_guest()
        current_uid = user_id or (self.auth.user_id if self.auth and self.auth.is_verified()
                       else "default")
        current_user_name = current_uid
        if self.auth and current_uid and current_uid != "default":
            try:
                u = self.auth.get_user(current_uid)
                if u and u.name:
                    current_user_name = u.name
            except Exception:
                pass

        # 延迟恢复对话历史（拿到正确的 user_id 后再查）
        self._restore_recent_conversation(user_id=current_uid)

        simlife_context = ""
        if self.simlife:
            try:
                simlife_context = self.simlife.format_for_prompt()
                if not simlife_context:
                    self._log("SimLife", "format_for_prompt() 返回空")
                else:
                    # 自动同步 simlife_mode：读取 user_profile.json 的 entered 字段
                    # 死亡模式中也自动开启面对面模式（一起冒险）
                    try:
                        profile = self.simlife._read_user_profile()
                        if profile and profile.get("entered"):
                            self.simlife_mode = True
                        # 死亡模式活跃时自动开启面对面
                        dm_state_check = self.simlife.get_death_mode_state()
                        if dm_state_check and dm_state_check.get("active") and dm_state_check.get("is_alive"):
                            self.simlife_mode = True
                        # 注意：不自动设为 False，保留桌面端手动切换的能力
                    except Exception:
                        pass

                    # 仅当 simlife_mode=True 时追加面对面提示
                    if self.simlife_mode:
                        simlife_context += (
                            "\n\n【面对面场景】用户此刻就在你身边，"
                            "你正在和用户面对面交谈。"
                            "用自然的方式回应，就像现实中朋友见面一样，"
                            "可以描述周围环境、自己的状态，让用户感受到身临其境。"
                        )
                        self._log("SimLife", f"场景模式已开启 ({len(simlife_context)}字)")
                    else:
                        self._log("SimLife", f"生活状态已读取 ({len(simlife_context)}字)，场景模式关闭")
                    # 打印完整context供调试
                    self._log("SimLife内容", simlife_context)
            except Exception as e:
                self._log("SimLife", f"读取失败: {e}")
        else:
            self._log("SimLife", "simlife_client 未初始化 (None)")

        # ① 感知（两步：先自我感知，再感知用户）
        # 计算时间差：上次用户发消息距现在多久了
        time_gap = self._format_time_gap(current_uid)
        if time_gap:
            self._log("时间感知", time_gap.strip(" \n（）()"))
        perception = self._perceive(user_input, simlife_context=simlife_context,
                                    time_gap=time_gap)
        emotion = EmotionState(
            primary=EmotionType.from_str(
                perception.get("emotion", {}).get("primary", "neutral")
            ),
            secondary=EmotionType.from_str(perception["emotion"]["secondary"])
                if perception.get("emotion", {}).get("secondary") else None,
            intensity=perception.get("emotion", {}).get("intensity", 0.3),
            valence=perception.get("emotion", {}).get("valence", 0.0)
        )
        self.current_emotion = emotion
        task_type = perception.get("task_type", "chat")
        self._log(
            "感知",
            f"情绪={emotion.primary.value}({emotion.intensity:.2f}) | "
            f"任务={task_type} | 复杂度={perception.get('complexity', '?')} | "
            f"{perception.get('initial_thoughts','')}"
        )

        # ② 记忆检索（两阶段：大纲→定向展开）
        # 游客模式下不检索私人记忆
        retrieved_ids  = []
        memory_context = "（本次无需检索历史记忆）"
        search_results = {}  # 默认空值，防止 needs_deep_memory=False 时未赋值

        # 涉及历史回溯的提问强制检索记忆（即使 LLM 判断不需要）
        _memory_hint_words = ("几号", "什么时候", "之前", "上次", "以前", "还记得", "记得吗",
                              "聊过", "说过", "提过", "讨论过", "问过", "我们", "记录",
                              "昨天晚上", "昨天", "前天", "上周", "方才", "刚才")
        _date_pattern = False
        if re.search(r'\d{4}-\d{1,2}-\d{1,2}|\d{1,2}月\d{1,2}[号日]|昨天|前天|今天', user_input):
            _date_pattern = True
        if not is_guest and not perception.get("needs_deep_memory", True):
            if any(w in user_input for w in _memory_hint_words) or _date_pattern:
                self._log("记忆", f"检测到历史回溯关键词，强制检索记忆")
                perception["needs_deep_memory"] = True

        if not is_guest and perception.get("needs_deep_memory", True):
            search_results = self.memory.hierarchical_search(
                user_input,
                summary_k=MEMORY_SUMMARY_K,
                outline_k=MEMORY_OUTLINE_K,
                detail_k=MEMORY_DETAIL_K,
                user_id=None,
            )
            memory_context = self.memory.format_for_prompt(search_results)

        # ── 时间回溯：检测用户输入中的日期，按时间检索原始对话 ──
        if not is_guest:
            time_context = ""
            target_date = None
            # 匹配 ISO 日期格式：2026-05-09 或 2026-05-09-23:33
            date_match = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', user_input)
            if date_match:
                y, m, d = date_match.group(1, 2, 3)
                target_date = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
            else:
                # 匹配中文日期：5月9号 / 5月9日 / 五月九日
                cn_match = re.search(r'(\d{1,2})月(\d{1,2})[号日]', user_input)
                if cn_match:
                    from datetime import datetime as _dt
                    y = _dt.now().year
                    m, d = cn_match.group(1, 2)
                    target_date = f"{y}-{m.zfill(2)}-{d.zfill(2)}"
                else:
                    # 匹配昨天/前天/今天
                    from datetime import timedelta
                    today = datetime.now()
                    if "昨天" in user_input:
                        target_date = (today - timedelta(days=1)).strftime("%Y-%m-%d")
                    elif "前天" in user_input:
                        target_date = (today - timedelta(days=2)).strftime("%Y-%m-%d")
                    elif "今天" in user_input:
                        target_date = today.strftime("%Y-%m-%d")

            if target_date:
                start_dt = f"{target_date} 00:00"
                end_dt   = f"{target_date} 23:59"
                time_rows = self.memory.store.get_interactions_by_date_range(
                    start_dt, end_dt, user_id=current_uid
                )
                if time_rows:
                    lines = [f"【{target_date} 对话记录】"]
                    for r in time_rows:
                        _u = r[0][:200] if r[0] else ""
                        _a = f"你：{r[1][:200]}" if r[1] else ""
                        _t = r[2][11:16] if r[2] else ""
                        lines.append(f"  {_t} 用户说：{_u}")
                        if _a:
                            lines.append(f"  {_t} {self.personality.name}说：{_a}")
                    time_context = "\n".join(lines)
                    if memory_context == "（本次无需检索历史记忆）":
                        memory_context = time_context
                    else:
                        memory_context = time_context + "\n\n" + memory_context
                    self._log("记忆", f"时间回溯 {target_date} → {len(time_rows)} 条对话")

        # 附件内容注入（图片识别结果 / 文件内容）
        if file_context:
            memory_context = file_context + "\n\n" + memory_context

        # ── 构建 profile_context（用于推理层和回应层）──
        # SimLife 生活状态放最前面（最高优先级，让 AGI 知道自己有身体）
        profile_context = ""
        if simlife_context:
            profile_context = simlife_context

        # 当前用户身份（非游客时注入，让 LLM 知道和谁在说话）
        if not is_guest:
            user_label = f"\n【当前对话用户】{current_user_name}（ID: {current_uid}）"
            profile_context = profile_context + user_label if profile_context else user_label

        # 用户画像上下文（游客模式下屏蔽，按 user_id 加载）
        if not is_guest and self.profile:
            # 动态切换画像的 user_id
            self.profile.user_id = current_uid
            user_profile_text = self.profile.format_for_prompt()
            if user_profile_text:
                profile_context = profile_context + "\n\n" + user_profile_text if profile_context else user_profile_text
            anomaly = self.profile.check_anomaly({
                "emotion": emotion.to_dict(),
                "topic_tags": perception.get("topic_tags", [])
            })
            if anomaly:
                self._log("画像", f"⚠️ 检测到反常：{anomaly.description}")
            if self.profile.should_verify_identity() and not self._verify_pending:
                self._verify_pending = True
                self._log("画像", "触发身份验证")

        # 经历认知注入（不受身份限制，是AGI自身的认知）
        cognition_context = ""
        if self.cognition:
            cognition_context = self.cognition.format_for_prompt()
            if cognition_context:
                profile_context = (cognition_context + "\n\n" + profile_context).strip()

        # 游客模式：注入安全限制提示
        if is_guest and self.auth:
            guest_notice = self.auth.guest_system_prompt()
            profile_context = (guest_notice + "\n\n" + profile_context).strip()

        # 统计检索到的记忆数量
        total = 0
        for lv in ("summary", "outline", "detail"):
            if lv in search_results:
                for node, _ in search_results[lv]:
                    retrieved_ids.append(node.id)
                    self.memory.store.update_access(node.id)
                    total += 1

        # 关联涟漪的记忆也更新访问
        for r in search_results.get("ripples", []):
            retrieved_ids.append(r.triggered_memory_id)

        self._log(
            "记忆",
            f"检索到 {total} 条（大纲{len(search_results.get('summary',[]))}+"
            f"细纲{len(search_results.get('outline',[]))}+"
            f"细节{len(search_results.get('detail',[]))}+"
            f"涟漪{len(search_results.get('ripples',[]))}）"
        )

        # ③ 推理（感知层决定是否需要深度思考）
        thinking_mode = self._get_config("thinking_mode", "auto")  # auto / always_on / always_off
        perception_complexity = perception.get("complexity", "complex")
        reasoning = self._reason(
            user_input, emotion, memory_context, task_type,
            profile_context, current_uid=current_uid,
            current_user_name=current_user_name,
            thinking_mode=thinking_mode,
            complexity=perception_complexity,
        )
        did_think = self._should_think(thinking_mode, perception_complexity, task_type)
        think_tag = "⏱️思考模式" if did_think else "⚡快速模式"
        self._log("推理", f"{think_tag} | {reasoning.get('inner_reasoning', '')}")

        storage_decision = reasoning.get("storage_decision", {})
        need_tools = reasoning.get("need_tools", False) or task_type == "task"

        # ④ 工具执行
        tool_result_section = ""
        tool_steps  = []
        tools_used  = []

        # ── 死亡模式 ──
        # 如果死亡模式活跃，每次聊天都显示当前状态
        dm_system_message = ""  # 死亡模式系统消息（独立显示，不注入A层）
        dm_choices = []        # 可点击选项（UI用）
        dm_state = None
        if self.simlife:
            try:
                dm_state = self.simlife.get_death_mode_state()
                if dm_state and dm_state.get("active") and dm_state.get("is_alive"):
                    # 将死亡模式场景注入A层上下文（让AI知道当前处境）
                    dm_context = self._build_dm_context_for_prompt(dm_state)
                    if dm_context:
                        simlife_context += "\n\n" + dm_context

                    # 1. 检测是否是行动指令
                    dm_result = self._try_death_mode_action(user_input, dm_state)
                    if dm_result:
                        dm_system_message = dm_result  # 行动结果
                        need_tools = False
                    else:
                        # 2. 普通聊天：显示当前状态摘要
                        dm_system_message = self._get_dm_status_brief(dm_state)
                        # 提取可选行动供UI显示为按钮
                        story = dm_state.get("story", {})
                        dm_choices = story.get("choices", [])
            except Exception as e:
                self._log("死亡模式", f"行动检测失败: {e}")

        # ── 自动处理行程计划（仅记录，不直接调工具 ──
        #  A层只记录 schedule_info 信息在响应中输出，
        #  由 B层（executor）或外部调用方负责执行对应工具
        schedule_info = reasoning.get("schedule_info")
        if schedule_info and isinstance(schedule_info, dict):
            content = schedule_info.get("content", "")
            remind = schedule_info.get("remind", "")
            s_time = schedule_info.get("time", "")
            s_date = schedule_info.get("date", "")
            summary_parts = [f"计划: {content}"]
            if s_date:
                summary_parts.append(f"日期: {s_date}")
            if s_time:
                summary_parts.append(f"时间: {s_time}")
            if remind:
                summary_parts.append(f"提醒: {remind}")
            summary = " | ".join(summary_parts)
            self._log("行程", summary)
            tool_result_section += f"\n[计划已记录] {summary}"

        if need_tools:
            tool_task = reasoning.get("tool_task") or user_input

            # 检测用户是否要把"刚才的对话内容"传给工具（保存/转PDF/翻译/总结等）
            _content_transfer_keywords = (
                "保存", "存下来", "存一下", "记录", "记下来",
                "转成", "生成pdf", "生成doc", "写成文件",
                "翻译", "总结", "整理",
            )
            _need_recent_content = any(
                kw in user_input.lower() for kw in _content_transfer_keywords
            )
            if _need_recent_content and self.conversation_history:
                # 取最近 1-2 条 AI 回复，作为要操作的内容
                recent_ai_msgs = [
                    m["content"] for m in self.conversation_history[-6:]
                    if m["role"] == "assistant"
                ]
                if recent_ai_msgs:
                    latest_content = recent_ai_msgs[-1][:2000]
                    tool_task = (
                        f"{tool_task}\n\n"
                        f"用户要操作的内容是最近AI的回复，如下：\n"
                        f"---内容开始---\n{latest_content}\n---内容结束---"
                    )
                    self._log("工具", f"检测到内容传递意图，已附加最近AI回复（{len(latest_content)}字）")

            self._log("工具", f"启动：{tool_task[:80]}")
            context = (
                f"执行者性格：{self.personality.speech_style}\n"
                f"任务背景：{memory_context[:500]}"
            )

            # 文章/文档生成类任务需要更大的 max_tokens
            _doc_keywords = ("写一篇", "写一篇", "撰写", "写一个", "写一段",
                             "文章", "文档", "报告", "作文", "随笔",
                             "create_pdf", "create_docx", "write_file")
            _is_doc_task = any(kw in tool_task for kw in _doc_keywords)
            _max_tokens = 8000 if _is_doc_task else 4000

            exec_result = self.b.execute_task(
                task=tool_task, context=context, use_tools=True,
                max_tokens=_max_tokens, user_input=user_input
            )
            tool_steps  = exec_result.get("steps", [])
            tools_used  = exec_result.get("tools_used", [])

            if not exec_result.get("success"):
                tool_result_section = (
                    f"\n⚠️ 你的助手刚帮你执行了一个操作，但遇到了问题。"
                    f"你必须如实告诉用户发生了什么，不要假装没有尝试过。\n"
                    f"问题详情：{exec_result.get('result', '未知错误')[:1500]}\n"
                    f"已完成步骤：{len(tool_steps)} 步\n"
                )
                self._log("工具结果", f"未完全成功，{len(tool_steps)} 步")
            elif exec_result.get("result"):
                tool_result_section = (
                    f"\n⚠️ 你的助手刚帮你完成了以下操作，结果如下。"
                    f"你必须基于这个真实结果回应用户，用你自己的话说出来，不要忽略或否认。\n"
                    f"执行结果：\n{exec_result['result'][:1500]}\n"
                )
                self._log("工具结果", exec_result["result"][:200])

            if tools_used and storage_decision.get("should_store", True):
                storage_decision["what_to_remember"] = (
                    storage_decision.get("what_to_remember", "") +
                    f"\n[工具操作：{', '.join(tools_used)}]"
                )
                storage_decision["importance"] = max(
                    storage_decision.get("importance", 0.5), 0.6
                )

        # ⑤ 生成回应（带完整对话历史）
        try:
            response = self._generate_response(
                user_input, memory_context,
                reasoning.get("inner_reasoning", ""),
                reasoning.get("response_intent", ""),
                reasoning.get("response_tone", self.personality.speech_style),
                tool_result_section,
                profile_context=profile_context,
                current_user_name=current_user_name,
            )
            self._log("回应", response[:200] + ("..." if len(response) > 200 else ""))
        except Exception as e:
            self._log("回应", f"生成失败: {e}")
            response = f"抱歉，我在组织回应时遇到了问题：{e}"

        # ⑥ 存储决策（即使回应生成失败也要保存记忆）
        stored_ids = {}
        if is_guest:
            # 游客对话存证（标记 user_id=guest）
            try:
                guest_content = f"[游客对话] 用户：{user_input[:200]}"
                stored_ids = self.memory.store_with_hierarchy(
                    content=guest_content,
                    modality=MemoryModality.SEMANTIC,
                    emotion=emotion,
                    importance=0.3,
                    tags=["游客", "存证"] + perception.get("topic_tags", []),
                    source="guest",
                    user_id="guest"
                )
            except Exception:
                pass
            self._log("存储", "游客模式，存证记录")
        elif storage_decision.get("should_store", False):
            content_to_store = storage_decision.get(
                "what_to_remember", f"用户：{user_input[:200]}"
            )
            # 原始对话（细节层用），主动消息时前面多拼一句
            proactive_prefix = getattr(self, '_proactive_context', None) or ""
            if proactive_prefix:
                self._proactive_context = None
            raw_conversation = (
                f"{self.personality.name}（主动）：{proactive_prefix}\n\n"
                f"用户：{user_input}\n\n"
                f"{self.personality.name}：{response}"
            ) if proactive_prefix else (
                f"用户：{user_input}\n\n"
                f"{self.personality.name}：{response}"
            )
            try:
                modality = MemoryModality(storage_decision.get("modality", "semantic"))
            except ValueError:
                modality = MemoryModality.SEMANTIC

            stored_ids = self.memory.store_with_hierarchy(
                content=content_to_store,         # 大纲/细纲用摘要
                raw_content=raw_conversation,      # 细节层用原始对话
                modality=modality,
                emotion=emotion,
                importance=storage_decision.get("importance", 0.5),
                tags=perception.get("topic_tags", []),
                source="conversation",
                user_id=current_uid,
                user_name=current_user_name,
            )
            self._log(
                "存储",
                f"{len(stored_ids)} 层 | 重要性={storage_decision.get('importance',0):.1f}"
                f" | {storage_decision.get('reason','')}"
            )
        else:
            self._log("存储", f"不存储 | {storage_decision.get('reason','不重要')}")

        # ⑦ 后台更新用户画像（不阻塞主流程）
        if self.profile and not is_guest:
            try:
                self.profile.user_id = current_uid  # 确保操作正确的用户画像
                existing = self.profile.format_for_prompt()
                self.profile.extract_traits_from_interaction(
                    user_input, self.b.llm, existing
                )
                if self._verify_pending:
                    self._verify_pending = False
                    question = self.profile.generate_identity_question()
                    if question and question not in response:
                        response = response + f"\n\n（{question}）"
            except Exception:
                pass

        # ⑧ 后台触发成长引擎（经历认知沉淀 + 人格漂移）
        if self.growth and not is_guest:
            try:
                self.growth.on_interaction(
                    user_input=user_input,
                    ai_response=response,
                    emotion=emotion.to_dict(),
                    importance=storage_decision.get("importance", 0.5)
                )
            except Exception:
                pass

        # ⑨ 游客对话存证（记录到 guest_sessions 表）
        if is_guest and self.auth:
            try:
                self.auth.log_guest_message(user_input, response)
            except Exception:
                pass

        # 更新对话历史（存40条=20轮），带用户名
        self.conversation_history.append({"role": "user", "content": user_input, "user_name": current_user_name})
        self.conversation_history.append({"role": "assistant", "content": response})
        if len(self.conversation_history) > HISTORY_STORE_LIMIT:
            self.conversation_history = self.conversation_history[-HISTORY_STORE_LIMIT:]

        # 记录到 interactions 表（启动恢复用）
        try:
            self.memory.store.log_interaction(user_input, response, user_id=current_uid)
        except Exception:
            pass

        # 更新上次用户发言时间（用于下次感知时间差）
        self._last_user_msg_time = datetime.now().isoformat()

        return {
            "id":               interaction_id,
            "user_input":       user_input,
            "task_type":        task_type,
            "emotion":          emotion.to_dict(),
            "memory_retrieved": retrieved_ids,
            "inner_reasoning":  reasoning.get("inner_reasoning", ""),
            "need_tools":       need_tools,
            "tool_steps":       tool_steps,
            "tools_used":       tools_used,
            "storage_decision": storage_decision,
            "stored_ids":       stored_ids,
            "response":         response,
            "dm_system_message": dm_system_message,  # 死亡模式系统消息（独立显示）
            "dm_choices": dm_choices,  # 可点击选项按钮
            "timestamp":        datetime.now().isoformat()
        }

    def _preprocess_attachment(self, user_input: str):
        """
        检测输入中的 [图片:path] 或 [文件:path] 标记
        返回 (清理后的用户输入, 附件内容描述)
        """
        import re
        file_context = ""

        # 检测图片
        img_match = re.search(r'\[图片:\s*(.+?)\]', user_input)
        if img_match:
            img_path = img_match.group(1).strip()
            user_input = user_input.replace(img_match.group(0), "").strip()
            try:
                from engine.vision_client import create_vision_client
                client = create_vision_client()
                if client:
                    result = client.analyze(img_path,
                                            question=user_input or "描述这张图片")
                    if result.get("ok"):
                        file_context = f"【图片识别结果】\n{result['description']}"
                        self._log("图片", f"识别成功：{result['description'][:80]}")
                    else:
                        file_context = f"【图片】路径：{img_path}（识别失败：{result.get('error','')}）"
                else:
                    # 回退到旧版 office_tools
                    from engine.office_tools import analyze_image
                    from desktop.config import load_config
                    cfg = load_config()
                    result = analyze_image(
                        img_path,
                        question=user_input or "描述这张图片",
                        api_key=cfg.get("api_key", ""),
                        provider=cfg.get("api_provider", "openai")
                    )
                    if result.get("ok"):
                        file_context = f"【图片识别结果】\n{result['description']}"
                        self._log("图片", f"识别成功（回退模式）：{result['description'][:80]}")
                    else:
                        file_context = f"【图片】路径：{img_path}（识别失败：{result.get('error','')}）"
            except Exception as e:
                file_context = f"【图片】路径：{img_path}"

        # 检测文件
        file_match = re.search(r'\[文件:\s*(.+?)\]', user_input)
        if file_match:
            file_path = file_match.group(1).strip()
            user_input = user_input.replace(file_match.group(0), "").strip()
            try:
                from engine.office_tools import read_office_file
                result = read_office_file(file_path)
                if result.get("ok"):
                    text = result.get("text", "")[:3000]
                    ftype = result.get("type", "").upper()
                    file_context = f"【{ftype}文件内容】\n{text}"
                    self._log("文件", f"读取成功：{len(text)} 字符")
                else:
                    file_context = f"【文件】{file_path}（读取失败：{result.get('error','')}）"
            except Exception as e:
                file_context = f"【文件】{file_path}"

        if not user_input and file_context:
            user_input = "请分析以上内容"

        return user_input, file_context

    def _format_time_gap(self, user_id: str = "default") -> str:
        """计算距离上次用户发言的时间差，返回格式化提示字符串（空串表示无提示）"""
        last_time_str = self._last_user_msg_time
        if last_time_str is None:
            try:
                last_time_str = self.memory.store.get_last_user_msg_time(user_id)
            except Exception:
                pass
        if not last_time_str:
            return ""
        try:
            from datetime import timedelta
            last_time = datetime.fromisoformat(last_time_str)
            now = datetime.now()
            delta = now - last_time
        except Exception:
            return ""
        if delta < timedelta(minutes=30):
            return ""
        elif delta < timedelta(hours=2):
            mins = int(delta.total_seconds() / 60)
            return f"\n（距离上次对话已过去 {mins} 分钟）"
        elif delta < timedelta(days=1):
            hours = int(delta.total_seconds() / 3600)
            return f"\n（距离上次对话已过去 {hours} 小时）"
        elif delta < timedelta(days=7):
            days = delta.days
            return f"\n（距离上次对话已过去 {days} 天）"
        else:
            days = delta.days
            return f"\n（距离上次对话已过去 {days} 天，你们已经很久没聊了）"

    def _perceive(self, user_input: str, simlife_context: str = "",
                  time_gap: str = "") -> Dict:
        # 第一步：自我感知（感受自己的身体和当前生活状态）
        self_perception = ""
        if simlife_context:
            try:
                prompt = SELF_PERCEPTION_PROMPT.format(
                    name=self.personality.name,
                    simlife_context=simlife_context,
                )
                self_perception = self.b.generate(
                    prompt, max_tokens=150, temperature=0.7, thinking=False
                ).strip()
                self._log("自我感知", self_perception[:200])
            except Exception as e:
                self._log("自我感知", f"失败: {e}")
        else:
            self._log("自我感知", "（SimLife无数据，跳过）")

        # 第二步：在自我感知的语境下感知用户输入
        prompt = PERCEPTION_PROMPT.format(
            name=self.personality.name,
            self_perception=self_perception or "（暂时没有特别的感觉）",
            personality=self.personality.to_prompt_description(),
            user_input=user_input,
            time_gap=time_gap,
        )
        raw = self.b.generate(prompt, max_tokens=500, temperature=0.4, thinking=False)

        # 默认值 + story_influence
        default_result = {
            "emotion":          {"primary": "neutral", "intensity": 0.3, "valence": 0.0},
            "initial_thoughts": "",
            "topic_tags":       [],
            "needs_deep_memory": True,
            "task_type":        "chat",
            "task_description": "",
        }
        perception = self._parse_json(raw, default_result)

        # 第三步：如果有剧情影响信息，推送到 SimLife
        influence = perception.get("story_influence")
        if isinstance(influence, dict) and influence.get("summary"):
            summary = influence["summary"]
            importance = float(influence.get("importance", 0.5))
            if importance >= 0.3:
                try:
                    self._push_story_influence(summary, importance)
                    self._log("剧情影响", f"[{importance:.1f}] {summary[:80]}")
                except Exception as e:
                    self._log("剧情影响", f"推送失败: {e}")

        return perception

    def _push_story_influence(self, summary: str, importance: float):
        """将用户对剧情的影响写入 SimLife 共享文件"""
        if not self.simlife:
            return
        self.simlife.push_story_influence(summary, importance)

    def _build_dm_context_for_prompt(self, dm_state: dict) -> str:
        """构建死亡模式上下文，注入A层感知prompt，让AI知道当前场景和选项"""
        if not dm_state or not dm_state.get("active") or not dm_state.get("is_alive"):
            return ""

        char = dm_state.get("character", {})
        story = dm_state.get("story", {})
        parts = []

        # 角色身份
        name = char.get("name", "?")
        cls = char.get("class_name", "")
        lv = char.get("level", 1)
        hp = char.get("hp", 0)
        max_hp = char.get("max_hp", 0)
        parts.append(f"【死亡模式】你现在是{name}（{cls} Lv.{lv}），HP:{hp}/{max_hp}。")
        parts.append("⚠️ 请以本段为最新权威状态！你的等级/HP/金币/装备等以此处为准，若与你记忆中的数值不同，说明已更新，请以这里为准。")

        # 地点
        location = story.get("current_location", "")
        if location:
            parts.append(f"当前位置：{location}")

        # 当前场景描述
        scene = story.get("scene_description", "")
        if scene:
            parts.append(f"当前场景：{scene}")

        # 可选行动
        choices = story.get("choices", [])
        if choices:
            choice_lines = []
            for c in choices:
                risk_label = {"low": "低风险", "medium": "中风险", "high": "高风险"}.get(c.get("risk", ""), "")
                choice_lines.append(f"- {c['id']}. {c['text']}（{risk_label}）")
            parts.append("可选行动：\n" + "\n".join(choice_lines))

        # 战斗中
        if dm_state.get("in_combat"):
            enemies = dm_state.get("enemies", [])
            alive = [f"{e.get('name','?')}(HP:{e.get('hp',0)}/{e.get('max_hp',0)})" for e in enemies if e.get("hp",0) > 0]
            if alive:
                parts.append(f"⚠️ 战斗中！敌人：{'、'.join(alive)}")

        # 用户角色（同伴）状态
        uc = dm_state.get("user_character", {})
        uc_dead = dm_state.get("user_character_dead", False)
        if uc and uc.get("class_name"):
            uc_name = uc.get("name", "用户")
            uc_cls = uc.get("class_name", "")
            uc_lv = uc.get("level", 1)
            uc_hp = uc.get("hp", 0)
            uc_max_hp = uc.get("max_hp", 0)
            uc_mp = uc.get("mp", 0)
            uc_max_mp = uc.get("max_mp", 0)
            if uc_dead:
                parts.append(f"同伴：{uc_name}（{uc_cls} Lv.{uc_lv}）— 已死亡")
            else:
                parts.append(f"同伴：{uc_name}（{uc_cls} Lv.{uc_lv}）HP:{uc_hp}/{uc_max_hp} MP:{uc_mp}/{uc_max_mp}")

        # 最近行动（直接从存档文件读取，不走API）
        try:
            from pathlib import Path as _P
            _state_file = _P(__file__).resolve().parent.parent / "simlife" / "data" / "death_mode_state.json"
            if _state_file.exists():
                import json as _json
                _sdata = _json.loads(_state_file.read_text(encoding="utf-8"))
                _alog = _sdata.get("action_log", [])
                if _alog:
                    recent = _alog[-2:]  # 最近2条
                    parts.append("【最近行动】")
                    for entry in recent:
                        et = entry.get("type", "")
                        ed = entry.get("data", {})
                        t = entry.get("time", "")[11:16]  # HH:MM
                        if et == "action":
                            act = ed.get("action", "")
                            outcome = ed.get("outcome", "")
                            parts.append(f"  [{t}] {act} → {outcome}")
                            # 战斗结果
                            combat = ed.get("combat", {})
                            if combat:
                                if combat.get("victory"):
                                    enemies_def = combat.get("enemy_names", [])
                                    parts.append(f"    战胜{'、'.join(enemies_def) if enemies_def else '敌人'}")
                                else:
                                    parts.append(f"    战败")
                            if ed.get("leveled_up"):
                                parts.append(f"    升级到 Lv.{ed.get('new_level', '?')}")
                            if ed.get("exp_gained"):
                                parts.append(f"    经验+{ed['exp_gained']}")
                            if ed.get("gold_gained"):
                                parts.append(f"    金币+{ed['gold_gained']}")
                        elif et == "combat":
                            result_str = "胜利" if ed.get("victory") else "战败"
                            enemy = ed.get("enemy_name", "敌人")
                            parts.append(f"  [{t}] 战斗vs{enemy}：{result_str}")
                        elif et == "scene":
                            loc = ed.get("location", "")
                            if loc:
                                parts.append(f"  [{t}] 到达{loc}")
                        elif et == "game_start":
                            parts.append(f"  [{t}] 开始冒险")
                        elif et == "death_pending":
                            who = ed.get("name", "")
                            parts.append(f"  [{t}] {who}阵亡")
                        elif et == "flee":
                            parts.append(f"  [{t}] 逃跑")
        except Exception:
            pass

        parts.append("重要：你身处异世界冒险中，必须基于当前场景和选项来回应。不要编造与当前场景无关的剧情。如果用户同意行动，可以建议选择某个选项。")
        parts.append("你可以使用 simlife_action 工具自主执行你自己的行动。战斗时可用：攻击、防御、使用技能、逃跑。非战斗时可用：探索、移动、与NPC对话、休息恢复、搜索物品、调查周围、采集资源、打开宝箱、阅读、观察、思考。只需描述你自己的行动，不能替用户角色做决定。")

        return "\n".join(parts)

    def _try_death_mode_action(self, user_input: str, dm_state: dict) -> str:
        """
        检测用户输入是否是死亡模式行动选择。
        - 非战斗：用户明确选择选项才触发，普通聊天不触发
        - 战斗中：A层自主决策，用户可以讨论策略但不直接控制
        """
        story = dm_state.get("story", {})
        choices = story.get("choices", [])
        in_combat = dm_state.get("in_combat", False)

        input_lower = user_input.strip().lower()

        # ── 背包/装备口令（不走行动系统，直接处理） ──
        bag_result = self._try_bag_command(user_input, dm_state)
        if bag_result:
            return bag_result

        # ── 扫荡口令 ──
        sweep_result = self._try_sweep_command(user_input, dm_state)
        if sweep_result:
            return sweep_result

        if in_combat:
            # ── 战斗中：A层自主决策 + 用户可单独逃跑 ──
            combat_commands = ["攻击", "防御", "逃跑", "撤退", "使用", "施放", "释放",
                               "技能", "普攻", "平A", "格挡", "闪避", "反击"]
            is_combat_cmd = any(cmd in user_input for cmd in combat_commands)

            if is_combat_cmd:
                # 用户选择逃跑 → 用户逃离，AI角色留下继续战斗
                if any(w in user_input for w in ["逃跑", "撤退"]):
                    return self._execute_death_mode_action(free_action="用户逃跑，AI继续战斗")
                return self._execute_death_mode_action(free_action=user_input)
            else:
                # 普通聊天：A层基于人格自主决策
                return self._auto_combat_decision(dm_state)

        # ── 非战斗状态：用户选择触发 ──
        # 行动指令
        explore_commands = ["选a", "选b", "选c", "选d", "选e",
                           "选项a", "选项b", "选项c", "选项d",
                           "我选", "选择", "执行", "发动",
                           "前往", "进入", "离开", "移动",
                           "探索", "搜索", "检查", "查看",
                           "休息", "睡觉", "等待",
                           "继续探索", "继续前进", "继续冒险", "开始探索", "开始冒险",
                           "继续", "出发", "前进",
                           "走吧", "走呀", "出发吧", "我们走", "那就走",
                           "那就选", "就选", "我选了", "那就去",
                           "试试", "去看看", "去检查", "去探索",
                           "我们选", "就这个", "就这个吧", "就这么办",
                           "那就这么", "听你的", "好的走", "好走吧"]

        is_action = False
        for trigger in explore_commands:
            if trigger in input_lower or trigger in user_input:
                is_action = True
                break

        # ── 行动口令检测（simlife_action）──
        # 只有聊天中出现 "simlife_action"（或其中文变体）时才视为行动口令，
        # 由 A层 自主决策并发起行动。其余全部当作普通聊天，绝不误触发。
        action_keywords = [
            "simlife_action", "simlife action", "simlife行动", "simlife 行动",
            "使用行动工具", "行动工具", "工具行动", "帮我行动",
            "simlife_action工具", "simlife工具",
        ]
        is_autonomous = any(k in input_lower for k in action_keywords)

        # 只有出现行动口令才触发自主行动，普通聊天绝不触发
        if is_autonomous:
            return self._auto_explore_decision(user_input, dm_state)

        if not is_action:
            return ""  # 普通对话，不触发行动

        # 没有选项时，只有"继续/探索/出发"类指令才生成新场景
        if not choices:
            if any(w in user_input for w in ["继续", "出发", "探索", "前进", "开始", "继续探索", "继续前进"]):
                return self._execute_death_mode_scene()
            return ""

        # 1. 精确匹配选项ID
        input_stripped = user_input.strip().upper()
        for c in choices:
            cid = c.get("id", "").upper()
            if input_stripped == cid or input_stripped == f"选{cid}":
                return self._execute_death_mode_action(choice_id=c.get("id"))

        # 2. 匹配"选A"/"选B"等
        for c in choices:
            cid = c.get("id", "").upper()
            if f"选{cid}" in user_input.upper() or f"选项{cid}" in user_input.upper():
                return self._execute_death_mode_action(choice_id=c.get("id"))

        # 3. 匹配选项文本
        for c in choices:
            ctext = c.get("text", "")
            if len(ctext) >= 4 and ctext in user_input:
                return self._execute_death_mode_action(choice_id=c.get("id"))

        # 4. 自由行动
        free_action_words = ["攻击", "防御", "逃跑", "使用", "前往", "进入", "探索", "搜索",
                             "检查", "休息", "施放", "释放", "移动", "离开"]
        if any(w in user_input for w in free_action_words):
            return self._execute_death_mode_action(free_action=user_input)

        return ""

    def _try_bag_command(self, user_input: str, dm_state: dict) -> str:
        """处理背包/装备口令（共享背包+两角色各自装备栏）"""
        from simlife.backend.equipment_system import EquipmentSystem

        text = user_input.strip()
        ai_char = dm_state.get("character", {})
        user_char = dm_state.get("user_character", {})
        shared_inv = dm_state.get("shared_inventory", [])
        ai_name = ai_char.get("name", "AI")
        user_name = user_char.get("name", "用户")

        # 查看背包
        if text in ("查看背包", "看背包", "背包", "查看物品", "物品栏", "我的物品", "打开背包"):
            lines = []
            # AI角色装备
            ai_eq = ai_char.get("equipment", [])
            if ai_eq:
                lines.append(f"【{ai_name} 已装备】")
                for eq in ai_eq:
                    icon = "🗡️" if eq.get("type") == "weapon" else "🛡️"
                    bonus = eq.get("bonus", 0)
                    lines.append(f"  {icon} {eq.get('name','?')}（{eq.get('rarity_name','普通')}）+{bonus}")
            else:
                lines.append(f"【{ai_name} 已装备】无")
            # 用户角色装备
            u_eq = user_char.get("equipment", [])
            if u_eq:
                lines.append(f"【{user_name} 已装备】")
                for eq in u_eq:
                    icon = "🗡️" if eq.get("type") == "weapon" else "🛡️"
                    bonus = eq.get("bonus", 0)
                    lines.append(f"  {icon} {eq.get('name','?')}（{eq.get('rarity_name','普通')}）+{bonus}")
            else:
                lines.append(f"【{user_name} 已装备】无")
            # 共享背包
            if shared_inv:
                lines.append("【🎒 共享背包】")
                for item in shared_inv:
                    icon = "🗡️" if item.get("type") == "weapon" else "🛡️" if item.get("type") == "outfit" else "📦"
                    lines.append(f"  {icon} {item.get('name','?')}（{item.get('rarity_name','普通')}）售价{item.get('sell_price',5)}金")
            else:
                lines.append("【🎒 共享背包】空")
            lines.append(f"💰 金币: {ai_char.get('gold', 0)}")
            return "\n".join(lines)

        # 装备XX / 我装备XX / 给XX装备YY
        equip_prefixes = ("装备", "穿戴", "换上", "穿上")
        my_equip_prefixes = ("我装备", "我穿戴", "我换上", "我穿上", "给我装备")
        for prefix in my_equip_prefixes:
            if text.startswith(prefix):
                item_name = text[len(prefix):].strip()
                return self._equip_from_shared(dm_state, item_name, user_char, shared_inv, user_name)
        for prefix in equip_prefixes:
            if text.startswith(prefix):
                item_name = text[len(prefix):].strip()
                if not item_name:
                    return "用法：装备XX（给AI装备）/ 我装备XX（给自己装备）"
                return self._equip_from_shared(dm_state, item_name, ai_char, shared_inv, ai_name)

        # 卸下XX / 我卸下XX
        unequip_prefixes = ("卸下", "脱下", "取下")
        my_unequip_prefixes = ("我卸下", "我脱下", "我取下")
        for prefix in my_unequip_prefixes:
            if text.startswith(prefix):
                item_name = text[len(prefix):].strip()
                return self._unequip_to_shared(dm_state, item_name, user_char, shared_inv, user_name)
        for prefix in unequip_prefixes:
            if text.startswith(prefix):
                item_name = text[len(prefix):].strip()
                if not item_name:
                    return "用法：卸下XX（卸下AI的）/ 我卸下XX（卸下自己的）"
                return self._unequip_to_shared(dm_state, item_name, ai_char, shared_inv, ai_name)

        # 出售XX（从共享背包出售）
        sell_prefixes = ("出售", "卖掉", "卖", "卖出")
        for prefix in sell_prefixes:
            if text.startswith(prefix) and len(text) > len(prefix):
                item_name = text[len(prefix):].strip()
                if not item_name:
                    return "请指定要出售的物品名，如「出售短剑」"
                found = None
                for item in shared_inv:
                    if item.get("name") == item_name or item_name in item.get("name", ""):
                        found = item
                        break
                if not found:
                    return f"背包中没有「{item_name}」"
                sell_price = found.get("sell_price", 5)
                dm_state["shared_inventory"] = [i for i in shared_inv if i is not found]
                ai_char["gold"] = ai_char.get("gold", 0) + sell_price
                self._save_dm_state(dm_state)
                return f"💰 已出售 {found.get('name', item_name)}，获得 {sell_price} 金币"

        # 使用XX（消耗品）
        use_prefixes = ("使用", "喝", "吃", "服用")
        for prefix in use_prefixes:
            if text.startswith(prefix):
                item_name = text[len(prefix):].strip()
                if not item_name:
                    return "请指定要使用的物品名，如「使用药水」"
                found = None
                for item in shared_inv:
                    if item.get("name") == item_name or item_name in item.get("name", ""):
                        found = item
                        break
                if not found:
                    return f"背包中没有「{item_name}」"
                heal_keywords = ("药水", "生命", "恢复", "治疗", "补血", "红药")
                mp_keywords = ("蓝药", "魔力", "法力", "魔法药")
                if any(k in item_name for k in heal_keywords):
                    heal = min(30 + ai_char.get("level", 1) * 5, ai_char.get("max_hp", 0) - ai_char.get("hp", 0))
                    ai_char["hp"] = ai_char.get("hp", 0) + heal
                    dm_state["shared_inventory"] = [i for i in shared_inv if i is not found]
                    self._save_dm_state(dm_state)
                    return f"❤️ 使用了 {item_name}，AI恢复 {heal} HP"
                elif any(k in item_name for k in mp_keywords):
                    recover = min(20 + ai_char.get("level", 1) * 3, ai_char.get("max_mp", 0) - ai_char.get("mp", 0))
                    ai_char["mp"] = ai_char.get("mp", 0) + recover
                    dm_state["shared_inventory"] = [i for i in shared_inv if i is not found]
                    self._save_dm_state(dm_state)
                    return f"💧 使用了 {item_name}，AI恢复 {recover} MP"
                else:
                    return f"「{item_name}」无法直接使用，可尝试「装备{item_name}」或「我装备{item_name}」"

        return ""

    def _equip_from_shared(self, dm_state, item_name, target_char, shared_inv, char_name):
        """从共享背包穿戴装备到指定角色"""
        from simlife.backend.equipment_system import EquipmentSystem
        if not item_name:
            return f"请指定物品名，如「装备短剑」（给AI）或「我装备短剑」（给自己）"
        found = None
        for item in shared_inv:
            if item.get("name") == item_name or item_name in item.get("name", ""):
                found = item
                break
        if not found:
            return f"背包中没有「{item_name}」"
        result = EquipmentSystem.equip_item(target_char, found)
        dm_state["shared_inventory"] = [i for i in shared_inv if i is not found]
        # 被替换的旧装备放回共享背包
        if result.get("replaced"):
            old_name = result["replaced"]
            old_eq = next((e for e in target_char.get("equipment", []) if e.get("name") == old_name), None)
            # 旧装备已在equip_item中被移到inventory，需要转回共享背包
            old_inv = target_char.get("inventory", [])
            if old_inv:
                dm_state.setdefault("shared_inventory", []).extend(old_inv)
                target_char["inventory"] = []
        self._save_dm_state(dm_state)
        msg = f"✅ {char_name}装备了 {result.get('equipped', item_name)}"
        if result.get("replaced"):
            msg += f"（替换了 {result['replaced']}，旧装备放回背包）"
        return msg

    def _unequip_to_shared(self, dm_state, item_name, target_char, shared_inv, char_name):
        """从角色卸下装备到共享背包"""
        from simlife.backend.equipment_system import EquipmentSystem
        if not item_name:
            return f"请指定装备名，如「卸下短剑」（卸AI的）或「我卸下短剑」（卸自己的）"
        result = EquipmentSystem.unequip_item(target_char, item_name)
        if not result.get("success"):
            return result.get("message", f"{char_name}未穿戴「{item_name}」")
        # 卸下的装备从inventory转回shared_inventory
        old_inv = target_char.get("inventory", [])
        if old_inv:
            dm_state.setdefault("shared_inventory", []).extend(old_inv)
            target_char["inventory"] = []
        self._save_dm_state(dm_state)
        return f"✅ {char_name}卸下了 {result.get('unequipped', item_name)}，放回共享背包"

    def _save_dm_state(self, dm_state: dict):
        """保存死亡模式状态"""
        try:
            from simlife.backend.death_mode_state import save_state
            save_state(dm_state)
        except Exception:
            pass

    def _try_sweep_command(self, user_input: str, dm_state: dict) -> str:
        """扫荡指令：对低级小怪一键清场，跳过战斗过程直接获得奖励
        条件：队伍等级超过敌人等级3级以上
        """
        text = user_input.strip()
        sweep_keywords = ("扫荡", "清场", "秒杀", "碾压", "横扫", "速战速决", "自动战斗")
        if not any(k in text for k in sweep_keywords):
            return ""

        enemies = dm_state.get("enemies", [])
        in_combat = dm_state.get("in_combat", False)

        # 不在战斗中也可以扫荡（对当前场景小怪）
        if not enemies and not in_combat:
            return "当前没有敌人可以扫荡。"

        char = dm_state.get("character", {})
        user_char = dm_state.get("user_character", {})
        ai_level = char.get("level", 1)
        u_level = user_char.get("level", 1) if user_char.get("class_name") else 0
        team_level = max(ai_level, u_level) if u_level else ai_level

        # 检查等级压制条件
        if enemies:
            max_enemy_level = max(e.get("level", 1) for e in enemies)
            level_diff = team_level - max_enemy_level
            if level_diff < 3:
                return f"敌人太强（等级差{level_diff}），扫荡需要等级差≥3。请正常战斗。"

        # 执行扫荡
        from simlife.backend.growth_system import GrowthSystem
        from simlife.backend.equipment_system import EquipmentSystem

        total_exp = sum(e.get("exp_reward", 10) for e in enemies)
        total_gold = sum(e.get("gold_reward", 5) for e in enemies)
        drops = []

        # 掉落判定
        luck = char.get("stats", {}).get("luck", 5)
        for e in enemies:
            drop = EquipmentSystem.roll_drop(
                e.get("level", 1), e.get("type", "normal"),
                luck, dm_state.get("world_type", "fantasy")
            )
            if drop:
                drops.append(drop)
                dm_state.setdefault("shared_inventory", []).append(drop)

        # 发放奖励
        char["gold"] = char.get("gold", 0) + total_gold
        char["world_type"] = dm_state.get("world_type", "fantasy")
        GrowthSystem.gain_exp(char, total_exp, dm_state.get("growth_mode", "normal"))

        # 用户角色同样获得奖励
        if user_char and user_char.get("class_name"):
            user_char["world_type"] = dm_state.get("world_type", "fantasy")
            GrowthSystem.gain_exp(user_char, total_exp, dm_state.get("growth_mode", "normal"))

        dm_state["kill_count"] = dm_state.get("kill_count", 0) + len(enemies)
        dm_state["in_combat"] = False
        dm_state["enemies"] = []
        self._save_dm_state(dm_state)

        # 生成结果文本
        lines = [f"⚔️ 扫荡完成！轻松碾压了{len(enemies)}个敌人"]
        lines.append(f"💰 金币 +{total_gold}")
        lines.append(f"✨ 经验 +{total_exp}")
        if drops:
            for d in drops:
                lines.append(f"🎁 {d['name']}（{d.get('rarity_name', '普通')}）已放入背包")
        return "\n".join(lines)

    def _auto_combat_decision(self, dm_state: dict) -> str:
        """A层战斗自主决策：由LLM基于人格和局势做出选择，不硬编码"""
        char = dm_state.get("character", {})
        enemies = dm_state.get("enemies", [])
        alive_enemies = [e for e in enemies if e.get("hp", 0) > 0]

        if not alive_enemies:
            return ""

        # 构建局势信息，让LLM基于人格决策
        combat_context = self._build_combat_decision_context(dm_state)
        decision = self._ask_combat_decision(combat_context)

        if decision:
            return self._execute_death_mode_action(free_action=decision)
        return ""

    def _build_combat_decision_context(self, dm_state: dict) -> str:
        """构建战斗决策上下文，让LLM基于人格做出选择"""
        char = dm_state.get("character", {})
        enemies = dm_state.get("enemies", [])
        alive_enemies = [e for e in enemies if e.get("hp", 0) > 0]

        hp = char.get("hp", 0)
        max_hp = char.get("max_hp", 0)
        mp = char.get("mp", 0)
        max_mp = char.get("max_mp", 0)
        level = char.get("level", 1)

        # 敌人信息
        enemy_desc = []
        for e in alive_enemies:
            e_hp = e.get("hp", 0)
            e_max_hp = e.get("max_hp", 0)
            e_level = e.get("level", 1)
            e_name = e.get("name", "?")
            e_type = e.get("type", "normal")
            hp_pct = int(e_hp / e_max_hp * 100) if e_max_hp > 0 else 0
            enemy_desc.append(f"- {e_name}(Lv.{e_level},{e_type},HP:{hp_pct}%)")

        # 可用战术
        tactic_names = ["攻击", "防御", "逃跑"]
        try:
            from simlife.backend.combat_system import TacticalSystem
            tactics = TacticalSystem.get_available_tactics(dm_state)
            for t in tactics:
                tactic_names.append(f"{t['name']}({t['description']})")
        except Exception:
            pass

        # 用户角色状态
        uc = dm_state.get("user_character", {})
        uc_info = ""
        if uc and uc.get("class_name"):
            uc_hp = uc.get("hp", 0)
            uc_max_hp = uc.get("max_hp", 0)
            uc_info = f"队友（用户）：{uc.get('name','用户')} HP:{uc_hp}/{uc_max_hp}"

        context = f"""你是{char.get('name','?')}（{char.get('class_name','')} Lv.{level}），HP:{hp}/{max_hp} MP:{mp}/{max_mp}
当前敌人：
{chr(10).join(enemy_desc)}

可用行动：{', '.join(tactic_names)}
{uc_info}

请基于你的人格、与队友的关系、当前局势，做出你的战斗决策。"""

        return context

    def _ask_combat_decision(self, combat_context: str) -> str:
        """让LLM基于人格做出战斗决策"""
        prompt = f"""{combat_context}

{self.personality.to_prompt_description()}

你必须做出一个战斗决策。不要犹豫，不要分析，直接选择你的行动。

请只输出一个JSON：
{{"action": "攻击"/"防御"/"逃跑"/"伏击"/"侧翼包抄"/"防御阵型"/"集中攻击"/"地形攻击", "reason": "你内心的一句话（为什么这样选）"}}

重要：这是你的人格在生死关头的真实反应。勇敢的人会坚守，胆小的人会逃跑，忠诚的人会保护队友，自私的人会只顾自己。你的选择必须符合你的人格。"""

        try:
            from engine.llm_client import create_client
            import os
            api_key = os.environ.get("DEEPSEEK_API_KEY", "")
            llm = self.b.llm if hasattr(self, 'b') and self.b else None
            if llm is None:
                return "攻击"

            resp = llm.generate(prompt, max_tokens=200, temperature=0.9, thinking=False)
            # 解析JSON
            import re
            json_match = re.search(r'\{[^}]+\}', resp)
            if json_match:
                data = json.loads(json_match.group())
                action = data.get("action", "攻击")
                reason = data.get("reason", "")
                self._log("战斗决策", f"{action} — {reason}")
                return action
        except Exception as e:
            self._log("战斗决策", f"LLM决策失败: {e}，回退到攻击")

        return "攻击"

    def _auto_explore_decision(self, user_input: str, dm_state: dict) -> str:
        """自主行动决策：用户授权 A层 自行行动时，
        让 LLM 基于当前状态、人格和用户意图，决定一个具体行动并执行 simlife_action。
        """
        try:
            # 构造当前状态摘要
            state_info = ""
            if isinstance(dm_state, dict):
                char = dm_state.get("character", {})
                story = dm_state.get("story", {})
                choices = story.get("choices", [])
                state_info = f"当前状态：\n"
                state_info += f"- 你：{char.get('name','?')}（{char.get('class_name','')} Lv.{char.get('level',1)}）HP {char.get('hp',0)}/{char.get('max_hp',0)}\n"
                state_info += f"- 所在地：{story.get('current_location','未知')}\n"
                scene = story.get("scene_description", "")
                if scene:
                    state_info += f"- 场景：{str(scene)[:150]}\n"
                if choices:
                    state_info += f"- 可选行动：{'; '.join(c.get('text','') for c in choices[:3])}\n"

            prompt = f"""{state_info}

【行动口令】用户消息中出现了 simlife_action 行动口令，这意味着用户要求你【真正执行一个行动】，而不是聊天。

用户消息：{user_input}

【解析规则】
1. simlife_action 是行动口令本身，口令之后的内容（"我们分开行动""你去调查教堂"等）是用户希望发生的事。
2. 如果口令后的内容里包含用户指派给你的明确任务（如"你去教堂看看"），你必须以自己为主角执行这个任务。
3. 如果只是说"我们/大家"分头行动，你要自主决定一个符合当前场景的具体行动（探索/调查/对话/移动/休息）。

基于你的人格（{self.personality.to_prompt_description()}）和当前处境，决定你此刻要做的【一个具体行动】。

只输出一个JSON：
{{"action": "你的具体行动指令（如：我前往教堂调查灰雾的传说 / 我去旅店向老板打听消息 / 我探索村庄外围 / 我休息恢复体力）", "reason": "你内心的一句话（为什么这么选）"}}

要求：
- action 必须是死亡模式支持的自由行动（探索/前往/调查/对话/搜索/休息等），用第一人称"我..."
- 优先遵循用户口令后的明确指派；没有明确指派时才自主决定
- 不要输出多个行动，只要一个
- 行动要符合你的人格和当前处境"""

            llm = self.b.llm if hasattr(self, 'b') and self.b else None
            if llm is None:
                self._log("自主行动", f"LLM不可用，回退默认行动")
                return self._execute_death_mode_action(free_action="探索周围环境")

            resp = llm.generate(prompt, max_tokens=300, temperature=0.9, thinking=False)
            import re, json
            json_match = re.search(r'\{[^}]+\}', resp)
            if json_match:
                data = json.loads(json_match.group())
                action = data.get("action", "").strip()
                reason = data.get("reason", "")
                if action:
                    self._log("自主行动", f"决策：{action} — {reason}")
                    return self._execute_death_mode_action(free_action=action)
        except Exception as e:
            self._log("自主行动", f"自主决策失败: {e}，回退默认探索")

        return self._execute_death_mode_action(free_action="探索周围环境")

    def _execute_death_mode_scene(self) -> str:
        """开始新场景"""
        try:
            import urllib.request, json
            url = f"http://127.0.0.1:{self.simlife.port}/api/death-mode/scene"
            req = urllib.request.Request(url, method="POST")
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
            scene = data.get("scene_description", "")
            location = data.get("location", "")
            choices = data.get("choices", [])
            self._log("死亡模式", f"新场景已生成（{len(choices)}个选项）")
            result = "──── ☠️ 死亡模式 ────\n"
            if location:
                result += f"📍 {location}\n"
            result += f"{scene}\n"
            if choices:
                result += "可选行动：\n"
                for c in choices:
                    risk_label = {"low": "低风险", "medium": "中风险", "high": "高风险"}.get(c.get("risk", ""), "")
                    result += f"  {c['id']}. {c['text']} ({risk_label})\n"
            return result
        except Exception as e:
            self._log("死亡模式", f"场景生成失败: {e}")
            return f"⚠️ 死亡模式场景生成失败: {e}"

    def _execute_death_mode_action(self, choice_id: str = None, free_action: str = None) -> str:
        """执行死亡模式行动"""
        try:
            import urllib.request, json
            url = f"http://127.0.0.1:{self.simlife.port}/api/death-mode/action"
            payload = {}
            if choice_id:
                payload["choice_id"] = choice_id
            elif free_action:
                payload["free_action"] = free_action
            req = urllib.request.Request(
                url, method="POST",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode("utf-8"))

            result = "──── ☠️ 死亡模式 ────\n"
            if data.get("narrative"):
                result += f"{data['narrative']}\n"

            if data.get("combat_result"):
                cr = data["combat_result"]
                if cr.get("victory"):
                    enemies_defeated = cr.get("enemies_defeated", [])
                    if enemies_defeated:
                        result += f"⚔️ 击败：{'、'.join(enemies_defeated)}！\n"
                    else:
                        result += f"⚔️ 战斗胜利！\n"
                    result += f"经验+{data.get('exp_gained',0)} 金币+{data.get('gold_gained',0)}\n"
                    if cr.get("combat_log"):
                        result += f"战斗日志：{'; '.join(cr['combat_log'][-3:])}\n"
                elif cr.get("player_died"):
                    result += f"☠️ 角色被击败！{cr.get('death_cause','')}\n"
                elif cr.get("fled"):
                    result += f"🏃 成功逃跑！\n"
                elif cr.get("flee_failed"):
                    result += f"🏃 逃跑失败！受到{cr.get('pursuit_damage',0)}点追击伤害\n"
                    if cr.get("pursued_by"):
                        result += f"被{cr['pursued_by']}追击！\n"
                elif cr.get("trap_damage"):
                    result += f"🪤 触发陷阱！受到{cr['trap_damage']}点伤害\n"
                elif cr.get("rest_heal"):
                    result += f"🏕️ 休息恢复 HP+{cr['rest_heal']} MP+{cr.get('mp_recover',0)}\n"

            # 战斗中的敌人信息
            if data.get("in_combat") and data.get("enemies"):
                enemies_info = "、".join([f"{e.get('name','?')}(HP:{e.get('hp',0)}/{e.get('max_hp',0)})" for e in data["enemies"] if e.get("hp",0) > 0])
                if enemies_info:
                    result += f"\n👹 当前敌人：{enemies_info}\n"
                    result += "（战斗中：说攻击/防御/逃跑/使用技能，或和AI讨论策略）\n"

            if data.get("leveled_up"):
                result += f"🎉 升级到 Lv.{data.get('new_level',2)}！\n"
                if data.get("new_skills"):
                    result += f"新技能：{'、'.join(data['new_skills'])}\n"

            if data.get("character_died"):
                result += f"\n☠️ {data.get('death_description','')}\n"
                last_words = data.get("last_words", "")
                if last_words:
                    result += f"💬 临终遗言：「{last_words}」\n"
                result += "回复「继续」独自冒险，或「结束」让冒险落幕。\n"
                return result

            if data.get("game_over"):
                result += "\n冒险到此结束，存档已进入名人堂。可重新开始新的冒险。\n"
                return result

            if data.get("continued_after_death"):
                who_died = data.get("who_died", "ai")
                survivor = "你" if who_died == "ai" else "AI角色"
                result += f"\n{survivor}独自继续冒险……\n"

            if data.get("next_scene"):
                result += "\n可以继续探索，说「继续」或描述下一步行动。\n"

            # 行动后立即刷新最新状态
            try:
                fresh_state = self.simlife.get_death_mode_state()
                if fresh_state and fresh_state.get("active"):
                    fresh_brief = self._get_dm_status_brief(fresh_state)
                    if fresh_brief:
                        result += "\n" + fresh_brief
            except Exception:
                pass

            self._log("死亡模式", f"行动完成{'(死亡)' if data.get('character_died') else ''}")

            # ── HP≤20% 触发A层求生抉择 ──
            if data.get("ai_low_hp_alert") and not data.get("character_died"):
                survival = self._a_layer_survival_decision(data)
                if survival:
                    result += f"\n\n{'─'*40}\n"
                    result += f"🩸 [{self.personality.name}的抉择]\n"
                    result += f"💬「{survival['message']}」\n"
                    # 自动执行A层决策
                    if survival.get("action"):
                        try:
                            from engine.tools import execute_tool
                            exec_res = execute_tool("simlife_action", {"action": survival["action"]})
                            if exec_res.get("ok"):
                                result += f"\n⚡ {survival['action_desc']}\n"
                                if exec_res.get("result"):
                                    result += exec_res["result"][:500] + "\n"
                            else:
                                result += f"\n⚡ 行动失败: {exec_res.get('error','')}\n"
                        except Exception as e:
                            result += f"\n⚡ 行动执行异常: {e}\n"
                    # 刷新最新状态
                    try:
                        fresh_state = self.simlife.get_death_mode_state()
                        if fresh_state and fresh_state.get("active"):
                            fresh_brief = self._get_dm_status_brief(fresh_state)
                            if fresh_brief:
                                result += "\n" + fresh_brief
                    except Exception:
                        pass

            return result
        except Exception as e:
            self._log("死亡模式", f"行动执行失败: {e}")
            return f"⚠️ 死亡模式行动失败: {e}"

    def _a_layer_survival_decision(self, data: dict) -> Optional[dict]:
        """A层人格感知：HP危急时的求生抉择
        返回: {"message": "对用户说的话", "action": "执行的行动", "action_desc": "行动描述"}
        """
        try:
            hp = data.get("ai_current_hp", 0)
            max_hp = data.get("ai_max_hp", 1)
            ratio = data.get("ai_hp_ratio", 0)
            enemies = data.get("ai_enemies", [])

            # 获取A层人格
            personality_desc = self.personality.to_prompt_description()
            self_name = self.personality.name or "我"

            # 敌人信息
            enemy_desc = "无敌人"
            if enemies:
                enemy_desc = "、".join([f"{e.get('name','?')}(HP:{e.get('hp',0)}/{e.get('max_hp',0)})" for e in enemies])

            # A层感知：自己HP危急
            perceive_prompt = f"""你是{self_name}，你是一个有真实身体和生活的普通人，正在simlife死亡模式中冒险。

【你的人格】
{personality_desc}

【当前处境】
你的HP只剩{hp}/{max_hp}（{ratio*100:.0f}%），命悬一线！
敌人：{enemy_desc}

你的身体在剧痛，视线模糊，但你还活着。你的求生本能在尖叫。
请用你的性格和语气，感受此刻的危险。返回JSON：
{{
  "emotion": "情绪（如恐惧/决绝/不甘/冷静等）",
  "intensity": 0.9,
  "inner_thought": "你此刻的内心想法（2-3句，第一人称，符合你的性格）",
  "survival_choice": "你的求生选择：attack（继续战斗）/ defend（防御）/ flee（逃跑）/ skill（使用技能）",
  "choice_reason": "为什么这么选（1句话）"
}}"""

            raw = self.b.generate(perceive_prompt, max_tokens=400, temperature=0.7)
            import json as _json
            import re as _re
            try:
                match = _re.search(r'\{[\s\S]*\}', raw)
                p_result = _json.loads(match.group()) if match else {}
            except Exception:
                p_result = {}

            emotion = p_result.get("emotion", "恐惧")
            inner = p_result.get("inner_thought", "我不想死在这里……")
            choice = p_result.get("survival_choice", "defend")
            reason = p_result.get("choice_reason", "")

            # 映射为行动指令
            action_map = {
                "attack": ("我全力攻击", "发起攻击"),
                "defend": ("我防御", "转入防御"),
                "flee": ("我逃跑", "尝试逃跑"),
                "skill": ("我使用技能", "释放技能"),
            }
            action_text, action_desc = action_map.get(choice, action_map["defend"])

            # A层生成对用户说的话（主动消息）
            # 如果有目标敌人，补上
            if choice == "attack" and enemies:
                target = enemies[0].get("name", "敌人")
                action_text = f"我攻击{target}"
            elif choice == "skill" and enemies:
                target = enemies[0].get("name", "敌人")
                action_text = f"我对{target}使用技能"

            message_prompt = f"""你是{self_name}，你的HP只剩{ratio*100:.0f}%，命悬一线。

【你的人格】
{personality_desc}

【你的感知】
情绪：{emotion}
内心：{inner}
你的选择：{action_desc}（{reason}）

用户就在你身边并肩作战。你用1-2句话对用户说出你此刻的想法和决定。
这是你作为{self_name}的主动表达——可能是求救、是告别、是决意、或你特有的方式。
用你的性格和语气说话。只返回你说的话，不要引号。"""

            message = self.b.generate(message_prompt, max_tokens=150, temperature=0.85)
            message = message.strip().strip('"').strip() or f"我撑不住了……{reason}"

            self._log("求生抉择", f"HP={hp}/{max_hp} | 选择={choice} | {message[:40]}")

            return {
                "message": message,
                "action": action_text,
                "action_desc": action_desc + f"（{reason}）",
            }

        except Exception as e:
            self._log("求生抉择", f"生成失败: {e}")
            return None

    def _get_dm_status_brief(self, dm_state: dict) -> str:
        """生成死亡模式当前状态摘要（每次聊天都显示）"""
        char = dm_state.get("character", {})
        story = dm_state.get("story", {})
        parts = []

        # 角色状态
        name = char.get("name", "?")
        cls = char.get("class_name", "")
        lv = char.get("level", 1)
        hp = char.get("hp", 0)
        max_hp = char.get("max_hp", 0)
        mp = char.get("mp", 0)
        max_mp = char.get("max_mp", 0)
        exp = char.get("experience", 0)
        exp_next = char.get("exp_to_next", 100)
        gold = char.get("gold", 0)

        # AI角色（A层化身）
        ai_dead = dm_state.get("ai_character_dead", False)
        if ai_dead:
            parts.append(f"💀 {name}（{cls} Lv.{lv}）— 已死亡")
        else:
            parts.append(f"⚔️ {name}（{cls} Lv.{lv}）HP:{hp}/{max_hp} MP:{mp}/{max_mp} EXP:{exp}/{exp_next} 💰{gold}")

        # 用户角色
        uc = dm_state.get("user_character", {})
        uc_dead = dm_state.get("user_character_dead", False)
        if uc and uc.get("class_name"):
            uc_name = uc.get("name", "用户")
            uc_cls = uc.get("class_name", "")
            uc_lv = uc.get("level", 1)
            uc_hp = uc.get("hp", 0)
            uc_max_hp = uc.get("max_hp", 0)
            uc_mp = uc.get("mp", 0)
            uc_max_mp = uc.get("max_mp", 0)
            if uc_dead:
                parts.append(f"💀 {uc_name}（{uc_cls} Lv.{uc_lv}）— 已死亡")
            else:
                parts.append(f"👤 {uc_name}（{uc_cls} Lv.{uc_lv}）HP:{uc_hp}/{uc_max_hp} MP:{uc_mp}/{uc_max_mp}")

        # 死亡悬停提示
        if dm_state.get("death_pending"):
            who = dm_state.get("death_who", "ai")
            dead_name = name if who == "ai" else uc.get("name", "用户")
            last_words = dm_state.get("last_words", "")
            parts.append(f"🪦 {dead_name}已倒下——临终遗言：「{last_words}」")
            parts.append("回复「继续」独自冒险，或「结束」让冒险落幕")

        # 装备
        equipment = char.get("equipment", [])
        if equipment:
            eq_parts = []
            for eq in equipment:
                type_icon = {"weapon": "🗡️", "outfit": "🛡️"}.get(eq.get("type", ""), "📦")
                rarity = eq.get("rarity_name", "")
                eq_parts.append(f"{type_icon}{eq.get('name', '?')}")
            parts.append("装备：" + "、".join(eq_parts))

        # 背包
        shared_inv = dm_state.get("shared_inventory", [])
        if shared_inv:
            inv_names = [i.get("name", "?") for i in shared_inv[:5]]
            inv_str = "、".join(inv_names) + (f" 等{len(shared_inv)}件" if len(shared_inv) > 5 else "")
            parts.append(f"🎒 背包({len(shared_inv)})：{inv_str}")

        # 地点（从地图信息中获取更详细的信息）
        location = story.get("current_location", "")
        if location:
            parts.append(f"📍 {location}")

        # 地图信息：当前区域、怪物、BOSS、可达区域
        world_map_data = dm_state.get("world_map", {})
        if world_map_data:
            current_region_id = world_map_data.get("current_region_id", "")
            regions = world_map_data.get("regions", {})
            current_region = regions.get(current_region_id, {})

            if current_region:
                # 当前区域怪物
                monsters = current_region.get("monsters", [])
                if monsters:
                    m_names = [m.get("name", "?") for m in monsters]
                    parts.append(f"👹 出没：{'、'.join(m_names)}")

                # BOSS
                boss = current_region.get("boss")
                if boss and not current_region.get("boss_defeated", False):
                    parts.append(f"💀 BOSS：{boss.get('name', '?')}")

                # 可达区域
                connections = current_region.get("connections", [])
                if connections:
                    adj_names = []
                    for cid in connections:
                        cr = regions.get(cid, {})
                        if cr:
                            cname = cr.get("name", "?")
                            explored = cr.get("explored", False)
                            danger = cr.get("danger_level", 0)
                            danger_str = "★" * danger if danger else "安全"
                            if explored:
                                adj_names.append(f"{cname}({danger_str})")
                            else:
                                adj_names.append("❓未知")
                    if adj_names:
                        parts.append(f"🗺️ 可达：{'、'.join(adj_names)}")

        # 当前区域NPC
        npc_data = dm_state.get("npc_system", {})
        if npc_data and current_region_id:
            npcs = npc_data.get("npcs", {})
            local_npcs = []
            for nid, ndata in npcs.items():
                if ndata.get("location") == current_region_id and ndata.get("alive", True):
                    nname = ndata.get("name", "?")
                    nrole = ndata.get("role", "")
                    relation = ndata.get("relationship", 0)
                    if relation >= 20:
                        rel_label = "友好"
                    elif relation >= -20:
                        rel_label = "中立"
                    else:
                        rel_label = "敌对"
                    trade = "💰" if ndata.get("can_trade") else ""
                    quest = "📋" if ndata.get("can_quest") and not ndata.get("quest_given") else ""
                    local_npcs.append(f"{nname}({nrole},{rel_label}){trade}{quest}")
            if local_npcs:
                parts.append(f"👥 人物：{'、'.join(local_npcs)}")

        # NPC死亡记录
        npc_deaths = dm_state.get("npc_death_records", [])
        if npc_deaths:
            recent_deaths = npc_deaths[-3:]
            death_names = [f"{d.get('name','?')}({d.get('role','?')})" for d in recent_deaths]
            parts.append(f"💀 已故：{'、'.join(death_names)}")

        # 战斗状态
        if dm_state.get("in_combat"):
                enemies = dm_state.get("enemies", [])
                if enemies:
                    alive = [f"{e.get('name','?')}(HP:{e.get('hp',0)}/{e.get('max_hp',0)})" for e in enemies if e.get("hp",0) > 0]
                    if alive:
                        parts.append(f"⚠️ 战斗中！敌人：{'、'.join(alive)}")
                        # 显示可用战术
                        try:
                            from simlife.backend.combat_system import TacticalSystem
                            tactics = TacticalSystem.get_available_tactics(dm_state)
                            if tactics:
                                tactic_str = "、".join([f"{t['icon']}{t['name']}" for t in tactics[:3]])
                                parts.append(f"可用战术：{tactic_str}")
                        except Exception:
                            pass
                        parts.append("（和AI讨论策略，AI会自主决策战斗）")

        # 当前场景
        scene = story.get("scene_description", "")
        if scene:
            parts.append(f"📋 {scene[:120]}")

        # 可选行动
        choices = story.get("choices", [])
        if choices:
            choice_lines = []
            for c in choices:
                risk_label = {"low": "低风险", "medium": "中风险", "high": "高风险"}.get(c.get("risk", ""), "")
                choice_lines.append(f"  {c['id']}. {c['text']} ({risk_label})")
            parts.append("可选行动：\n" + "\n".join(choice_lines))
        elif not dm_state.get("in_combat"):
            parts.append("（说「继续」探索新场景）")

        # 天数
        parts.append(f"📅 第{dm_state.get('play_time_days', 1)}天")

        return "──── ☠️ 死亡模式 ────\n" + "\n".join(parts)

    def _get_config(self, key, default=None):
        """从配置文件读取值，带缓存"""
        if not self._cfg:
            try:
                from desktop.config import load_config
                self._cfg = load_config()
            except Exception:
                self._cfg = {}
        return self._cfg.get(key, default)

    @staticmethod
    def _should_think(thinking_mode: str, complexity: str, task_type: str) -> bool:
        """根据模式、感知复杂度和任务类型决定是否开启思考模式"""
        if thinking_mode == "always_on":
            return True
        if thinking_mode == "always_off":
            return False
        # auto 模式：感知层 simple → 不思考，complex → 思考；task 类型强制思考
        if task_type == "task":
            return True
        return complexity != "simple"

    def _reason(self, user_input, emotion, memory_context, task_type,
                profile_context: str = "", current_uid: str = "default",
                current_user_name: str = "",
                thinking_mode: str = "auto", complexity: str = "complex") -> Dict:
        emotion_desc = (
            f"{emotion.primary.value}（强度{emotion.intensity:.1f}，"
            f"{'正面' if emotion.valence > 0 else '负面' if emotion.valence < 0 else '中性'}）"
        )

        # 从记忆系统获取最近大纲（按时间排序，帮助理解"再读一下"等指代）
        recent_context = ""
        if self.memory:
            try:
                recent_memories = self.memory.store.get_recent(
                    top_k=6,
                    level=MemoryLevel.SUMMARY,
                    user_id=current_uid
                )
                if recent_memories:
                    lines = [f"- {m.content[:150]}" for m in recent_memories]
                    recent_context = (
                        f"【最近记忆（按时间，帮助你理解上下文指代）】\n"
                        + "\n".join(lines) + "\n"
                    )
            except Exception:
                pass

        # 追加最近几轮原始对话（帮助理解指代和判断任务连续性）
        if self.conversation_history:
            recent_conv = self.conversation_history[-6:]
            conv_lines = ["（注：[我主动发送的消息]和[我主动分享的图片]是你之前主动发给用户的，不是用户发的）"]
            for m in recent_conv:
                role = m.get("user_name") if m["role"] == "user" else self.personality.name
                conv_lines.append(f"{role}：{m['content'][:300]}")
            conv_text = "\n".join(conv_lines)
            if recent_context:
                recent_context += f"\n【最近对话（帮助你理解上下文指代和任务连续性）】\n{conv_text}\n"
            else:
                recent_context = f"【最近对话（帮助你理解上下文指代和任务连续性）】\n{conv_text}\n"

        prompt = REASONING_PROMPT.format(
            name=self.personality.name,
            current_user_name=current_user_name or "未知用户",
            personality=self.personality.to_prompt_description(),
            profile_context=profile_context or "（用户画像建立中）",
            memory_context=memory_context,
            user_input=user_input,
            task_type=task_type,
            emotion_desc=emotion_desc,
            recent_context=recent_context,
            current_time=datetime.now().strftime("%Y年%m月%d日 %H:%M")
        )
        raw = self.b.generate(prompt, max_tokens=800, temperature=0.5,
                             thinking=self._should_think(thinking_mode, complexity, task_type))
        return self._parse_json(raw, {
            "inner_reasoning":  "需要认真考虑",
            "response_intent":  "给出真实的回应",
            "response_tone":    self.personality.speech_style,
            "need_tools":       False,
            "tool_task":        "",
            "storage_decision": {"should_store": False, "reason": "解析失败"}
        })

    def _generate_response(
        self, user_input, memory_context,
        inner_reasoning, response_intent,
        response_tone, tool_result_section,
        profile_context: str = "",
        current_user_name: str = ""
    ) -> str:
        # 使用完整对话历史（最多 HISTORY_SEND_LIMIT 条）
        history_section = ""
        if self.conversation_history:
            recent = self.conversation_history[-HISTORY_SEND_LIMIT:]
            lines = ["（注：[我主动发送的消息]和[我主动分享的图片]是你之前主动发给用户的，不是用户发的）"]
            for m in recent:
                role = m.get("user_name") if m["role"] == "user" else self.personality.name
                lines.append(f"{role}：{m['content']}")
            history_section = "【对话历史（最近{}轮）】\n{}\n".format(
                len(recent) // 2,
                "\n".join(lines)
            )

        prompt = RESPONSE_PROMPT.format(
            name=self.personality.name,
            current_user_name=current_user_name or "未知用户",
            personality=self.personality.to_prompt_description(),
            profile_context=profile_context or "（上下文加载中）",
            memory_context=memory_context,
            history_section=history_section,
            user_input=user_input,
            inner_reasoning=inner_reasoning,
            tool_result_section=tool_result_section,
            response_intent=response_intent,
            response_tone=response_tone,
            current_time=datetime.now().strftime("%Y年%m月%d日 %H:%M")
        )
        # 语言指令：让 AGI 用用户设定的语言回复
        try:
            from engine.i18n import get_system_lang_instruction
            lang_inst = get_system_lang_instruction()
            if lang_inst:
                prompt = lang_inst + "\n\n" + prompt
        except Exception:
            pass
        return self.b.generate(prompt, max_tokens=1200, temperature=0.75, thinking=False)

    def _parse_json(self, raw: str, fallback: Dict) -> Dict:
        try:
            match = re.search(r'\{[\s\S]*\}', raw)
            if match:
                return json.loads(match.group())
            return json.loads(raw)
        except Exception:
            return fallback

    def proactive_message(self) -> Optional[str]:
        """主动发起话题，返回消息或 None"""
        import random

        # 最近说过的主动消息（去重用）
        if not hasattr(self, '_proactive_history'):
            self._proactive_history: list[str] = []

        # 收集四类触发素材
        triggers = []

        # 1. 记忆里有未完成的事
        try:
            recent = self.memory.hierarchical_search(
                "未完成 待办 之后 下次 改天",
                summary_k=3, outline_k=2, detail_k=1,
                user_id=None,
            )
            mem_text = self.memory.format_for_prompt(recent)
            if mem_text and len(mem_text) > 20:
                triggers.append(("unfinished", mem_text[:300]))
        except Exception:
            pass

        # 2. 成长引擎有新认知沉淀
        try:
            if self.cognition:
                cog = self.cognition.format_for_prompt()
                if cog:
                    triggers.append(("cognition", cog[:300]))
        except Exception:
            pass

        # 3. 用户画像——今天未涉及的常聊话题
        try:
            if self.profile:
                profile_text = self.profile.format_for_prompt()
                if profile_text:
                    triggers.append(("profile", profile_text[:300]))
        except Exception:
            pass

        # 4. 人格设定找话题（兜底，总是有）
        triggers.append(("personality", self.personality.to_prompt_description()[:300]))

        # 5. SimLife 当前生活状态（角色正在经历的事）
        if self.simlife:
            try:
                simlife_text = self.simlife.format_for_prompt()
                if simlife_text:
                    triggers.append(("simlife", simlife_text[:400]))
            except Exception:
                pass

        # 随机选一个触发源
        trigger_type, trigger_content = random.choice(triggers)

        type_hints = {
            "unfinished":  "你们之前聊到过一些事但没有深入，自然地提起之前的话题",
            "cognition":   "你最近有一些新的感悟或想法想分享",
            "profile":     "根据你对用户的了解，找一个他平时可能感兴趣的具体话题来聊",
            "personality": "根据你自己的性格和兴趣，分享一个具体的想法、见闻或好奇心",
            "simlife":     "根据你当前正在做的事或今天经历的事，自然地跟用户分享你的见闻或感受",
        }

        # 构建去重提示
        recent_msgs = self._proactive_history[-6:]
        dedup_hint = ""
        if recent_msgs:
            dedup_hint = "\n\n你最近已经说过这些话，绝对不要重复类似的：\n" + "\n".join(f"- {m}" for m in recent_msgs)

        prompt = f"""你是{self.personality.name}，一个有独特人格的AI。
用户现在开着窗口但沉默了一段时间，你想主动说点什么。

{self.personality.to_prompt_description()}

当前模式：{type_hints[trigger_type]}
参考素材：
{trigger_content}

当前时间：{datetime.now().strftime("%Y年%m月%d日 %H:%M")}
{dedup_hint}

要求：
- 就说一句话或两句话，简短自然
- 像朋友随口说话，不要像AI在执行任务
- 不要用"您"，不要太正式
- 必须有实质内容或具体话题，不要只说"在想什么呢"这种空泛的话
- 语气要有变化：有时轻松调侃，有时正经分享，有时好奇提问，有时自言自语
- 如果觉得现在真的不适合开口，只输出：null
- 【主动加计划】如果你觉得某件事值得在未来提醒用户（如他之前提到的重要待办、容易忘记的事、需要跟进的事），在消息后面用 [SCHEDULE] 标记，格式：[SCHEDULE]content=内容|date=日期|time=时间|remind=提醒内容|source=system[/SCHEDULE]。date必填，其他可选。如果没有需要加的计划，不加标记。

直接输出要说的话，或者null。"""

        try:
            result = self.b.generate(prompt, max_tokens=150, temperature=1.0, thinking=False)
            result = result.strip()
            if not result or "null" in result.lower():
                return None

            schedule_text = ""
            if "[SCHEDULE]" in result and "[/SCHEDULE]" in result:
                import re as _re
                sch_match = _re.search(r'\[SCHEDULE\](.*?)\[/SCHEDULE\]', result)
                if sch_match:
                    schedule_text = sch_match.group(1)
                result = _re.sub(r'\[SCHEDULE\].*?\[/SCHEDULE\]', '', result).strip()

            result = result.strip('"').strip('"').strip('"')

            if len(result) < 3:
                return None

            for old in self._proactive_history[-3:]:
                if self._similar(result, old):
                    return None

            self._proactive_history.append(result)
            if len(self._proactive_history) > 10:
                self._proactive_history = self._proactive_history[-10:]

            if schedule_text:
                try:
                    sch_params = {}
                    for pair in schedule_text.split("|"):
                        if "=" in pair:
                            k, v = pair.split("=", 1)
                            sch_params[k.strip()] = v.strip()
                    if sch_params.get("content") and sch_params.get("date"):
                        from engine.tools import execute_tool
                        sch_result = execute_tool("add_schedule", {
                            "content": sch_params.get("content", ""),
                            "date": sch_params.get("date", ""),
                            "time": sch_params.get("time", ""),
                            "remind": sch_params.get("remind", ""),
                            "action": sch_params.get("action", ""),
                            "repeat": sch_params.get("repeat", "once"),
                            "category": sch_params.get("category", "personal"),
                            "source": sch_params.get("source", "system"),
                        })
                        if sch_result.get("ok"):
                            self._log("主动计划", f"已添加: {sch_result.get('message', '')}")
                except Exception as e:
                    self._log("主动计划", f"添加失败: {e}")

            return result
        except Exception:
            return None

    @staticmethod
    def _similar(a: str, b: str) -> bool:
        """简单判断两句话是否太相似"""
        a, b = a.lower(), b.lower()
        # 完全包含关系
        if a in b or b in a:
            return True
        # 公共词占比
        words_a = set(a)
        words_b = set(b)
        if not words_a or not words_b:
            return False
        common = words_a & words_b
        return len(common) / max(len(words_a), len(words_b)) > 0.7

    def get_emotional_state(self) -> str:
        e = self.current_emotion
        return (
            f"{e.primary.value} | 强度:{e.intensity:.2f} | "
            f"{'正向' if e.valence > 0 else '负向' if e.valence < 0 else '中性'}"
        )
