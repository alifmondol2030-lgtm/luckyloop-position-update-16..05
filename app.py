from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_cors import CORS
import sqlite3
from datetime import datetime, timedelta
import os
import secrets
import string

app = Flask(__name__)
CORS(app)

app.secret_key = os.environ.get("SECRET_KEY", "luckyloop_secret_key_2024_xk92")

DB = os.path.join(os.environ.get("DB_PATH", "."), "jobs.db")

ADMIN_PASSWORD  = os.environ.get("ADMIN_PASSWORD", "luckyloop_admin_2024")
VIEWER_PASSWORD = os.environ.get("VIEWER_PASSWORD", "luckyloop2024")


def init_db():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            job_name   TEXT    UNIQUE NOT NULL,
            position   TEXT,
            available  TEXT,
            link       TEXT,
            updated_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS scraper_status (
            id         INTEGER PRIMARY KEY,
            status     TEXT,
            message    TEXT,
            updated_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            device_id    TEXT PRIMARY KEY,
            device_name  TEXT,
            license_key  TEXT,
            license_type TEXT,
            ip_address   TEXT,
            first_seen   TEXT,
            last_seen    TEXT,
            is_blocked   INTEGER DEFAULT 0,
            block_reason TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS license_keys (
            key_id       INTEGER PRIMARY KEY AUTOINCREMENT,
            license_key  TEXT    UNIQUE NOT NULL,
            label        TEXT,
            max_devices  INTEGER DEFAULT 1,
            bound_device TEXT,
            created_at   TEXT,
            activated_at TEXT,
            is_active    INTEGER DEFAULT 1
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS announcement (
            id         INTEGER PRIMARY KEY,
            enabled    INTEGER DEFAULT 0,
            message    TEXT    DEFAULT '',
            updated_at TEXT    DEFAULT ''
        )
    """)
    c.execute("""
        INSERT OR IGNORE INTO announcement (id, enabled, message, updated_at)
        VALUES (1, 0, '', '')
    """)

    # ══ NEW: users validity table ══
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            username     TEXT    UNIQUE NOT NULL,
            display_name TEXT,
            license_key  TEXT,
            expires_at   TEXT,
            created_at   TEXT,
            note         TEXT
        )
    """)

    cols = [row[1] for row in c.execute("PRAGMA table_info(jobs)")]
    if "updated_at" not in cols:
        c.execute("ALTER TABLE jobs ADD COLUMN updated_at TEXT")
    conn.commit()
    conn.close()
    print("[DB] Ready")


def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


def is_viewer_logged_in():
    return session.get("viewer_logged_in") is True


def check_admin(req):
    pw = req.headers.get("X-Admin-Password") or req.args.get("password") or ""
    return pw == ADMIN_PASSWORD


def generate_license_key(label=""):
    chars  = string.ascii_uppercase + string.digits
    suffix = ''.join(secrets.choice(chars) for _ in range(16))
    prefix = label.replace(" ", "-")[:12].upper() if label else "USER"
    return f"LL-{prefix}-{suffix}"


# ══════════════════════════════════════════════════════════
#  VIEWER LOGIN/LOGOUT
# ══════════════════════════════════════════════════════════

@app.route("/viewer-login", methods=["POST"])
def viewer_login():
    data = request.get_json(silent=True) or {}
    pw = str(data.get("password", "") or "").strip()
    if pw == VIEWER_PASSWORD:
        session["viewer_logged_in"] = True
        session.permanent = True
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "ভুল পাসওয়ার্ড"}), 401


@app.route("/viewer-logout")
def viewer_logout():
    session.pop("viewer_logged_in", None)
    return redirect("/latest")


# ══════════════════════════════════════════════════════════
#  PROTECTED ROUTES
# ══════════════════════════════════════════════════════════

@app.route("/")
def home():
    if not is_viewer_logged_in():
        return render_template("latest.html", locked=True)
    return render_template("index.html")


@app.route("/latest")
def latest():
    if not is_viewer_logged_in():
        return render_template("latest.html", locked=True)
    return render_template("latest.html", locked=False)


@app.route("/api/latest")
def api_latest():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM jobs ORDER BY updated_at DESC"
    ).fetchall()
    status_row = conn.execute(
        "SELECT * FROM scraper_status WHERE id=1"
    ).fetchone()
    conn.close()
    scraper_ok  = True
    scraper_msg = "OK"
    if status_row:
        scraper_ok  = status_row["status"] == "ok"
        scraper_msg = status_row["message"]
    return jsonify({
        "jobs":       [dict(r) for r in rows],
        "scraper_ok": scraper_ok,
        "scraper_msg": scraper_msg
    })


# ══════════════════════════════════════════════════════════
#  EXISTING ROUTES
# ══════════════════════════════════════════════════════════

@app.route("/api/scraper-status", methods=["POST"])
def update_scraper_status():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "no data"}), 400
    status  = data.get("status", "ok")
    message = data.get("message", "")
    now     = datetime.now().isoformat()
    conn = get_db()
    conn.execute("""
        INSERT INTO scraper_status (id, status, message, updated_at)
        VALUES (1, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            status     = excluded.status,
            message    = excluded.message,
            updated_at = excluded.updated_at
    """, (status, message, now))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/save", methods=["POST", "OPTIONS"])
def save_job():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"status": "error", "message": "No JSON body received"}), 400
    job_name  = str(data.get("job_name",  "") or "").strip()
    position  = str(data.get("position",  "") or "").strip()
    available = str(data.get("available", "") or "").strip()
    link      = str(data.get("link",      "") or "").strip()
    now       = datetime.now().isoformat()
    if not job_name:
        return jsonify({"status": "error", "message": "job_name is required"}), 400
    conn = get_db()
    conn.execute("""
        INSERT INTO jobs (job_name, position, available, link, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(job_name) DO UPDATE SET
            position   = excluded.position,
            available  = excluded.available,
            link       = excluded.link,
            updated_at = excluded.updated_at
    """, (job_name, position, available, link, now))
    conn.commit()
    conn.close()
    return jsonify({"status": "saved", "job_name": job_name})


# ══════════════════════════════════════════════════════════
#  DEVICE MANAGEMENT ROUTES
# ══════════════════════════════════════════════════════════

@app.route("/api/heartbeat", methods=["POST"])
def heartbeat():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"ok": False, "blocked": False}), 400

    device_id    = str(data.get("device_id",    "") or "").strip()
    device_name  = str(data.get("device_name",  "") or "Unknown").strip()
    license_key  = str(data.get("license_key",  "") or "").strip()
    license_type = str(data.get("license_type", "") or "").strip()
    ip_address   = request.headers.get("X-Forwarded-For", request.remote_addr or "")
    now          = datetime.now().isoformat()

    if not device_id:
        return jsonify({"ok": False, "blocked": False, "reason": "no device_id"}), 400

    conn = get_db()
    existing = conn.execute(
        "SELECT * FROM devices WHERE device_id=?", (device_id,)
    ).fetchone()

    if existing:
        conn.execute("""
            UPDATE devices SET
                device_name  = ?,
                license_key  = ?,
                license_type = ?,
                ip_address   = ?,
                last_seen    = ?
            WHERE device_id = ?
        """, (device_name, license_key, license_type, ip_address, now, device_id))
        is_blocked   = bool(existing["is_blocked"])
        block_reason = existing["block_reason"] or ""
    else:
        conn.execute("""
            INSERT INTO devices
                (device_id, device_name, license_key, license_type, ip_address, first_seen, last_seen, is_blocked)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """, (device_id, device_name, license_key, license_type, ip_address, now, now))
        is_blocked   = False
        block_reason = ""

    conn.commit()
    conn.close()

    if is_blocked:
        return jsonify({"ok": False, "blocked": True, "reason": block_reason or "আপনার device block করা হয়েছে।"})

    return jsonify({"ok": True, "blocked": False})


@app.route("/api/check/<device_id>", methods=["GET"])
def check_device(device_id):
    conn = get_db()
    row = conn.execute(
        "SELECT is_blocked, block_reason FROM devices WHERE device_id=?", (device_id,)
    ).fetchone()
    conn.close()

    if not row:
        return jsonify({"ok": True, "blocked": False})
    if row["is_blocked"]:
        return jsonify({
            "ok": False,
            "blocked": True,
            "reason": row["block_reason"] or "আপনার device block করা হয়েছে।"
        })
    return jsonify({"ok": True, "blocked": False})


# ══════════════════════════════════════════════════════════
#  LICENSE KEY API
# ══════════════════════════════════════════════════════════

@app.route("/api/license/verify", methods=["POST"])
def license_verify():
    data = request.get_json(silent=True) or {}
    license_key = str(data.get("license_key", "") or "").strip()
    device_id   = str(data.get("device_id",   "") or "").strip()
    device_name = str(data.get("device_name", "") or "Unknown").strip()

    if not license_key or not device_id:
        return jsonify({"ok": False, "valid": False, "message": "❌ Missing license_key or device_id"}), 400

    conn = get_db()
    row = conn.execute(
        "SELECT * FROM license_keys WHERE license_key=?", (license_key,)
    ).fetchone()

    if not row:
        conn.close()
        return jsonify({"ok": False, "valid": False, "message": "❌ Invalid License Key!"})

    if not row["is_active"]:
        conn.close()
        return jsonify({"ok": False, "valid": False, "message": "❌ This license key has been deactivated!"})

    bound = row["bound_device"]
    now   = datetime.now().isoformat()

    if bound and bound != device_id:
        conn.close()
        return jsonify({
            "ok":      False,
            "valid":   False,
            "message": "❌ This license key is already activated on another device! Contact admin."
        })

    if not bound:
        conn.execute(
            "UPDATE license_keys SET bound_device=?, activated_at=? WHERE license_key=?",
            (device_id, now, license_key)
        )
        conn.commit()

    # ── Check if user validity info is linked to this license ──
    user_row = conn.execute(
        "SELECT * FROM users WHERE license_key=?", (license_key,)
    ).fetchone()

    label = row["label"] or "License Key Active"
    conn.close()

    response = {
        "ok":           True,
        "valid":        True,
        "message":      f"✅ License Activated! ({label})",
        "license_type": label
    }

    if user_row:
        response["user_info"] = {
            "display_name": user_row["display_name"] or user_row["username"],
            "username":     user_row["username"],
            "expires_at":   user_row["expires_at"] or "",
        }

    return jsonify(response)


@app.route("/api/license/unbind", methods=["POST"])
def license_unbind():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    license_key = str(data.get("license_key", "") or "").strip()
    if not license_key:
        return jsonify({"error": "license_key required"}), 400
    conn = get_db()
    conn.execute(
        "UPDATE license_keys SET bound_device=NULL, activated_at=NULL WHERE license_key=?",
        (license_key,)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "message": "Key unbound successfully"})


# ══════════════════════════════════════════════════════════
#  USER VALIDITY API  (app polls this)
# ══════════════════════════════════════════════════════════

@app.route("/api/user/info", methods=["POST"])
def user_info():
    """App sends license_key → gets display_name + days remaining."""
    data        = request.get_json(silent=True) or {}
    license_key = str(data.get("license_key", "") or "").strip()

    if not license_key:
        return jsonify({"ok": False, "message": "license_key required"}), 400

    conn = get_db()
    user = conn.execute(
        "SELECT * FROM users WHERE license_key=?", (license_key,)
    ).fetchone()
    conn.close()

    if not user:
        return jsonify({"ok": False, "message": "User not found"})

    expires_at   = user["expires_at"] or ""
    days_left    = None
    is_expired   = False

    if expires_at:
        try:
            exp_dt    = datetime.fromisoformat(expires_at)
            delta     = exp_dt - datetime.now()
            days_left = max(0, delta.days)
            is_expired = delta.total_seconds() <= 0
        except:
            pass

    return jsonify({
        "ok":          True,
        "display_name": user["display_name"] or user["username"],
        "username":    user["username"],
        "expires_at":  expires_at,
        "days_left":   days_left,
        "is_expired":  is_expired,
    })


# ══════════════════════════════════════════════════════════
#  ADMIN LICENSE ROUTES
# ══════════════════════════════════════════════════════════

@app.route("/api/admin/licenses", methods=["GET"])
def admin_get_licenses():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM license_keys ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/admin/licenses/generate", methods=["POST"])
def admin_generate_license():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    label       = str(data.get("label", "") or "").strip()
    max_devices = int(data.get("max_devices", 1))
    count       = max(1, min(int(data.get("count", 1)), 50))

    now  = datetime.now().isoformat()
    conn = get_db()
    generated = []
    for _ in range(count):
        key = generate_license_key(label)
        while conn.execute("SELECT 1 FROM license_keys WHERE license_key=?", (key,)).fetchone():
            key = generate_license_key(label)
        conn.execute(
            "INSERT INTO license_keys (license_key, label, max_devices, created_at, is_active) VALUES (?,?,?,?,1)",
            (key, label, max_devices, now)
        )
        generated.append(key)
    conn.commit()
    conn.close()
    print(f"[LICENSE] Generated {count} key(s) — label: {label or 'none'}")
    return jsonify({"ok": True, "keys": generated})


@app.route("/api/admin/licenses/toggle", methods=["POST"])
def admin_toggle_license():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    license_key = str(data.get("license_key", "") or "").strip()
    is_active   = int(bool(data.get("is_active", True)))
    if not license_key:
        return jsonify({"error": "license_key required"}), 400
    conn = get_db()
    conn.execute(
        "UPDATE license_keys SET is_active=? WHERE license_key=?",
        (is_active, license_key)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/admin/licenses/delete", methods=["POST"])
def admin_delete_license():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    license_key = str(data.get("license_key", "") or "").strip()
    if not license_key:
        return jsonify({"error": "license_key required"}), 400
    conn = get_db()
    conn.execute("DELETE FROM license_keys WHERE license_key=?", (license_key,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════
#  ADMIN USER VALIDITY ROUTES
# ══════════════════════════════════════════════════════════

@app.route("/api/admin/users", methods=["GET"])
def admin_get_users():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM users ORDER BY created_at DESC"
    ).fetchall()
    conn.close()

    result = []
    for r in rows:
        d = dict(r)
        expires_at = d.get("expires_at") or ""
        days_left  = None
        is_expired = False
        if expires_at:
            try:
                exp_dt    = datetime.fromisoformat(expires_at)
                delta     = exp_dt - datetime.now()
                days_left = max(0, delta.days)
                is_expired = delta.total_seconds() <= 0
            except:
                pass
        d["days_left"]  = days_left
        d["is_expired"] = is_expired
        result.append(d)
    return jsonify(result)


@app.route("/api/admin/users/add", methods=["POST"])
def admin_add_user():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    data         = request.get_json(silent=True) or {}
    username     = str(data.get("username",     "") or "").strip()
    display_name = str(data.get("display_name", "") or "").strip()
    license_key  = str(data.get("license_key",  "") or "").strip()
    days         = int(data.get("days", 30))
    note         = str(data.get("note", "") or "").strip()

    if not username or not license_key:
        return jsonify({"error": "username and license_key required"}), 400

    expires_at = (datetime.now() + timedelta(days=days)).isoformat()
    now        = datetime.now().isoformat()

    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO users (username, display_name, license_key, expires_at, created_at, note)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                display_name = excluded.display_name,
                license_key  = excluded.license_key,
                expires_at   = excluded.expires_at,
                note         = excluded.note
        """, (username, display_name or username, license_key, expires_at, now, note))
        conn.commit()
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500
    conn.close()
    return jsonify({"ok": True, "username": username, "expires_at": expires_at})


@app.route("/api/admin/users/extend", methods=["POST"])
def admin_extend_user():
    """Add more days to existing user's validity."""
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    data     = request.get_json(silent=True) or {}
    username = str(data.get("username", "") or "").strip()
    days     = int(data.get("days", 30))

    if not username:
        return jsonify({"error": "username required"}), 400

    conn = get_db()
    row  = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "User not found"}), 404

    existing_exp = row["expires_at"]
    try:
        base = datetime.fromisoformat(existing_exp) if existing_exp else datetime.now()
        if base < datetime.now():
            base = datetime.now()
    except:
        base = datetime.now()

    new_exp = (base + timedelta(days=days)).isoformat()
    conn.execute("UPDATE users SET expires_at=? WHERE username=?", (new_exp, username))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "username": username, "new_expires_at": new_exp})


@app.route("/api/admin/users/delete", methods=["POST"])
def admin_delete_user():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    data     = request.get_json(silent=True) or {}
    username = str(data.get("username", "") or "").strip()
    if not username:
        return jsonify({"error": "username required"}), 400
    conn = get_db()
    conn.execute("DELETE FROM users WHERE username=?", (username,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════
#  ANNOUNCEMENT API
# ══════════════════════════════════════════════════════════

@app.route("/api/announcement", methods=["GET"])
def get_announcement():
    conn = get_db()
    row = conn.execute("SELECT * FROM announcement WHERE id=1").fetchone()
    conn.close()
    if not row:
        return jsonify({"enabled": False, "message": ""})
    return jsonify({
        "enabled": bool(row["enabled"]),
        "message": row["message"] or ""
    })


@app.route("/api/admin/announcement", methods=["POST"])
def set_announcement():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    data    = request.get_json(silent=True) or {}
    enabled = 1 if data.get("enabled") else 0
    message = str(data.get("message", "") or "").strip()
    now     = datetime.now().isoformat()
    conn = get_db()
    conn.execute(
        "UPDATE announcement SET enabled=?, message=?, updated_at=? WHERE id=1",
        (enabled, message, now)
    )
    conn.commit()
    conn.close()
    print(f"[ANN] enabled={enabled} msg={message[:60]}")
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════
#  ADMIN PANEL ROUTE
# ══════════════════════════════════════════════════════════

@app.route("/admin")
def admin_panel():
    return render_template("admin.html")


@app.route("/api/admin/devices", methods=["GET"])
def admin_get_devices():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM devices ORDER BY last_seen DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/admin/block", methods=["POST"])
def admin_block():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    device_id = str(data.get("device_id", "") or "").strip()
    reason    = str(data.get("reason", "Admin কর্তৃক block করা হয়েছে") or "").strip()
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    conn = get_db()
    conn.execute(
        "UPDATE devices SET is_blocked=1, block_reason=? WHERE device_id=?",
        (reason, device_id)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "blocked": True})


@app.route("/api/admin/unblock", methods=["POST"])
def admin_unblock():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    device_id = str(data.get("device_id", "") or "").strip()
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    conn = get_db()
    conn.execute(
        "UPDATE devices SET is_blocked=0, block_reason='' WHERE device_id=?",
        (device_id,)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "blocked": False})


@app.route("/api/admin/delete", methods=["POST"])
def admin_delete():
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    device_id = str(data.get("device_id", "") or "").strip()
    if not device_id:
        return jsonify({"error": "device_id required"}), 400
    conn = get_db()
    conn.execute("DELETE FROM devices WHERE device_id=?", (device_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


# ══════════════════════════════════════════════════════════
init_db()

from scraper import start_scraper
start_scraper()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
