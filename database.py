import sys
import sqlite3
import json
from pathlib import Path

# ─── パス解決 ────────────────────────────────────────────────────────────────

if getattr(sys, 'frozen', False):
    _BASE_DIR = Path(sys.executable).parent
else:
    _BASE_DIR = Path(__file__).parent

# ユーザーごとのローカル設定ファイル（各PCのAppDataに保存）
_CONFIG_DIR  = Path.home() / "AppData" / "Roaming" / "ApySchedule"
_CONFIG_FILE = _CONFIG_DIR / "config.json"

# デフォルト: EXE と同じフォルダ
_DEFAULT_DB_PATH = _BASE_DIR / "schedule.db"


def get_config_path() -> Path:
    return _CONFIG_FILE


def get_db_path() -> Path:
    """設定ファイルから DB パスを読む。未設定なら None を返す。"""
    if _CONFIG_FILE.exists():
        try:
            cfg = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
            p = cfg.get("db_path", "")
            if p:
                return Path(p)
        except Exception:
            pass
    return None


def set_db_path(path: Path):
    """DB パスをローカル設定ファイルに保存する。"""
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cfg = {}
    if _CONFIG_FILE.exists():
        try:
            cfg = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    cfg["db_path"] = str(path)
    _CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_db_path() -> Path:
    p = get_db_path()
    return p if p else _DEFAULT_DB_PATH


# 現在の DB パス（モジュール変数として公開）
DB_PATH = _resolve_db_path()


def refresh_db_path():
    """設定変更後に DB_PATH を再解決する。"""
    global DB_PATH
    DB_PATH = _resolve_db_path()


def get_connection():
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")   # 30秒待機
    conn.execute("PRAGMA journal_mode = WAL")      # 複数ユーザー同時アクセス対応
    return conn


def init_db():
    from version import DB_SCHEMA_VERSION
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS workers (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                department TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                category    TEXT NOT NULL DEFAULT '',
                created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS schedules (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_id       INTEGER NOT NULL,
                task_id         INTEGER NOT NULL,
                scheduled_date  TEXT NOT NULL,
                scheduled_hours REAL NOT NULL DEFAULT 0.0,
                status          TEXT NOT NULL DEFAULT 'planned',
                note            TEXT NOT NULL DEFAULT '',
                created_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at      TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (worker_id) REFERENCES workers(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id)   REFERENCES tasks(id)   ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS actuals (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                schedule_id  INTEGER,
                worker_id    INTEGER NOT NULL,
                task_id      INTEGER NOT NULL,
                actual_date  TEXT NOT NULL,
                actual_hours REAL NOT NULL DEFAULT 0.0,
                note         TEXT NOT NULL DEFAULT '',
                created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (schedule_id) REFERENCES schedules(id) ON DELETE SET NULL,
                FOREIGN KEY (worker_id)   REFERENCES workers(id)   ON DELETE CASCADE,
                FOREIGN KEY (task_id)     REFERENCES tasks(id)     ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                table_name  TEXT NOT NULL,
                record_id   INTEGER,
                action      TEXT NOT NULL,
                old_values  TEXT,
                new_values  TEXT,
                changed_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS schedule_snapshots (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL UNIQUE,
                data          TEXT NOT NULL,
                created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            );
        """)
        # DB スキーマバージョンを settings に記録（未設定なら現在値で初期化）
        r = conn.execute("SELECT value FROM settings WHERE key='db_schema_version'").fetchone()
        if r is None:
            conn.execute(
                "INSERT INTO settings (key,value) VALUES ('db_schema_version',?)",
                (str(DB_SCHEMA_VERSION),),
            )


def get_db_schema_version() -> int:
    """DBに記録されているスキーマバージョンを返す。未記録なら 1。"""
    with get_connection() as conn:
        r = conn.execute(
            "SELECT value FROM settings WHERE key='db_schema_version'"
        ).fetchone()
    return int(r['value']) if r else 1


def check_schema_compatibility() -> tuple[bool, str]:
    """アプリの想定スキーマバージョンとDB実際のバージョンを比較する。
    Returns (is_compatible, message).
    """
    from version import DB_SCHEMA_VERSION as APP_SCHEMA
    db_ver = get_db_schema_version()
    if db_ver > APP_SCHEMA:
        return False, (
            f"データベースのスキーマバージョン（v{db_ver}）が\n"
            f"このアプリの対応バージョン（v{APP_SCHEMA}）より新しいです。\n\n"
            "最新版のアプリを使用してください。"
        )
    return True, ""


# ─── helpers ──────────────────────────────────────────────────────────────────

def _log(conn, table_name, record_id, action, old, new):
    conn.execute(
        "INSERT INTO history (table_name,record_id,action,old_values,new_values) VALUES (?,?,?,?,?)",
        (table_name, record_id, action,
         json.dumps(old, ensure_ascii=False) if old is not None else None,
         json.dumps(new, ensure_ascii=False) if new is not None else None),
    )


def _row(conn, sql, params=()):
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else {}


# ─── workers ──────────────────────────────────────────────────────────────────

def get_all_workers():
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM workers ORDER BY name")]


def add_worker(name, department=""):
    with get_connection() as conn:
        cur = conn.execute("INSERT INTO workers (name,department) VALUES (?,?)", (name, department))
        _log(conn, "workers", cur.lastrowid, "INSERT", None, {"name": name, "department": department})
        return cur.lastrowid


def update_worker(worker_id, name, department=""):
    with get_connection() as conn:
        old = _row(conn, "SELECT * FROM workers WHERE id=?", (worker_id,))
        conn.execute("UPDATE workers SET name=?,department=? WHERE id=?", (name, department, worker_id))
        _log(conn, "workers", worker_id, "UPDATE", old, {"name": name, "department": department})


def delete_worker(worker_id):
    with get_connection() as conn:
        old = _row(conn, "SELECT * FROM workers WHERE id=?", (worker_id,))
        conn.execute("DELETE FROM workers WHERE id=?", (worker_id,))
        _log(conn, "workers", worker_id, "DELETE", old, None)


# ─── tasks ────────────────────────────────────────────────────────────────────

def get_all_tasks():
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM tasks ORDER BY title")]


def add_task(title, description="", category=""):
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (title,description,category) VALUES (?,?,?)",
            (title, description, category),
        )
        _log(conn, "tasks", cur.lastrowid, "INSERT", None,
             {"title": title, "description": description, "category": category})
        return cur.lastrowid


def update_task(task_id, title, description="", category=""):
    with get_connection() as conn:
        old = _row(conn, "SELECT * FROM tasks WHERE id=?", (task_id,))
        conn.execute(
            "UPDATE tasks SET title=?,description=?,category=? WHERE id=?",
            (title, description, category, task_id),
        )
        _log(conn, "tasks", task_id, "UPDATE", old,
             {"title": title, "description": description, "category": category})


def delete_task(task_id):
    with get_connection() as conn:
        old = _row(conn, "SELECT * FROM tasks WHERE id=?", (task_id,))
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        _log(conn, "tasks", task_id, "DELETE", old, None)


# ─── schedules ────────────────────────────────────────────────────────────────

def get_schedules(worker_id=None, date_from=None, date_to=None):
    sql = """
        SELECT s.id, w.name AS worker_name, t.title AS task_title,
               s.scheduled_date, s.scheduled_hours, s.status, s.note,
               s.worker_id, s.task_id
        FROM schedules s
        JOIN workers w ON s.worker_id = w.id
        JOIN tasks   t ON s.task_id   = t.id
        WHERE 1=1
    """
    params = []
    if worker_id:
        sql += " AND s.worker_id=?"; params.append(worker_id)
    if date_from:
        sql += " AND s.scheduled_date>=?"; params.append(date_from)
    if date_to:
        sql += " AND s.scheduled_date<=?"; params.append(date_to)
    sql += " ORDER BY s.scheduled_date, w.name"
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(sql, params)]


def add_schedule(worker_id, task_id, scheduled_date, scheduled_hours,
                 status="planned", note=""):
    _op = None
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO schedules (worker_id,task_id,scheduled_date,scheduled_hours,status,note)"
            " VALUES (?,?,?,?,?,?)",
            (worker_id, task_id, scheduled_date, scheduled_hours, status, note),
        )
        new_id = cur.lastrowid
        _log(conn, "schedules", new_id, "INSERT", None, {
            "worker_id": worker_id, "task_id": task_id,
            "scheduled_date": scheduled_date, "scheduled_hours": scheduled_hours,
            "status": status, "note": note,
        })
        if not _in_undo_redo:
            _op = {'table': 'schedules', 'record_id': new_id, 'action': 'INSERT',
                   'old': None, 'new': _row(conn, "SELECT * FROM schedules WHERE id=?", (new_id,))}
    if _op:
        _push_op(_op)
    return new_id


def update_schedule(schedule_id, worker_id, task_id, scheduled_date,
                    scheduled_hours, status, note):
    _op = None
    with get_connection() as conn:
        old = _row(conn, "SELECT * FROM schedules WHERE id=?", (schedule_id,))
        conn.execute(
            "UPDATE schedules SET worker_id=?,task_id=?,scheduled_date=?,"
            "scheduled_hours=?,status=?,note=?,"
            "updated_at=datetime('now','localtime') WHERE id=?",
            (worker_id, task_id, scheduled_date, scheduled_hours, status, note, schedule_id),
        )
        _log(conn, "schedules", schedule_id, "UPDATE", old, {
            "worker_id": worker_id, "task_id": task_id,
            "scheduled_date": scheduled_date, "scheduled_hours": scheduled_hours,
            "status": status, "note": note,
        })
        if not _in_undo_redo:
            _op = {'table': 'schedules', 'record_id': schedule_id, 'action': 'UPDATE',
                   'old': old, 'new': _row(conn, "SELECT * FROM schedules WHERE id=?", (schedule_id,))}
    if _op:
        _push_op(_op)


def delete_schedule(schedule_id):
    _op = None
    with get_connection() as conn:
        old = _row(conn, "SELECT * FROM schedules WHERE id=?", (schedule_id,))
        conn.execute("DELETE FROM schedules WHERE id=?", (schedule_id,))
        _log(conn, "schedules", schedule_id, "DELETE", old, None)
        if not _in_undo_redo:
            _op = {'table': 'schedules', 'record_id': schedule_id, 'action': 'DELETE',
                   'old': old, 'new': None}
    if _op:
        _push_op(_op)


def get_schedule_by_id(schedule_id):
    with get_connection() as conn:
        r = conn.execute(
            "SELECT s.id, w.name AS worker_name, t.title AS task_title,"
            " s.scheduled_date, s.scheduled_hours, s.status, s.note,"
            " s.worker_id, s.task_id"
            " FROM schedules s"
            " JOIN workers w ON s.worker_id=w.id"
            " JOIN tasks   t ON s.task_id=t.id"
            " WHERE s.id=?", (schedule_id,)
        ).fetchone()
        return dict(r) if r else None


# ─── actuals ──────────────────────────────────────────────────────────────────

def get_actuals(worker_id=None, date_from=None, date_to=None):
    sql = """
        SELECT a.id, w.name AS worker_name, t.title AS task_title,
               a.actual_date, a.actual_hours, a.note,
               a.worker_id, a.task_id, a.schedule_id
        FROM actuals a
        JOIN workers w ON a.worker_id = w.id
        JOIN tasks   t ON a.task_id   = t.id
        WHERE 1=1
    """
    params = []
    if worker_id:
        sql += " AND a.worker_id=?"; params.append(worker_id)
    if date_from:
        sql += " AND a.actual_date>=?"; params.append(date_from)
    if date_to:
        sql += " AND a.actual_date<=?"; params.append(date_to)
    sql += " ORDER BY a.actual_date, w.name"
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(sql, params)]


def add_actual(worker_id, task_id, actual_date, actual_hours,
               schedule_id=None, note=""):
    _op = None
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO actuals (schedule_id,worker_id,task_id,actual_date,actual_hours,note)"
            " VALUES (?,?,?,?,?,?)",
            (schedule_id, worker_id, task_id, actual_date, actual_hours, note),
        )
        new_id = cur.lastrowid
        _log(conn, "actuals", new_id, "INSERT", None, {
            "worker_id": worker_id, "task_id": task_id,
            "actual_date": actual_date, "actual_hours": actual_hours, "note": note,
        })
        if not _in_undo_redo:
            _op = {'table': 'actuals', 'record_id': new_id, 'action': 'INSERT',
                   'old': None, 'new': _row(conn, "SELECT * FROM actuals WHERE id=?", (new_id,))}
    if _op:
        _push_op(_op)
    return new_id


def update_actual(actual_id, worker_id, task_id, actual_date, actual_hours, note):
    _op = None
    with get_connection() as conn:
        old = _row(conn, "SELECT * FROM actuals WHERE id=?", (actual_id,))
        conn.execute(
            "UPDATE actuals SET worker_id=?,task_id=?,actual_date=?,actual_hours=?,note=? WHERE id=?",
            (worker_id, task_id, actual_date, actual_hours, note, actual_id),
        )
        _log(conn, "actuals", actual_id, "UPDATE", old, {
            "worker_id": worker_id, "task_id": task_id,
            "actual_date": actual_date, "actual_hours": actual_hours, "note": note,
        })
        if not _in_undo_redo:
            _op = {'table': 'actuals', 'record_id': actual_id, 'action': 'UPDATE',
                   'old': old, 'new': _row(conn, "SELECT * FROM actuals WHERE id=?", (actual_id,))}
    if _op:
        _push_op(_op)


def delete_actual(actual_id):
    _op = None
    with get_connection() as conn:
        old = _row(conn, "SELECT * FROM actuals WHERE id=?", (actual_id,))
        conn.execute("DELETE FROM actuals WHERE id=?", (actual_id,))
        _log(conn, "actuals", actual_id, "DELETE", old, None)
        if not _in_undo_redo:
            _op = {'table': 'actuals', 'record_id': actual_id, 'action': 'DELETE',
                   'old': old, 'new': None}
    if _op:
        _push_op(_op)


def get_actual_by_id(actual_id):
    with get_connection() as conn:
        r = conn.execute(
            "SELECT a.id, w.name AS worker_name, t.title AS task_title,"
            " a.actual_date, a.actual_hours, a.note,"
            " a.worker_id, a.task_id, a.schedule_id"
            " FROM actuals a"
            " JOIN workers w ON a.worker_id=w.id"
            " JOIN tasks   t ON a.task_id=t.id"
            " WHERE a.id=?", (actual_id,)
        ).fetchone()
        return dict(r) if r else None


# ─── chart summary ────────────────────────────────────────────────────────────

def get_summary_by_worker(date_from=None, date_to=None):
    w_s, w_a = [], []
    p_s, p_a = [], []
    if date_from:
        w_s.append("s.scheduled_date>=?"); p_s.append(date_from)
        w_a.append("a.actual_date>=?");    p_a.append(date_from)
    if date_to:
        w_s.append("s.scheduled_date<=?"); p_s.append(date_to)
        w_a.append("a.actual_date<=?");    p_a.append(date_to)

    def where(clauses):
        return ("AND " + " AND ".join(clauses)) if clauses else ""

    with get_connection() as conn:
        sched = {r["name"]: r["total"] for r in conn.execute(
            f"SELECT w.name, COALESCE(SUM(s.scheduled_hours),0) AS total"
            f" FROM workers w LEFT JOIN schedules s ON w.id=s.worker_id {where(w_s)}"
            f" GROUP BY w.id,w.name ORDER BY w.name", p_s)}
        actual = {r["name"]: r["total"] for r in conn.execute(
            f"SELECT w.name, COALESCE(SUM(a.actual_hours),0) AS total"
            f" FROM workers w LEFT JOIN actuals a ON w.id=a.worker_id {where(w_a)}"
            f" GROUP BY w.id,w.name ORDER BY w.name", p_a)}

    all_names = sorted(set(list(sched) + list(actual)))
    return [{"name": n, "scheduled": sched.get(n, 0), "actual": actual.get(n, 0)}
            for n in all_names]


# ─── reset ────────────────────────────────────────────────────────────────────

def reset_db():
    """全テーブルのデータを削除し、オートインクリメントをリセットする。"""
    with get_connection() as conn:
        conn.executescript("""
            PRAGMA foreign_keys = OFF;
            DELETE FROM history;
            DELETE FROM actuals;
            DELETE FROM schedules;
            DELETE FROM tasks;
            DELETE FROM workers;
            DELETE FROM sqlite_sequence;
            PRAGMA foreign_keys = ON;
        """)


# ─── settings ────────────────────────────────────────────────────────────────

def get_setting(key: str, default: str = '') -> str:
    with get_connection() as conn:
        r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default


def set_setting(key: str, value: str):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO settings (key,value) VALUES (?,?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


# ─── task text colors ────────────────────────────────────────────────────────

def get_task_text_colors() -> dict:
    """タスクIDをキー・テキスト色(#RRGGBB)を値とする辞書を返す。"""
    v = get_setting('task_text_colors', '{}')
    try:
        return json.loads(v)
    except Exception:
        return {}


def set_task_text_color(task_id: int, color: str):
    """タスクのテキスト色を保存する。color が空文字ならリセット。"""
    colors = get_task_text_colors()
    if color:
        colors[str(task_id)] = color
    else:
        colors.pop(str(task_id), None)
    set_setting('task_text_colors', json.dumps(colors))


# ─── history ──────────────────────────────────────────────────────────────────

def get_history(limit=100):
    with get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM history ORDER BY changed_at DESC LIMIT ?", (limit,))]


# ─── undo / redo ──────────────────────────────────────────────────────────────

_undo_stack   = []    # list of list[op-dict]  (action groups)
_redo_stack   = []
_current_group = None  # list being built while begin_action is active
_in_undo_redo  = False  # suppress stack pushes during undo/redo execution

_MAX_STACK = 50


def begin_action():
    """複数の DB 操作を 1 つの Undo アクションとして記録開始。"""
    global _current_group
    _current_group = []


def end_action():
    """begin_action() 以降の操作を 1 つの Undo アクションとして確定。"""
    global _current_group
    if _current_group:
        _undo_stack.append(_current_group)
        if len(_undo_stack) > _MAX_STACK:
            _undo_stack.pop(0)
        _redo_stack.clear()
    _current_group = None


def _push_op(op):
    global _current_group
    if _in_undo_redo:
        return
    if _current_group is not None:
        _current_group.append(op)
    else:
        _undo_stack.append([op])
        if len(_undo_stack) > _MAX_STACK:
            _undo_stack.pop(0)
        _redo_stack.clear()


def can_undo():
    return bool(_undo_stack)


def can_redo():
    return bool(_redo_stack)


def _apply_inverse(op):
    """op の逆操作を DB に直接実行（history ログなし）。"""
    table = op['table']
    rid   = op['record_id']
    old   = op.get('old')
    with get_connection() as conn:
        if op['action'] == 'INSERT':
            conn.execute(f"DELETE FROM {table} WHERE id=?", (rid,))
        elif op['action'] == 'UPDATE' and old:
            cols = [k for k in old if k != 'id']
            conn.execute(
                f"UPDATE {table} SET {', '.join(k+'=?' for k in cols)} WHERE id=?",
                [old[k] for k in cols] + [rid],
            )
        elif op['action'] == 'DELETE' and old:
            cols = list(old.keys())
            conn.execute(
                f"INSERT OR REPLACE INTO {table} ({', '.join(cols)})"
                f" VALUES ({', '.join('?' for _ in cols)})",
                [old[k] for k in cols],
            )


def _apply_forward(op):
    """op を DB に直接再実行（history ログなし）。"""
    table = op['table']
    rid   = op['record_id']
    new   = op.get('new')
    with get_connection() as conn:
        if op['action'] == 'INSERT' and new:
            cols = list(new.keys())
            conn.execute(
                f"INSERT OR REPLACE INTO {table} ({', '.join(cols)})"
                f" VALUES ({', '.join('?' for _ in cols)})",
                [new[k] for k in cols],
            )
        elif op['action'] == 'UPDATE' and new:
            cols = [k for k in new if k != 'id']
            conn.execute(
                f"UPDATE {table} SET {', '.join(k+'=?' for k in cols)} WHERE id=?",
                [new[k] for k in cols] + [rid],
            )
        elif op['action'] == 'DELETE':
            conn.execute(f"DELETE FROM {table} WHERE id=?", (rid,))


def do_undo():
    global _in_undo_redo
    if not _undo_stack:
        return False
    ops = _undo_stack.pop()
    _in_undo_redo = True
    try:
        for op in reversed(ops):
            _apply_inverse(op)
        _redo_stack.append(ops)
        return True
    finally:
        _in_undo_redo = False


def do_redo():
    global _in_undo_redo
    if not _redo_stack:
        return False
    ops = _redo_stack.pop()
    _in_undo_redo = True
    try:
        for op in ops:
            _apply_forward(op)
        _undo_stack.append(ops)
        return True
    finally:
        _in_undo_redo = False


# ─── schedule_snapshots ───────────────────────────────────────────────────────

def save_snapshot(snapshot_date: str) -> bool:
    """指定日の全予定・担当者・作業をスナップショットとして保存する。
    同日のスナップショットが既存の場合は上書き。
    Returns True if saved, False if nothing to save."""
    workers   = get_all_workers()
    tasks     = get_all_tasks()
    schedules = get_schedules()   # 全期間・全担当者

    data = json.dumps({
        'snapshot_date': snapshot_date,
        'workers':       workers,
        'tasks':         tasks,
        'schedules':     schedules,
    }, ensure_ascii=False)

    with get_connection() as conn:
        conn.execute(
            "INSERT INTO schedule_snapshots (snapshot_date, data) VALUES (?,?)"
            " ON CONFLICT(snapshot_date) DO UPDATE SET data=excluded.data,"
            " created_at=datetime('now','localtime')",
            (snapshot_date, data),
        )
    return True


def auto_save_today_snapshot():
    """今日のスナップショットが未保存なら保存する。
    既存なら何もしない（起動時の自動保存に使用）。"""
    from datetime import date as _date
    today = _date.today().strftime('%Y-%m-%d')
    with get_connection() as conn:
        r = conn.execute(
            "SELECT id FROM schedule_snapshots WHERE snapshot_date=?", (today,)
        ).fetchone()
    if r is None:
        save_snapshot(today)


def get_snapshot(snapshot_date: str) -> dict | None:
    """指定日のスナップショットを返す。存在しなければ None。"""
    with get_connection() as conn:
        r = conn.execute(
            "SELECT data FROM schedule_snapshots WHERE snapshot_date=?",
            (snapshot_date,),
        ).fetchone()
    if r is None:
        return None
    try:
        return json.loads(r['data'])
    except Exception:
        return None


def get_snapshot_dates() -> list[str]:
    """スナップショットが存在する日付リストを降順で返す。"""
    with get_connection() as conn:
        return [r['snapshot_date'] for r in conn.execute(
            "SELECT snapshot_date FROM schedule_snapshots ORDER BY snapshot_date DESC"
        )]


def delete_snapshot(snapshot_date: str):
    """指定日のスナップショットを削除する。"""
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM schedule_snapshots WHERE snapshot_date=?", (snapshot_date,)
        )
