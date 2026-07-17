import os
import io
import time as _time_module
import telebot
import random
import re
import json
import unicodedata
import hashlib
import secrets as secrets_module
from google import genai
from faker import Faker
from datetime import datetime as _dt, timedelta
from werkzeug.security import generate_password_hash, check_password_hash as _wz_check
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from threading import Thread, Lock
from functools import wraps
from collections import deque

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Persistent KV Store (PostgreSQL ▶ JSON file fallback)
# Set DATABASE_URL env var to enable cross-deploy persistence.
# Without it the app works normally using local JSON files.
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
_db_conn = None
_db_lock = Lock()

def _get_db():
    """Return a live psycopg2 connection, or None if DATABASE_URL not set."""
    global _db_conn
    if not _DATABASE_URL:
        return None
    with _db_lock:
        try:
            if _db_conn is None or _db_conn.closed:
                import psycopg2
                _db_conn = psycopg2.connect(_DATABASE_URL, sslmode='require')
                _db_conn.autocommit = True
                with _db_conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS kv_store (
                            key   TEXT PRIMARY KEY,
                            value TEXT NOT NULL
                        )
                    """)
        except Exception as e:
            print(f"[DB] connect error: {e}")
            _db_conn = None
    return _db_conn

def db_get(key: str):
    """Return parsed JSON for key, or None (no DB or key missing)."""
    conn = _get_db()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM kv_store WHERE key = %s", (key,))
            row = cur.fetchone()
            return json.loads(row[0]) if row else None
    except Exception as e:
        print(f"[DB] get({key}) error: {e}")
        return None

def db_set(key: str, value) -> bool:
    """Upsert JSON-serialised value. Returns True on success."""
    conn = _get_db()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO kv_store (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (key, json.dumps(value, ensure_ascii=False)))
        return True
    except Exception as e:
        print(f"[DB] set({key}) error: {e}")
        return False

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Config — loaded from PostgreSQL then config.json
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONFIG_FILE = "config.json"
config_lock = Lock()

def _hash_password(password: str) -> str:
    """Return a Werkzeug scrypt/PBKDF2 hash of the password."""
    return generate_password_hash(password)

NAMES_DEFAULT_FILE = "names_default.json"

# ── Profile field definitions ──────────────────
FIELD_KEYS = ['full_name', 'nickname', 'facebook_id', 'google', 'whatsapp', 'email', 'mobile', 'username']
FIELD_LABELS = {
    'full_name':   'Withdrawer Name',
    'nickname':    'Nickname',
    'facebook_id': 'Facebook ID',
    'google':      'Google',
    'whatsapp':    'WhatsApp',
    'email':       'Email',
    'mobile':      'Mobile',
    'username':    'Username',
}
FIELD_EMOJI = {
    'full_name':   '👤',
    'nickname':    '🏷️',
    'facebook_id': '📘',
    'google':      '🔵',
    'whatsapp':    '💬',
    'email':       '📧',
    'mobile':      '📞',
    'username':    '🔗',
}

# Minimal emergency fallback — used only when names_default.json is missing or corrupt.
_EMERGENCY_DEFAULTS: dict = {
    "bd_first_names": ["Md"],
    "bd_last_names":  ["Rahman"],
    "bd_prefixes":    ["Md."],
}

def load_name_defaults() -> dict:
    """Load and validate default name lists from names_default.json.

    Returns a dict with keys bd_first_names, bd_last_names, bd_prefixes.
    Each value is guaranteed to be a non-empty list of non-empty strings.
    Falls back to _EMERGENCY_DEFAULTS (and prints a warning) on any error.
    """
    def _valid_str_list(val) -> bool:
        return (
            isinstance(val, list)
            and len(val) > 0
            and all(isinstance(s, str) and s.strip() for s in val)
        )

    try:
        with open(NAMES_DEFAULT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        result = {}
        for key in ("bd_first_names", "bd_last_names", "bd_prefixes"):
            val = data.get(key)
            if not _valid_str_list(val):
                raise ValueError(
                    f"'{key}' in {NAMES_DEFAULT_FILE} must be a non-empty list of strings"
                )
            result[key] = val
        return result

    except Exception as e:
        print(f"⚠️  Could not load {NAMES_DEFAULT_FILE}: {e} — using emergency defaults.")
        return {k: v[:] for k, v in _EMERGENCY_DEFAULTS.items()}

NAME_DEFAULTS = load_name_defaults()

# Fail fast at startup if we are stuck with the emergency defaults and the file
# is simply absent (common misconfiguration), so the operator notices immediately.
if NAME_DEFAULTS == {k: v[:] for k, v in _EMERGENCY_DEFAULTS.items()}:
    import warnings
    warnings.warn(
        f"{NAMES_DEFAULT_FILE} could not be loaded — "
        "name generation will be severely limited. "
        "Provide a valid names_default.json to restore full functionality.",
        RuntimeWarning,
        stacklevel=1,
    )

# Default AI prompt templates — placeholders filled at runtime:
#   BD prompt   : {prefixes}, {first_names}, {last_names}
#   Intl prompt : {country}
DEFAULT_AI_PROMPT_BD = (
    "তুমি একটি Bangladeshi নাম জেনারেটর। নিচে আমাদের নামের ডেটাবেজ থেকে কিছু উদাহরণ দেওয়া হলো:\n\n"
    "উপসর্গ (Prefix): {prefixes}\n"
    "প্রথম নাম উদাহরণ: {first_names}\n"
    "শেষ নাম উদাহরণ: {last_names}\n\n"
    "এই ডেটার ধরন ও ছন্দ বজায় রেখে একটি সম্পূর্ণ নতুন, realistic Bangladeshi পুরুষের নাম তৈরি করো।\n"
    "নামটি হুবহু উদাহরণের মতো না হয়ে নতুন ও স্বাভাবিক হতে হবে।\n"
    "ফরম্যাট: [উপসর্গ] [প্রথম নাম] [শেষ নাম]\n"
    "শুধু নামটি দাও — আর কিছু নয়, কোনো ব্যাখ্যা নয়।"
)

DEFAULT_AI_PROMPT_INTL = (
    "Generate a single realistic male full name from {country}.\n"
    "The name should sound natural and authentic for that country.\n"
    "Return only the name — no explanation, no extra text."
)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Default Bot Text Templates (all dashboard-editable)
# Placeholders use Python str.format() syntax: {variable_name}
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DEFAULT_BOT_TEXTS = {
    # /start
    "welcome": (
        "👋 ফেক প্রোফাইল জেনারেটর বটে স্বাগতম!\n\n"
        "যেকোনো দেশের নাম লিখুন:\n{country_keys}\n\n"
        "🇧🇩 এখন পর্যন্ত {used_count} টি নাম ব্যবহৃত হয়েছে।\n"
        "✅ আরও {remaining} টি ইউনিক নাম বাকি আছে।\n\n"
        "📋 /history — আগের প্রোফাইল দেখুন\n"
        "🤖 /ainame [দেশ] — AI দিয়ে real-style নাম তৈরি করুন"
    ),
    # admin notification — new user joined
    "new_user_notify": (
        "🆕 *নতুন ইউজার জয়েন করেছে!*\n\n"
        "👤 নাম: {fullname}\n"
        "🔗 Username: {uname}\n"
        "🆔 ID: `{user_id}`\n"
        "📊 মোট ইউজার: {total_users}"
    ),
    # /panel (admin)
    "panel_reply": (
        "⚙️ কন্ট্রোল প্যানেল:\n\n"
        "বট চালু আছে ✅\n"
        "ডেভলপার: {developer_name}\n"
        "মোট সম্ভাব্য নাম: {total_combinations}\n"
        "ব্যবহৃত নাম: {used_count}\n"
        "বাকি নাম: {remaining}"
    ),
    "panel_not_admin":    "❌ আপনি এই বটের অ্যাডমিন নন!",
    # /reset (admin)
    "reset_success":      "✅ সমস্ত ব্যবহৃত নাম রিসেট করা হয়েছে!",
    "reset_not_admin":    "❌ শুধু অ্যাডমিন এই কমান্ড ব্যবহার করতে পারবেন!",
    # /history
    "history_empty": (
        "📭 আপনি এখনও কোনো প্রোফাইল জেনারেট করেননি।\n"
        "যেকোনো দেশের নাম লিখলেই প্রোফাইল পাবেন!"
    ),
    "history_copy_hint":  "💡 টেক্সটে ট্যাপ করলেই কপি হয়ে যাবে।",
    # ban reply
    "banned_reply": (
        "🚫 আপনাকে এই বট থেকে ব্যান করা হয়েছে।\n"
        "আপনি আর এই বট ব্যবহার করতে পারবেন না।"
    ),
    # /ainame
    "ai_unavailable":     "⚠️ AI name generator এখন উপলব্ধ নেই।",
    "ai_unknown_country": "⚠️ অজানা দেশ।\nলিখুন: {keys}",
    "ai_generating":      "🤖 AI দিয়ে নাম তৈরি হচ্ছে, একটু অপেক্ষা করুন…",
    "ai_profile_failed":  "⚠️ প্রোফাইল তৈরি করা সম্ভব হয়নি।",
    # AI reply template — placeholders: dev_line, ai_badge, tg_mention, country, field_lines
    "ai_reply": (
        "{dev_line}"
        "{ai_badge}\n"
        "🆔 Your Telegram: {tg_mention}\n"
        "🌍 দেশ: {country}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "{field_lines}"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 টেক্সটে ট্যাপ করলেই অটো-কপি হয়ে যাবে।"
    ),
    # regular profile reply
    "unknown_country": (
        "⚠️ দুঃখিত, এটি কোনো সঠিক দেশের নাম নয়।\n\n"
        "লিখুন: {keys}"
    ),
    # profile reply template — placeholders: dev_line, tg_mention, country, field_lines
    "profile_reply": (
        "{dev_line}"
        "🆔 Your Telegram: {tg_mention}\n"
        "🌍 দেশ: {country}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "{field_lines}"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "💡 তথ্যের ওপর ট্যাপ করলেই অটো-কপি হয়ে যাবে।"
    ),
    "profile_failed":     "⚠️ দুঃখিত, প্রোফাইল ডাটা জেনারেট করা সম্ভব হয়নি।",
    # admin notification — bot crashed
    "bot_crash_notify": (
        "⚠️ বট unexpected ভাবে বন্ধ হয়ে গেছে!\n\n"
        "🔴 Error: {error}\n\n"
        "Dashboard থেকে বট রিস্টার্ট করুন।"
    ),
}

def load_config():
    defaults = {
        "bot_token": "", "password_hash": "",
        "bot_reply_fields": FIELD_KEYS[:],
        "bd_first_names": NAME_DEFAULTS["bd_first_names"][:],
        "bd_last_names":  NAME_DEFAULTS["bd_last_names"][:],
        "bd_prefixes":    NAME_DEFAULTS["bd_prefixes"][:],
        "admin_id":       int(os.environ.get("ADMIN_ID", "0") or "0"),
        "developer_name": os.environ.get("DEVELOPER_NAME", ""),
        "ai_prompt_bd":   DEFAULT_AI_PROMPT_BD,
        "ai_prompt_intl": DEFAULT_AI_PROMPT_INTL,
        "bot_texts":      {k: v for k, v in DEFAULT_BOT_TEXTS.items()},
        "nickname_sfx": ["07", "Official", "Gamer", "Pro", "Boss", "Real", "King", "BD", "X", ""],
        "countries": {
            "bangladesh": {"locale": "en_US", "code": "+880", "digits": ["13XXXXXXXX", "14XXXXXXXX", "15XXXXXXXX", "16XXXXXXXX", "19XXXXXXXX"], "is_bd": True},
            "bd":         {"locale": "en_US", "code": "+880", "digits": ["13XXXXXXXX", "14XXXXXXXX", "15XXXXXXXX", "16XXXXXXXX", "19XXXXXXXX"], "is_bd": True},
            "india":      {"locale": "en_IN", "code": "+91",  "digits": "XXXXXXXXXX", "is_bd": False},
            "usa":        {"locale": "en_US", "code": "+1",   "digits": "XXXXXXXXXX", "is_bd": False},
            "uk":         {"locale": "en_GB", "code": "+44",  "digits": "XXXXXXXXXX", "is_bd": False},
            "canada":     {"locale": "en_CA", "code": "+1",   "digits": "XXXXXXXXXX", "is_bd": False},
            "france":     {"locale": "fr_FR", "code": "+33",  "digits": "XXXXXXXXXX", "is_bd": False},
            "germany":    {"locale": "de_DE", "code": "+49",  "digits": "XXXXXXXXXX", "is_bd": False},
            "japan":      {"locale": "ja_JP", "code": "+81",  "digits": "XXXXXXXXXX", "is_bd": False},
        },
    }
    db_data = db_get("config")
    if db_data:
        saved_texts = db_data.pop("bot_texts", {})
        defaults.update(db_data)
        if saved_texts:
            defaults["bot_texts"].update(saved_texts)  # deep merge — new keys keep defaults
    return defaults

def save_config(cfg: dict):
    with config_lock:
        db_set("config", cfg)

def get_text(key: str, **kwargs) -> str:
    """Fetch a bot message template from CONFIG (dashboard-editable) and format it.
    Falls back to DEFAULT_BOT_TEXTS if the key is missing from config.
    Format errors are silently caught — the raw template is returned.
    """
    texts = CONFIG.get("bot_texts", {})
    template = texts.get(key) or DEFAULT_BOT_TEXTS.get(key, key)
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, ValueError, IndexError):
        return template

CONFIG = load_config()

# Bootstrap password hash from env var on first run (no stored hash yet)
if not CONFIG.get("password_hash"):
    _env_pass = os.environ.get("DASHBOARD_PASSWORD", "").strip()
    if not _env_pass:
        raise RuntimeError(
            "DASHBOARD_PASSWORD environment variable must be set on first run "
            "to initialise the dashboard password."
        )
    CONFIG["password_hash"] = _hash_password(_env_pass)
    save_config(CONFIG)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Gemini AI Setup
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
_GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

def generate_ai_name(country_key: str = "bangladesh") -> str | None:
    """Use Gemini to generate a realistic name, guided by the bot's own name lists.
    Prompts are loaded from CONFIG so they can be customised from the dashboard.
    Supported placeholders:
      BD prompt   — {prefixes}, {first_names}, {last_names}
      Intl prompt — {country}
    """
    if not _GEMINI_KEY:
        return None
    is_bd = country_key.lower() in ("bangladesh", "bd")

    if is_bd:
        sample_firsts = random.sample(get_first_names(), min(15, len(get_first_names())))
        sample_lasts  = random.sample(get_last_names(),  min(15, len(get_last_names())))
        prefixes      = get_prefixes()
        template = CONFIG.get("ai_prompt_bd") or DEFAULT_AI_PROMPT_BD
        prompt = template.format(
            prefixes    = ", ".join(prefixes),
            first_names = ", ".join(sample_firsts),
            last_names  = ", ".join(sample_lasts),
            country     = country_key.capitalize(),   # available but rarely used in BD template
        )
    else:
        template = CONFIG.get("ai_prompt_intl") or DEFAULT_AI_PROMPT_INTL
        prompt = template.format(
            country     = country_key.capitalize(),
            prefixes    = "",   # available but not meaningful for intl
            first_names = "",
            last_names  = "",
        )

    try:
        client   = genai.Client(api_key=_GEMINI_KEY)
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
        )
        name = response.text.strip().strip("\"'").strip()
        # Sanity check: must be 2–5 words, no special chars beyond periods/spaces
        if name and 2 <= len(name.split()) <= 5:
            return name
        return None
    except Exception as e:
        print(f"[generate_ai_name] error: {e}")
        return None

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Flask App Setup
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
app = Flask('')
app.secret_key = os.environ.get("SESSION_SECRET", "")
if not app.secret_key:
    raise RuntimeError("SESSION_SECRET environment variable must be set.")

# Recent profile log (in-memory, last 50)
recent_log = deque(maxlen=50)

# ── Jinja filter ──
@app.template_filter('format_num')
def format_num(value):
    try:
        return f"{int(value):,}"
    except Exception:
        return value

# ── Auth helpers ──
def _is_legacy_hash(h: str) -> bool:
    """Detect the old static-salt SHA-256 hex digest (64 hex chars, no $ prefix)."""
    return bool(h) and len(h) == 64 and all(c in '0123456789abcdef' for c in h)

def _legacy_hash(password: str) -> str:
    salt = "bot_dashboard_salt_v1"
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()

def check_password(plain: str) -> bool:
    stored = CONFIG.get("password_hash", "")
    if _is_legacy_hash(stored):
        if _legacy_hash(plain) != stored:
            return False
        # Migrate to secure hash on successful login
        CONFIG["password_hash"] = _hash_password(plain)
        save_config(CONFIG)
        return True
    return _wz_check(stored, plain)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            if request.path.startswith('/api/'):
                return jsonify(success=False, error='Unauthorized'), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Telegram Bot — hot-swappable
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
bot = None
bot_thread = None
bot_lock = Lock()
bot_status = {"running": False, "token_preview": "", "error": ""}

# Admin ID and developer name are now stored in config.json and managed via the dashboard.

def make_bot(token: str):
    """Create, validate (via get_me), and return a TeleBot instance, or None on error."""
    token = token.strip()
    if not token:
        return None, "No token provided."
    try:
        b = telebot.TeleBot(token)
        b.get_me()          # synchronous API call — raises if token is invalid
        register_handlers(b)
        return b, ""
    except Exception as e:
        return None, str(e)

def start_bot_polling(b):
    """Run infinity_polling in a daemon thread."""
    try:
        b.remove_webhook()
        b.infinity_polling(skip_pending=True)
    except Exception as e:
        bot_status["running"] = False
        bot_status["error"] = str(e)
        # Notify admin about the crash
        admin_id = get_admin_id()
        if admin_id:
            try:
                b.send_message(
                    admin_id,
                    get_text("bot_crash_notify", error=str(e)[:300])
                )
            except Exception:
                pass

def launch_bot(token: str):
    """Stop any existing bot and start a new one."""
    global bot, bot_thread
    with bot_lock:
        # Stop existing bot
        if bot:
            try:
                bot.stop_polling()
            except Exception:
                pass
            bot = None
        bot_status["running"] = False
        bot_status["error"] = ""

        new_bot, err = make_bot(token)
        if not new_bot:
            bot_status["error"] = err or "Invalid token."
            return False, bot_status["error"]

        bot = new_bot
        bot_status["token_preview"] = token[:10] + "..." if len(token) > 10 else token
        t = Thread(target=start_bot_polling, args=(new_bot,), daemon=True)
        t.start()
        bot_thread = t
        bot_status["running"] = True
        return True, ""

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Dynamic config accessors — all read from CONFIG (managed via dashboard API)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def get_first_names():     return CONFIG.get("bd_first_names", NAME_DEFAULTS["bd_first_names"])
def get_last_names():      return CONFIG.get("bd_last_names",  NAME_DEFAULTS["bd_last_names"])
def get_prefixes():        return CONFIG.get("bd_prefixes",    NAME_DEFAULTS["bd_prefixes"])
def get_country_details(): return CONFIG.get("countries", {})
def get_nickname_sfx():    return CONFIG.get("nickname_sfx", [""])
def get_admin_id():
    try:
        return int(CONFIG.get("admin_id") or 0)
    except (TypeError, ValueError):
        return 0
def get_developer_name():  return CONFIG.get("developer_name", "")
def get_total_combinations():
    return max(1, len(get_first_names()) * len(get_last_names()) * len(get_prefixes()))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Banned Users
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BANNED_FILE  = "banned_users.json"
banned_lock  = Lock()

def load_banned() -> dict:
    db_data = db_get("banned")
    if db_data is not None:
        return {int(k): v for k, v in db_data.items()}
    return {}

def save_banned(data: dict):
    db_set("banned", data)

BANNED_USERS: dict = load_banned()   # {user_id(int): {username, first_name, reason, timestamp}}

def is_banned(user_id: int) -> bool:
    return user_id in BANNED_USERS

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Persistent Used Names  (BD + non-BD, all in one set)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USED_NAMES_FILE  = "used_names.json"
used_names_lock  = Lock()

def load_used_names():
    db_data = db_get("used_names")
    return set(db_data) if db_data is not None else set()

def save_used_names(used: set):
    db_set("used_names", list(used))

USED_NAMES = load_used_names()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Persistent Used Phones  (global uniqueness)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
used_phones_lock = Lock()

def load_used_phones() -> set:
    db_data = db_get("used_phones")
    return set(db_data) if db_data is not None else set()

def save_used_phones(used: set):
    db_set("used_phones", list(used))

USED_PHONES: set = load_used_phones()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Persistent Used Usernames  (global uniqueness)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
used_usernames_lock = Lock()

def load_used_usernames() -> set:
    db_data = db_get("used_usernames")
    return set(db_data) if db_data is not None else set()

def save_used_usernames(used: set):
    db_set("used_usernames", list(used))

USED_USERNAMES: set = load_used_usernames()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Name-Usage Log  (who got which BD name + when)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NAME_LOG_FILE = "name_log.json"
name_log_lock = Lock()

def load_name_log() -> list:
    db_data = db_get("name_log")
    return db_data if isinstance(db_data, list) else []

def save_name_log(log: list):
    db_set("name_log", log)

NAME_LOG: list = load_name_log()

def log_name_usage(bd_name: str, user_id: int, username: str | None, first_name: str | None):
    """Record which Telegram user received this BD name."""
    from datetime import datetime, timezone
    entry = {
        "name":       bd_name,
        "user_id":    user_id,
        "username":   username or "",
        "first_name": first_name or "",
        "timestamp":  datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    with name_log_lock:
        NAME_LOG.append(entry)
        save_name_log(NAME_LOG)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Users registry — all users who ever used the bot
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USERS_FILE = "users.json"
users_lock = Lock()

def load_users() -> dict:
    db_data = db_get("users")
    if db_data is not None:
        return {int(k): v for k, v in db_data.items()}
    return {}

def save_users(data: dict):
    db_set("users", data)

KNOWN_USERS: dict = load_users()  # {user_id: {username, first_name, last_seen, profile_count}}

def track_user(user_id: int, username: str | None, first_name: str | None, increment_count: bool = False) -> bool:
    """Upsert user into registry. Thread-safe. Returns True if this is a brand-new user."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with users_lock:
        is_new = user_id not in KNOWN_USERS
        existing = KNOWN_USERS.get(user_id, {})
        KNOWN_USERS[user_id] = {
            "username":      username or existing.get("username", ""),
            "first_name":    first_name or existing.get("first_name", ""),
            "last_seen":     now,
            "profile_count": existing.get("profile_count", 0) + (1 if increment_count else 0),
        }
        save_users(KNOWN_USERS)
    return is_new

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Admin Notifications
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def notify_admin(text: str):
    """Send a notification to the admin user. Silently ignores errors."""
    admin_id = get_admin_id()
    if not admin_id:
        return
    b = bot
    if not b or not bot_status.get("running"):
        return
    try:
        b.send_message(admin_id, text, parse_mode="Markdown")
    except Exception as e:
        print(f"[notify_admin] failed: {e}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Per-User Profile History
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MAX_HISTORY_PER_USER = 10
user_profiles_lock = Lock()

def load_user_profiles() -> dict:
    db_data = db_get("user_profiles")
    if db_data is not None:
        return {int(k): v for k, v in db_data.items()}
    return {}

def save_user_profiles(data: dict):
    db_set("user_profiles", data)

USER_PROFILES: dict = load_user_profiles()

def record_user_profile(user_id: int, profile: dict):
    """Append a profile snapshot to the user's history (keep last MAX_HISTORY_PER_USER)."""
    from datetime import datetime, timezone
    entry = {k: profile.get(k, "") for k in profile}
    entry["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with user_profiles_lock:
        history = USER_PROFILES.get(user_id, [])
        history = history[-(MAX_HISTORY_PER_USER - 1):]
        history.append(entry)
        USER_PROFILES[user_id] = history
        save_user_profiles(USER_PROFILES)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Broadcast state (in-memory)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
broadcast_status = {"running": False, "total": 0, "sent": 0, "failed": 0, "done": False, "message": ""}
broadcast_lock = Lock()

def _do_broadcast(text: str, user_ids: list, bot_snapshot):
    """Run in a daemon thread. Sends message to each user_id."""
    import time
    for uid in user_ids:
        success = False
        try:
            if bot_snapshot:
                bot_snapshot.send_message(uid, text)
                success = True
        except Exception:
            pass
        with broadcast_lock:
            if success:
                broadcast_status["sent"] += 1
            else:
                broadcast_status["failed"] += 1
        time.sleep(0.05)  # ~20 msg/s — safe for Telegram limits
    with broadcast_lock:
        broadcast_status["running"] = False
        broadcast_status["done"] = True

def generate_unique_bd_name():
    global USED_NAMES
    with used_names_lock:
        total = get_total_combinations()
        if len(USED_NAMES) >= total:
            USED_NAMES = set()
            save_used_names(USED_NAMES)
        attempts = 0
        while True:
            prefix    = random.choice(get_prefixes())
            first     = random.choice(get_first_names())
            last      = random.choice(get_last_names())
            full_name = f"{prefix} {first} {last}"
            attempts += 1
            if full_name not in USED_NAMES:
                USED_NAMES.add(full_name)
                save_used_names(USED_NAMES)
                return full_name
            if attempts > total:
                USED_NAMES = set()
                save_used_names(USED_NAMES)

def generate_fake_phone(code, pattern_or_list):
    """Pick a random pattern from a list (or use the single string) then generate."""
    if isinstance(pattern_or_list, list) and pattern_or_list:
        pattern = random.choice(pattern_or_list)
    else:
        pattern = pattern_or_list
    return code + "".join(
        str(random.randint(0, 9)) if c == 'X' else c for c in pattern
    )

def clean_to_english(text):
    return "".join(
        c for c in unicodedata.normalize('NFD', text)
        if unicodedata.category(c) != 'Mn'
    )

def generate_profile(country_key):
    global USED_PHONES, USED_USERNAMES
    country_details = get_country_details()
    if country_key not in country_details:
        return None
    details = country_details[country_key]

    # ── 1. Unique full name ──────────────────────────────────────
    if details['is_bd']:
        full_name = generate_unique_bd_name()
    else:
        fake = Faker(details['locale'])
        # Retry until we get a name no other user has received
        with used_names_lock:
            for _ in range(200):
                candidate = clean_to_english(fake.name_male())
                if candidate not in USED_NAMES:
                    full_name = candidate
                    USED_NAMES.add(full_name)
                    save_used_names(USED_NAMES)
                    break
            else:
                # Safety valve: use as-is (extremely rare edge case)
                full_name = clean_to_english(fake.name_male())

    # ── 2. Derive base tokens ────────────────────────────────────
    tokens    = full_name.split()
    nick_base = re.sub(r'[^a-zA-Z]', '', tokens[-1] if len(tokens) > 1 else tokens[0])
    if not nick_base:
        nick_base = "User"

    clean_name = re.sub(r'[^a-zA-Z0-9]', '', full_name).lower()
    if not clean_name:
        clean_name = "user" + str(random.randint(1000, 9999))

    sfx_list = get_nickname_sfx()
    sfx      = random.choice(sfx_list) if sfx_list else ""
    nickname = f"{nick_base.capitalize()}{sfx}" if sfx else nick_base.capitalize()
    facebook_id = full_name

    # ── 3. Unique username (→ email) ─────────────────────────────
    with used_usernames_lock:
        for _ in range(10_000):
            rnum     = random.randint(100_000, 999_999)   # 6-digit suffix
            username = f"{clean_name}{rnum}"
            if username not in USED_USERNAMES:
                USED_USERNAMES.add(username)
                save_used_usernames(USED_USERNAMES)
                break
        else:
            rnum     = random.randint(100_000, 999_999)
            username = f"{clean_name}{rnum}"

    email = f"{username}@gmail.com"

    # ── 4. Unique phone ──────────────────────────────────────────
    with used_phones_lock:
        for _ in range(10_000):
            phone = generate_fake_phone(details['code'], details['digits'])
            if phone not in USED_PHONES:
                USED_PHONES.add(phone)
                save_used_phones(USED_PHONES)
                break
        # If somehow all tried phones are taken, last generated value is used

    return {
        "country":     country_key,
        "full_name":   full_name,
        "nickname":    nickname,
        "username":    username,
        "facebook_id": facebook_id,
        "google":      email,
        "whatsapp":    phone,
        "email":       email,
        "mobile":      phone,
    }

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Telegram Handler Registration
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def register_handlers(b: telebot.TeleBot):

    def _get_enabled_fields():
        return CONFIG.get("bot_reply_fields", FIELD_KEYS)

    @b.message_handler(commands=['start'])
    def send_welcome(message):
        is_new = track_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        used_count   = len(USED_NAMES)
        remaining    = get_total_combinations() - used_count
        country_keys = ", ".join(k.capitalize() for k in get_country_details().keys())
        b.reply_to(message, get_text("welcome",
            country_keys=country_keys,
            used_count=f"{used_count:,}",
            remaining=f"{remaining:,}",
        ))
        if is_new:
            user = message.from_user
            uname    = f"@{user.username}" if user.username else "N/A"
            fullname = f"{user.first_name or ''} {user.last_name or ''}".strip() or "N/A"
            Thread(target=notify_admin, args=(
                get_text("new_user_notify",
                    fullname=fullname, uname=uname,
                    user_id=user.id, total_users=f"{len(KNOWN_USERS):,}"),
            ), daemon=True).start()

    @b.message_handler(commands=['panel'])
    def admin_panel(message):
        admin_id = get_admin_id()
        if admin_id and message.from_user.id == admin_id:
            total = get_total_combinations()
            b.reply_to(message, get_text("panel_reply",
                developer_name=get_developer_name(),
                total_combinations=f"{total:,}",
                used_count=f"{len(USED_NAMES):,}",
                remaining=f"{total - len(USED_NAMES):,}",
            ))
        else:
            b.reply_to(message, get_text("panel_not_admin"))

    @b.message_handler(commands=['reset'])
    def reset_names(message):
        admin_id = get_admin_id()
        if admin_id and message.from_user.id == admin_id:
            global USED_NAMES
            USED_NAMES = set()
            save_used_names(USED_NAMES)
            b.reply_to(message, get_text("reset_success"))
        else:
            b.reply_to(message, get_text("reset_not_admin"))

    @b.message_handler(commands=['history'])
    def send_history(message):
        track_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        with user_profiles_lock:
            history = list(USER_PROFILES.get(message.from_user.id, []))
        if not history:
            b.reply_to(message, get_text("history_empty"))
            return
        lines = [f"📋 আপনার শেষ *{len(history)}* টি প্রোফাইল:\n"]
        for i, p in enumerate(reversed(history), 1):
            ts = p.get("timestamp", "")[:10]
            country = p.get("country", "").capitalize()
            lines.append(f"━━━ #{i} ┃ {country} ┃ {ts} ━━━")
            lines.append(f"👤 `{p.get('full_name', '')}`")
            lines.append(f"📧 `{p.get('email', '')}`")
            lines.append(f"📞 `{p.get('mobile', '')}`")
            lines.append("")
        lines.append(get_text("history_copy_hint"))
        b.reply_to(message, "\n".join(lines), parse_mode="Markdown")

    @b.message_handler(commands=['ainame'])
    def send_ai_name(message):
        track_user(message.from_user.id, message.from_user.username, message.from_user.first_name)

        if is_banned(message.from_user.id):
            b.reply_to(message, get_text("banned_reply"))
            return

        if not _GEMINI_KEY:
            b.reply_to(message, get_text("ai_unavailable"))
            return

        parts       = message.text.strip().split(maxsplit=1)
        country_arg = parts[1].strip().lower() if len(parts) > 1 else "bangladesh"

        country_details = get_country_details()
        if country_arg not in country_details:
            keys = ", ".join(k.capitalize() for k in country_details.keys())
            b.reply_to(message, get_text("ai_unknown_country", keys=keys))
            return

        wait_msg = b.reply_to(message, get_text("ai_generating"))

        def _do_ainame():
            ai_name = generate_ai_name(country_arg)

            # Fall back to regular generation if AI fails
            profile = generate_profile(country_arg)
            if not profile:
                try:
                    b.delete_message(message.chat.id, wait_msg.message_id)
                except Exception:
                    pass
                b.reply_to(message, get_text("ai_profile_failed"))
                return

            if ai_name:
                profile["full_name"]   = ai_name
                profile["facebook_id"] = ai_name
                clean = re.sub(r'[^a-zA-Z0-9]', '', ai_name).lower()
                if clean:
                    rnum = random.randint(1000, 9999)
                    profile["username"] = f"{clean}{rnum}"
                    profile["email"]    = f"{clean}{rnum}@gmail.com"
                    profile["google"]   = profile["email"]

            Thread(target=record_user_profile, args=(message.from_user.id, profile), daemon=True).start()

            enabled = _get_enabled_fields()
            field_lines = ""
            for key in FIELD_KEYS:
                if key in enabled and key in profile:
                    field_lines += f"{FIELD_EMOJI[key]} {FIELD_LABELS[key]}: `{profile[key]}`\n"

            dev_name   = get_developer_name()
            dev_line   = f"👤 Developer: {dev_name}\n" if dev_name else ""
            tg         = message.from_user.username
            tg_mention = f"@{tg}" if tg else "Not Available"
            ai_badge   = "🤖 *AI Generated*" if ai_name else "⚡ *Auto Generated*"

            try:
                b.delete_message(message.chat.id, wait_msg.message_id)
            except Exception:
                pass

            b.reply_to(message,
                get_text("ai_reply",
                    dev_line=dev_line, ai_badge=ai_badge,
                    tg_mention=tg_mention, country=country_arg.capitalize(),
                    field_lines=field_lines,
                ),
                parse_mode="Markdown"
            )

        Thread(target=_do_ainame, daemon=True).start()

    # ────────────────────────────────────────────
    # Admin Bot Commands — Dashboard Control via Bot
    # ────────────────────────────────────────────
    def _admin_only(msg) -> bool:
        """Returns True if sender is admin, otherwise replies and returns False."""
        admin_id = get_admin_id()
        if admin_id and msg.from_user.id == admin_id:
            return True
        b.reply_to(msg, "❌ এই কমান্ড শুধু অ্যাডমিন ব্যবহার করতে পারবেন!")
        return False

    @b.message_handler(commands=['admin', 'menu'])
    def admin_menu(message):
        if not _admin_only(message): return
        b.reply_to(message,
            "🔐 *অ্যাডমিন কন্ট্রোল প্যানেল*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📊 *পরিসংখ্যান ও লগ*\n"
            "• /stats — বট স্ট্যাটস\n"
            "• /users — ইউজার লিস্ট\n"
            "• /usage — নেম ইউজেজ লগ\n\n"
            "🚫 *ব্যান ম্যানেজমেন্ট*\n"
            "• /banned — ব্যানড লিস্ট\n"
            "• /ban `<id>` [কারণ] — ব্যান করুন\n"
            "• /unban `<id>` — ব্যান তুলুন\n\n"
            "⚙️ *কনফিগ ও ফিল্ড*\n"
            "• /config — বর্তমান কনফিগ\n"
            "• /fields — প্রোফাইল ফিল্ড স্ট্যাটাস\n"
            "• /setdev `<নাম>` — ডেভলপার নাম\n"
            "• /setadminid `<id>` — অ্যাডমিন ID\n\n"
            "🧪 *জেনারেট ও টেস্ট*\n"
            "• /gen `<country>` — টেস্ট প্রোফাইল\n"
            "• /reset — ব্যবহৃত নাম রিসেট\n\n"
            "📢 *ব্রডকাস্ট*\n"
            "• /broadcast `<টেক্সট>` — সবাইকে মেসেজ\n\n"
            "🛑 *বট স্টপ*\n"
            "• /stopbot — পোলিং বন্ধ করুন",
            parse_mode="Markdown"
        )

    @b.message_handler(commands=['stats'])
    def bot_stats(message):
        if not _admin_only(message): return
        total  = get_total_combinations()
        used   = len(USED_NAMES)
        remain = max(total - used, 0)
        b.reply_to(message,
            "📊 *বট স্ট্যাটস*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔤 মোট নাম সম্ভাবনা: `{total:,}`\n"
            f"✅ ব্যবহৃত নাম: `{used:,}`\n"
            f"🆕 বাকি নাম: `{remain:,}`\n\n"
            f"👥 মোট ইউজার: `{len(KNOWN_USERS):,}`\n"
            f"🚫 ব্যানড ইউজার: `{len(BANNED_USERS):,}`\n"
            f"🌍 সাপোর্টেড দেশ: `{len(get_country_details())}`\n\n"
            f"👤 ডেভলপার: {get_developer_name() or '_(সেট নেই)_'}\n"
            f"🆔 Admin ID: `{get_admin_id() or '(সেট নেই)'}`",
            parse_mode="Markdown"
        )

    @b.message_handler(commands=['users'])
    def users_list(message):
        if not _admin_only(message): return
        parts    = message.text.strip().split()
        page     = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
        per_page = 10
        all_u    = sorted(KNOWN_USERS.items(),
                          key=lambda x: x[1].get("profile_count", 0), reverse=True)
        total        = len(all_u)
        total_pages  = max((total + per_page - 1) // per_page, 1)
        page         = max(1, min(page, total_pages))
        start        = (page - 1) * per_page
        chunk        = all_u[start:start + per_page]
        lines = [f"👥 *ইউজার লিস্ট* — পেজ {page}/{total_pages} (মোট {total:,})\n"]
        for rank, (uid, info) in enumerate(chunk, start + 1):
            uname = f"@{info['username']}" if info.get("username") else "—"
            name  = info.get("first_name") or "—"
            count = info.get("profile_count", 0)
            lines.append(f"{rank}. {name} {uname}\n   🆔 `{uid}` | 📋 {count} profiles")
        if page < total_pages:
            lines.append(f"\n➡️ পরের পেজ: /users {page + 1}")
        b.reply_to(message, "\n".join(lines), parse_mode="Markdown")

    @b.message_handler(commands=['usage'])
    def usage_list(message):
        if not _admin_only(message): return
        parts    = message.text.strip().split()
        page     = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
        per_page = 15
        names    = sorted(USED_NAMES)
        total    = len(names)
        if not total:
            b.reply_to(message, "ℹ️ এখনও কোনো নাম ব্যবহৃত হয়নি।")
            return
        total_pages = max((total + per_page - 1) // per_page, 1)
        page        = max(1, min(page, total_pages))
        start       = (page - 1) * per_page
        chunk       = names[start:start + per_page]
        lines = [f"📋 *ব্যবহৃত নাম লগ* — পেজ {page}/{total_pages} (মোট {total:,})\n"]
        for i, name in enumerate(chunk, start + 1):
            lines.append(f"{i}. `{name}`")
        if page < total_pages:
            lines.append(f"\n➡️ পরের পেজ: /usage {page + 1}")
        b.reply_to(message, "\n".join(lines), parse_mode="Markdown")

    @b.message_handler(commands=['banned'])
    def banned_list_cmd(message):
        if not _admin_only(message): return
        if not BANNED_USERS:
            b.reply_to(message, "✅ কোনো ব্যানড ইউজার নেই।")
            return
        lines = [f"🚫 *ব্যানড ইউজার* (মোট {len(BANNED_USERS)})\n"]
        for uid, info in list(BANNED_USERS.items())[:20]:
            uname  = f"@{info.get('username')}" if info.get("username") else "—"
            reason = info.get("reason") or "—"
            lines.append(f"• `{uid}` {uname}\n  কারণ: {reason}")
        if len(BANNED_USERS) > 20:
            lines.append(f"\n…আরও {len(BANNED_USERS) - 20} জন (ড্যাশবোর্ড দেখুন)")
        b.reply_to(message, "\n".join(lines), parse_mode="Markdown")

    @b.message_handler(commands=['ban'])
    def ban_user_cmd(message):
        if not _admin_only(message): return
        parts = message.text.strip().split(maxsplit=2)
        if len(parts) < 2 or not parts[1].lstrip('-').isdigit():
            b.reply_to(message, "⚠️ ব্যবহার: /ban `<user_id>` [কারণ]", parse_mode="Markdown")
            return
        uid    = int(parts[1])
        reason = parts[2].strip() if len(parts) > 2 else "অ্যাডমিন কর্তৃক ব্যান"
        if uid in BANNED_USERS:
            b.reply_to(message, f"ℹ️ ইউজার `{uid}` ইতিমধ্যে ব্যান আছে।", parse_mode="Markdown")
            return
        info = KNOWN_USERS.get(uid, {})
        BANNED_USERS[uid] = {
            "username":   info.get("username"),
            "first_name": info.get("first_name"),
            "reason":     reason,
            "timestamp":  _dt.utcnow().isoformat(),
        }
        save_banned(BANNED_USERS)
        b.reply_to(message,
            f"✅ ইউজার `{uid}` ব্যান করা হয়েছে।\nকারণ: {reason}",
            parse_mode="Markdown"
        )

    @b.message_handler(commands=['unban'])
    def unban_user_cmd(message):
        if not _admin_only(message): return
        parts = message.text.strip().split()
        if len(parts) < 2 or not parts[1].lstrip('-').isdigit():
            b.reply_to(message, "⚠️ ব্যবহার: /unban `<user_id>`", parse_mode="Markdown")
            return
        uid = int(parts[1])
        if uid not in BANNED_USERS:
            b.reply_to(message, f"ℹ️ ইউজার `{uid}` ব্যানড নেই।", parse_mode="Markdown")
            return
        BANNED_USERS.pop(uid)
        save_banned(BANNED_USERS)
        b.reply_to(message, f"✅ ইউজার `{uid}` আনব্যান করা হয়েছে।", parse_mode="Markdown")

    @b.message_handler(commands=['broadcast'])
    def broadcast_cmd(message):
        if not _admin_only(message): return
        parts = message.text.strip().split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            b.reply_to(message, "⚠️ ব্যবহার: /broadcast `<মেসেজ টেক্সট>`", parse_mode="Markdown")
            return
        text     = parts[1].strip()
        user_ids = list(KNOWN_USERS.keys())
        if not user_ids:
            b.reply_to(message, "❌ কোনো ইউজার নেই।")
            return
        wait_msg = b.reply_to(message, f"📢 {len(user_ids):,} জনকে মেসেজ পাঠানো হচ্ছে…")
        def _do_bc():
            sent = failed = 0
            for uid in user_ids:
                try:
                    b.send_message(uid, text)
                    sent += 1
                    _time_module.sleep(0.05)   # rate-limit
                except Exception:
                    failed += 1
            try:
                b.edit_message_text(
                    f"✅ ব্রডকাস্ট সম্পন্ন!\n\n"
                    f"📤 পাঠানো: {sent}\n"
                    f"❌ ব্যর্থ: {failed}",
                    message.chat.id, wait_msg.message_id
                )
            except Exception:
                pass
        Thread(target=_do_bc, daemon=True).start()

    @b.message_handler(commands=['gen', 'generate'])
    def gen_profile_cmd(message):
        if not _admin_only(message): return
        parts       = message.text.strip().split(maxsplit=1)
        country_arg = parts[1].strip().lower() if len(parts) > 1 else "bangladesh"
        country_details = get_country_details()
        if country_arg not in country_details:
            keys = ", ".join(k.capitalize() for k in country_details.keys())
            b.reply_to(message, f"⚠️ অজানা দেশ। লিখুন: {keys}")
            return
        try:
            profile     = generate_profile(country_arg)
            enabled     = CONFIG.get("bot_reply_fields", FIELD_KEYS)
            field_lines = ""
            for key in FIELD_KEYS:
                if key in enabled and key in profile:
                    field_lines += f"{FIELD_EMOJI[key]} {FIELD_LABELS[key]}: `{profile[key]}`\n"
            b.reply_to(message,
                f"🧪 *টেস্ট প্রোফাইল* — {country_arg.capitalize()}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"{field_lines}"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"_(লগ বা হিস্ট্রিতে সেভ হয়নি)_",
                parse_mode="Markdown"
            )
        except Exception:
            b.reply_to(message, "⚠️ প্রোফাইল তৈরি করা সম্ভব হয়নি।")

    @b.message_handler(commands=['config'])
    def show_config_cmd(message):
        if not _admin_only(message): return
        token = CONFIG.get("bot_token", "")
        if len(token) > 12:
            token_masked = f"{token[:8]}…{token[-4:]}"
        elif token:
            token_masked = token
        else:
            token_masked = "_(সেট নেই)_"
        enabled_fields = CONFIG.get("bot_reply_fields", FIELD_KEYS)
        sfx_sample     = ", ".join(CONFIG.get("nickname_sfx", [])[:5])
        b.reply_to(message,
            "⚙️ *বর্তমান কনফিগ*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🤖 Token: `{token_masked}`\n"
            f"🆔 Admin ID: `{get_admin_id() or '(সেট নেই)'}`\n"
            f"👤 Developer: {get_developer_name() or '_(সেট নেই)_'}\n\n"
            f"📋 এনাবল্ড ফিল্ড: {len(enabled_fields)}/{len(FIELD_KEYS)}\n"
            f"🔤 মোট নাম সম্ভাবনা: `{get_total_combinations():,}`\n"
            f"🏷️ Nickname suffix (প্রথম ৫): {sfx_sample}\n\n"
            f"সম্পাদনা: /setdev, /setadminid বা ড্যাশবোর্ড",
            parse_mode="Markdown"
        )

    @b.message_handler(commands=['fields'])
    def show_fields_cmd(message):
        if not _admin_only(message): return
        enabled = set(CONFIG.get("bot_reply_fields", FIELD_KEYS))
        lines   = ["📋 *প্রোফাইল ফিল্ড স্ট্যাটাস*\n"]
        for key in FIELD_KEYS:
            icon  = "✅" if key in enabled else "❌"
            label = FIELD_LABELS.get(key, key)
            emoji = FIELD_EMOJI.get(key, "")
            lines.append(f"{icon} {emoji} {label} (`{key}`)")
        lines.append("\n_ফিল্ড চালু/বন্ধ করতে ড্যাশবোর্ডের Settings ট্যাব ব্যবহার করুন।_")
        b.reply_to(message, "\n".join(lines), parse_mode="Markdown")

    @b.message_handler(commands=['setdev'])
    def set_developer_cmd(message):
        if not _admin_only(message): return
        parts = message.text.strip().split(maxsplit=1)
        name  = parts[1].strip() if len(parts) > 1 else ""
        CONFIG["developer_name"] = name
        save_config(CONFIG)
        if name:
            b.reply_to(message, f"✅ ডেভলপার নাম সেট হয়েছে: *{name}*", parse_mode="Markdown")
        else:
            b.reply_to(message, "✅ ডেভলপার নাম সরিয়ে দেওয়া হয়েছে।")

    @b.message_handler(commands=['setadminid'])
    def set_admin_id_cmd(message):
        if not _admin_only(message): return
        parts = message.text.strip().split()
        if len(parts) < 2 or not parts[1].lstrip('-').isdigit():
            b.reply_to(message, "⚠️ ব্যবহার: /setadminid `<telegram_id>`", parse_mode="Markdown")
            return
        new_id = int(parts[1])
        CONFIG["admin_id"] = new_id
        save_config(CONFIG)
        b.reply_to(message, f"✅ Admin ID সেট হয়েছে: `{new_id}`", parse_mode="Markdown")

    @b.message_handler(commands=['stopbot'])
    def stop_bot_cmd(message):
        if not _admin_only(message): return
        b.reply_to(message, "🛑 বট পোলিং বন্ধ করা হচ্ছে…")
        Thread(target=lambda: b.stop_polling(), daemon=True).start()

    @b.message_handler(func=lambda message: True)
    def handle_all_messages(message):
        is_new = track_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        if is_new:
            user = message.from_user
            uname    = f"@{user.username}" if user.username else "N/A"
            fullname = f"{user.first_name or ''} {user.last_name or ''}".strip() or "N/A"
            Thread(target=notify_admin, args=(
                get_text("new_user_notify",
                    fullname=fullname, uname=uname,
                    user_id=user.id, total_users=f"{len(KNOWN_USERS):,}"),
            ), daemon=True).start()

        if is_banned(message.from_user.id):
            b.reply_to(message, get_text("banned_reply"))
            return

        if not message.text:
            return

        country_input   = message.text.strip().lower()
        country_details = get_country_details()
        if country_input not in country_details:
            keys = ", ".join(k.capitalize() for k in country_details.keys())
            b.reply_to(message, get_text("unknown_country", keys=keys))
            return
        try:
            profile = generate_profile(country_input)
            recent_log.append(profile)
            Thread(target=record_user_profile, args=(message.from_user.id, profile), daemon=True).start()
            tg          = message.from_user.username
            tg_mention  = f"@{tg}" if tg else "Not Available"
            dev_name    = get_developer_name()
            if country_details[country_input].get('is_bd'):
                log_name_usage(
                    bd_name    = profile['full_name'],
                    user_id    = message.from_user.id,
                    username   = message.from_user.username,
                    first_name = message.from_user.first_name,
                )
            track_user(
                message.from_user.id,
                message.from_user.username,
                message.from_user.first_name,
                increment_count=True,
            )
            enabled = _get_enabled_fields()
            field_lines = ""
            for key in FIELD_KEYS:
                if key in enabled and key in profile:
                    emoji = FIELD_EMOJI[key]
                    label = FIELD_LABELS[key]
                    field_lines += f"{emoji} {label}: `{profile[key]}`\n"
            dev_line = f"👤 Developer: {dev_name}\n" if dev_name else ""
            b.reply_to(message,
                get_text("profile_reply",
                    dev_line=dev_line, tg_mention=tg_mention,
                    country=country_input.capitalize(), field_lines=field_lines,
                ),
                parse_mode="Markdown"
            )
        except Exception:
            b.reply_to(message, get_text("profile_failed"))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Flask Routes — Auth
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/')
def index():
    return redirect(url_for('dashboard') if session.get('logged_in') else url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if check_password(request.form.get('password', '')):
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        error = 'Wrong password. Try again.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Flask Routes — Dashboard
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/dashboard')
@login_required
def dashboard():
    total = get_total_combinations()
    return render_template(
        'dashboard.html',
        total_combinations=total,
        used_count=len(USED_NAMES),
        remaining=total - len(USED_NAMES),
        recent_log=list(recent_log)[-20:][::-1],
        log_count=len(recent_log),
        bot_status=bot_status,
        bot_token_saved=bool(CONFIG.get("bot_token", "").strip()),
        first_names=sorted(get_first_names()),
        last_names=sorted(get_last_names()),
        prefixes=get_prefixes(),
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Flask Routes — API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/api/generate', methods=['POST'])
@login_required
def api_generate():
    data    = request.get_json(force=True)
    country = data.get('country', 'bangladesh').lower()
    profile = generate_profile(country)
    if not profile:
        return jsonify(success=False, error='Unknown country')
    recent_log.append(profile)
    return jsonify(success=True, profile=profile)

@app.route('/api/reset', methods=['POST'])
@login_required
def api_reset():
    global USED_NAMES
    USED_NAMES = set()
    save_used_names(USED_NAMES)
    return jsonify(success=True, message='✅ সমস্ত ব্যবহৃত নাম রিসেট করা হয়েছে!')

@app.route('/api/stats')
@login_required
def api_stats():
    total = get_total_combinations()
    return jsonify(
        total_combinations=total,
        used_count=len(USED_NAMES),
        remaining=total - len(USED_NAMES),
        log_count=len(recent_log),
        bot_running=bot_status["running"],
        bot_error=bot_status["error"],
        first_count=len(get_first_names()),
        last_count=len(get_last_names()),
        prefix_count=len(get_prefixes()),
    )

@app.route('/api/names', methods=['GET'])
@login_required
def api_names_get():
    return jsonify(
        bd_first_names=sorted(get_first_names()),
        bd_last_names=sorted(get_last_names()),
        bd_prefixes=get_prefixes(),
        total_combinations=get_total_combinations(),
    )

@app.route('/api/names/add', methods=['POST'])
@login_required
def api_names_add():
    data  = request.get_json(force=True)
    kind  = data.get('kind', '')
    names = [n.strip().title() for n in data.get('names', []) if n.strip()]
    if kind not in ('bd_first_names', 'bd_last_names', 'bd_prefixes'):
        return jsonify(success=False, error='Invalid list type.')
    if not names:
        return jsonify(success=False, error='No valid names provided.')
    if kind == 'bd_prefixes':
        names = [n.strip() for n in data.get('names', []) if n.strip()]  # preserve prefix case
    existing = set(CONFIG.get(kind, []))
    added = [n for n in names if n not in existing]
    CONFIG[kind] = list(existing) + added
    save_config(CONFIG)
    return jsonify(success=True, added=len(added),
                   total=len(CONFIG[kind]),
                   total_combinations=get_total_combinations(),
                   message=f'✅ {len(added)} টি নাম যোগ করা হয়েছে!')

@app.route('/api/names/delete', methods=['POST'])
@login_required
def api_names_delete():
    data  = request.get_json(force=True)
    kind  = data.get('kind', '')
    name  = data.get('name', '').strip()
    if kind not in ('bd_first_names', 'bd_last_names', 'bd_prefixes'):
        return jsonify(success=False, error='Invalid list type.')
    lst = CONFIG.get(kind, [])
    if len(lst) <= 1:
        return jsonify(success=False, error='Cannot delete — list must have at least 1 item.')
    if name not in lst:
        return jsonify(success=False, error='Name not found.')
    CONFIG[kind] = [n for n in lst if n != name]
    save_config(CONFIG)
    return jsonify(success=True,
                   total=len(CONFIG[kind]),
                   total_combinations=get_total_combinations(),
                   message=f'🗑️ "{name}" মুছে ফেলা হয়েছে।')

@app.route('/api/name-usage', methods=['GET'])
@login_required
def api_name_usage():
    """Return full name-usage log, newest first."""
    q = request.args.get('q', '').strip().lower()
    with name_log_lock:
        data = list(NAME_LOG)          # copy under lock
    data.reverse()                     # newest first
    if q:
        data = [
            e for e in data
            if q in e['name'].lower()
            or q in e['username'].lower()
            or q in e['first_name'].lower()
            or q in str(e['user_id'])
        ]
    return jsonify(entries=data, total=len(NAME_LOG))

@app.route('/api/name-usage/delete', methods=['POST'])
@login_required
def api_name_usage_delete():
    """Remove exactly the first matching entry by name+user_id combo, then free the name."""
    global USED_NAMES
    data = request.get_json(force=True)
    name = data.get('name', '').strip()
    if not name:
        return jsonify(success=False, error='Name required.')
    with name_log_lock:
        idx = next((i for i, e in enumerate(NAME_LOG) if e['name'] == name), None)
        if idx is None:
            return jsonify(success=False, error='Entry not found.')
        NAME_LOG.pop(idx)
        save_name_log(NAME_LOG)
    with used_names_lock:
        USED_NAMES.discard(name)
        save_used_names(USED_NAMES)
    return jsonify(success=True, message=f'✅ "{name}" লগ থেকে মুছে নাম মুক্ত করা হয়েছে।')

@app.route('/api/name-usage/reset-user', methods=['POST'])
@login_required
def api_name_usage_reset_user():
    """Remove all entries for one Telegram user_id (frees their names too)."""
    global USED_NAMES
    data = request.get_json(force=True)
    try:
        user_id = int(data.get('user_id', 0))
    except (TypeError, ValueError):
        return jsonify(success=False, error='Invalid user_id.')
    if not user_id:
        return jsonify(success=False, error='user_id required.')
    with name_log_lock:
        freed = [e['name'] for e in NAME_LOG if e['user_id'] == user_id]
        NAME_LOG[:] = [e for e in NAME_LOG if e['user_id'] != user_id]
        save_name_log(NAME_LOG)
    with used_names_lock:
        for n in freed:
            USED_NAMES.discard(n)
        save_used_names(USED_NAMES)
    return jsonify(success=True, freed=len(freed),
                   message=f'✅ এই ইউজারের {len(freed)} টি নাম মুক্ত করা হয়েছে।')

@app.route('/api/name-usage/reset-all', methods=['POST'])
@login_required
def api_name_usage_reset_all():
    """Wipe entire usage log and free all BD names."""
    global USED_NAMES
    with name_log_lock:
        NAME_LOG.clear()
        save_name_log(NAME_LOG)
    with used_names_lock:
        USED_NAMES = set()
        save_used_names(USED_NAMES)
    return jsonify(success=True, message='✅ সমস্ত ট্র্যাকিং ডেটা রিসেট হয়েছে!')

# ── Ban / Unban ──────────────────────────────
@app.route('/api/banned', methods=['GET'])
@login_required
def api_banned_list():
    with banned_lock:
        data = [
            {"user_id": uid, **info}
            for uid, info in BANNED_USERS.items()
        ]
    data.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return jsonify(entries=data, total=len(data))

@app.route('/api/banned/ban', methods=['POST'])
@login_required
def api_ban_user():
    from datetime import datetime, timezone
    global BANNED_USERS
    body     = request.get_json(force=True)
    try:
        user_id = int(body.get("user_id", 0))
    except (TypeError, ValueError):
        return jsonify(success=False, error="Invalid user_id.")
    if not user_id:
        return jsonify(success=False, error="user_id required.")
    reason   = str(body.get("reason", "")).strip() or "No reason given"
    username = str(body.get("username", "")).strip()
    first_name = str(body.get("first_name", "")).strip()
    with banned_lock:
        BANNED_USERS[user_id] = {
            "username":   username,
            "first_name": first_name,
            "reason":     reason,
            "timestamp":  datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }
        save_banned(BANNED_USERS)
    label = f"@{username}" if username else first_name or str(user_id)
    return jsonify(success=True, message=f"🚫 {label} ব্যান করা হয়েছে।")

@app.route('/api/banned/unban', methods=['POST'])
@login_required
def api_unban_user():
    global BANNED_USERS
    body = request.get_json(force=True)
    try:
        user_id = int(body.get("user_id", 0))
    except (TypeError, ValueError):
        return jsonify(success=False, error="Invalid user_id.")
    if not user_id:
        return jsonify(success=False, error="user_id required.")
    with banned_lock:
        if user_id not in BANNED_USERS:
            return jsonify(success=False, error="User is not banned.")
        info = BANNED_USERS.pop(user_id)
        save_banned(BANNED_USERS)
    label = f"@{info.get('username')}" if info.get('username') else info.get('first_name') or str(user_id)
    return jsonify(success=True, message=f"✅ {label} আনব্যান করা হয়েছে।")

@app.route('/api/names/reset-defaults', methods=['POST'])
@login_required
def api_names_reset_defaults():
    data = request.get_json(force=True)
    kind = data.get('kind', '')
    if kind not in ('bd_first_names', 'bd_last_names', 'bd_prefixes'):
        return jsonify(success=False, error='Invalid list type.')
    # Reload from file each time so changes to names_default.json take effect
    fresh_defaults = load_name_defaults()
    new_list = fresh_defaults.get(kind, [])
    if not new_list:
        return jsonify(success=False, error=f'Could not load defaults from {NAMES_DEFAULT_FILE}.')
    CONFIG[kind] = new_list[:]
    save_config(CONFIG)
    return jsonify(success=True,
                   total=len(CONFIG[kind]),
                   total_combinations=get_total_combinations(),
                   message='✅ ডিফল্ট লিস্টে ফিরে যাওয়া হয়েছে!')

@app.route('/api/set-bot-token', methods=['POST'])
@login_required
def api_set_bot_token():
    data  = request.get_json(force=True)
    token = data.get('token', '').strip()
    if not token:
        return jsonify(success=False, error='Token cannot be empty.')
    ok, err = launch_bot(token)
    if not ok:
        return jsonify(success=False, error=f'Invalid token: {err}')
    CONFIG['bot_token'] = token
    save_config(CONFIG)
    return jsonify(success=True, message='✅ Bot connected successfully!')

@app.route('/api/stop-bot', methods=['POST'])
@login_required
def api_stop_bot():
    global bot
    with bot_lock:
        if bot:
            try:
                bot.stop_polling()
            except Exception:
                pass
            bot = None
        bot_status["running"] = False
        bot_status["error"]   = ""
        bot_status["token_preview"] = ""
    CONFIG['bot_token'] = ''
    save_config(CONFIG)
    return jsonify(success=True, message='🛑 Bot stopped.')

@app.route('/api/change-password', methods=['POST'])
@login_required
def api_change_password():
    data         = request.get_json(force=True)
    current_pass = data.get('current', '')
    new_pass     = data.get('new', '').strip()
    if not check_password(current_pass):
        return jsonify(success=False, error='Current password is incorrect.')
    if len(new_pass) < 6:
        return jsonify(success=False, error='New password must be at least 6 characters.')
    CONFIG['password_hash'] = _hash_password(new_pass)
    save_config(CONFIG)
    return jsonify(success=True, message='✅ Password changed! Please log in again.')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Flask Routes — Countries API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/api/countries', methods=['GET'])
@login_required
def api_countries_get():
    return jsonify(countries=get_country_details())

@app.route('/api/countries/add', methods=['POST'])
@login_required
def api_countries_add():
    data   = request.get_json(force=True)
    key    = data.get('key', '').strip().lower()
    locale = data.get('locale', '').strip()
    code   = data.get('code', '').strip()
    is_bd  = bool(data.get('is_bd', False))
    # Accept either a list of patterns or a single string (backward compat)
    raw_patterns = data.get('patterns') or data.get('digits') or []
    if isinstance(raw_patterns, str):
        raw_patterns = [raw_patterns]
    patterns = [p.strip() for p in raw_patterns if str(p).strip()]
    if not key:
        return jsonify(success=False, error='Country key is required (e.g. "usa").')
    if not locale or not code or not patterns:
        return jsonify(success=False, error='locale, code এবং অন্তত একটি digit pattern দিতে হবে।')
    countries = CONFIG.get('countries', {})
    exists = key in countries
    # Store as list so generate_fake_phone can pick randomly
    countries[key] = {'locale': locale, 'code': code, 'digits': patterns, 'is_bd': is_bd}
    CONFIG['countries'] = countries
    save_config(CONFIG)
    verb = 'আপডেট' if exists else 'যোগ'
    return jsonify(success=True, total=len(countries),
                   message=f'✅ "{key}" {verb} করা হয়েছে!')

@app.route('/api/countries/delete', methods=['POST'])
@login_required
def api_countries_delete():
    data = request.get_json(force=True)
    key  = data.get('key', '').strip().lower()
    countries = CONFIG.get('countries', {})
    if key not in countries:
        return jsonify(success=False, error='Country not found.')
    if len(countries) <= 1:
        return jsonify(success=False, error='At least one country must remain.')
    del countries[key]
    CONFIG['countries'] = countries
    save_config(CONFIG)
    return jsonify(success=True, total=len(countries),
                   message=f'🗑️ "{key}" মুছে ফেলা হয়েছে।')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Flask Routes — Bot Config API (admin_id, developer_name, nickname_sfx)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/api/bot-config', methods=['GET'])
@login_required
def api_bot_config_get():
    return jsonify(
        admin_id=CONFIG.get('admin_id', 0),
        developer_name=CONFIG.get('developer_name', ''),
        nickname_sfx=CONFIG.get('nickname_sfx', []),
    )

@app.route('/api/bot-config', methods=['POST'])
@login_required
def api_bot_config_set():
    data = request.get_json(force=True)
    if 'admin_id' in data:
        try:
            CONFIG['admin_id'] = int(data['admin_id']) if data['admin_id'] else 0
        except (TypeError, ValueError):
            return jsonify(success=False, error='admin_id must be a number.')
    if 'developer_name' in data:
        CONFIG['developer_name'] = str(data['developer_name']).strip()
    if 'nickname_sfx' in data:
        raw = data['nickname_sfx']
        if not isinstance(raw, list):
            return jsonify(success=False, error='nickname_sfx must be a list.')
        CONFIG['nickname_sfx'] = [str(s) for s in raw]
    save_config(CONFIG)
    return jsonify(success=True, message='✅ Bot config আপডেট হয়েছে!')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Flask Routes — Fields config API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/api/fields-config', methods=['GET'])
@login_required
def api_fields_config_get():
    return jsonify(
        all_fields=[{"key": k, "label": FIELD_LABELS[k], "emoji": FIELD_EMOJI[k]} for k in FIELD_KEYS],
        enabled=CONFIG.get("bot_reply_fields", FIELD_KEYS),
    )

@app.route('/api/fields-config', methods=['POST'])
@login_required
def api_fields_config_set():
    data = request.get_json(force=True)
    enabled = data.get("enabled", [])
    if not isinstance(enabled, list):
        return jsonify(success=False, error="enabled must be a list.")
    valid = [k for k in enabled if k in FIELD_KEYS]
    if not valid:
        return jsonify(success=False, error="অন্তত একটি ফিল্ড চালু রাখতে হবে।")
    CONFIG["bot_reply_fields"] = valid
    save_config(CONFIG)
    return jsonify(success=True, enabled=valid, message="✅ ফিল্ড সেটিং সেভ হয়েছে!")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Flask Routes — AI Prompt Customizer API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/api/ai-prompts', methods=['GET'])
@login_required
def api_ai_prompts_get():
    return jsonify(
        bd=CONFIG.get('ai_prompt_bd', DEFAULT_AI_PROMPT_BD),
        intl=CONFIG.get('ai_prompt_intl', DEFAULT_AI_PROMPT_INTL),
        default_bd=DEFAULT_AI_PROMPT_BD,
        default_intl=DEFAULT_AI_PROMPT_INTL,
    )

@app.route('/api/ai-prompts', methods=['POST'])
@login_required
def api_ai_prompts_set():
    data = request.get_json(force=True)
    changed = False
    if 'bd' in data:
        val = str(data['bd']).strip()
        if not val:
            return jsonify(success=False, error='BD prompt খালি রাখা যাবে না।')
        CONFIG['ai_prompt_bd'] = val
        changed = True
    if 'intl' in data:
        val = str(data['intl']).strip()
        if not val:
            return jsonify(success=False, error='International prompt খালি রাখা যাবে না।')
        CONFIG['ai_prompt_intl'] = val
        changed = True
    if changed:
        save_config(CONFIG)
    return jsonify(success=True, message='✅ AI Prompt সেভ হয়েছে!')

@app.route('/api/bot-texts', methods=['GET'])
@login_required
def api_bot_texts_get():
    current = CONFIG.get("bot_texts", {})
    merged  = {k: current.get(k, v) for k, v in DEFAULT_BOT_TEXTS.items()}
    return jsonify(texts=merged, defaults={k: v for k, v in DEFAULT_BOT_TEXTS.items()})

@app.route('/api/bot-texts', methods=['POST'])
@login_required
def api_bot_texts_set():
    data        = request.get_json(force=True)
    texts_input = data.get("texts", {})
    if not isinstance(texts_input, dict):
        return jsonify(success=False, error="texts must be a dict.")
    bot_texts = CONFIG.get("bot_texts", {k: v for k, v in DEFAULT_BOT_TEXTS.items()})
    updated = 0
    for key, val in texts_input.items():
        if key not in DEFAULT_BOT_TEXTS:
            continue
        val = str(val).strip()
        if not val:
            return jsonify(success=False, error=f'"{key}" খালি রাখা যাবে না।')
        bot_texts[key] = val
        updated += 1
    CONFIG["bot_texts"] = bot_texts
    save_config(CONFIG)
    return jsonify(success=True, message=f'✅ {updated} টি text সেভ হয়েছে!')

@app.route('/api/bot-texts/reset', methods=['POST'])
@login_required
def api_bot_texts_reset():
    data = request.get_json(force=True)
    key  = data.get("key", "all")
    bot_texts = CONFIG.get("bot_texts", {k: v for k, v in DEFAULT_BOT_TEXTS.items()})
    if key == "all":
        CONFIG["bot_texts"] = {k: v for k, v in DEFAULT_BOT_TEXTS.items()}
        save_config(CONFIG)
        return jsonify(success=True, texts=CONFIG["bot_texts"], message="✅ সব text ডিফল্টে ফিরে গেছে!")
    if key not in DEFAULT_BOT_TEXTS:
        return jsonify(success=False, error="Unknown text key.")
    bot_texts[key] = DEFAULT_BOT_TEXTS[key]
    CONFIG["bot_texts"] = bot_texts
    save_config(CONFIG)
    return jsonify(success=True, default_value=DEFAULT_BOT_TEXTS[key],
                   message=f'✅ "{key}" ডিফল্টে ফিরে গেছে!')

@app.route('/api/ai-prompts/reset', methods=['POST'])
@login_required
def api_ai_prompts_reset():
    data = request.get_json(force=True)
    kind = data.get('kind', 'both')
    if kind in ('bd', 'both'):
        CONFIG['ai_prompt_bd'] = DEFAULT_AI_PROMPT_BD
    if kind in ('intl', 'both'):
        CONFIG['ai_prompt_intl'] = DEFAULT_AI_PROMPT_INTL
    save_config(CONFIG)
    label = {'bd': 'BD', 'intl': 'International', 'both': 'সব'}.get(kind, 'সব')
    return jsonify(success=True,
                   bd=CONFIG['ai_prompt_bd'],
                   intl=CONFIG['ai_prompt_intl'],
                   message=f'✅ {label} prompt ডিফল্টে ফিরে গেছে!')

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Flask Routes — User stats API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/api/user-stats', methods=['GET'])
@login_required
def api_user_stats():
    q = request.args.get('q', '').strip().lower()
    with users_lock:
        data = [
            {"user_id": uid, **info}
            for uid, info in KNOWN_USERS.items()
        ]
    data.sort(key=lambda x: x.get("profile_count", 0), reverse=True)
    if q:
        data = [
            e for e in data
            if q in str(e["user_id"])
            or q in (e.get("username") or "").lower()
            or q in (e.get("first_name") or "").lower()
        ]
    return jsonify(entries=data, total=len(KNOWN_USERS))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Flask Routes — Broadcast API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/api/broadcast', methods=['POST'])
@login_required
def api_broadcast():
    if not bot or not bot_status.get("running"):
        return jsonify(success=False, error="বট চালু নেই — আগে বট কানেক্ট করুন।")
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify(success=False, error="মেসেজ খালি রাখা যাবে না।")
    with users_lock:
        user_ids = list(KNOWN_USERS.keys())
    if not user_ids:
        return jsonify(success=False, error="কোনো ইউজার রেজিস্টার্ড নেই — বটে কেউ message পাঠালে ট্র্যাক হবে।")
    # Atomically check-and-mark running under lock, then snapshot bot reference
    with broadcast_lock:
        if broadcast_status.get("running"):
            return jsonify(success=False, error="একটি broadcast চলছে, শেষ হওয়া পর্যন্ত অপেক্ষা করুন।")
        broadcast_status.update({"running": True, "total": len(user_ids), "sent": 0, "failed": 0, "done": False})
        bot_snapshot = bot  # capture current bot so mid-flight swaps don't affect this run
    t = Thread(target=_do_broadcast, args=(text, user_ids, bot_snapshot), daemon=True)
    t.start()
    return jsonify(success=True, total=len(user_ids),
                   message=f"✅ {len(user_ids)} জনকে broadcast শুরু হয়েছে।")

@app.route('/api/broadcast-status', methods=['GET'])
@login_required
def api_broadcast_status():
    with broadcast_lock:
        return jsonify(**broadcast_status)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Scheduled Messages
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
schedules_lock = Lock()

def load_schedules() -> list:
    db_data = db_get("schedules")
    return db_data if isinstance(db_data, list) else []

def save_schedules(data: list):
    db_set("schedules", data)

SCHEDULES: list = load_schedules()

WEEKDAY_NAMES = ["সোমবার","মঙ্গলবার","বুধবার","বৃহস্পতিবার","শুক্রবার","শনিবার","রবিবার"]

def _compute_next_run(time_str: str, repeat: str, weekday: int = 0) -> str:
    """Return ISO timestamp of next run for this schedule."""
    now = _dt.now()
    h, m = map(int, time_str.split(':'))
    base = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if repeat in ('once', 'daily'):
        candidate = base if base > now else base + timedelta(days=1)
    elif repeat == 'weekly':
        days_ahead = (int(weekday) - now.weekday()) % 7
        candidate = base + timedelta(days=days_ahead)
        if candidate <= now:
            candidate += timedelta(weeks=1)
    else:
        candidate = base if base > now else base + timedelta(days=1)
    return candidate.strftime('%Y-%m-%dT%H:%M:%S')

def _send_scheduled(sched: dict) -> bool:
    """Send a scheduled text message to all known users.
    Returns True if the send was attempted (bot running), False if skipped."""
    b = bot
    if not b or not bot_status.get('running'):
        return False          # bot down — do NOT consume the schedule
    text = sched.get('text', '').strip()
    if not text:
        return True           # nothing to send but schedule is valid
    with users_lock:
        user_ids = list(KNOWN_USERS.keys())
    for uid in user_ids:
        try:
            b.send_message(uid, text)
        except Exception:
            pass
        _time_module.sleep(0.05)
    return True

def _run_due_schedules():
    global SCHEDULES
    now_str = _dt.now().strftime('%Y-%m-%dT%H:%M:%S')

    # 1. Collect due schedules under lock, then release before sending
    with schedules_lock:
        due = [s for s in SCHEDULES
               if s.get('active', True)
               and s.get('next_run', '') <= now_str
               and s.get('next_run', '')]

    if not due:
        return

    # 2. Send outside the lock so API calls don't block schedule CRUD
    executed_ids = set()
    for sched in due:
        try:
            sent = _send_scheduled(sched)
        except Exception as e:
            print(f"[Scheduler] send error: {e}")
            sent = False
        if sent:
            executed_ids.add(sched['id'])

    if not executed_ids:
        return   # bot was down for all — don't advance any state

    # 3. Re-acquire lock to persist updated next_run / active
    with schedules_lock:
        changed = False
        for sched in SCHEDULES:
            if sched['id'] not in executed_ids:
                continue
            repeat = sched.get('repeat', 'once')
            if repeat == 'once':
                sched['active'] = False
            elif repeat == 'daily':
                sched['next_run'] = _compute_next_run(sched['time'], 'daily')
            elif repeat == 'weekly':
                sched['next_run'] = _compute_next_run(sched['time'], 'weekly', sched.get('weekday', 0))
            changed = True
        if changed:
            save_schedules(SCHEDULES)

def _scheduler_loop():
    """Background daemon: checks every 30 s for due schedules."""
    while True:
        _time_module.sleep(30)
        try:
            _run_due_schedules()
        except Exception as e:
            print(f"[Scheduler] loop error: {e}")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Flask Routes — Schedules API
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/api/schedules', methods=['GET'])
@login_required
def api_schedules_get():
    with schedules_lock:
        return jsonify(schedules=list(SCHEDULES))

@app.route('/api/schedules', methods=['POST'])
@login_required
def api_schedules_add():
    data      = request.get_json(force=True)
    text      = (data.get('text') or '').strip()
    time_str  = (data.get('time') or '').strip()
    repeat    = data.get('repeat', 'daily')
    weekday   = int(data.get('weekday', 0) or 0)
    if not text:
        return jsonify(success=False, error='মেসেজ খালি রাখা যাবে না।')
    if not time_str or ':' not in time_str:
        return jsonify(success=False, error='সময় সঠিকভাবে দিন (HH:MM)।')
    if repeat not in ('once', 'daily', 'weekly'):
        return jsonify(success=False, error='Invalid repeat type.')
    next_run = _compute_next_run(time_str, repeat, weekday)
    sched = {
        'id':         secrets_module.token_hex(8),
        'text':       text,
        'time':       time_str,
        'repeat':     repeat,
        'weekday':    weekday,
        'next_run':   next_run,
        'active':     True,
        'created_at': _dt.now().strftime('%Y-%m-%dT%H:%M:%S'),
    }
    with schedules_lock:
        SCHEDULES.append(sched)
        save_schedules(SCHEDULES)
    return jsonify(success=True, schedule=sched,
                   message=f'✅ Schedule যোগ হয়েছে! পরবর্তী রান: {next_run}')

@app.route('/api/schedules/delete', methods=['POST'])
@login_required
def api_schedules_delete():
    data = request.get_json(force=True)
    sid  = data.get('id', '')
    with schedules_lock:
        idx = next((i for i, s in enumerate(SCHEDULES) if s['id'] == sid), None)
        if idx is None:
            return jsonify(success=False, error='Schedule পাওয়া যায়নি।')
        SCHEDULES.pop(idx)
        save_schedules(SCHEDULES)
    return jsonify(success=True, message='🗑️ Schedule মুছে ফেলা হয়েছে।')

@app.route('/api/schedules/toggle', methods=['POST'])
@login_required
def api_schedules_toggle():
    data = request.get_json(force=True)
    sid  = data.get('id', '')
    with schedules_lock:
        sched = next((s for s in SCHEDULES if s['id'] == sid), None)
        if not sched:
            return jsonify(success=False, error='Schedule পাওয়া যায়নি।')
        sched['active'] = not sched.get('active', True)
        if sched['active']:
            sched['next_run'] = _compute_next_run(
                sched['time'], sched['repeat'], sched.get('weekday', 0))
        save_schedules(SCHEDULES)
    return jsonify(success=True, active=sched['active'],
                   message=f"✅ {'চালু' if sched['active'] else 'বন্ধ'} করা হয়েছে।")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Flask Routes — Send Media to User(s)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/api/send-media', methods=['POST'])
@login_required
def api_send_media():
    if not bot or not bot_status.get('running'):
        return jsonify(success=False, error='বট চালু নেই — আগে বট কানেক্ট করুন।')
    media_type   = request.form.get('type', 'text')
    target       = request.form.get('target', 'user')
    user_id_str  = request.form.get('user_id', '').strip()
    caption      = request.form.get('caption', '').strip() or None
    text_msg     = request.form.get('text', '').strip()
    file_obj     = request.files.get('file')

    if target == 'all':
        with users_lock:
            user_ids = list(KNOWN_USERS.keys())
        if not user_ids:
            return jsonify(success=False, error='কোনো ইউজার রেজিস্টার্ড নেই।')
    else:
        try:
            user_ids = [int(user_id_str)]
        except (ValueError, TypeError):
            return jsonify(success=False, error='Valid User ID দিন।')

    ALLOWED_TYPES = {'text', 'photo', 'video', 'audio', 'document'}
    if media_type not in ALLOWED_TYPES:
        return jsonify(success=False, error=f'অবৈধ মিডিয়া টাইপ: {media_type}')
    if media_type != 'text' and not file_obj:
        return jsonify(success=False, error='ফাইল সিলেক্ট করুন।')
    if media_type == 'text' and not text_msg:
        return jsonify(success=False, error='মেসেজ লিখুন।')

    # Read file into BytesIO so pyTelegramBotAPI can seek+reuse it
    # and gets a proper .name attribute for multipart upload
    file_buf = None
    if file_obj and media_type != 'text':
        raw = file_obj.read()
        file_buf = io.BytesIO(raw)
        file_buf.name = file_obj.filename or f'file.{media_type}'

    b = bot
    sent = failed = 0
    for uid in user_ids:
        try:
            if media_type == 'text':
                b.send_message(uid, text_msg)
            elif media_type == 'photo':
                file_buf.seek(0); b.send_photo(uid, file_buf, caption=caption)
            elif media_type == 'video':
                file_buf.seek(0); b.send_video(uid, file_buf, caption=caption)
            elif media_type == 'audio':
                file_buf.seek(0); b.send_audio(uid, file_buf, caption=caption)
            elif media_type == 'document':
                file_buf.seek(0); b.send_document(uid, file_buf, caption=caption)
            sent += 1
        except Exception as e:
            failed += 1
            print(f"[SendMedia] uid={uid} type={media_type} error: {e}")
        if target == 'all':
            _time_module.sleep(0.05)

    msg = f'✅ {sent} জনকে পাঠানো হয়েছে।'
    if failed:
        msg += f' ❌ {failed} টি ব্যর্থ।'
    return jsonify(success=True, sent=sent, failed=failed, message=msg)

@app.route('/health')
def health():
    return "Profile Generator Bot is alive 24/7!"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Entry Point
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def run_web_server():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, use_reloader=False)

if __name__ == '__main__':
    # Start background scheduler
    _sched_thread = Thread(target=_scheduler_loop, daemon=True)
    _sched_thread.start()

    # Auto-start bot if token saved in config
    saved_token = CONFIG.get("bot_token", "").strip()
    if not saved_token:
        saved_token = os.environ.get("BOT_TOKEN", "").strip()
    if saved_token:
        ok, err = launch_bot(saved_token)
        if ok:
            print(f"🚀 Bot started | মোট সম্ভাব্য BD নাম: {get_total_combinations():,}")
        else:
            print(f"⚠️  Bot failed to start: {err}")
    else:
        print("ℹ️  No BOT_TOKEN — dashboard-only mode. Set token from the dashboard.")

    run_web_server()
