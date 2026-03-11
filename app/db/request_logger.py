"""
请求日志数据库模块（SQLite）

记录每次搜索请求的关键信息，用于后续分析和审计。
表结构：
  - id            INTEGER  自增主键
  - agent_id      TEXT     代理人号
  - query         TEXT     自然语言原始问题（结构化搜索为空字符串）
  - request_payload TEXT   请求入参（JSON）
  - result_data   TEXT     返回结果中最多 3 条客户数据（JSON）
  - matched_level INTEGER  命中层级（1-4）
  - confidence    REAL     置信度
  - request_time  TEXT     请求时间（ISO 8601）
"""

import json
import sqlite3
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from loguru import logger

# 数据库文件路径：项目根目录下 logs/requests.db
_DB_PATH = Path(__file__).parent.parent.parent / "logs" / "requests.db"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS search_requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT    NOT NULL,
    query           TEXT    NOT NULL DEFAULT '',
    request_payload TEXT    NOT NULL DEFAULT '{}',
    result_data     TEXT    NOT NULL DEFAULT '[]',
    matched_level   INTEGER NOT NULL DEFAULT 0,
    confidence      REAL    NOT NULL DEFAULT 0.0,
    request_time    TEXT    NOT NULL
)
"""

_INSERT_SQL = """
INSERT INTO search_requests
    (agent_id, query, request_payload, result_data, matched_level, confidence, request_time)
VALUES (?, ?, ?, ?, ?, ?, ?)
"""


def _init_db(db_path: Path) -> None:
    """初始化数据库，创建表（如不存在）。"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(_CREATE_TABLE_SQL)
        conn.commit()
    finally:
        conn.close()


def _write_sync(
    db_path: Path,
    agent_id: str,
    query: str,
    request_payload: Dict[str, Any],
    result_list: List[Any],
    matched_level: int,
    confidence: float,
    request_time: str,
) -> None:
    """同步写入一条日志记录（在线程池中执行）。"""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            _INSERT_SQL,
            (
                agent_id,
                query,
                json.dumps(request_payload, ensure_ascii=False),
                json.dumps(result_list[:3], ensure_ascii=False),
                matched_level,
                confidence,
                request_time,
            ),
        )
        conn.commit()
    finally:
        conn.close()


class RequestLogger:
    """异步请求日志记录器（SQLite 后端）。"""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or _DB_PATH
        _init_db(self._db_path)
        logger.info(f"RequestLogger initialized: {self._db_path}")

    async def log(
        self,
        *,
        agent_id: str,
        query: str,
        request_payload: Dict[str, Any],
        response_data: Dict[str, Any],
        matched_level: int = 0,
        confidence: float = 0.0,
    ) -> None:
        """
        异步记录一条请求日志。

        Args:
            agent_id:        代理人号
            query:           自然语言原始问题
            request_payload: 请求入参字典
            response_data:   搜索响应的 data 字段（含 list / total）
            matched_level:   命中层级
            confidence:      置信度
        """
        result_list: List[Any] = []
        if isinstance(response_data, dict):
            result_list = response_data.get("list", []) or []

        request_time = datetime.now().isoformat(timespec="seconds")

        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                _write_sync,
                self._db_path,
                agent_id,
                query,
                request_payload,
                result_list,
                matched_level,
                confidence,
                request_time,
            )
        except Exception as e:
            # 日志写入失败不应影响主流程
            logger.warning(f"RequestLogger write failed: {e}")


# 全局单例
_request_logger: Optional[RequestLogger] = None


def get_request_logger() -> RequestLogger:
    global _request_logger
    if _request_logger is None:
        _request_logger = RequestLogger()
    return _request_logger
