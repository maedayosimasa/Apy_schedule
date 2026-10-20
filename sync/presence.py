"""共有フォルダ内の「誰がどのDBをメインで開いているか」をロックファイルで管理する。

各ユーザーはメインで開いている間 `<ユーザー名>.lock` を共有フォルダに置き、
一定間隔で heartbeat を更新する。Box Drive がこのファイルを同期するので、
他のPCからも「使用中」が見える。異常終了で残ったロックは STALE_SEC 経過で無効扱い。
"""
from __future__ import annotations
import json
import os
import socket
from datetime import datetime
from pathlib import Path

from sync.auth import user_has_password
from sync.reader import load_db_snapshot

LOCK_SUFFIX  = ".lock"
STALE_SEC    = 180          # heartbeat がこれより古いロックは無効（異常終了の残骸）
HEARTBEAT_MS = 60 * 1000    # heartbeat 更新間隔


def _lock_path(folder: Path, user: str) -> Path:
    return folder / f"{user}{LOCK_SUFFIX}"


def _me() -> dict:
    return {"host": socket.gethostname(), "pid": os.getpid()}


def is_mine(lock: dict) -> bool:
    me = _me()
    return lock.get("host") == me["host"] and lock.get("pid") == me["pid"]


def read_lock(folder: Path, user: str) -> dict | None:
    """有効なロック情報を返す。ロックなし・期限切れ・読めない場合は None。"""
    p = _lock_path(folder, user)
    try:
        lock = json.loads(p.read_text(encoding="utf-8"))
        beat = datetime.fromisoformat(lock["heartbeat"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if (datetime.now() - beat).total_seconds() > STALE_SEC:
        return None
    return lock


def _write_lock(folder: Path, user: str, started: str, admin: bool = False):
    now = datetime.now().isoformat(timespec="seconds")
    data = {**_me(), "user": user, "started": started, "heartbeat": now, "admin": admin}
    _lock_path(folder, user).write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )


def acquire(folder: Path, user: str, admin: bool = False):
    """自分がこのユーザーのDBをメインで開いたことを記録する（admin=管理者として編集中）。"""
    try:
        _write_lock(folder, user, datetime.now().isoformat(timespec="seconds"), admin)
    except OSError:
        pass   # 共有フォルダに書けなくてもアプリ自体は動かす


def heartbeat(folder: Path, user: str):
    lock = read_lock(folder, user)
    if lock is not None and not is_mine(lock):
        return   # 他のPCが使用中（自分がロックを奪わない）
    started = (lock or {}).get("started") or datetime.now().isoformat(timespec="seconds")
    try:
        _write_lock(folder, user, started, bool((lock or {}).get("admin")))
    except OSError:
        pass


def release(folder: Path, user: str):
    """自分のロックだけを削除する（他PCのロックは消さない）。"""
    p = _lock_path(folder, user)
    try:
        lock = json.loads(p.read_text(encoding="utf-8"))
        if is_mine(lock):
            p.unlink()
    except (OSError, ValueError):
        pass


def active_users(folder: Path) -> dict[str, dict]:
    """現在メインで開かれているユーザー名 → ロック情報。"""
    result = {}
    for p in folder.glob(f"*{LOCK_SUFFIX}"):
        lock = read_lock(folder, p.stem)
        if lock is not None:
            result[p.stem] = lock
    return result


def list_users(folder: Path) -> list[dict]:
    """共有フォルダ内の全ユーザーDBの概要（名前・担当者・件数・更新日時・使用中）を返す。"""
    active = active_users(folder)
    users = []
    for f in sorted(folder.glob("*.db")):
        snap = load_db_snapshot(f) or {}
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
        except OSError:
            mtime = None
        users.append({
            "name":      f.stem,
            "path":      f,
            "workers":   [w["name"] for w in snap.get("workers", [])],
            "schedules": len(snap.get("schedules", [])),
            "readable":  bool(snap),
            "mtime":     mtime,
            "lock":      active.get(f.stem),
            "has_password": user_has_password(f),
        })
    return users
