from flask import Flask, request, jsonify, render_template, session, redirect, url_for
from flask_cors import CORS
import sqlite3
from datetime import datetime
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
    # license_keys table — bound_device এখন JSON list (multiple devices support)
    c.execute("""
        CREATE TABLE IF NOT EXISTS license_keys (
            key_id        INTEGER PRIMARY KEY AUTOINCREMENT,
            license_key   TEXT    UNIQUE NOT NULL,
            label         TEXT,
            max_devices   INTEGER DEFAULT 1,
            bound_devices TEXT    DEFAULT '[]',
            bound_device  TEXT,
            created_at    TEXT,
            activated_at  TEXT,
            is_active     INTEGER DEFAULT 1
        )
    """)

    # ── Migration: পুরনো DB তে bound_devices column না থাকলে add করো ──
    cols = [row[1] for row in c.execute("PRAGMA table_info(license_keys)")]
    if "bound_devices" not in cols:
        c.execute("ALTER TABLE license_keys ADD COLUMN bound_devices TEXT DEFAULT '[]'")
        # পুরনো bound_device data migrate করো
        c.execute("UPDATE license_keys SET bound_devices = '[\"' || bound_device || '\"]' WHERE bound_device IS NOT NULL AND bound_device != ''")

    cols2 = [row[1] for row in c.execute("PRAGMA table_info(jobs)")]
    if "updated_at" not in cols2:
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
        "jobs":        [dict(r) for r in rows],
        "scraper_ok":  scraper_ok,
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
#  DEVICE MANAGEMENT
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
#  ✅ FIXED: LICENSE KEY VERIFY — Multi-device support
# ══════════════════════════════════════════════════════════

import json as _json

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

    max_devices = int(row["max_devices"] or 1)
    now         = datetime.now().isoformat()

    # bound_devices — JSON list of device IDs
    try:
        bound_devices = _json.loads(row["bound_devices"] or "[]")
        if not isinstance(bound_devices, list):
            bound_devices = []
    except:
        bound_devices = []

    # এই device আগে থেকেই bound থাকলে — allow করো
    if device_id in bound_devices:
        label = row["label"] or "License Key Active"
        conn.close()
        return jsonify({
            "ok":           True,
            "valid":        True,
            "message":      f"✅ License Activated! ({label})",
            "license_type": label
        })

    # নতুন device — limit check করো
    if len(bound_devices) >= max_devices:
        conn.close()
        return jsonify({
            "ok":    False,
            "valid": False,
            "message": f"❌ Device limit reached! This key allows max {max_devices} device(s). Contact admin to increase limit."
        })

    # নতুন device add করো
    bound_devices.append(device_id)
    conn.execute(
        "UPDATE license_keys SET bound_devices=?, bound_device=?, activated_at=? WHERE license_key=?",
        (_json.dumps(bound_devices), device_id, now, license_key)
    )
    conn.commit()

    label = row["label"] or "License Key Active"
    conn.close()

    return jsonify({
        "ok":           True,
        "valid":        True,
        "message":      f"✅ License Activated! ({label})",
        "license_type": label
    })


@app.route("/api/license/unbind", methods=["POST"])
def license_unbind():
    """Admin: unbind সব device অথবা specific device।"""
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    license_key = str(data.get("license_key", "") or "").strip()
    device_id   = str(data.get("device_id",   "") or "").strip()  # optional

    if not license_key:
        return jsonify({"error": "license_key required"}), 400

    conn = get_db()

    if device_id:
        # Specific device unbind
        row = conn.execute(
            "SELECT bound_devices FROM license_keys WHERE license_key=?", (license_key,)
        ).fetchone()
        if row:
            try:
                bound = _json.loads(row["bound_devices"] or "[]")
                if device_id in bound:
                    bound.remove(device_id)
            except:
                bound = []
            conn.execute(
                "UPDATE license_keys SET bound_devices=? WHERE license_key=?",
                (_json.dumps(bound), license_key)
            )
    else:
        # সব device unbind
        conn.execute(
            "UPDATE license_keys SET bound_devices='[]', bound_device=NULL, activated_at=NULL WHERE license_key=?",
            (license_key,)
        )

    conn.commit()
    conn.close()
    return jsonify({"ok": True, "message": "Unbound successfully"})


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

    result = []
    for r in rows:
        d = dict(r)
        try:
            bound = _json.loads(d.get("bound_devices") or "[]")
        except:
            bound = []
        d["bound_devices_list"] = bound
        d["bound_count"]        = len(bound)
        result.append(d)

    return jsonify(result)


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
            "INSERT INTO license_keys (license_key, label, max_devices, bound_devices, created_at, is_active) VALUES (?,?,?,?,?,1)",
            (key, label, max_devices, "[]", now)
        )
        generated.append(key)
    conn.commit()
    conn.close()
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


@app.route("/api/admin/licenses/update-limit", methods=["POST"])
def admin_update_limit():
    """Admin: key এর max_devices limit বাড়ানো/কমানো।"""
    if not check_admin(request):
        return jsonify({"error": "Unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    license_key = str(data.get("license_key", "") or "").strip()
    max_devices = int(data.get("max_devices", 1))
    if not license_key:
        return jsonify({"error": "license_key required"}), 400
    conn = get_db()
    conn.execute(
        "UPDATE license_keys SET max_devices=? WHERE license_key=?",
        (max_devices, license_key)
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "message": f"Limit updated to {max_devices} devices"})


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
#  ADMIN PANEL
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
