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

DEFAULT_FIRST_NAMES = [
    "Arif", "Sajid", "Tanvir", "Fahim", "Rifat", "Mehedi", "Asif", "Sabbir",
    "Nayeem", "Imran", "Sohan", "Tamim", "Emon", "Shakil", "Rony", "Hasan",
    "Rakib", "Anik", "Alamin", "Rashed", "Zubair", "Rayhan", "Siam", "Abir",
    "Arafat", "Jahid", "Riyad", "Sourav", "Ashik", "Akash", "Sagar", "Joy",
    "Rahat", "Sohel", "Mizan", "Kamrul", "Farhan", "Shafiq", "Rezaul", "Belal",
    "Tariq", "Nazmul", "Shahin", "Mahbub", "Hasnat", "Zahid", "Touhid", "Nurul",
    "Ripon", "Shahriar", "Minhaj", "Arman", "Shaon", "Sumon", "Liton", "Babu",
    "Tushar", "Palash", "Jewel", "Karim", "Rokon", "Jony", "Hridoy", "Sagor",
    "Robin", "Ratul", "Pavel", "Tanveer", "Nafiz", "Tahmid", "Imon", "Adnan",
    "Masud", "Robiul", "Shohag", "Babul", "Dulal", "Mithu", "Rubel",
    "Riaz", "Sirajul", "Alamgir", "Mintu", "Shamsul", "Masum", "Wahid", "Rasel",
    "Saiful", "Tomal", "Nirob", "Redwan", "Jabed", "Kawsar", "Mahfuz", "Ismail",
    "Faisal", "Morshed", "Shorif", "Habib", "Farid", "Mamun", "Billal", "Ahad",
    "Salman", "Samiul", "Yasin", "Iqbal", "Motiur", "Saddam", "Alam", "Badal",
    "Mainul", "Mostafa", "Abul", "Shafiul", "Tarikul", "Atikur",
    "Golam", "Delwar", "Jalal", "Khairul", "Obaidul", "Lutfur", "Nazrul",
    "Rashidul", "Mujibur", "Forhad", "Anwar", "Ashraful", "Khaled", "Murad",
    "Bazlur", "Azizul", "Nasrul", "Tajul", "Shajahan", "Enayet", "Hafizur",
    "Quamrul", "Jahangir", "Faruk", "Feroz", "Haroon", "Idris", "Jakir",
    "Kamal", "Lokman", "Monir", "Nadir", "Omar", "Parvez", "Quader", "Rabiul",
    "Sultan", "Titu", "Umar", "Wasim", "Yusuf", "Zahirul", "Abubakar",
    "Biplob", "Chanchal", "Deepu", "Emdad", "Fuad", "Gulzar", "Hanif",
    "Jasim", "Khalid", "Liaquat", "Minhazul", "Nasim", "Obaid", "Prodip", "Rafiq",
    "Sajjad", "Tarek", "Ujjal", "Yeakub", "Ziaul",
]
DEFAULT_LAST_NAMES = [
    "Rahman", "Hasan", "Ahmed", "Faisal", "Hossain", "Islam", "Iqbal", "Chowdhury",
    "Khan", "Ali", "Uddin", "Sarker", "Miah", "Bhuiyan", "Sheikh", "Talukder",
    "Biswas", "Siddique", "Zaman", "Saha", "Rana", "Howlader", "Haq", "Haque",
    "Mia", "Mollick", "Mondal", "Munshi", "Nath", "Patwary", "Prodhan", "Quazi",
    "Roy", "Shikder", "Thakur", "Bepari", "Dewan", "Farazi", "Gazi", "Haldar",
    "Joardar", "Kazi", "Laskar", "Majumder", "Nawab", "Pandit", "Reza", "Tarafder",
    "Molla", "Akand", "Banik", "Das", "Gain", "Halder", "Karmakar", "Naskar",
    "Palodhi", "Sikdar", "Bakshi", "Chakraborty", "Datta", "Ghosh", "Mandal",
    "Podder", "Raha", "Samaddar", "Ganguly", "Bose", "Sen", "Nandi", "Dey",
    "Choudhury", "Matin", "Karim", "Amin", "Aziz", "Bashar", "Habib", "Jamil",
    "Kabir", "Latif", "Mazid", "Noor", "Osman", "Quasem", "Sabur", "Taher",
    "Wahab", "Yousuf", "Zahir", "Abedin", "Bari", "Hussain", "Rashid", "Sattar",
    "Mannan", "Momen", "Samad", "Khondker", "Morshed", "Huda", "Anwar", "Faruq",
    "Gaffar", "Harun", "Kashem", "Mafizur", "Nizam", "Quddus", "Rahim", "Salam",
]
DEFAULT_PREFIXES = ["Md.", "Mohammad", "Mohammed", "Md", "M."]

def load_config():
    defaults = {
        "bot_token": "", "password_hash": "",
        "bd_first_names": DEFAULT_FIRST_NAMES[:],
        "bd_last_names":  DEFAULT_LAST_NAMES[:],
        "bd_prefixes":    DEFAULT_PREFIXES[:],
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
def get_first_names(): return CONFIG.get("bd_first_names", DEFAULT_FIRST_NAMES)
def get_last_names():  return CONFIG.get("bd_last_names",  DEFAULT_LAST_NAMES)
def get_prefixes():    return CONFIG.get("bd_prefixes",    DEFAULT_PREFIXES)
def get_total_combinations():
    return max(1, len(get_first_names()) * len(get_last_names()) * len(get_prefixes()))

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

@app.route('/api/names/reset-defaults', methods=['POST'])
@login_required
def api_names_reset_defaults():
    data = request.get_json(force=True)
    kind = data.get('kind', '')
    if kind == 'bd_first_names':
        CONFIG['bd_first_names'] = DEFAULT_FIRST_NAMES[:]
    elif kind == 'bd_last_names':
        CONFIG['bd_last_names'] = DEFAULT_LAST_NAMES[:]
    elif kind == 'bd_prefixes':
        CONFIG['bd_prefixes'] = DEFAULT_PREFIXES[:]
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
