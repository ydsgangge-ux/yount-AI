"""
AGI Web Chat — Claude 风格网页版
Flask + Flask-SocketIO 实现，共享同一个 ConsciousnessAgent 实例
由 main.py 调用 start_web_chat(agent, auth_manager) 启动
"""

import os
import json
import uuid
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from flask import Flask, request, session, jsonify, send_from_directory
from flask_socketio import SocketIO, emit
from engine.memory import MemoryStore

# ── 全局共享实例（由 start_web_chat 注入）─────────────────
_agent = None
_auth_manager = None
_scheduler = None

# ── Flask App ───────────────────────────────────────────
app = Flask(
    __name__,
    static_folder=os.path.join(os.path.dirname(__file__), "web", "static"),
    template_folder=os.path.join(os.path.dirname(__file__), "web", "templates"),
)
app.secret_key = os.environ.get("AGI_WEB_SECRET", uuid.uuid4().hex)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ── 聊天记录存储 ────────────────────────────────────────
CHAT_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "AGI-Desktop" / "web_chats"
CHAT_DIR.mkdir(parents=True, exist_ok=True)


def _get_chat_file(user_id: str) -> Path:
    safe_uid = user_id.replace("/", "_").replace("\\", "_")
    return CHAT_DIR / f"{safe_uid}.json"


def _load_chats(user_id: str) -> list:
    fp = _get_chat_file(user_id)
    if fp.exists():
        try:
            return json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_chats(user_id: str, chats: list):
    fp = _get_chat_file(user_id)
    fp.write_text(json.dumps(chats, ensure_ascii=False, indent=2), encoding="utf-8")


def _check_auth() -> Optional[dict]:
    uid = session.get("user_id")
    if not uid:
        return None
    return {"user_id": uid, "name": session.get("name", "")}


# ── HTTP 路由 ───────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(app.template_folder, "index.html")


@app.route("/api/login", methods=["POST"])
def login():
    global _auth_manager
    if not _auth_manager:
        return jsonify({"ok": False, "error": "认证服务未就绪"}), 503
    data = request.get_json(silent=True) or {}
    passphrase = data.get("passphrase", "").strip()
    if not passphrase:
        return jsonify({"ok": False, "error": "请输入密码短语"}), 400
    user = _auth_manager.verify_passphrase(passphrase)
    if not user:
        return jsonify({"ok": False, "error": "密码短语错误"}), 401
    session["user_id"] = user.user_id
    session["name"] = user.name
    return jsonify({"ok": True, "name": user.name, "user_id": user.user_id})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/me")
def me():
    info = _check_auth()
    if not info:
        return jsonify({"ok": False, "error": "未登录"}), 401
    return jsonify({"ok": True, "name": info["name"], "user_id": info["user_id"]})


@app.route("/api/personality")
def get_personality():
    info = _check_auth()
    if not info:
        return jsonify({"ok": False, "error": "未登录"}), 401
    if not _agent:
        return jsonify({"ok": False, "error": "引擎未就绪"}), 503
    p = _agent.personality
    return jsonify({"ok": True, "personality": p.to_dict()})


@app.route("/api/personality", methods=["POST"])
def update_personality():
    info = _check_auth()
    if not info:
        return jsonify({"ok": False, "error": "未登录"}), 401
    if not _auth_manager or not _auth_manager.is_verified():
        return jsonify({"ok": False, "error": "需要身份验证"}), 403
    data = request.get_json(silent=True) or {}
    from desktop.config import PERSONALITY_FILE
    try:
        existing = {}
        if PERSONALITY_FILE.exists():
            existing = json.loads(PERSONALITY_FILE.read_text(encoding="utf-8"))
        existing.update(data)
        PERSONALITY_FILE.write_text(
            json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if _agent:
            from engine.models import PersonalityCore
            _agent.personality = PersonalityCore.from_dict(existing)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/chats")
def list_chats():
    info = _check_auth()
    if not info:
        return jsonify({"ok": False, "error": "未登录"}), 401
    chats = _load_chats(info["user_id"])
    summaries = []
    for c in chats:
        msgs = c.get("messages", [])
        first_user = ""
        for m in msgs:
            if m.get("role") == "user":
                first_user = m.get("content", "")[:60]
                break
        summaries.append({
            "id": c.get("id", ""),
            "title": c.get("title", first_user or "新对话"),
            "created_at": c.get("created_at", ""),
            "updated_at": c.get("updated_at", ""),
            "message_count": len(msgs),
        })
    return jsonify({"ok": True, "chats": summaries})


@app.route("/api/chats/<chat_id>")
def get_chat(chat_id):
    info = _check_auth()
    if not info:
        return jsonify({"ok": False, "error": "未登录"}), 401
    chats = _load_chats(info["user_id"])
    for c in chats:
        if c.get("id") == chat_id:
            return jsonify({"ok": True, "chat": c})
    return jsonify({"ok": False, "error": "对话不存在"}), 404


@app.route("/api/chats/<chat_id>", methods=["DELETE"])
def delete_chat(chat_id):
    info = _check_auth()
    if not info:
        return jsonify({"ok": False, "error": "未登录"}), 401
    chats = _load_chats(info["user_id"])
    chats = [c for c in chats if c.get("id") != chat_id]
    _save_chats(info["user_id"], chats)
    return jsonify({"ok": True})


@app.route("/api/images/<path:filename>")
def serve_image(filename):
    from engine.image_gen import get_image_dir
    return send_from_directory(str(get_image_dir()), filename)


@app.route("/api/timed-tasks")
def list_timed_tasks():
    info = _check_auth()
    if not info:
        return jsonify({"ok": False, "error": "未登录"}), 401
    if not _scheduler:
        return jsonify({"ok": False, "error": "调度器未就绪"}), 503
    tasks = _scheduler.list_tasks(status="pending")
    return jsonify({"ok": True, "tasks": tasks})


# ── WebSocket 事件 ──────────────────────────────────────
@socketio.on("connect")
def on_connect():
    pass

@socketio.on("login")
def on_login(data):
    global _auth_manager
    if not _auth_manager:
        emit("auth_result", {"ok": False, "error": "认证服务未就绪"})
        return
    passphrase = (data.get("passphrase") or "").strip()
    if not passphrase:
        emit("auth_result", {"ok": False, "error": "请输入密码短语"})
        return
    user = _auth_manager.verify_passphrase(passphrase)
    if not user:
        emit("auth_result", {"ok": False, "error": "密码短语错误"})
        return
    session["user_id"] = user.user_id
    session["name"] = user.name
    emit("auth_result", {"ok": True, "name": user.name, "user_id": user.user_id})

@socketio.on("logout")
def on_logout():
    session.clear()
    emit("auth_result", {"ok": False, "error": "已退出"})

@socketio.on("chat:message")
def on_chat_message(data):
    info = _check_auth()
    if not info:
        emit("error", {"message": "未登录"})
        return
    if not _agent:
        emit("error", {"message": "引擎未就绪"})
        return

    message = data.get("message", "").strip()
    chat_id = data.get("chat_id", "")
    if not message:
        return

    user_id = info["user_id"]

    chats = _load_chats(user_id)
    chat = None
    if chat_id:
        for c in chats:
            if c.get("id") == chat_id:
                chat = c
                break
    if not chat:
        chat_id = uuid.uuid4().hex[:12]
        chat = {
            "id": chat_id,
            "title": message[:40],
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "messages": [],
        }
        chats.insert(0, chat)

    chat["messages"].append({
        "role": "user",
        "content": message,
        "timestamp": datetime.now().isoformat(),
    })

    emit("chat:typing", {"chat_id": chat_id})

    try:
        result = _agent.process(message, user_id=user_id)
        reply = result.get("response", str(result))
        tool_steps = result.get("tool_steps", [])
        tools_used = result.get("tools_used", [])
        emotion = result.get("emotion", {})
    except Exception as e:
        reply = f"引擎错误：{e}"
        tool_steps = []
        tools_used = []
        emotion = {}

    ai_msg = {
        "role": "assistant",
        "content": reply,
        "timestamp": datetime.now().isoformat(),
        "tool_steps": tool_steps,
        "tools_used": tools_used,
        "emotion": emotion,
    }
    chat["messages"].append(ai_msg)
    chat["updated_at"] = datetime.now().isoformat()

    _save_chats(user_id, chats)

    emit("chat:reply", {
        "chat_id": chat_id,
        "message": ai_msg,
    })

    if not data.get("chat_id"):
        emit("chat:created", {
            "chat_id": chat_id,
            "title": chat["title"],
        })


@socketio.on("chat:stop")
def on_chat_stop(data):
    emit("chat:stopped", {"chat_id": data.get("chat_id", "")})


@socketio.on("get_chat_list")
def on_get_chat_list():
    info = _check_auth()
    if not info:
        emit("chat:list", [])
        return
    chats = _load_chats(info["user_id"])
    result = []
    for c in chats:
        result.append({
            "id": c.get("id", ""),
            "title": c.get("title", "新对话"),
            "created_at": c.get("created_at", ""),
            "updated_at": c.get("updated_at", ""),
            "message_count": len(c.get("messages", [])),
            "starred": c.get("starred", False),
        })
    emit("chat:list", result)


@socketio.on("load_chat")
def on_load_chat(data):
    info = _check_auth()
    if not info:
        emit("error", {"message": "未登录"})
        return
    chat_id = data.get("chat_id", "")
    chats = _load_chats(info["user_id"])
    for c in chats:
        if c.get("id") == chat_id:
            emit("chat:loaded", {
                "chat_id": c["id"],
                "title": c.get("title", "新对话"),
                "messages": c.get("messages", []),
            })
            return
    emit("error", {"message": "对话不存在"})


@socketio.on("delete_chat")
def on_delete_chat(data):
    info = _check_auth()
    if not info:
        emit("error", {"message": "未登录"})
        return
    chat_id = data.get("chat_id", "")
    chats = _load_chats(info["user_id"])
    chats = [c for c in chats if c.get("id") != chat_id]
    _save_chats(info["user_id"], chats)
    emit("chat:list", [])


@socketio.on("rename_chat")
def on_rename_chat(data):
    info = _check_auth()
    if not info:
        return
    chat_id = data.get("chat_id", "")
    title = (data.get("title") or "").strip()
    if not chat_id or not title:
        return
    chats = _load_chats(info["user_id"])
    for c in chats:
        if c.get("id") == chat_id:
            c["title"] = title
            break
    _save_chats(info["user_id"], chats)


@socketio.on("list_timed_tasks")
def on_list_timed_tasks():
    tasks = []
    if _scheduler:
        for status in ["pending", "done", "cancelled", "expired"]:
            tasks.extend(_scheduler.list_tasks(status=status))
    emit("timed_task_list", tasks)


@socketio.on("get_tool_list")
def on_get_tool_list():
    tools = []
    try:
        from engine.tools import TOOL_REGISTRY
        for name, info in TOOL_REGISTRY.items():
            schema = info.get("schema", {})
            desc = schema.get("description", "")
            risk = info.get("risk", "low")
            params = schema.get("input_schema", {}).get("properties", {})
            param_names = list(params.keys())
            tools.append({
                "name": name,
                "description": desc,
                "risk": risk,
                "params": param_names,
            })
    except Exception:
        pass
    emit("tool_list", tools)


# ── 定时任务推送 ────────────────────────────────────────
def _on_timed_task_for_web(task: dict):
    """定时任务触发时，通过 SocketIO 推送到所有已连接的 Web 客户端"""
    action = task.get("action", "speak")
    content = task.get("content", "")
    params = task.get("action_params", {})
    if action == "speak":
        message = params.get("message", content)
    elif action == "tool":
        message = f"（定时任务）执行了 {params.get('tool_name', '工具')}"
    else:
        message = content
    socketio.emit("timed:reminder", {
        "message": message,
        "task_content": content,
        "timestamp": datetime.now().isoformat(),
    })


# ── 对外启动接口 ────────────────────────────────────────
def start_web_chat(agent, auth_manager, scheduler=None, host="0.0.0.0", port=18766):
    """在 daemon 线程里启动 Flask-SocketIO 服务，不阻塞 Qt 主线程"""
    global _agent, _auth_manager, _scheduler
    _agent = agent
    _auth_manager = auth_manager
    _scheduler = scheduler

    def _run():
        try:
            import socket
            ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            ip = "本机IP"
        print(f"\n🌐 网页版访问 → http://{ip}:{port}")
        print(f"💻 本机访问 → http://localhost:{port}")
        print(f"🔑 登录方式：桌面端密码短语\n")
        socketio.run(app, host=host, port=port, allow_unsafe_werkzeug=True, log_output=False)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t
