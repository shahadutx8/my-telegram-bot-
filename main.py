import os
import telebot
import random
import re
import json
import unicodedata
import hashlib
import secrets as secrets_module
from faker import Faker
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

def load_config():
    defaults = {
        "bot_token": "", "password_hash": "",
        "bot_reply_fields": FIELD_KEYS[:],
        "bd_first_names": NAME_DEFAULTS["bd_first_names"][:],
        "bd_last_names":  NAME_DEFAULTS["bd_last_names"][:],
        "bd_prefixes":    NAME_DEFAULTS["bd_prefixes"][:],
        "admin_id":       int(os.environ.get("ADMIN_ID", "0") or "0"),
        "developer_name": os.environ.get("DEVELOPER_NAME", ""),
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
        defaults.update(db_data)
    return defaults

def save_config(cfg: dict):
    with config_lock:
        db_set("config", cfg)

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
# Persistent Used Names
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

def track_user(user_id: int, username: str | None, first_name: str | None, increment_count: bool = False):
    """Upsert user into registry. Thread-safe."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with users_lock:
        existing = KNOWN_USERS.get(user_id, {})
        KNOWN_USERS[user_id] = {
            "username":      username or existing.get("username", ""),
            "first_name":    first_name or existing.get("first_name", ""),
            "last_seen":     now,
            "profile_count": existing.get("profile_count", 0) + (1 if increment_count else 0),
        }
        save_users(KNOWN_USERS)

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
    country_details = get_country_details()
    if country_key not in country_details:
        return None
    details = country_details[country_key]

    if details['is_bd']:
        full_name = generate_unique_bd_name()
    else:
        fake = Faker(details['locale'])
        full_name = clean_to_english(fake.name_male())

    # Derive nickname from original name tokens BEFORE stripping
    tokens     = full_name.split()
    nick_base  = re.sub(r'[^a-zA-Z]', '', tokens[-1] if len(tokens) > 1 else tokens[0])
    if not nick_base:
        nick_base = "User"

    clean_name = re.sub(r'[^a-zA-Z0-9]', '', full_name).lower()
    if not clean_name:
        clean_name = "user" + str(random.randint(100, 999))

    random_num   = random.randint(1000, 9999)
    suffix_num   = random.randint(10, 99)
    sfx_list     = get_nickname_sfx()
    sfx          = random.choice(sfx_list) if sfx_list else ""
    nickname     = f"{nick_base.capitalize()}{sfx}" if sfx else nick_base.capitalize()
    username     = f"{clean_name}{random_num}"
    email        = f"{clean_name}{random_num}@gmail.com"
    phone        = generate_fake_phone(details['code'], details['digits'])
    facebook_id  = full_name

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
        track_user(message.from_user.id, message.from_user.username, message.from_user.first_name)
        used_count   = len(USED_NAMES)
        remaining    = get_total_combinations() - used_count
        country_keys = ", ".join(k.capitalize() for k in get_country_details().keys())
        b.reply_to(message,
            "👋 ফেক প্রোফাইল জেনারেটর বটে স্বাগতম!\n\n"
            f"যেকোনো দেশের নাম লিখুন:\n{country_keys}\n\n"
            f"🇧🇩 এখন পর্যন্ত {used_count:,} টি নাম ব্যবহৃত হয়েছে।\n"
            f"✅ আরও {remaining:,} টি ইউনিক নাম বাকি আছে।"
        )

    @b.message_handler(commands=['panel'])
    def admin_panel(message):
        admin_id = get_admin_id()
        if admin_id and message.from_user.id == admin_id:
            total = get_total_combinations()
            b.reply_to(message,
                f"⚙️ কন্ট্রোল প্যানেল:\n\n"
                f"বট চালু আছে ✅\n"
                f"ডেভলপার: {get_developer_name()}\n"
                f"মোট সম্ভাব্য নাম: {total:,}\n"
                f"ব্যবহৃত নাম: {len(USED_NAMES):,}\n"
                f"বাকি নাম: {total - len(USED_NAMES):,}"
            )
        else:
            b.reply_to(message, "❌ আপনি এই বটের অ্যাডমিন নন!")

    @b.message_handler(commands=['reset'])
    def reset_names(message):
        admin_id = get_admin_id()
        if admin_id and message.from_user.id == admin_id:
            global USED_NAMES
            USED_NAMES = set()
            save_used_names(USED_NAMES)
            b.reply_to(message, "✅ সমস্ত ব্যবহৃত নাম রিসেট করা হয়েছে!")
        else:
            b.reply_to(message, "❌ শুধু অ্যাডমিন এই কমান্ড ব্যবহার করতে পারবেন!")

    @b.message_handler(func=lambda message: True)
    def handle_all_messages(message):
        # Always track the user
        track_user(message.from_user.id, message.from_user.username, message.from_user.first_name)

        # Ban check — reply and stop immediately
        if is_banned(message.from_user.id):
            b.reply_to(message,
                "🚫 আপনাকে এই বট থেকে ব্যান করা হয়েছে।\n"
                "আপনি আর এই বট ব্যবহার করতে পারবেন না।"
            )
            return

        # Ignore non-text updates (stickers, photos, voice, etc.)
        if not message.text:
            return

        country_input   = message.text.strip().lower()
        country_details = get_country_details()
        if country_input not in country_details:
            keys = ", ".join(k.capitalize() for k in country_details.keys())
            b.reply_to(message,
                f"⚠️ দুঃখিত, এটি কোনো সঠিক দেশের নাম নয়।\n\n"
                f"লিখুন: {keys}"
            )
            return
        try:
            profile = generate_profile(country_input)
            recent_log.append(profile)
            tg          = message.from_user.username
            tg_mention  = f"@{tg}" if tg else "Not Available"
            dev_name    = get_developer_name()
            # Track who received this BD name
            if country_details[country_input].get('is_bd'):
                log_name_usage(
                    bd_name    = profile['full_name'],
                    user_id    = message.from_user.id,
                    username   = message.from_user.username,
                    first_name = message.from_user.first_name,
                )
            # Update profile count for this user
            track_user(
                message.from_user.id,
                message.from_user.username,
                message.from_user.first_name,
                increment_count=True,
            )
            # Build reply using only enabled fields
            enabled = _get_enabled_fields()
            field_lines = ""
            for key in FIELD_KEYS:
                if key in enabled and key in profile:
                    emoji = FIELD_EMOJI[key]
                    label = FIELD_LABELS[key]
                    field_lines += f"{emoji} {label}: `{profile[key]}`\n"
            dev_line = f"👤 Developer: {dev_name}\n" if dev_name else ""
            b.reply_to(message,
                f"{dev_line}"
                f"🆔 Your Telegram: {tg_mention}\n"
                f"🌍 দেশ: {country_input.capitalize()}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"{field_lines}"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 তথ্যের ওপর ট্যাপ করলেই অটো-কপি হয়ে যাবে।",
                parse_mode="Markdown"
            )
        except Exception:
            b.reply_to(message, "⚠️ দুঃখিত, প্রোফাইল ডাটা জেনারেট করা সম্ভব হয়নি।")

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
