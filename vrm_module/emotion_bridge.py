"""
emotion_bridge.py — 情绪状态映射层（v2）

将 AGI-DPA 内部情绪状态（字符串/数值）映射为 Live2D 表情/动作参数。
主程序只需调用 translate() 即可获取 (表情名, 强度, 动作组)。
新增：
  - 动作推荐（每种情绪对应最佳动作组）
  - 副情绪支持（primary + secondary 混合）
  - 效价 valence 传递（影响 JS 端微表情）
"""

# AGI-DPA 情绪 → (Live2D 表情名, 基础强度, 推荐动作组)
EMOTION_MAP: dict[str, tuple[str, float, str]] = {
    # ── 正面情绪 ──
    "happy":        ("happy",     1.0, "tap"),
    "excited":      ("happy",     0.8, "tap"),
    "joy":          ("happy",     1.0, "tap"),
    "love":         ("love",      0.9, "tap"),
    "gratitude":    ("happy",     0.7, "flick"),
    "pride":        ("happy",     0.6, "flick_up"),
    "anticipation": ("happy",     0.4, "flick"),
    "trust":        ("neutral",   0.7, "idle"),

    # ── 负面情绪 ──
    "sad":          ("sad",       0.7, "flick_down"),
    "sadness":      ("sad",       0.8, "flick_down"),
    "angry":        ("angry",     0.6, "shake"),
    "anger":        ("angry",     0.8, "shake"),
    "fear":         ("fear",      0.6, "shake"),
    "anxious":      ("sad",       0.5, "flick_down"),
    "shame":        ("sad",       0.6, "flick_down"),
    "disgust":      ("disgust",   0.5, "shake"),

    # ── 中性/认知情绪 ──
    "neutral":      ("neutral",   1.0, "idle"),
    "calm":         ("neutral",   0.8, "idle"),
    "surprised":    ("surprised", 1.0, "flick_up"),
    "surprise":     ("surprised", 1.0, "flick_up"),
    "curious":      ("curious",   0.5, "flick_up"),
    "thinking":     ("thinking",  0.3, "flick3"),
    "confused":     ("surprised", 0.4, "flick"),
    "bored":        ("neutral",   0.5, "idle"),
    "nostalgic":    ("nostalgic", 0.3, "flick_down"),
}


def translate(emotion_key: str, intensity: float = 1.0) -> tuple[str, float]:
    """
    将 AGI-DPA 情绪 key 映射为 VRM 表情参数（向后兼容）。

    Args:
        emotion_key: 情绪字符串，如 "happy", "sad" 等
        intensity:   原始情绪强度 0~1

    Returns:
        (vrm_expression_name, vrm_intensity) 元组
    """
    name, base, _ = EMOTION_MAP.get(emotion_key.lower(), ("neutral", 1.0, "idle"))
    return name, base * intensity


def translate_full(emotion_key: str, intensity: float = 1.0) -> tuple[str, float, str]:
    """
    将 AGI-DPA 情绪 key 映射为完整 Live2D 参数。

    Args:
        emotion_key: 情绪字符串，如 "happy", "sad" 等
        intensity:   原始情绪强度 0~1

    Returns:
        (expression_name, intensity, motion_group) 元组
    """
    name, base, motion = EMOTION_MAP.get(emotion_key.lower(), ("neutral", 1.0, "idle"))
    return name, base * intensity, motion


def translate_with_secondary(
    primary: str,
    secondary: str | None = None,
    intensity: float = 1.0,
    valence: float = 0.0,
) -> dict:
    """
    映射主/副情绪为完整 Live2D 参数（用于 A 层人格感应）。

    Args:
        primary:    主情绪
        secondary:  副情绪（可选）
        intensity:  情绪强度 0~1
        valence:    效价 -1(负面) ~ 1(正面)

    Returns:
        dict: {expression, intensity, motion, secondary, valence}
    """
    name, base, motion = EMOTION_MAP.get(primary.lower(), ("neutral", 1.0, "idle"))
    result = {
        "expression": name,
        "intensity": base * intensity,
        "motion": motion,
        "secondary": None,
        "valence": valence,
    }

    if secondary:
        sec_name, sec_base, _ = EMOTION_MAP.get(secondary.lower(), ("neutral", 0.3, "idle"))
        result["secondary"] = sec_name

    return result
