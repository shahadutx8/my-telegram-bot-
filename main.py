import os
import telebot
import random
import re
import json
import unicodedata
import hashlib
import secrets as secrets_module
from faker import Faker
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from threading import Thread, Lock
from functools import wraps
from collections import deque

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Config — loaded from config.json (overrides env vars)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONFIG_FILE = "config.json"
config_lock = Lock()

def _hash_password(password: str) -> str:
    """Return a salted SHA-256 hex digest of the password."""
    salt = "bot_dashboard_salt_v1"
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()

NAMES_DEFAULT_FILE = "names_default.json"

def load_name_defaults() -> dict:
    """Load default name lists from names_default.json (managed outside main.py)."""
    try:
        with open(NAMES_DEFAULT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {
                "bd_first_names": data.get("bd_first_names", []),
                "bd_last_names":  data.get("bd_last_names", []),
                "bd_prefixes":    data.get("bd_prefixes", []),
            }
    except Exception as e:
        print(f"⚠️  Could not load {NAMES_DEFAULT_FILE}: {e}")
        return {"bd_first_names": [], "bd_last_names": [], "bd_prefixes": []}

NAME_DEFAULTS = load_name_defaults()

def load_config():
    defaults = {
        "bot_token": "", "password_hash": "",
        "bd_first_names": NAME_DEFAULTS["bd_first_names"][:],
        "bd_last_names":  NAME_DEFAULTS["bd_last_names"][:],
        "bd_prefixes":    NAME_DEFAULTS["bd_prefixes"][:],
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                defaults.update(data)
        except Exception:
            pass
    return defaults

def save_config(cfg: dict):
    with config_lock:
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Config save error: {e}")

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
def check_password(plain: str) -> bool:
    return _hash_password(plain) == CONFIG.get("password_hash", "")

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

ADMIN_ID = int(os.environ.get("ADMIN_ID", "7170129517"))
DEVELOPER_NAME = os.environ.get("DEVELOPER_NAME", "Shahadut Hossain")

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
# Country Config
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COUNTRY_DETAILS = {
    'bangladesh': {'locale': 'en_US', 'code': '+880', 'digits': '1XXXXXXXXX', 'is_bd': True},
    'bd':         {'locale': 'en_US', 'code': '+880', 'digits': '1XXXXXXXXX', 'is_bd': True},
    'india':      {'locale': 'en_IN', 'code': '+91',  'digits': 'XXXXXXXXXX', 'is_bd': False},
    'usa':        {'locale': 'en_US', 'code': '+1',   'digits': 'XXXXXXXXXX', 'is_bd': False},
    'uk':         {'locale': 'en_GB', 'code': '+44',  'digits': 'XXXXXXXXXX', 'is_bd': False},
    'canada':     {'locale': 'en_CA', 'code': '+1',   'digits': 'XXXXXXXXXX', 'is_bd': False},
    'france':     {'locale': 'fr_FR', 'code': '+33',  'digits': 'XXXXXXXXXX', 'is_bd': False},
    'germany':    {'locale': 'de_DE', 'code': '+49',  'digits': 'XXXXXXXXXX', 'is_bd': False},
    'japan':      {'locale': 'ja_JP', 'code': '+81',  'digits': 'XXXXXXXXXX', 'is_bd': False},
}

NICKNAME_SFX = ["07", "Official", "Gamer", "Pro", "Boss", "Real", "King", "BD", "X", ""]

# ── Dynamic name-list accessors (always read from CONFIG) ──
def get_first_names(): return CONFIG.get("bd_first_names", NAME_DEFAULTS["bd_first_names"])
def get_last_names():  return CONFIG.get("bd_last_names",  NAME_DEFAULTS["bd_last_names"])
def get_prefixes():    return CONFIG.get("bd_prefixes",    NAME_DEFAULTS["bd_prefixes"])
def get_total_combinations():
    return max(1, len(get_first_names()) * len(get_last_names()) * len(get_prefixes()))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Banned Users
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BANNED_FILE  = "banned_users.json"
banned_lock  = Lock()

def load_banned() -> dict:
    if os.path.exists(BANNED_FILE):
        try:
            with open(BANNED_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # keys are stored as strings in JSON; convert back to int
                return {int(k): v for k, v in data.items()}
        except Exception:
            return {}
    return {}

def save_banned(data: dict):
    try:
        with open(BANNED_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

BANNED_USERS: dict = load_banned()   # {user_id(int): {username, first_name, reason, timestamp}}

def is_banned(user_id: int) -> bool:
    return user_id in BANNED_USERS

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Persistent Used Names
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USED_NAMES_FILE  = "used_names.json"
used_names_lock  = Lock()

def load_used_names():
    if os.path.exists(USED_NAMES_FILE):
        try:
            with open(USED_NAMES_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_used_names(used: set):
    try:
        with open(USED_NAMES_FILE, "w", encoding="utf-8") as f:
            json.dump(list(used), f, ensure_ascii=False)
    except Exception:
        pass

USED_NAMES = load_used_names()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Name-Usage Log  (who got which BD name + when)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NAME_LOG_FILE = "name_log.json"
name_log_lock = Lock()

def load_name_log() -> list:
    if os.path.exists(NAME_LOG_FILE):
        try:
            with open(NAME_LOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []
    return []

def save_name_log(log: list):
    try:
        with open(NAME_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

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

def generate_fake_phone(code, pattern):
    return code + "".join(
        str(random.randint(0, 9)) if c == 'X' else c for c in pattern
    )

def clean_to_english(text):
    return "".join(
        c for c in unicodedata.normalize('NFD', text)
        if unicodedata.category(c) != 'Mn'
    )

def generate_profile(country_key):
    if country_key not in COUNTRY_DETAILS:
        return None
    details = COUNTRY_DETAILS[country_key]

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
    sfx          = random.choice(NICKNAME_SFX)
    nickname     = f"{nick_base.capitalize()}{sfx}" if sfx else nick_base.capitalize()
    username     = f"{clean_name}{random_num}"
    email        = f"{clean_name}{random_num}@gmail.com"
    phone        = generate_fake_phone(details['code'], details['digits'])
    facebook_id  = f"{clean_name}.{suffix_num}"

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

    @b.message_handler(commands=['start'])
    def send_welcome(message):
        used_count = len(USED_NAMES)
        remaining  = get_total_combinations() - used_count
        b.reply_to(message,
            "👋 ফেক প্রোফাইল জেনারেটর বটে স্বাগতম!\n\n"
            "যেকোনো দেশের নাম লিখুন:\n"
            "🇧🇩 Bangladesh  🇮🇳 India  🇺🇸 USA\n"
            "🇬🇧 UK  🇨🇦 Canada  🇫🇷 France\n"
            "🇩🇪 Germany  🇯🇵 Japan\n\n"
            f"🇧🇩 এখন পর্যন্ত {used_count:,} টি নাম ব্যবহৃত হয়েছে।\n"
            f"✅ আরও {remaining:,} টি ইউনিক নাম বাকি আছে।"
        )

    @b.message_handler(commands=['panel'])
    def admin_panel(message):
        if message.from_user.id == ADMIN_ID:
            total = get_total_combinations()
            b.reply_to(message,
                f"⚙️ কন্ট্রোল প্যানেল:\n\n"
                f"বট চালু আছে ✅\n"
                f"ডেভলপার: {DEVELOPER_NAME}\n"
                f"মোট সম্ভাব্য নাম: {total:,}\n"
                f"ব্যবহৃত নাম: {len(USED_NAMES):,}\n"
                f"বাকি নাম: {total - len(USED_NAMES):,}"
            )
        else:
            b.reply_to(message, "❌ আপনি এই বটের অ্যাডমিন নন!")

    @b.message_handler(commands=['reset'])
    def reset_names(message):
        if message.from_user.id == ADMIN_ID:
            global USED_NAMES
            USED_NAMES = set()
            save_used_names(USED_NAMES)
            b.reply_to(message, "✅ সমস্ত ব্যবহৃত নাম রিসেট করা হয়েছে!")
        else:
            b.reply_to(message, "❌ শুধু অ্যাডমিন এই কমান্ড ব্যবহার করতে পারবেন!")

    @b.message_handler(func=lambda message: True)
    def handle_all_messages(message):
        # Ban check — reply and stop immediately
        if is_banned(message.from_user.id):
            b.reply_to(message,
                "🚫 আপনাকে এই বট থেকে ব্যান করা হয়েছে।\n"
                "আপনি আর এই বট ব্যবহার করতে পারবেন না।"
            )
            return

        country_input = message.text.strip().lower()
        if country_input not in COUNTRY_DETAILS:
            b.reply_to(message,
                "⚠️ দুঃখিত, এটি কোনো সঠিক দেশের নাম নয়।\n\n"
                "লিখুন: Bangladesh, India, USA, UK, Canada, France, Germany বা Japan"
            )
            return
        try:
            profile = generate_profile(country_input)
            recent_log.append(profile)
            tg          = message.from_user.username
            tg_mention  = f"@{tg}" if tg else "Not Available"
            # Track who received this BD name
            if COUNTRY_DETAILS[country_input].get('is_bd'):
                log_name_usage(
                    bd_name    = profile['full_name'],
                    user_id    = message.from_user.id,
                    username   = message.from_user.username,
                    first_name = message.from_user.first_name,
                )
            b.reply_to(message,
                f"👤 Developer: {DEVELOPER_NAME}\n"
                f"🆔 Your Telegram: {tg_mention}\n"
                f"🌍 দেশ: {country_input.capitalize()}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 Withdrawer Name: `{profile['full_name']}`\n"
                f"🏷️ Nickname: `{profile['nickname']}`\n"
                f"📘 Facebook ID: `{profile['facebook_id']}`\n"
                f"🔵 Google: `{profile['google']}`\n"
                f"💬 WhatsApp: `{profile['whatsapp']}`\n"
                f"📧 Email: `{profile['email']}`\n"
                f"📞 Mobile: `{profile['mobile']}`\n"
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
    # Reload from file each time so changes to names_default.json take effect
    fresh_defaults = load_name_defaults()
    if kind in ('bd_first_names', 'bd_last_names', 'bd_prefixes'):
        CONFIG[kind] = fresh_defaults.get(kind, [])[:]
    else:
        return jsonify(success=False, error='Invalid list type.')
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
