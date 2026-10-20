"""管理者・ユーザーのパスワード管理。

- 管理者: 共有フォルダの `_admin.json` に保存。無ければ初期パスワード "admin" で
          自動作成し、初回ログイン時に変更を必須にする（must_change）。
- ユーザー: 各ユーザー自身のDBの settings テーブル（key=auth_password）に保存。
           ユーザーごとのファイルなので、BOX 同期で他人と書き込みが衝突しない。
           未設定ならパスワードなしでログインできる。

パスワードは PBKDF2-SHA256（ソルト付き）でハッシュ化して保存し、平文は保存しない。
※ DBファイル自体は共有フォルダにあるため、これは誤操作・なりすまし防止のための
  簡易な仕組みであり、フォルダにアクセスできる人からデータを守るものではない。
"""
from __future__ import annotations
import hashlib
import hmac
import json
import os
import sqlite3
from pathlib import Path

ADMIN_FILE       = "_admin.json"
ADMIN_LABEL      = "管理者"
DEFAULT_ADMIN_PW = "admin"
_SETTING_KEY     = "auth_password"
_ITERATIONS      = 200_000


# ── ハッシュ ──────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters)
        )
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(digest.hex(), hash_hex)


# ── 管理者 ────────────────────────────────────────────────────────────────────

def _admin_path(folder: Path) -> Path:
    return folder / ADMIN_FILE


def _read_admin(folder: Path) -> dict:
    try:
        return json.loads(_admin_path(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def ensure_admin(folder: Path):
    """管理者が未作成なら初期パスワードで作成する（既にあれば何もしない）。"""
    if _read_admin(folder).get("password"):
        return
    _write_admin(folder, hash_password(DEFAULT_ADMIN_PW), must_change=True)


def _write_admin(folder: Path, hashed: str, must_change: bool):
    _admin_path(folder).write_text(
        json.dumps({"password": hashed, "must_change": must_change}, ensure_ascii=False),
        encoding="utf-8",
    )


def verify_admin(folder: Path, password: str) -> bool:
    stored = _read_admin(folder).get("password", "")
    return bool(stored) and verify_password(password, stored)


def admin_must_change(folder: Path) -> bool:
    return bool(_read_admin(folder).get("must_change", False))


def set_admin_password(folder: Path, password: str):
    _write_admin(folder, hash_password(password), must_change=False)


# ── ユーザー ──────────────────────────────────────────────────────────────────

def user_db_path(folder: Path, user: str) -> Path:
    return folder / f"{user}.db"


def get_user_password_hash(db_path: Path) -> str:
    """ユーザーDBに保存されたパスワードハッシュ。未設定・未作成・読めない場合は空文字。"""
    if not db_path.exists():
        return ""
    try:
        conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=3)
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE key=?", (_SETTING_KEY,)
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return ""
    return row[0] if row else ""


def user_has_password(db_path: Path) -> bool:
    return bool(get_user_password_hash(db_path))


def verify_user(db_path: Path, password: str) -> bool:
    """パスワード未設定のユーザーは常に True。"""
    stored = get_user_password_hash(db_path)
    return not stored or verify_password(password, stored)


def set_user_password(db_path: Path, password: str):
    """ユーザーのパスワードを設定する。空文字ならパスワードを解除する。"""
    conn = sqlite3.connect(str(db_path), timeout=30)
    try:
        with conn:
            if password:
                conn.execute(
                    "INSERT INTO settings(key, value) VALUES(?, ?)"
                    " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (_SETTING_KEY, hash_password(password)),
                )
            else:
                conn.execute("DELETE FROM settings WHERE key=?", (_SETTING_KEY,))
    finally:
        conn.close()
