"""Encrypted state persistence to the GitHub repo (survives 6h shift restarts).

state.db → gzip → openssl AES-256-CBC (PBKDF2, STATE_KEY) → base64 →
Contents API PUT `state.db.enc`. Restored on boot before the DB is opened.
"""
import base64
import gzip
import logging
import os
import subprocess

import requests

log = logging.getLogger("seltbot.state")

GH = "https://api.github.com"
PATH = "state.db.enc"


def _openssl(data: bytes, key: str, decrypt: bool = False) -> bytes:
    args = ["openssl", "enc", "-aes-256-cbc", "-pbkdf2"]
    if decrypt:
        args.append("-d")
    args += ["-pass", "env:SELTBOT_KEY"]
    env = dict(os.environ)
    env["SELTBOT_KEY"] = key
    r = subprocess.run(args, input=data, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, env=env)
    if r.returncode != 0:
        raise RuntimeError("openssl failed: " + r.stderr.decode(errors="replace")[:200])
    return r.stdout


def pack(db_path: str, key: str) -> str:
    with open(db_path, "rb") as f:
        raw = f.read()
    return base64.b64encode(_openssl(gzip.compress(raw, 6), key)).decode()


def unpack(data_b64: str, key: str, out_path: str):
    data = base64.b64decode(data_b64)
    raw = gzip.decompress(_openssl(data, key, decrypt=True))
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(raw)
    return len(raw)


def _api(repo, token, method, path, **kw):
    return requests.request(
        method, f"{GH}/repos/{repo}/{path}",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json"},
        timeout=60, **kw)


def persist(dbh, repo, token, key, note="tick"):
    """Upload the (checkpointed) DB to the repo as encrypted state."""
    if not (repo and token and key):
        log.info("persist skipped (no repo/token/key config)")
        return False
    try:
        dbh.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        dbh.commit()
        content = pack(dbh.path, key)
        sha = None
        r = _api(repo, token, "GET", f"contents/{PATH}")
        if r.status_code == 200:
            sha = r.json().get("sha")
        for attempt in range(3):
            body = {"message": f"state: {note}", "content": content}
            if sha:
                body["sha"] = sha
            r = _api(repo, token, "PUT", f"contents/{PATH}", json=body)
            if r.status_code in (200, 201):
                log.info("state pushed (%d bytes b64)", len(content))
                return True
            if r.status_code in (409, 422) and attempt < 2:
                r2 = _api(repo, token, "GET", f"contents/{PATH}")
                sha = r2.json().get("sha") if r2.status_code == 200 else None
                continue
            log.warning("state push failed: %s %s", r.status_code, r.text[:200])
            return False
    except Exception:
        log.exception("persist failed")
    return False


def restore(db_path, repo, token, key):
    """Download + decrypt state into db_path. True if restored."""
    if not (repo and token and key):
        return False
    try:
        r = _api(repo, token, "GET", f"contents/{PATH}")
        if r.status_code == 404:
            log.info("no state file yet — fresh start")
            return False
        if r.status_code != 200:
            log.warning("state fetch failed: %s", r.status_code)
            return False
        data = (r.json().get("content") or "").replace("\n", "")
        n = unpack(data, key, db_path)
        log.info("state restored (%d bytes)", n)
        return True
    except Exception:
        log.exception("restore failed — starting fresh")
    return False
