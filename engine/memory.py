"""
分层记忆系统
SQLite 存储 + 余弦相似度向量检索
可替换为 ChromaDB：pip install chromadb 后修改 MemoryStore 类
"""

import sqlite3
from engine.db_guard import guarded_connect
import json
import math
import hashlib
import uuid
import os
import numpy as np
from typing import List, Optional, Tuple, Dict, Any
from datetime import datetime, timedelta
from pathlib import Path

from engine.models import (
    MemoryNode, MemoryModality, MemoryLevel,
    EmotionState, EmotionType
)


def _embedding_to_blob(vec: List[float]) -> bytes:
    """向量 → float32 二进制 BLOB"""
    return np.array(vec, dtype=np.float32).tobytes()


def _blob_to_embedding(blob: bytes) -> List[float]:
    """float32 二进制 BLOB → 向量列表"""
    return np.frombuffer(blob, dtype=np.float32).tolist()


def cosine_similarity(a, b) -> float:
    """余弦相似度"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# ── 向量模型：自动检测可用方案 ─────────────────────
_embedding_model = None
_embedding_mode  = "hash"   # "transformer" | "hash"


def _local_model_path(model_name: str) -> Optional[str]:
    """返回模型在本机 HF 缓存的完整快照目录（含 config.json），无缓存则 None。

    路径形如：<cache>/models--<org>--<name>/snapshots/<commit>。
    必须传完整 repo id（含组织前缀），因为缓存目录名是 models--sentence-transformers--...。
    """
    cache_root = os.environ.get("HF_HUB_CACHE") or os.path.join(
        os.path.expanduser("~"), ".cache", "huggingface", "hub")
    repo_dir = os.path.join(cache_root, "models--" + model_name.replace("/", "--"))
    # 优先用 refs/main 指向的 commit 快照
    refs_file = os.path.join(repo_dir, "refs", "main")
    if os.path.isfile(refs_file):
        commit = open(refs_file).read().strip()
        snap = os.path.join(repo_dir, "snapshots", commit)
        if os.path.isfile(os.path.join(snap, "config.json")):
            return snap
    # 兜底：扫描 snapshots，返回第一个含 config.json 的快照目录
    snaps = os.path.join(repo_dir, "snapshots")
    if os.path.isdir(snaps):
        for root, _, files in os.walk(snaps):
            if "config.json" in files:
                return root
    return None


def _model_cached(model_name: str) -> bool:
    """模型是否已完整缓存在本地 HF 缓存（snapshots 下含权重文件）"""
    return _local_model_path(model_name) is not None


def _init_embedding():
    """启动时检测 sentence-transformers，有则使用，没有降级到哈希"""
    global _embedding_model, _embedding_mode
    try:
        # 先测试 torch 是否能正常加载（Python 3.14 下 DLL 可能失败）
        import importlib
        try:
            import torch  # noqa: F401
        except Exception:
            raise ImportError("torch 不可用，跳过 sentence-transformers")

        from sentence_transformers import SentenceTransformer
        # 必须带组织前缀 "sentence-transformers/"：缓存目录名是
        # models--sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2，
        # 缺前缀会判"未缓存"，进而联网超时降级。
        model_name = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
        # 关键：缓存命中时必须喂【本地目录路径】而不是 repo id。
        # 新版 transformers 对非本地路径会在 tokenizer 加载时走 is_base_mistral → model_info
        # 联网查询，即使传了 local_files_only 也会 HTTP 超时/OfflineModeIsEnabled，
        # 最终被静默降级到哈希。传本地路径后 _is_local=True，完全不联网。
        local_path = _local_model_path(model_name)
        try:
            if local_path:
                _embedding_model = SentenceTransformer(local_path)
            else:
                # 未缓存 → 首次联网下载
                _embedding_model = SentenceTransformer(model_name)
        except Exception:
            # 本地路径加载失败（缓存损坏等）：联网也救不了；未缓存下载失败同样直接降级
            raise
        _embedding_mode  = "transformer"
        print(f"✅ 语义向量：sentence-transformers ({local_path or model_name})")
    except ImportError:
        _embedding_mode = "hash"
        # 静默降级，不打印警告（用户不需要知道）
    except Exception:
        _embedding_mode = "hash"
        # DLL 错误等静默处理，不打印堆栈

# 懒加载：第一次使用 embedding 时才初始化，不在 import 时执行
_embedding_initialized = False

def _ensure_embedding():
    global _embedding_initialized
    if not _embedding_initialized:
        _embedding_initialized = True
        try:
            _init_embedding()
        except Exception as e:
            global _embedding_mode
            _embedding_mode = "hash"
            print(f"[Embedding] 初始化失败，降级到哈希模式: {e}")


def get_embedding(text: str, dim: int = 384) -> List[float]:
    _ensure_embedding()
    """
    获取文本向量
    有 sentence-transformers → 真实语义向量（dim=384）
    无 → 哈希向量（dim=128，仅供关键词匹配用）
    """
    if _embedding_mode == "transformer" and _embedding_model is not None:
        try:
            vec = _embedding_model.encode(text, normalize_embeddings=True)
            return vec.tolist()
        except Exception:
            pass   # 降级

    # 哈希散射向量（dim=128）
    actual_dim = 128
    vec = [0.0] * actual_dim
    for i, char in enumerate(text):
        idx = (ord(char) * 2654435761 + i * 40503) % actual_dim
        vec[idx] += 1.0 / (1 + i * 0.1)
    words = text.lower().split()
    for word in words:
        h = int(hashlib.md5(word.encode()).hexdigest(), 16)
        for j in range(4):
            idx = (h >> (j * 8)) % actual_dim
            vec[idx] += 0.5
    norm = math.sqrt(sum(x * x for x in vec))
    if norm > 0:
        vec = [x / norm for x in vec]
    return vec


# 向下兼容旧代码
def simple_embedding(text: str, dim: int = 128) -> List[float]:
    return get_embedding(text, dim)


class MemoryStore:
    """
    记忆存储核心
    SQLite 实现，接口设计与 ChromaDB 兼容
    """

    def __init__(self, db_path: str = "memory.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with guarded_connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    modality TEXT NOT NULL,
                    level TEXT NOT NULL,
                    emotion_json TEXT NOT NULL,
                    importance REAL NOT NULL,
                    tags_json TEXT,
                    associations_json TEXT,
                    source TEXT,
                    embedding_json TEXT,
                    created_at TEXT,
                    last_accessed TEXT,
                    access_count INTEGER DEFAULT 0,
                    decay_factor REAL DEFAULT 1.0,
                    user_id TEXT DEFAULT 'default'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS interactions (
                    id TEXT PRIMARY KEY,
                    user_input TEXT,
                    emotion_json TEXT,
                    memory_ids_json TEXT,
                    reasoning TEXT,
                    response TEXT,
                    storage_decision_json TEXT,
                    timestamp TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_modality ON memories(modality)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_level ON memories(level)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_importance ON memories(importance)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_user ON memories(user_id)")
            conn.commit()

        # 迁移：旧数据库没有 user_id / user_name 列时自动添加
        with guarded_connect(self.db_path) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()]
            if "user_id" not in cols:
                conn.execute("ALTER TABLE memories ADD COLUMN user_id TEXT DEFAULT 'default'")
                conn.commit()
            if "user_name" not in cols:
                conn.execute("ALTER TABLE memories ADD COLUMN user_name TEXT DEFAULT ''")
                conn.commit()

        # 迁移：interactions 表添加 user_id 列 + 索引
        with guarded_connect(self.db_path) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(interactions)").fetchall()]
            if "user_id" not in cols:
                conn.execute("ALTER TABLE interactions ADD COLUMN user_id TEXT DEFAULT 'default'")
                conn.commit()
            conn.execute("CREATE INDEX IF NOT EXISTS idx_interactions_user ON interactions(user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_interactions_time ON interactions(timestamp)")

        # 迁移：embedding_blob 列（JSON → 二进制 BLOB，加速检索）
        with guarded_connect(self.db_path) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()]
            if "embedding_blob" not in cols:
                conn.execute("ALTER TABLE memories ADD COLUMN embedding_blob BLOB")
                conn.commit()
                print("[Memory] 已添加 embedding_blob 列")

            # 灌入现有数据的 BLOB（从 embedding_json 转换）
            rows = conn.execute(
                "SELECT id, embedding_json FROM memories WHERE embedding_blob IS NULL AND embedding_json IS NOT NULL"
            ).fetchall()
            migrated = 0
            for mid, emb_json in rows:
                if emb_json:
                    try:
                        vec = json.loads(emb_json)
                        blob = _embedding_to_blob(vec)
                        conn.execute("UPDATE memories SET embedding_blob=? WHERE id=?", (blob, mid))
                        migrated += 1
                    except Exception:
                        pass
            if migrated > 0:
                conn.commit()
                print(f"[Memory] embedding_blob 迁移完成: {migrated} 条")

    def add(self, node: MemoryNode, user_id: str = "default", user_name: str = "") -> str:
        """添加记忆节点"""
        if not node.id:
            node.id = str(uuid.uuid4())
        if node.embedding is None:
            node.embedding = get_embedding(node.content)

        # 双写：embedding_json（回滚保险）+ embedding_blob（加速检索）
        emb_json = json.dumps(node.embedding)
        emb_blob = _embedding_to_blob(node.embedding) if node.embedding else None

        with guarded_connect(self.db_path) as conn:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()]
            if "embedding_blob" in cols:
                conn.execute("""
                    INSERT OR REPLACE INTO memories
                    (id,content,modality,level,emotion_json,importance,tags_json,associations_json,
                     source,embedding_json,created_at,last_accessed,access_count,decay_factor,user_id,user_name,embedding_blob)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    node.id, node.content, node.modality.value, node.level.value,
                    json.dumps(node.emotion.to_dict()),
                    node.importance,
                    json.dumps(node.tags),
                    json.dumps(node.associations),
                    node.source,
                    emb_json,
                    node.created_at, node.last_accessed,
                    node.access_count, node.decay_factor,
                    user_id, user_name, emb_blob
                ))
            elif "user_name" in cols:
                conn.execute("""
                    INSERT OR REPLACE INTO memories
                    (id,content,modality,level,emotion_json,importance,tags_json,associations_json,
                     source,embedding_json,created_at,last_accessed,access_count,decay_factor,user_id,user_name)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    node.id, node.content, node.modality.value, node.level.value,
                    json.dumps(node.emotion.to_dict()),
                    node.importance,
                    json.dumps(node.tags),
                    json.dumps(node.associations),
                    node.source,
                    emb_json,
                    node.created_at, node.last_accessed,
                    node.access_count, node.decay_factor,
                    user_id, user_name
                ))
            else:
                conn.execute("""
                    INSERT OR REPLACE INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (
                    node.id, node.content, node.modality.value, node.level.value,
                    json.dumps(node.emotion.to_dict()),
                    node.importance,
                    json.dumps(node.tags),
                    json.dumps(node.associations),
                    node.source,
                    emb_json,
                    node.created_at, node.last_accessed,
                    node.access_count, node.decay_factor,
                    user_id
                ))
            conn.commit()
        return node.id

    def get(self, memory_id: str) -> Optional[MemoryNode]:
        """按ID获取记忆"""
        with guarded_connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM memories WHERE id=?", (memory_id,)
            ).fetchone()
        return self._row_to_node(row) if row else None

    def search(
        self,
        query: str,
        top_k: int = 5,
        modality: Optional[MemoryModality] = None,
        level: Optional[MemoryLevel] = None,
        min_importance: float = 0.0,
        emotion_filter: Optional[EmotionType] = None,
        user_id: Optional[str] = None
    ) -> List[Tuple[MemoryNode, float]]:
        """
        语义检索记忆
        返回 (节点, 相似度分数) 列表，按分数降序
        user_id=None 时检索所有用户（兼容旧行为）
        """
        query_vec = get_embedding(query)

        # 构建查询条件
        conditions = ["decay_factor > 0.1"]
        params = []
        if modality:
            conditions.append("modality=?")
            params.append(modality.value)
        if level:
            conditions.append("level=?")
            params.append(level.value)
        if min_importance > 0:
            conditions.append("importance>=?")
            params.append(min_importance)
        if user_id is not None:
            conditions.append("(user_id=? OR user_id='default' OR user_id='system')")
            params.append(user_id)

        where = " AND ".join(conditions)

        with guarded_connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT * FROM memories WHERE {where}", params
            ).fetchall()

        # 计算相似度并排序
        scored = []
        for row in rows:
            node = self._row_to_node(row)
            if node and node.embedding:
                sim = cosine_similarity(query_vec, node.embedding)
                # 综合分数 = 语义相似度 * 重要性权重 * 衰减系数 * 情绪加成
                emotion_bonus = 1.0 + node.emotion.intensity * 0.3
                score = sim * node.effective_importance() * emotion_bonus
                if emotion_filter and node.emotion.primary != emotion_filter:
                    score *= 0.5
                scored.append((node, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def get_recent(
        self,
        top_k: int = 6,
        level: Optional[MemoryLevel] = None,
        user_id: Optional[str] = None
    ) -> List[MemoryNode]:
        """按时间倒序获取最近存储的记忆（不依赖语义匹配）"""
        conditions = []
        params: list = []
        if level:
            conditions.append("level=?")
            params.append(level.value)
        if user_id:
            conditions.append("user_id=?")
            params.append(user_id)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        with guarded_connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT * FROM memories {where} "
                f"ORDER BY created_at DESC LIMIT ?",
                (*params, top_k)
            ).fetchall()
        return [self._row_to_node(r) for r in rows if r]

    def log_interaction(
        self,
        user_input: str,
        response: str,
        user_id: str = "default",
    ):
        """记录每轮对话到 interactions 表（启动恢复用）"""
        with guarded_connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO interactions (id, user_input, response, timestamp, user_id) "
                "VALUES (?,?,?,?,?)",
                (
                    str(uuid.uuid4())[:12],
                    user_input[:2000],
                    response[:2000],
                    datetime.now().isoformat(),
                    user_id,
                )
            )
            conn.commit()

    def get_recent_interactions(
        self, limit: int = 10, user_id: str = "default"
    ) -> List[tuple]:
        """取最近 N 条对话记录（时间倒序），用于启动时恢复上下文"""
        with guarded_connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT user_input, response FROM interactions "
                "WHERE user_id=? ORDER BY timestamp DESC LIMIT ?",
                (user_id, limit)
            ).fetchall()
        return rows

    def get_last_user_msg_time(self, user_id: str = "default") -> Optional[str]:
        """取最后一条用户消息的时间戳，没有记录返回 None"""
        with guarded_connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT timestamp FROM interactions "
                "WHERE user_id=? ORDER BY timestamp DESC LIMIT 1",
                (user_id,)
            ).fetchone()
        return row[0] if row else None

    def get_interactions_by_date_range(
        self, start_date: str, end_date: str,
        user_id: str = "default"
    ) -> List[tuple]:
        """按日期范围取对话记录（时间正序），用于按时间回溯"""
        with guarded_connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT user_input, response, timestamp FROM interactions "
                "WHERE user_id=? AND timestamp >= ? AND timestamp <= ? "
                "ORDER BY timestamp ASC",
                (user_id, start_date, end_date)
            ).fetchall()
        return rows

    def get_by_date_range(
        self,
        start_date: str,
        end_date: str,
        level: Optional[MemoryLevel] = None,
        user_id: Optional[str] = None,
        top_k: int = 30,
    ) -> List[MemoryNode]:
        """按日期范围查询记忆（按时间倒序）"""
        conditions = ["created_at >= ?", "created_at <= ?"]
        params: list = [start_date, end_date]
        if level:
            conditions.append("level=?")
            params.append(level.value)
        if user_id:
            conditions.append("user_id=?")
            params.append(user_id)
        where = " AND ".join(conditions)
        with guarded_connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT * FROM memories WHERE {where} "
                f"ORDER BY created_at DESC LIMIT ?",
                (*params, top_k)
            ).fetchall()
        return [self._row_to_node(r) for r in rows if r]

    def search_by_level(
        self, query: str, level: MemoryLevel, top_k: int = 3,
        user_id: Optional[str] = None
    ) -> List[Tuple[MemoryNode, float]]:
        """按层级搜索"""
        return self.search(query, top_k=top_k, level=level, user_id=user_id)

    def get_siblings(self, summary_node_id: str) -> Dict[str, Optional[MemoryNode]]:
        """
        通过大纲节点ID，定向获取同一记忆的细纲和细节
        大纲ID格式：xxxx_summary → 找 xxxx_outline 和 xxxx_detail
        这是「大纲命中→精准展开」的核心方法
        """
        base_id = summary_node_id.replace("_summary", "").replace("_outline", "").replace("_detail", "")
        result = {"outline": None, "detail": None}
        for level_suffix in ("_outline", "_detail"):
            node = self.get(base_id + level_suffix)
            if node:
                key = level_suffix.lstrip("_")
                result[key] = node
        return result

    def get_by_base_ids(self, base_ids: List[str],
                        levels: List[str] = None) -> List[MemoryNode]:
        """
        批量按 base_id 前缀获取记忆节点
        用于大纲命中后批量拉取对应细纲/细节
        """
        if not base_ids:
            return []
        levels = levels or ["outline", "detail"]
        target_ids = []
        for bid in base_ids:
            clean = bid.replace("_summary","").replace("_outline","").replace("_detail","")
            for lv in levels:
                target_ids.append(f"{clean}_{lv}")

        if not target_ids:
            return []

        placeholders = ",".join("?" * len(target_ids))
        with guarded_connect(self.db_path) as conn:
            rows = conn.execute(
                f"SELECT * FROM memories WHERE id IN ({placeholders})",
                target_ids
            ).fetchall()
        nodes = [self._row_to_node(r) for r in rows]
        return [n for n in nodes if n is not None]

    def update_access(self, memory_id: str):
        """更新访问记录，同时回升衰减系数（被想起的记忆更难遗忘）"""
        with guarded_connect(self.db_path) as conn:
            conn.execute("""
                UPDATE memories
                SET last_accessed=?,
                    access_count=access_count+1,
                    decay_factor=MIN(1.0, decay_factor * 1.05)
                WHERE id=?
            """, (datetime.now().isoformat(), memory_id))
            conn.commit()

    def apply_decay(self, decay_rate: float = 0.995):
        """
        记忆衰减 - 模拟遗忘曲线
        三重保护：重要性高 + 情绪强烈 + 最近访问过 → 衰减更慢
        被检索时 update_access 已让 decay_factor 回升5%
        """
        from datetime import datetime as _dt
        now = _dt.now()
        with guarded_connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, importance, decay_factor, emotion_json, last_accessed FROM memories"
            ).fetchall()

            for row in rows:
                mid, importance, decay, emotion_json, last_accessed = row
                emotion = EmotionState.from_dict(json.loads(emotion_json))

                # 重要性 + 情绪保护
                protection = importance * 0.5 + emotion.intensity * 0.3

                # 最近访问保护：7天内访问过的记忆额外减缓衰减
                if last_accessed:
                    try:
                        days_ago = (now - _dt.fromisoformat(last_accessed)).days
                        if days_ago <= 7:
                            protection = min(1.0, protection + 0.2 * (1 - days_ago / 7))
                    except Exception:
                        pass

                actual_decay = decay_rate + protection * (1 - decay_rate) * 0.8
                new_decay = max(0.05, decay * actual_decay)
                conn.execute(
                    "UPDATE memories SET decay_factor=? WHERE id=?",
                    (new_decay, mid)
                )
            conn.commit()

    def get_stats(self) -> Dict[str, Any]:
        """获取记忆库统计"""
        with guarded_connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            by_level = conn.execute(
                "SELECT level, COUNT(*) FROM memories GROUP BY level"
            ).fetchall()
            by_modality = conn.execute(
                "SELECT modality, COUNT(*) FROM memories GROUP BY modality"
            ).fetchall()
            avg_importance = conn.execute(
                "SELECT AVG(importance) FROM memories"
            ).fetchone()[0]

        return {
            "total": total,
            "by_level": dict(by_level),
            "by_modality": dict(by_modality),
            "avg_importance": round(avg_importance or 0, 3)
        }

    def _row_to_node(self, row) -> Optional[MemoryNode]:
        if not row:
            return None
        try:
            user_name = row[15] if len(row) > 15 else ""
            # 优先从 embedding_blob 读取（快），回退到 embedding_json（兼容旧数据）
            embedding = None
            if len(row) > 16 and row[16]:
                embedding = _blob_to_embedding(row[16])
            elif row[9]:
                embedding = json.loads(row[9])
            return MemoryNode(
                id=row[0], content=row[1],
                modality=MemoryModality(row[2]),
                level=MemoryLevel(row[3]),
                emotion=EmotionState.from_dict(json.loads(row[4])),
                importance=row[5],
                tags=json.loads(row[6] or "[]"),
                associations=json.loads(row[7] or "[]"),
                source=row[8] or "conversation",
                user_id=row[14] if len(row) > 14 else "default",
                user_name=user_name,
                embedding=embedding,
                created_at=row[10], last_accessed=row[11],
                access_count=row[12], decay_factor=row[13]
            )
        except Exception:
            return None


class HierarchicalMemoryManager:
    """
    分层记忆管理器
    实现 大纲→细纲→细节 的渐进式检索
    """

    def __init__(self, store: MemoryStore):
        self.store = store

    def hierarchical_search(
        self, query: str, max_detail: int = 2
    ) -> Dict[str, List[Tuple[MemoryNode, float]]]:
        """
        分层检索：先查大纲，再按需展开
        返回各层级的检索结果
        """
        results = {}

        # 第一步：查大纲（最快，最少内容）
        summaries = self.store.search_by_level(query, MemoryLevel.SUMMARY, top_k=5)
        results["summary"] = summaries

        # 第二步：如果大纲相关，查细纲
        if summaries and summaries[0][1] > 0.3:
            outlines = self.store.search_by_level(query, MemoryLevel.OUTLINE, top_k=4)
            results["outline"] = outlines

            # 第三步：如果细纲高度相关，才展开细节
            if outlines and outlines[0][1] > 0.5:
                details = self.store.search_by_level(query, MemoryLevel.DETAIL, top_k=max_detail)
                results["detail"] = details

        return results

    def store_with_hierarchy(
        self,
        content: str,
        modality: MemoryModality,
        emotion: EmotionState,
        importance: float,
        tags: List[str] = None,
        source: str = "conversation"
    ) -> Dict[str, str]:
        """
        按重要性和情绪强度决定存储层级
        返回各层存储的节点ID
        """
        stored_ids = {}
        base_id = str(uuid.uuid4())[:8]

        # 规则：情绪强烈或重要性高 → 细节层
        if emotion.is_strong() or importance >= 0.8:
            node = MemoryNode(
                id=f"{base_id}_detail",
                content=content,
                modality=modality,
                level=MemoryLevel.DETAIL,
                emotion=emotion,
                importance=importance,
                tags=tags or [],
                source=source
            )
            stored_ids["detail"] = self.store.add(node)

        # 中等重要性 → 细纲层（摘要版本）
        if importance >= 0.4 or emotion.is_moderate():
            summary_content = content[:200] + "..." if len(content) > 200 else content
            node = MemoryNode(
                id=f"{base_id}_outline",
                content=summary_content,
                modality=modality,
                level=MemoryLevel.OUTLINE,
                emotion=emotion,
                importance=importance,
                tags=tags or [],
                source=source
            )
            stored_ids["outline"] = self.store.add(node)

        # 所有内容都存大纲（只存关键词/主题）
        keywords = " ".join(tags) if tags else content[:80]
        node = MemoryNode(
            id=f"{base_id}_summary",
            content=keywords,
            modality=modality,
            level=MemoryLevel.SUMMARY,
            emotion=emotion,
            importance=importance,
            tags=tags or [],
            source=source
        )
        stored_ids["summary"] = self.store.add(node)

        return stored_ids

    def format_for_prompt(
        self, results: Dict[str, List[Tuple[MemoryNode, float]]]
    ) -> str:
        """将检索结果格式化为 A 层可用的 prompt 片段"""
        if not results:
            return "（无相关记忆）"

        lines = ["【相关记忆】"]

        if "summary" in results and results["summary"]:
            lines.append("\n[大纲级]")
            for node, score in results["summary"][:3]:
                lines.append(f"  · {node.content} (重要性:{node.importance:.1f})")

        if "outline" in results and results["outline"]:
            lines.append("\n[细纲级]")
            for node, score in results["outline"][:2]:
                emotion_desc = f"{node.emotion.primary.value}({node.emotion.intensity:.1f})"
                lines.append(f"  · {node.content[:100]} [情绪:{emotion_desc}]")

        if "detail" in results and results["detail"]:
            lines.append("\n[细节级]")
            for node, score in results["detail"][:1]:
                lines.append(f"  · {node.content[:300]}")

        return "\n".join(lines)
