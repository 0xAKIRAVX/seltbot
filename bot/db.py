"""SQLite persistence layer (settings kv, notes, filters, replies, tasks, stats...)."""
import json
import os
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE, text TEXT, media TEXT, media_name TEXT, created INTEGER);
CREATE TABLE IF NOT EXISTS filters (id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER, pattern TEXT, reply TEXT, hits INTEGER DEFAULT 0,
    UNIQUE(chat_id, pattern));
CREATE TABLE IF NOT EXISTS replies (id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT, match TEXT, texts TEXT, hits INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS seen (user_id INTEGER, kind TEXT, last INTEGER,
    PRIMARY KEY(user_id, kind));
CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT, at INTEGER, every INTEGER, text TEXT, chat_id INTEGER,
    last_run INTEGER, active INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS counters (chat_id INTEGER, day TEXT, direction TEXT,
    n INTEGER DEFAULT 0, PRIMARY KEY(chat_id, day, direction));
CREATE TABLE IF NOT EXISTS cmd_usage (name TEXT PRIMARY KEY, n INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS ai_sessions (user_id INTEGER PRIMARY KEY,
    history TEXT, updated INTEGER);
CREATE TABLE IF NOT EXISTS sudoers (user_id INTEGER PRIMARY KEY, added INTEGER);
CREATE TABLE IF NOT EXISTS blocked (user_id INTEGER PRIMARY KEY, added INTEGER);
CREATE TABLE IF NOT EXISTS alerts (id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT, value TEXT);
CREATE TABLE IF NOT EXISTS rules (id INTEGER PRIMARY KEY AUTOINCREMENT,
    trig TEXT, tval TEXT, act TEXT, aval TEXT,
    enabled INTEGER DEFAULT 1, hits INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS photos (id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT, data TEXT, added INTEGER);
"""


class DB:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---------- generic kv ----------
    def setting(self, k, default=None):
        row = self.conn.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["v"])
        except Exception:
            return row["v"]

    def set_setting(self, k, v):
        self.conn.execute(
            "INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (k, json.dumps(v, ensure_ascii=False)))

    def del_setting(self, k):
        self.conn.execute("DELETE FROM kv WHERE k=?", (k,))

    # ---------- notes ----------
    def note_save(self, key, text, media=None, media_name=None):
        self.conn.execute(
            "INSERT INTO notes(key,text,media,media_name,created) VALUES(?,?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET text=excluded.text, media=excluded.media, "
            "media_name=excluded.media_name, created=excluded.created",
            (key, text, media, media_name, int(time.time())))

    def note_get(self, key):
        return self.conn.execute("SELECT * FROM notes WHERE key=?", (key,)).fetchone()

    def notes_list(self, q=None):
        if q:
            like = f"%{q}%"
            return self.conn.execute(
                "SELECT * FROM notes WHERE key LIKE ? OR text LIKE ? ORDER BY id DESC LIMIT 40",
                (like, like)).fetchall()
        return self.conn.execute("SELECT * FROM notes ORDER BY id DESC LIMIT 60").fetchall()

    def note_del(self, key):
        cur = self.conn.execute("DELETE FROM notes WHERE key=?", (key,))
        return cur.rowcount > 0

    def notes_clear(self):
        self.conn.execute("DELETE FROM notes")

    # ---------- filters ----------
    def filter_add(self, chat_id, pattern, reply):
        self.conn.execute(
            "INSERT INTO filters(chat_id,pattern,reply) VALUES(?,?,?) "
            "ON CONFLICT(chat_id,pattern) DO UPDATE SET reply=excluded.reply",
            (chat_id, pattern.lower(), reply))

    def filter_del(self, chat_id, pattern):
        cur = self.conn.execute(
            "DELETE FROM filters WHERE chat_id=? AND pattern=?", (chat_id, pattern.lower()))
        return cur.rowcount > 0

    def filters_list(self, chat_id=None):
        if chat_id is None:
            return self.conn.execute("SELECT * FROM filters ORDER BY id").fetchall()
        return self.conn.execute(
            "SELECT * FROM filters WHERE chat_id=? ORDER BY id", (chat_id,)).fetchall()

    def filters_clear(self, chat_id=None):
        if chat_id is None:
            self.conn.execute("DELETE FROM filters")
        else:
            self.conn.execute("DELETE FROM filters WHERE chat_id=?", (chat_id,))

    def filter_hit(self, fid):
        self.conn.execute("UPDATE filters SET hits=hits+1 WHERE id=?", (fid,))

    # ---------- autoreply rules ----------
    def reply_rule_add(self, kind, match, texts):
        self.conn.execute("INSERT INTO replies(kind,match,texts) VALUES(?,?,?)",
                          (kind, match.lower(), json.dumps(texts, ensure_ascii=False)))

    def reply_rules(self):
        return self.conn.execute("SELECT * FROM replies ORDER BY id").fetchall()

    def reply_rule_del(self, rid):
        cur = self.conn.execute("DELETE FROM replies WHERE id=?", (rid,))
        return cur.rowcount > 0

    def reply_rules_clear(self):
        self.conn.execute("DELETE FROM replies")

    def reply_hit(self, rid):
        self.conn.execute("UPDATE replies SET hits=hits+1 WHERE id=?", (rid,))

    # ---------- seen (cooldowns) ----------
    def seen(self, user_id, kind):
        row = self.conn.execute(
            "SELECT last FROM seen WHERE user_id=? AND kind=?", (user_id, kind)).fetchone()
        return row["last"] if row else 0

    def touch_seen(self, user_id, kind, t=None):
        self.conn.execute(
            "INSERT INTO seen(user_id,kind,last) VALUES(?,?,?) "
            "ON CONFLICT(user_id,kind) DO UPDATE SET last=excluded.last",
            (user_id, kind, t or int(time.time())))

    # ---------- scheduler ----------
    def task_add(self, kind, at, every, text, chat_id):
        cur = self.conn.execute(
            "INSERT INTO tasks(kind,at,every,text,chat_id,active) VALUES(?,?,?,?,?,1)",
            (kind, int(at), every, text, chat_id))
        return cur.lastrowid

    def tasks_due(self, now):
        return self.conn.execute(
            "SELECT * FROM tasks WHERE active=1 AND at<=? ORDER BY at LIMIT 20", (now,)).fetchall()

    def tasks_all(self):
        return self.conn.execute(
            "SELECT * FROM tasks WHERE active=1 ORDER BY at LIMIT 60").fetchall()

    def task_done(self, tid):
        self.conn.execute("UPDATE tasks SET active=0, last_run=? WHERE id=?",
                          (int(time.time()), tid))

    def task_next(self, tid, nxt):
        self.conn.execute("UPDATE tasks SET at=?, last_run=? WHERE id=?",
                          (int(nxt), int(time.time()), tid))

    def task_del(self, tid):
        cur = self.conn.execute("DELETE FROM tasks WHERE id=?", (tid,))
        return cur.rowcount > 0

    def tasks_clear(self):
        self.conn.execute("DELETE FROM tasks")

    # ---------- stats ----------
    def counters_bump(self, chat_id, day, direction, n=1):
        self.conn.execute(
            "INSERT INTO counters(chat_id,day,direction,n) VALUES(?,?,?,?) "
            "ON CONFLICT(chat_id,day,direction) DO UPDATE SET n=n+?",
            (chat_id, day, direction, n, n))

    def counters_days(self, days=7):
        return self.conn.execute(
            "SELECT day, direction, SUM(n) s FROM counters WHERE day>=? GROUP BY day,direction ORDER BY day DESC",
            (days,)).fetchall()

    def counters_total(self):
        return self.conn.execute(
            "SELECT direction, SUM(n) s FROM counters GROUP BY direction").fetchall()

    def top_chats(self, day_prefix=None, limit=5):
        if day_prefix:
            return self.conn.execute(
                "SELECT chat_id, SUM(n) s FROM counters WHERE day LIKE ? GROUP BY chat_id ORDER BY s DESC LIMIT ?",
                (day_prefix + "%", limit)).fetchall()
        return self.conn.execute(
            "SELECT chat_id, SUM(n) s FROM counters GROUP BY chat_id ORDER BY s DESC LIMIT ?",
            (limit,)).fetchall()

    def cmd_bump(self, name):
        self.conn.execute(
            "INSERT INTO cmd_usage(name,n) VALUES(?,1) ON CONFLICT(name) DO UPDATE SET n=n+1",
            (name,))

    def cmd_top(self, limit=10):
        return self.conn.execute(
            "SELECT name,n FROM cmd_usage ORDER BY n DESC LIMIT ?", (limit,)).fetchall()

    # ---------- ai sessions ----------
    def ai_history(self, user_id):
        row = self.conn.execute("SELECT history FROM ai_sessions WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            return []
        try:
            return json.loads(row["history"])
        except Exception:
            return []

    def ai_history_set(self, user_id, hist):
        self.conn.execute(
            "INSERT INTO ai_sessions(user_id,history,updated) VALUES(?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET history=excluded.history, updated=excluded.updated",
            (user_id, json.dumps(hist[-20:], ensure_ascii=False), int(time.time())))

    def ai_history_clear(self, user_id):
        self.conn.execute("DELETE FROM ai_sessions WHERE user_id=?", (user_id,))

    # ---------- security ----------
    def sudoers(self):
        return [r["user_id"] for r in self.conn.execute("SELECT user_id FROM sudoers").fetchall()]

    def sudo_add(self, uid):
        self.conn.execute("INSERT OR IGNORE INTO sudoers(user_id,added) VALUES(?,?)", (uid, int(time.time())))

    def sudo_del(self, uid):
        cur = self.conn.execute("DELETE FROM sudoers WHERE user_id=?", (uid,))
        return cur.rowcount > 0

    def blocked(self):
        return [r["user_id"] for r in self.conn.execute("SELECT user_id FROM blocked").fetchall()]

    def block_add(self, uid):
        self.conn.execute("INSERT OR IGNORE INTO blocked(user_id,added) VALUES(?,?)", (uid, int(time.time())))

    def block_del(self, uid):
        cur = self.conn.execute("DELETE FROM blocked WHERE user_id=?", (uid,))
        return cur.rowcount > 0

    # ---------- alerts ----------
    def alert_add(self, kind, value):
        self.conn.execute("INSERT INTO alerts(kind,value) VALUES(?,?)", (kind, value.lower()))

    def alert_del(self, aid):
        cur = self.conn.execute("DELETE FROM alerts WHERE id=?", (aid,))
        return cur.rowcount > 0

    def alerts_all(self):
        return self.conn.execute("SELECT * FROM alerts ORDER BY id").fetchall()

    # ---------- IF-THEN rules ----------
    def rule_add(self, trig, tval, act, aval):
        cur = self.conn.execute(
            "INSERT INTO rules(trig,tval,act,aval,enabled,hits) VALUES(?,?,?,?,1,0)",
            (trig, tval, act, aval))
        return cur.lastrowid

    def rules_all(self):
        return self.conn.execute(
            "SELECT * FROM rules ORDER BY id LIMIT 100").fetchall()

    def rule_del(self, rid):
        cur = self.conn.execute("DELETE FROM rules WHERE id=?", (rid,))
        return cur.rowcount > 0

    def rules_clear(self):
        self.conn.execute("DELETE FROM rules")

    def rule_hit(self, rid):
        self.conn.execute("UPDATE rules SET hits=hits+1 WHERE id=?", (rid,))

    def rule_toggle(self, rid, on):
        cur = self.conn.execute("UPDATE rules SET enabled=? WHERE id=?",
                                (1 if on else 0, rid))
        return cur.rowcount > 0

    # ---------- photos ----------
    def photo_add(self, name, data):
        count = self.conn.execute("SELECT COUNT(*) c FROM photos").fetchone()["c"]
        if count >= 5:
            self.conn.execute("DELETE FROM photos WHERE id=(SELECT MIN(id) FROM photos)")
        self.conn.execute("INSERT INTO photos(name,data,added) VALUES(?,?,?)",
                          (name, data, int(time.time())))

    def photos_all(self):
        return self.conn.execute("SELECT id,name,added FROM photos ORDER BY id").fetchall()

    def photo_get(self, pid):
        return self.conn.execute("SELECT * FROM photos WHERE id=?", (pid,)).fetchone()

    def photo_del(self, pid):
        cur = self.conn.execute("DELETE FROM photos WHERE id=?", (pid,))
        return cur.rowcount > 0

    # ---------- misc ----------
    def commit(self):
        self.conn.commit()

    def size(self):
        try:
            return os.path.getsize(self.path)
        except Exception:
            return 0

    def close(self):
        try:
            self.conn.commit()
            self.conn.close()
        except Exception:
            pass
