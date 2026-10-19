"""全ユーザーDBのデータをマージして保持するスレッドセーフなメモリキャッシュ。"""
from __future__ import annotations
from pathlib import Path
from threading import Lock


class SharedDataCache:

    def __init__(self):
        self._lock = Lock()
        self._snapshots: dict[str, dict] = {}   # db_stem -> snapshot

    # ── 更新 ─────────────────────────────────────────────────────────────────

    def update(self, db_path: Path, snapshot: dict):
        with self._lock:
            self._snapshots[db_path.stem] = snapshot

    def remove(self, db_path: Path):
        with self._lock:
            self._snapshots.pop(db_path.stem, None)

    # ── 参照 ─────────────────────────────────────────────────────────────────

    def sources(self) -> list[str]:
        with self._lock:
            return list(self._snapshots.keys())

    def get_all_schedules(self) -> list[dict]:
        with self._lock:
            result = []
            for source, snap in self._snapshots.items():
                for s in snap.get("schedules", []):
                    row = dict(s)
                    row["_source"] = source
                    row["_uid"]    = f"{source}:{s['id']}"
                    result.append(row)
            return result

    def get_all_actuals(self) -> list[dict]:
        with self._lock:
            result = []
            for source, snap in self._snapshots.items():
                for a in snap.get("actuals", []):
                    row = dict(a)
                    row["_source"] = source
                    row["_uid"]    = f"{source}:{a['id']}"
                    result.append(row)
            return result

    def get_all_workers(self) -> list[dict]:
        with self._lock:
            result = []
            for source, snap in self._snapshots.items():
                for w in snap.get("workers", []):
                    row = dict(w)
                    row["_source"] = source
                    row["_uid"]    = f"{source}:{w['id']}"
                    result.append(row)
            return result


# モジュールレベルのシングルトン（アプリ全体で共有）
shared_cache = SharedDataCache()
