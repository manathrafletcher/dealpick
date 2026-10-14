"""
MFA DealPick
------------
Used-car dealerships in Tamil Nadu and Kerala log in, record a car deal, get a state-aware
sale agreement, and draft legal notices. A notice cannot be sent until an advocate approves it.

The approval rule is enforced here on the server, not only in the interface:
  * a notice moves draft -> pending_review -> approved -> sent; only an advocate can approve
  * approval stores a hash of the exact text; any later edit by the dealer withdraws approval
  * the clean (unwatermarked) document and "mark as sent" only work for an approved notice
    whose text still matches the approved hash

Run locally:   python dealpick_app.py        (http://127.0.0.1:8081)
Deploy:        gunicorn dealpick_app:app --workers 1 --threads 8 --timeout 180
"""

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import traceback
from functools import wraps

from flask import Flask, g, jsonify, request, send_file, send_from_directory, session
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import check_password_hash, generate_password_hash

import legal_content as lc
from ai_client import ai_available, ai_generate
from docgen import build_docx

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DATABASE_PATH") or os.path.join(BASE_DIR, "dealpick.db")
APP_NAME = "MFA DealPick"

app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "static"), static_url_path="/static")
_secret = os.environ.get("SECRET_KEY", "").strip()
if not _secret:
    _secret = secrets.token_hex(32)
    print("[DealPick] SECRET_KEY is not set. Using a temporary key; everyone is logged out on restart.")
app.config.update(
    SECRET_KEY=_secret,
    MAX_CONTENT_LENGTH=1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),
    PERMANENT_SESSION_LIFETIME=dt.timedelta(days=14),
)
if os.environ.get("RENDER"):
    # Behind Render's proxy: trust one hop so request.remote_addr is the visitor, not the proxy.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# ------------------------------------------------------------------ database

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('dealer','advocate')),
  name TEXT NOT NULL DEFAULT '',
  dealership_name TEXT NOT NULL DEFAULT '',
  signatory TEXT NOT NULL DEFAULT '',
  address TEXT NOT NULL DEFAULT '',
  city TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL DEFAULT 'TN',
  gstin TEXT NOT NULL DEFAULT '',
  trade_cert TEXT NOT NULL DEFAULT '',
  phone TEXT NOT NULL DEFAULT '',
  bar_enrolment TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  ref TEXT NOT NULL DEFAULT '',
  state TEXT NOT NULL,
  stage INTEGER NOT NULL DEFAULT 0,
  buyer_name TEXT NOT NULL,
  vehicle TEXT NOT NULL,
  price REAL NOT NULL,
  data TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agreements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  deal_id INTEGER NOT NULL REFERENCES deals(id),
  version INTEGER NOT NULL,
  body TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  deal_id INTEGER NOT NULL REFERENCES deals(id),
  user_id INTEGER NOT NULL REFERENCES users(id),
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  prev_body TEXT,
  facts TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'draft',
  advocate_comment TEXT NOT NULL DEFAULT '',
  decided_by INTEGER REFERENCES users(id),
  approved_by INTEGER REFERENCES users(id),
  approved_at TEXT,
  approved_hash TEXT,
  submitted_at TEXT,
  sent_on TEXT,
  sent_mode TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  notice_id INTEGER NOT NULL REFERENCES notices(id),
  at TEXT NOT NULL,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_deals_user ON deals(user_id);
CREATE INDEX IF NOT EXISTS idx_notices_deal ON notices(deal_id);
CREATE INDEX IF NOT EXISTS idx_notices_status ON notices(status);
"""


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    folder = os.path.dirname(DB_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    conn = connect()
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


init_db()


def db():
    if "db" not in g:
        g.db = connect()
    return g.db


@app.teardown_appcontext
def _close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fail(msg, code=400):
    return jsonify({"success": False, "message": msg}), code


def ok(**kw):
    kw["success"] = True
    return jsonify(kw)


# ------------------------------------------------------------------ security

@app.before_request
def _csrf_guard():
    # State-changing API calls must carry a header a cross-site form cannot set.
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.path.startswith("/api/"):
        if request.headers.get("X-Requested-With") != "DealPick":
            return fail("Request blocked. Reload the page and try again.", 403)


@app.after_request
def _headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "same-origin"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
    if os.environ.get("RENDER"):
        resp.headers["Strict-Transport-Security"] = "max-age=31536000"
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.errorhandler(413)
def _too_large(_e):
    return fail("That request is too large.", 413)


@app.errorhandler(Exception)
def _on_error(e):
    if isinstance(e, HTTPException):
        if request.path.startswith("/api/"):
            return fail(e.description or e.name, e.code)
        return e
    traceback.print_exc()
    return fail("Something went wrong on the server. Please try again.", 500)


_FAILS = {}


def _throttled(key):
    t = time.time()
    if len(_FAILS) > 2000:                                  # keep the table from growing without limit
        for k in [k for k, v in _FAILS.items() if not v or t - v[-1] > 600]:
            _FAILS.pop(k, None)
    recent = [x for x in _FAILS.get(key, []) if t - x < 600]
    if recent:
        _FAILS[key] = recent
    else:
        _FAILS.pop(key, None)
    return len(recent) >= 6


def current_user():
    uid = session.get("uid")
    if not uid:
        return None
    return db().execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()


def login_required(role=None):
    def deco(fn):
        @wraps(fn)
        def inner(*a, **kw):
            u = current_user()
            if not u:
                return fail("Please log in.", 401)
            if role and u["role"] != role:
                return fail("This is only available to " + ("dealerships." if role == "dealer" else "advocates."), 403)
            g.user = u
            return fn(*a, **kw)
        return inner
    return deco


def public_user(u):
    keys = ("id", "email", "name", "role", "dealership_name", "signatory", "address", "city",
            "state", "gstin", "trade_cert", "phone", "bar_enrolment")
    return {k: u[k] for k in keys}


# ------------------------------------------------------------------ accounts

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PROFILE_FIELDS = ("dealership_name", "signatory", "address", "city", "state", "gstin", "trade_cert", "phone")


def _txt(v, n=300):
    return str(v or "").strip()[:n]


@app.post("/api/register")
def register():
    j = request.get_json(silent=True) or {}
    role = j.get("role")
    email = _txt(j.get("email")).lower()
    pw = str(j.get("password") or "")
    if role not in ("dealer", "advocate"):
        return fail("Choose dealership or advocate sign-up.")
    if not EMAIL_RE.match(email):
        return fail("Enter a valid email address.")
    if len(pw) < 8:
        return fail("Use a password of at least 8 characters.")
    if not _txt(j.get("name")):
        return fail("Enter your name.")
    vals = {"name": _txt(j.get("name")), "phone": _txt(j.get("phone"), 30)}
    if role == "dealer":
        for k, label in (("dealership_name", "dealership name"), ("address", "dealership address"), ("city", "city")):
            if not _txt(j.get(k)):
                return fail(f"Enter your {label}.")
        if j.get("state") not in lc.STATES:
            return fail("Choose Tamil Nadu or Kerala.")
        for k in PROFILE_FIELDS:
            vals[k] = _txt(j.get(k), 500)
        vals["signatory"] = vals["signatory"] or vals["name"]
    else:
        code = os.environ.get("ADVOCATE_INVITE_CODE", "").strip()
        if not code:
            return fail("Advocate sign-up is switched off. The site owner turns it on by setting ADVOCATE_INVITE_CODE.", 403)
        if not hmac.compare_digest(code.encode("utf-8"), _txt(j.get("invite_code"), 200).encode("utf-8")):
            return fail("That invite code is not right.", 403)
        if not _txt(j.get("bar_enrolment")):
            return fail("Enter your Bar Council enrolment number. It appears on every notice you approve.")
        vals["bar_enrolment"] = _txt(j.get("bar_enrolment"), 60)
    if db().execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        return fail("An account with this email already exists. Log in instead.", 409)
    cols = ["email", "password_hash", "role", "created_at"] + list(vals)
    args = [email, generate_password_hash(pw), role, now()] + list(vals.values())
    try:
        cur = db().execute(f"INSERT INTO users ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", args)
        db().commit()
    except sqlite3.IntegrityError:
        return fail("An account with this email already exists. Log in instead.", 409)
    session.clear()
    session["uid"] = cur.lastrowid
    session.permanent = True
    return ok(user=public_user(db().execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()))


@app.post("/api/login")
def login():
    j = request.get_json(silent=True) or {}
    email = _txt(j.get("email")).lower()
    key = (request.remote_addr, email)
    if _throttled(key):
        return fail("Too many tries. Wait 10 minutes and try again.", 429)
    u = db().execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not u or not check_password_hash(u["password_hash"], str(j.get("password") or "")):
        _FAILS.setdefault(key, []).append(time.time())
        return fail("Email or password is not right.", 401)
    session.clear()
    session["uid"] = u["id"]
    session.permanent = True
    return ok(user=public_user(u))


@app.post("/api/logout")
def logout():
    session.clear()
    return ok()


@app.get("/api/me")
def me():
    u = current_user()
    return ok(user=public_user(u) if u else None, ai=ai_available())


@app.put("/api/profile")
@login_required("dealer")
def update_profile():
    j = request.get_json(silent=True) or {}
    vals = {k: _txt(j.get(k), 500) for k in PROFILE_FIELDS}
    for k in ("dealership_name", "address", "city"):
        if not vals[k]:
            return fail("Dealership name, address and city are required.")
    if vals["state"] not in lc.STATES:
        return fail("Choose Tamil Nadu or Kerala.")
    db().execute(f"UPDATE users SET {','.join(k + '=?' for k in vals)} WHERE id=?", list(vals.values()) + [g.user["id"]])
    db().commit()
    return ok(user=public_user(db().execute("SELECT * FROM users WHERE id=?", (g.user["id"],)).fetchone()))


# ------------------------------------------------------------------ deals

DEAL_KEYS = [
    "buyer_name", "buyer_rel", "buyer_rel_name", "buyer_age", "buyer_address", "buyer_city", "buyer_state",
    "buyer_phone", "buyer_email", "buyer_id_type", "buyer_id_no",
    "make", "model", "variant", "year", "reg_no", "reg_state", "chassis", "engine_no", "colour", "fuel",
    "odometer", "owners", "rc_holder", "hypothecated", "financier", "insurance_policy", "insurance_valid",
    "known_defects", "accident_history",
    "price", "advance", "advance_date", "advance_mode", "balance_due_date", "balance_mode",
    "finance_by_buyer", "buyer_financier", "delivery_date", "warranty_days", "warranty_km", "warranty_scope",
    "transfer_cost_bearer", "interest_rate", "forfeit_pct",
    "deal_state", "place", "jurisdiction_city", "arbitration", "agreement_date", "stamp_value",
    "extra_clauses", "witness1", "witness2",
]
NUMERIC = {"buyer_age": "Buyer age", "year": "Year", "odometer": "Odometer", "price": "Sale price", "advance": "Advance",
           "warranty_days": "Warranty days", "warranty_km": "Warranty km", "interest_rate": "Interest rate",
           "forfeit_pct": "Forfeiture percentage", "stamp_value": "Stamp paper value"}
LONG_TEXT = {"buyer_address", "known_defects", "extra_clauses"}
DATE_KEYS = {"advance_date": "Advance date", "balance_due_date": "Balance due date", "delivery_date": "Delivery date",
             "insurance_valid": "Insurance validity date", "agreement_date": "Agreement date"}
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def valid_date(v):
    """True for a real calendar date written YYYY-MM-DD (what the date pickers send)."""
    return bool(_DATE_RE.fullmatch(v or "")) and lc.parse_date(v) is not None


def clean_deal(j):
    d, errs = {}, []
    for k in DEAL_KEYS:
        v = _txt(j.get(k), 2000 if k in LONG_TEXT else 200)
        if k in NUMERIC and v:
            v = re.sub(r"[,\s]", "", v)
            if not re.fullmatch(r"\d+(\.\d+)?", v):
                errs.append(f"{NUMERIC[k]} must be a number.")
        d[k] = v
    for k in ("reg_no", "chassis", "engine_no"):
        d[k] = re.sub(r"\s+", " ", d[k]).upper()
    # Aadhaar numbers are never stored in full. Besides the "Aadhaar" ID type, a 12-digit number is treated as
    # Aadhaar even if the type was left blank or set to something else (no other ID here is 12 digits).
    digits = re.sub(r"\D", "", d["buyer_id_no"])
    id_type = d["buyer_id_type"].lower()
    if id_type.startswith("aadhaar") or (len(digits) == 12 and not re.search(r"[A-Za-z]", d["buyer_id_no"].replace("X", "").replace("x", ""))):
        if len(digits) >= 4:
            d["buyer_id_no"] = "XXXX XXXX " + digits[-4:]
        elif "X" not in d["buyer_id_no"].upper():
            d["buyer_id_no"] = ""
    for k, label in (("buyer_name", "buyer name"), ("buyer_address", "buyer address"), ("make", "make"),
                     ("model", "model"), ("reg_no", "registration number"), ("price", "sale price")):
        if not d[k]:
            errs.append(f"Enter the {label}.")
    for k, label in DATE_KEYS.items():
        if d[k] and not valid_date(d[k]):
            errs.append(f"{label} is not a valid date.")
    if d["year"] and re.fullmatch(r"\d+", d["year"]) and not 1950 <= int(d["year"]) <= lc.today_ist().year + 1:
        errs.append("Year of manufacture looks wrong.")
    if d["buyer_age"] and re.fullmatch(r"\d+", d["buyer_age"]) and not 1 <= int(d["buyer_age"]) <= 120:
        errs.append("Buyer age looks wrong.")
    for k in ("forfeit_pct", "interest_rate"):
        if d[k] and re.fullmatch(r"\d+(\.\d+)?", d[k]) and float(d[k]) > 100:
            errs.append(f"{NUMERIC[k]} cannot be more than 100.")
    if not errs:
        if lc.num(d["price"]) <= 0:
            errs.append("The sale price must be more than zero.")
        if lc.num(d["advance"]) > lc.num(d["price"]):
            errs.append("The advance cannot be more than the sale price.")
    if d["deal_state"] not in lc.STATES:
        errs.append("Choose the state this deal is made in.")
    return d, errs


def deal_dict(row):
    d = json.loads(row["data"])
    d.update(id=row["id"], ref=row["ref"], stage=row["stage"], state=row["state"], created_at=row["created_at"],
             updated_at=row["updated_at"])
    return d


def own_deal(deal_id):
    row = db().execute("SELECT * FROM deals WHERE id=? AND user_id=?", (deal_id, g.user["id"])).fetchone()
    return row


@app.get("/api/deals")
@login_required("dealer")
def list_deals():
    rows = db().execute(
        """SELECT d.id, d.ref, d.state, d.stage, d.buyer_name, d.vehicle, d.price, d.updated_at,
                  json_extract(d.data,'$.reg_no') AS reg_no,
                  (SELECT COUNT(*) FROM notices n WHERE n.deal_id=d.id) AS notices,
                  (SELECT COUNT(*) FROM notices n WHERE n.deal_id=d.id AND n.status='pending_review') AS pending,
                  (SELECT COUNT(*) FROM notices n WHERE n.deal_id=d.id AND n.status='approved') AS approved,
                  (SELECT COUNT(*) FROM notices n WHERE n.deal_id=d.id AND n.status='changes_requested') AS changes
           FROM deals d WHERE d.user_id=? ORDER BY d.updated_at DESC""", (g.user["id"],)).fetchall()
    return ok(deals=[dict(r) for r in rows])


@app.post("/api/deals")
@login_required("dealer")
def create_deal():
    d, errs = clean_deal(request.get_json(silent=True) or {})
    if errs:
        return fail(" ".join(errs))
    t = now()
    cur = db().execute(
        "INSERT INTO deals (user_id, state, buyer_name, vehicle, price, data, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        (g.user["id"], d["deal_state"], d["buyer_name"], lc.vehicle_label(d), lc.num(d["price"]), json.dumps(d), t, t))
    did = cur.lastrowid
    db().execute("UPDATE deals SET ref=? WHERE id=?", (f"DP-{d['deal_state']}-{t[:4]}-{did:05d}", did))
    db().commit()
    return ok(id=did)


@app.put("/api/deals/<int:deal_id>")
@login_required("dealer")
def update_deal(deal_id):
    row = own_deal(deal_id)
    if not row:
        return fail("Deal not found.", 404)
    d, errs = clean_deal(request.get_json(silent=True) or {})
    if errs:
        return fail(" ".join(errs))
    ref = f"DP-{d['deal_state']}-{row['created_at'][:4]}-{deal_id:05d}"
    db().execute("UPDATE deals SET state=?, ref=?, buyer_name=?, vehicle=?, price=?, data=?, updated_at=? WHERE id=?",
                 (d["deal_state"], ref, d["buyer_name"], lc.vehicle_label(d), lc.num(d["price"]), json.dumps(d), now(), deal_id))
    db().commit()
    return ok(id=deal_id)


@app.post("/api/deals/<int:deal_id>/stage")
@login_required("dealer")
def set_stage(deal_id):
    row = own_deal(deal_id)
    if not row:
        return fail("Deal not found.", 404)
    try:
        stage = int((request.get_json(silent=True) or {}).get("stage"))
    except (TypeError, ValueError):
        return fail("Choose a stage.")
    if not 0 <= stage <= 3:
        return fail("Choose a stage.")
    db().execute("UPDATE deals SET stage=?, updated_at=? WHERE id=?", (stage, now(), deal_id))
    db().commit()
    return ok(stage=stage)


def notice_prefill(d):
    price, adv = lc.num(d.get("price")), lc.num(d.get("advance"))
    pct = lc.num(d.get("forfeit_pct"), 10)
    return {"due_amount": int(max(0, price - adv)), "due_date": d.get("balance_due_date", ""),
            "delivered_on": d.get("delivery_date", ""), "forfeit_amount": int(min(adv, price * pct / 100)),
            "cheque_amount": int(max(0, price - adv))}


@app.get("/api/deals/<int:deal_id>")
@login_required("dealer")
def get_deal(deal_id):
    row = own_deal(deal_id)
    if not row:
        return fail("Deal not found.", 404)
    d = deal_dict(row)
    agreements = db().execute("SELECT id, version, created_at FROM agreements WHERE deal_id=? ORDER BY version DESC", (deal_id,)).fetchall()
    notices = db().execute("SELECT id, type, title, status, updated_at FROM notices WHERE deal_id=? ORDER BY updated_at DESC", (deal_id,)).fetchall()
    return ok(deal=d, compliance=lc.compliance(public_user(g.user), d),
              agreements=[dict(a) for a in agreements],
              notices=[dict(n, type_label=lc.NOTICE_TYPES[n["type"]]["label"]) for n in notices],
              notice_prefill=notice_prefill(d),
              balance=lc.balance_due(d), state_name=lc.STATES[row["state"]]["name"])


# ------------------------------------------------------------------ agreements

def _safe(s):
    return re.sub(r"[^\w\-]+", "_", s or "").strip("_") or "document"


@app.post("/api/deals/<int:deal_id>/agreement")
@login_required("dealer")
def make_agreement(deal_id):
    row = own_deal(deal_id)
    if not row:
        return fail("Deal not found.", 404)
    if not g.user["dealership_name"] or not g.user["address"]:
        return fail("Complete your dealership details first.")
    d = deal_dict(row)
    body = lc.build_agreement(public_user(g.user), d)
    ver = (db().execute("SELECT COALESCE(MAX(version),0) FROM agreements WHERE deal_id=?", (deal_id,)).fetchone()[0]) + 1
    cur = db().execute("INSERT INTO agreements (deal_id, version, body, created_at) VALUES (?,?,?,?)", (deal_id, ver, body, now()))
    db().execute("UPDATE deals SET stage=MAX(stage,1), updated_at=? WHERE id=?", (now(), deal_id))
    db().commit()
    return ok(id=cur.lastrowid, version=ver)


def _agreement_for(aid):
    """Agreement row if the current user may see it: the owning dealer, or an advocate reviewing a notice on that deal."""
    a = db().execute("SELECT a.*, d.user_id, d.ref, d.data FROM agreements a JOIN deals d ON d.id=a.deal_id WHERE a.id=?", (aid,)).fetchone()
    if not a:
        return None
    u = g.user
    if u["role"] == "dealer" and a["user_id"] == u["id"]:
        return a
    if u["role"] == "advocate" and db().execute(
            "SELECT 1 FROM notices WHERE deal_id=? AND status!='draft' LIMIT 1", (a["deal_id"],)).fetchone():
        return a
    return None


@app.get("/api/agreements/<int:aid>")
@login_required()
def get_agreement(aid):
    a = _agreement_for(aid)
    if not a:
        return fail("Agreement not found.", 404)
    return ok(id=a["id"], version=a["version"], body=a["body"], created_at=a["created_at"])


@app.get("/api/agreements/<int:aid>/docx")
@login_required()
def agreement_docx(aid):
    a = _agreement_for(aid)
    if not a:
        return fail("Agreement not found.", 404)
    reg = json.loads(a["data"]).get("reg_no", "")
    buf = build_docx(a["body"], footer=f"{a['ref']}   Sale agreement v{a['version']}")
    return send_file(buf, as_attachment=True, download_name=f"Sale-Agreement_{_safe(reg)}_v{a['version']}.docx",
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


# ------------------------------------------------------------------ notices

EDITABLE = ("draft", "changes_requested")
SEND_MODES = ("Registered post A.D.", "Speed post", "Email", "Hand delivery")


def digest(title, body):
    return hashlib.sha256((title + "\n" + body).encode("utf-8")).hexdigest()


def log_event(nid, actor, action, detail=""):
    db().execute("INSERT INTO events (notice_id, at, actor, action, detail) VALUES (?,?,?,?,?)", (nid, now(), actor, action, detail))


def actor_name(u):
    if u["role"] == "advocate":
        return f"Adv. {u['name']}"
    return u["dealership_name"] or u["name"]


def can_see_notice(n):
    u = g.user
    if u["role"] == "dealer":
        return n["user_id"] == u["id"]
    return n["status"] != "draft"


def get_notice(nid):
    n = db().execute("SELECT * FROM notices WHERE id=?", (nid,)).fetchone()
    return n if n and can_see_notice(n) else None


def is_final(n):
    return n["status"] in ("approved", "sent") and bool(n["approved_hash"]) and n["approved_hash"] == digest(n["title"], n["body"])


def notice_json(n):
    advocate = None
    if n["approved_by"]:
        a = db().execute("SELECT name, bar_enrolment FROM users WHERE id=?", (n["approved_by"],)).fetchone()
        advocate = {"name": a["name"], "enrolment": a["bar_enrolment"]} if a else None
    deal = db().execute("SELECT * FROM deals WHERE id=?", (n["deal_id"],)).fetchone()
    d = json.loads(deal["data"])
    owner = db().execute("SELECT dealership_name, phone, city FROM users WHERE id=?", (n["user_id"],)).fetchone()
    facts = json.loads(n["facts"] or "{}")
    events = db().execute("SELECT at, actor, action, detail FROM events WHERE notice_id=? ORDER BY id DESC", (n["id"],)).fetchall()
    latest_agr = db().execute("SELECT id, version FROM agreements WHERE deal_id=? ORDER BY version DESC LIMIT 1", (n["deal_id"],)).fetchone()
    out = {
        "id": n["id"], "deal_id": n["deal_id"], "type": n["type"], "type_label": lc.NOTICE_TYPES[n["type"]]["label"],
        "title": n["title"], "body": n["body"], "status": n["status"], "comment": n["advocate_comment"],
        "approved_at": n["approved_at"], "advocate": advocate, "final": is_final(n),
        "approval_code": (n["approved_hash"] or "")[:10].upper() if is_final(n) else "",
        "sent_on": n["sent_on"], "sent_mode": n["sent_mode"], "can_undo": bool(n["prev_body"]) and n["status"] in EDITABLE,
        "updated_at": n["updated_at"], "submitted_at": n["submitted_at"],
        "events": [dict(e) for e in events],
        "deal": {"ref": deal["ref"], "buyer": lc.buyer_block(d, short=True), "vehicle": lc.vehicle_long(d),
                 "price": lc.inr(d.get("price")), "advance": lc.inr(d.get("advance")), "balance": lc.inr(lc.balance_due(d)),
                 "delivery_date": lc.dmy(d.get("delivery_date")), "state": lc.STATES[deal["state"]]["name"],
                 "dealership": owner["dealership_name"], "dealer_phone": owner["phone"], "stage": deal["stage"],
                 "agreement_id": latest_agr["id"] if latest_agr else None,
                 "agreement_version": latest_agr["version"] if latest_agr else None},
    }
    if n["type"] == "cheque_dishonour":
        out["s138_days_left"] = lc.s138_deadline(facts)
    return out


@app.get("/api/notice-types")
@login_required()
def notice_types():
    return ok(types=[{"key": k, "label": v["label"], "blurb": v["blurb"], "fields": v["fields"]} for k, v in lc.NOTICE_TYPES.items()])


@app.post("/api/deals/<int:deal_id>/notices")
@login_required("dealer")
def create_notice(deal_id):
    row = own_deal(deal_id)
    if not row:
        return fail("Deal not found.", 404)
    j = request.get_json(silent=True) or {}
    ntype = j.get("type")
    if ntype not in lc.NOTICE_TYPES:
        return fail("Choose a notice type.")
    raw = j.get("facts") or {}
    if not isinstance(raw, dict):
        return fail("The notice details were not understood. Reload the page and try again.")
    d = deal_dict(row)
    d["_stage"] = row["stage"]
    facts = {}
    for f in lc.NOTICE_TYPES[ntype]["fields"]:
        v = _txt(raw.get(f["key"]), 3000 if f["type"] == "textarea" else 200) or f["default"]
        if f["type"] == "number" and v:
            v = re.sub(r"[,\s]", "", v)
            if not re.fullmatch(r"\d+(\.\d+)?", v):
                return fail(f"{f['label']} must be a number.")
            if f["key"].endswith("_days") and not 1 <= float(v) <= 365:
                return fail(f"{f['label']} must be between 1 and 365.")
        if f["type"] == "date" and v and not valid_date(v):
            return fail(f"{f['label']} is not a valid date.")
        if f["required"] and not v:
            return fail(f"Fill in: {f['label']}.")
        facts[f["key"]] = v
    if ntype == "cancellation_forfeiture" and lc.num(facts.get("forfeit_amount")) > lc.num(d.get("advance")):
        return fail(f"You can't keep more than the advance you received ({lc.inr(d.get('advance'))}).")
    agr = db().execute("SELECT created_at FROM agreements WHERE deal_id=? ORDER BY version DESC LIMIT 1", (deal_id,)).fetchone()
    title, body = lc.build_notice(ntype, public_user(g.user), d, facts, lc.ist_date(agr["created_at"]) if agr else "")
    t = now()
    cur = db().execute(
        "INSERT INTO notices (deal_id, user_id, type, title, body, facts, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (deal_id, g.user["id"], ntype, title, body, json.dumps(facts), "draft", t, t))
    log_event(cur.lastrowid, actor_name(g.user), "created", lc.NOTICE_TYPES[ntype]["label"])
    db().commit()
    return ok(id=cur.lastrowid)


def _notice_row_dict(r):
    r = dict(r)
    r["type_label"] = lc.NOTICE_TYPES[r["type"]]["label"]
    return r


@app.get("/api/notices")
@login_required("dealer")
def list_notices():
    rows = db().execute(
        """SELECT n.id, n.deal_id, n.type, n.title, n.status, n.updated_at, d.buyer_name, d.vehicle, d.ref
           FROM notices n JOIN deals d ON d.id=n.deal_id WHERE n.user_id=? ORDER BY n.updated_at DESC""", (g.user["id"],)).fetchall()
    return ok(notices=[_notice_row_dict(r) for r in rows])


@app.get("/api/review")
@login_required("advocate")
def review_queue():
    base = """SELECT n.id, n.type, n.title, n.status, n.submitted_at, n.updated_at, d.buyer_name, d.vehicle, u.dealership_name, d.state
              FROM notices n JOIN deals d ON d.id=n.deal_id JOIN users u ON u.id=n.user_id """
    queue = db().execute(base + "WHERE n.status='pending_review' ORDER BY n.submitted_at ASC").fetchall()
    done = db().execute(base + "WHERE n.decided_by=? AND n.status IN ('approved','sent','changes_requested') ORDER BY n.updated_at DESC LIMIT 20",
                        (g.user["id"],)).fetchall()
    return ok(queue=[_notice_row_dict(r) for r in queue], decided=[_notice_row_dict(r) for r in done])


@app.get("/api/notices/<int:nid>")
@login_required()
def notice_detail(nid):
    n = get_notice(nid)
    if not n:
        return fail("Notice not found.", 404)
    return ok(notice=notice_json(n))


@app.put("/api/notices/<int:nid>")
@login_required()
def edit_notice(nid):
    n = get_notice(nid)
    if not n:
        return fail("Notice not found.", 404)
    j = request.get_json(silent=True) or {}
    title, body = _txt(j.get("title"), 300), str(j.get("body") or "").replace("\r\n", "\n").strip()
    if not title or not body:
        return fail("A notice needs a title and text.")
    if len(body) > 60000:
        return fail("That notice is too long.")
    if title == n["title"] and body == n["body"]:
        return ok(notice=notice_json(n))
    u = g.user
    if u["role"] == "dealer":
        if n["status"] == "sent":
            return fail("This notice has been sent. Draft a new one instead.", 409)
        was = n["status"]
        db().execute("UPDATE notices SET title=?, body=?, status='draft', approved_hash=NULL, approved_by=NULL, approved_at=NULL, "
                     "submitted_at=NULL, updated_at=? WHERE id=?", (title, body, now(), nid))
        log_event(nid, actor_name(u), "edited",
                  "Approval withdrawn. Send it to your advocate again." if was == "approved" else
                  ("Taken back from the advocate for editing." if was == "pending_review" else ""))
    else:
        if n["status"] != "pending_review":
            return fail("You can edit a notice only while it waits for your review.", 409)
        db().execute("UPDATE notices SET title=?, body=?, updated_at=? WHERE id=?", (title, body, now(), nid))
        log_event(nid, actor_name(u), "advocate_edited", "Advocate changed the wording.")
    db().commit()
    return ok(notice=notice_json(get_notice(nid)))


# --- AI polish (background job so no request is held open) -------------------------------

JOBS = {}


def _numbers(text):
    return set(re.findall(r"\d[\d,./-]*\d|\d", text))


def _polish_job(jid, nid):
    job = JOBS[jid]
    conn = connect()
    try:
        n = conn.execute("SELECT * FROM notices WHERE id=?", (nid,)).fetchone()
        original = n["body"]
        out = ai_generate(original, system=lc.POLISH_SYSTEM, temperature=0.2, max_tokens=3200)
        out = re.sub(r"^```\w*\n|\n```$", "", out.strip()).strip()
        if not out or "NOTICE" not in out.upper()[:300]:
            raise RuntimeError("The AI did not return a notice. Your draft is unchanged.")
        missing = [x for x in _numbers(original) if x not in out]
        if missing:
            raise RuntimeError("The AI changed some figures or dates, so its version was not used. Your draft is unchanged.")
        done = conn.execute("UPDATE notices SET prev_body=?, body=?, status='draft', updated_at=? "
                            "WHERE id=? AND body=? AND status IN ('draft','changes_requested')",
                            (original, out, now(), nid, original))
        if done.rowcount != 1:
            conn.rollback()
            raise RuntimeError("The notice changed while the AI worked, so its version was not used.")
        conn.execute("INSERT INTO events (notice_id, at, actor, action, detail) VALUES (?,?,?,?,?)",
                     (nid, now(), job["actor"], "ai_polish", "AI tidied the wording. Undo is available."))
        conn.commit()
        job["status"] = "done"
    except Exception as e:                                  # surfaced to the person in the interface
        job["status"], job["message"] = "error", str(e)[:300]
    finally:
        conn.close()


@app.post("/api/notices/<int:nid>/polish")
@login_required("dealer")
def polish_notice(nid):
    n = get_notice(nid)
    if not n:
        return fail("Notice not found.", 404)
    if n["status"] not in EDITABLE:
        return fail("Take the notice back for editing before using AI.", 409)
    if not ai_available():
        return fail("AI tidy-up is not switched on for this site. You can still edit the text by hand.", 400)
    for k in [k for k, v in JOBS.items() if time.time() - v["started"] > 3600]:
        JOBS.pop(k, None)
    jid = secrets.token_hex(8)
    JOBS[jid] = {"status": "running", "message": "", "user": g.user["id"], "notice": nid, "started": time.time(), "actor": actor_name(g.user)}
    threading.Thread(target=_polish_job, args=(jid, nid), daemon=True).start()
    return ok(job=jid)


@app.get("/api/jobs/<jid>")
@login_required()
def job_status(jid):
    job = JOBS.get(jid)
    if not job or job["user"] != g.user["id"]:
        return fail("Job not found.", 404)
    return ok(status=job["status"], message=job["message"])


@app.post("/api/notices/<int:nid>/undo")
@login_required("dealer")
def undo_notice(nid):
    n = get_notice(nid)
    if not n or not n["prev_body"] or n["status"] not in EDITABLE:
        return fail("Nothing to undo.", 404)
    db().execute("UPDATE notices SET body=prev_body, prev_body=NULL, status='draft', updated_at=? WHERE id=?", (now(), nid))
    log_event(nid, actor_name(g.user), "undo_ai", "Went back to the wording before the AI tidy-up.")
    db().commit()
    return ok(notice=notice_json(get_notice(nid)))


# --- the approval workflow -----------------------------------------------------------------

@app.post("/api/notices/<int:nid>/submit")
@login_required("dealer")
def submit_notice(nid):
    n = get_notice(nid)
    if not n:
        return fail("Notice not found.", 404)
    if n["status"] not in EDITABLE:
        return fail("This notice is already with the advocate or approved.", 409)
    if not n["body"].strip():
        return fail("Write the notice before sending it for review.")
    db().execute("UPDATE notices SET status='pending_review', submitted_at=?, advocate_comment='', updated_at=? WHERE id=?", (now(), now(), nid))
    log_event(nid, actor_name(g.user), "submitted", "Sent to an advocate for review.")
    db().commit()
    adv = db().execute("SELECT COUNT(*) FROM users WHERE role='advocate'").fetchone()[0]
    return ok(notice=notice_json(get_notice(nid)), advocates=adv)


@app.post("/api/notices/<int:nid>/decision")
@login_required("advocate")
def decide_notice(nid):
    n = get_notice(nid)
    if not n:
        return fail("Notice not found.", 404)
    if n["status"] != "pending_review":
        return fail("This notice is not waiting for review.", 409)
    j = request.get_json(silent=True) or {}
    action, comment = j.get("action"), _txt(j.get("comment"), 2000)
    u = g.user
    if action == "approve":
        db().execute("UPDATE notices SET status='approved', approved_hash=?, approved_by=?, decided_by=?, approved_at=?, advocate_comment=?, updated_at=? WHERE id=?",
                     (digest(n["title"], n["body"]), u["id"], u["id"], now(), comment, now(), nid))
        log_event(nid, actor_name(u), "approved", comment or "Approved as written.")
    elif action == "changes":
        if not comment:
            return fail("Tell the dealership what to change.")
        db().execute("UPDATE notices SET status='changes_requested', decided_by=?, advocate_comment=?, updated_at=? WHERE id=?",
                     (u["id"], comment, now(), nid))
        log_event(nid, actor_name(u), "changes_requested", comment)
    else:
        return fail("Choose approve or request changes.")
    db().commit()
    return ok(notice=notice_json(get_notice(nid)))


@app.post("/api/notices/<int:nid>/sent")
@login_required("dealer")
def mark_sent(nid):
    n = get_notice(nid)
    if not n:
        return fail("Notice not found.", 404)
    if n["status"] != "approved" or not is_final(n):
        return fail("Only a notice approved by an advocate can be marked as sent.", 409)
    j = request.get_json(silent=True) or {}
    mode = j.get("mode")
    if mode not in SEND_MODES:
        return fail("Choose how the notice was sent.")
    raw_date = _txt(j.get("date"), 20)
    if raw_date and not valid_date(raw_date):
        return fail("Enter a valid date.")
    on = lc.parse_date(raw_date) or lc.today_ist()
    if on > lc.today_ist():
        return fail("The date sent can't be in the future.")
    db().execute("UPDATE notices SET status='sent', sent_on=?, sent_mode=?, updated_at=? WHERE id=?", (on.isoformat(), mode, now(), nid))
    log_event(nid, actor_name(g.user), "sent", f"{mode} on {lc.dmy(on.isoformat())}")
    db().commit()
    return ok(notice=notice_json(get_notice(nid)))


@app.get("/api/notices/<int:nid>/docx")
@login_required()
def notice_docx(nid):
    n = get_notice(nid)
    if not n:
        return fail("Notice not found.", 404)
    final = is_final(n)
    owner = db().execute("SELECT dealership_name FROM users WHERE id=?", (n["user_id"],)).fetchone()
    deal = db().execute("SELECT ref FROM deals WHERE id=?", (n["deal_id"],)).fetchone()
    text = n["body"]
    if final:
        a = db().execute("SELECT name, bar_enrolment FROM users WHERE id=?", (n["approved_by"],)).fetchone()
        text += "\n\n" + "\n".join([
            ">> Yours faithfully,", ">>", ">>", f">> **{a['name']}**", f">> Advocate, Enrolment No. {a['bar_enrolment']}",
            f">> Approved on {lc.dmy_utc(n['approved_at'])}. Approval code {n['approved_hash'][:10].upper()}.",
            f">> For and on behalf of {owner['dealership_name']}"])
        banner = None
    else:
        text += "\n\n>> [Advocate's signature and enrolment number appear here once the notice is approved.]"
        banner = ("WITH ADVOCATE FOR REVIEW. NOT APPROVED. DO NOT SEND." if n["status"] == "pending_review"
                  else "DRAFT. NOT APPROVED BY AN ADVOCATE. DO NOT SEND.")
    buf = build_docx(text, header_banner=banner, footer=f"{deal['ref']}   Notice {n['id']}")
    name = f"Notice_{n['id']}_{_safe(lc.NOTICE_TYPES[n['type']]['label'])}" + ("" if final else "_DRAFT") + ".docx"
    return send_file(buf, as_attachment=True, download_name=name,
                     mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


# ------------------------------------------------------------------ pages

@app.get("/healthz")
def healthz():
    return "ok", 200


@app.get("/")
def index():
    resp = send_from_directory(app.static_folder, "index.html")
    resp.headers["Cache-Control"] = "no-cache"
    return resp


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8081))
    print("\n" + "=" * 60)
    print(f"  {APP_NAME}")
    print(f"  Open: http://127.0.0.1:{port}")
    print(f"  AI tidy-up (GROQ_API_KEY): {'on' if ai_available() else 'off'}")
    print(f"  Advocate sign-up (ADVOCATE_INVITE_CODE): {'on' if os.environ.get('ADVOCATE_INVITE_CODE') else 'off'}")
    print(f"  Database: {DB_PATH}")
    print("=" * 60 + "\n")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
