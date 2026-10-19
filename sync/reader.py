"""他ユーザーDBを読み取り専用・即closeで読み込むモジュール。"""
from __future__ import annotations
import sqlite3
from pathlib import Path


def load_db_snapshot(db_path: Path) -> dict | None:
    """RO接続でDB全体を読み取り、dictで返す。失敗・ロック中はNone。"""
    uri = f"file:{db_path.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=3)
        conn.row_factory = sqlite3.Row
        data = {
            "workers": [dict(r) for r in conn.execute(
                "SELECT * FROM workers ORDER BY name"
            )],
            "tasks": [dict(r) for r in conn.execute(
                "SELECT * FROM tasks ORDER BY title"
            )],
            "schedules": [dict(r) for r in conn.execute(
                "SELECT s.*, w.name AS worker_name, t.title AS task_title"
                " FROM schedules s"
                " JOIN workers w ON s.worker_id = w.id"
                " JOIN tasks   t ON s.task_id   = t.id"
            )],
            "actuals": [dict(r) for r in conn.execute(
                "SELECT a.*, w.name AS worker_name, t.title AS task_title"
                " FROM actuals a"
                " JOIN workers w ON a.worker_id = w.id"
                " JOIN tasks   t ON a.task_id   = t.id"
            )],
        }
        conn.close()   # Box Drive がファイルを掴めるよう即座にclose
        return data
    except Exception:
        return None    # ロック中・破損・未存在 → 前回キャッシュをそのまま維持
