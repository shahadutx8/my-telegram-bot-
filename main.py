import os
import telebot
import random
import re
import json
import unicodedata
from faker import Faker
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from threading import Thread
from functools import wraps
from collections import deque

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Flask App Setup
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
app = Flask('')

# Require secrets — refuse to start with weak defaults
_secret_key = os.environ.get("SESSION_SECRET", "")
if not _secret_key:
    raise RuntimeError("SESSION_SECRET environment variable must be set before running.")
app.secret_key = _secret_key

# Dashboard password — must be set via env var
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "")
if not DASHBOARD_PASSWORD:
    raise RuntimeError("DASHBOARD_PASSWORD environment variable must be set before running.")

# Recent profile log (in-memory, last 50)
recent_log = deque(maxlen=50)

# ── Jinja filter ──
@app.template_filter('format_num')
def format_num(value):
    try:
        return f"{int(value):,}"
    except Exception:
        return value

# ── Auth decorator ──
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            # Return JSON for API routes, redirect for web routes
            if request.path.startswith('/api/'):
                return jsonify(success=False, error='Unauthorized'), 401
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Telegram Bot Config
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
bot = telebot.TeleBot(BOT_TOKEN) if BOT_TOKEN else None

ADMIN_ID = int(os.environ.get("ADMIN_ID", "7170129517"))
DEVELOPER_NAME = os.environ.get("DEVELOPER_NAME", "Shahadut Hossain")

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

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BD Names
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BD_FIRST_NAMES = [
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
    "Mainul", "Mostafa", "Abul", "Shafiul", "Shafiur", "Tarikul", "Atikur",
    "Golam", "Delwar", "Jalal", "Khairul", "Obaidul", "Tofazzal", "Lutfur", "Nazrul",
    "Rashidul", "Mujibur", "Forhad", "Anwar", "Ashraful", "Khaled", "Murad",
    "Bazlur", "Azizul", "Nasrul", "Tajul", "Shajahan", "Enayet", "Hafizur", "Joynal",
    "Quamrul", "Jahangir", "Faruk", "Feroz", "Giash", "Haroon", "Idris", "Jakir",
    "Kamal", "Lokman", "Monir", "Nadir", "Omar", "Parvez", "Quader", "Rabiul",
    "Sultan", "Titu", "Umar", "Wasim", "Yusuf", "Zahirul", "Abubakar",
    "Biplob", "Chanchal", "Deepu", "Emdad", "Fuad", "Gulzar", "Hanif",
    "Jasim", "Khalid", "Liaquat", "Minhazul", "Nasim", "Obaid", "Prodip", "Rafiq",
    "Sajjad", "Tarek", "Ujjal", "Wasim", "Yeakub", "Ziaul",
]

BD_LAST_NAMES = [
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

BD_PREFIXES = ["Md.", "Mohammad", "Mohammed", "Md", "M."]

NICKNAME_SUFFIXES = ["07", "Official", "Gamer", "Pro", "Boss", "Real", "King", "BD", "X", ""]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Persistent Used Names
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USED_NAMES_FILE = "used_names.json"

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
TOTAL_COMBINATIONS = len(BD_PREFIXES) * len(BD_FIRST_NAMES) * len(BD_LAST_NAMES)

def generate_unique_bd_name():
    global USED_NAMES
    if len(USED_NAMES) >= TOTAL_COMBINATIONS:
        USED_NAMES = set()
        save_used_names(USED_NAMES)

    attempts = 0
    while True:
        prefix = random.choice(BD_PREFIXES)
        first  = random.choice(BD_FIRST_NAMES)
        last   = random.choice(BD_LAST_NAMES)
        full_name = f"{prefix} {first} {last}"
        attempts += 1
        if full_name not in USED_NAMES:
            USED_NAMES.add(full_name)
            save_used_names(USED_NAMES)
            return full_name
        if attempts > TOTAL_COMBINATIONS:
            USED_NAMES = set()
            save_used_names(USED_NAMES)

def generate_fake_phone(code, pattern):
    number = "".join(
        str(random.randint(0, 9)) if c == 'X' else c
        for c in pattern
    )
    return f"{code}{number}"

def clean_to_english(text):
    return "".join(
        c for c in unicodedata.normalize('NFD', text)
        if unicodedata.category(c) != 'Mn'
    )

def generate_profile(country_key):
    """Generate a full profile dict for the given country key."""
    if country_key not in COUNTRY_DETAILS:
        return None

    details = COUNTRY_DETAILS[country_key]

    if details['is_bd']:
        full_name = generate_unique_bd_name()
    else:
        fake = Faker(details['locale'])
        full_name = clean_to_english(fake.name_male())

    # Extract first token BEFORE stripping spaces
    name_tokens = full_name.split()
    first_token = re.sub(r'[^a-zA-Z0-9]', '', name_tokens[-1] if len(name_tokens) > 1 else name_tokens[0]).lower()
    if not first_token:
        first_token = "user"

    clean_name  = re.sub(r'[^a-zA-Z0-9]', '', full_name).lower()
    if not clean_name:
        clean_name = "user" + str(random.randint(100, 999))

    random_num  = random.randint(1000, 9999)
    suffix_num  = random.randint(10, 99)

    # Nickname from first real name token
    nickname_sfx = random.choice(NICKNAME_SUFFIXES)
    nickname    = f"{first_token.capitalize()}{nickname_sfx}" if nickname_sfx else first_token.capitalize()

    username    = f"{clean_name}{random_num}"
    email       = f"{clean_name}{random_num}@gmail.com"
    google      = email   # Google account = Gmail
    phone       = generate_fake_phone(details['code'], details['digits'])
    facebook_id = f"{clean_name.replace(' ', '.')}.{suffix_num}"
    whatsapp    = phone   # WhatsApp uses same number

    return {
        "country":     country_key,
        "full_name":   full_name,
        "nickname":    nickname,
        "username":    username,
        "facebook_id": facebook_id,
        "google":      google,
        "whatsapp":    whatsapp,
        "email":       email,
        "mobile":      phone,
    }

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Flask Routes — Dashboard
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@app.route('/')
def index():
    if session.get('logged_in'):
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('password') == DASHBOARD_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        error = 'Wrong password. Try again.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template(
        'dashboard.html',
        total_combinations=TOTAL_COMBINATIONS,
        used_count=len(USED_NAMES),
        remaining=TOTAL_COMBINATIONS - len(USED_NAMES),
        recent_log=list(recent_log)[-20:][::-1],
        log_count=len(recent_log),
    )

@app.route('/api/generate', methods=['POST'])
@login_required
def api_generate():
    data = request.get_json(force=True)
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
    return jsonify(
        total_combinations=TOTAL_COMBINATIONS,
        used_count=len(USED_NAMES),
        remaining=TOTAL_COMBINATIONS - len(USED_NAMES),
        log_count=len(recent_log),
    )

@app.route('/health')
def health():
    return "Profile Generator Bot is alive 24/7!"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Telegram Bot Handlers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
if bot:
    @bot.message_handler(commands=['start'])
    def send_welcome(message):
        used_count = len(USED_NAMES)
        remaining  = TOTAL_COMBINATIONS - used_count
        welcome_text = (
            "👋 ফেক প্রোফাইল জেনারেটর বটে স্বাগতম!\n\n"
            "যেকোনো দেশের নাম লিখুন:\n"
            "🇧🇩 Bangladesh  🇮🇳 India  🇺🇸 USA\n"
            "🇬🇧 UK  🇨🇦 Canada  🇫🇷 France\n"
            "🇩🇪 Germany  🇯🇵 Japan\n\n"
            f"🇧🇩 এখন পর্যন্ত {used_count:,} টি নাম ব্যবহৃত হয়েছে।\n"
            f"✅ আরও {remaining:,} টি ইউনিক নাম বাকি আছে।"
        )
        bot.reply_to(message, welcome_text)

    @bot.message_handler(commands=['panel'])
    def admin_panel(message):
        if message.from_user.id == ADMIN_ID:
            msg = (
                f"⚙️ কন্ট্রোল প্যানেল:\n\n"
                f"বট চালু আছে ✅\n"
                f"ডেভলপার: {DEVELOPER_NAME}\n"
                f"মোট সম্ভাব্য নাম: {TOTAL_COMBINATIONS:,}\n"
                f"ব্যবহৃত নাম: {len(USED_NAMES):,}\n"
                f"বাকি নাম: {TOTAL_COMBINATIONS - len(USED_NAMES):,}"
            )
            bot.reply_to(message, msg)
        else:
            bot.reply_to(message, "❌ আপনি এই বটের অ্যাডমিন নন!")

    @bot.message_handler(commands=['reset'])
    def reset_names(message):
        if message.from_user.id == ADMIN_ID:
            global USED_NAMES
            USED_NAMES = set()
            save_used_names(USED_NAMES)
            bot.reply_to(message, "✅ সমস্ত ব্যবহৃত নাম রিসেট করা হয়েছে!")
        else:
            bot.reply_to(message, "❌ শুধু অ্যাডমিন এই কমান্ড ব্যবহার করতে পারবেন!")

    @bot.message_handler(func=lambda message: True)
    def handle_all_messages(message):
        user_input    = message.text.strip()
        country_input = user_input.lower()

        if country_input not in COUNTRY_DETAILS:
            bot.reply_to(
                message,
                "⚠️ দুঃখিত, এটি কোনো সঠিক দেশের নাম নয়।\n\n"
                "লিখুন: Bangladesh, India, USA, UK, Canada, France, Germany বা Japan"
            )
            return

        try:
            profile = generate_profile(country_input)
            recent_log.append(profile)
            user_tg_username = message.from_user.username
            tg_mention = f"@{user_tg_username}" if user_tg_username else "Not Available"

            response = (
                f"👤 Developer: {DEVELOPER_NAME}\n"
                f"🆔 Your Telegram: {tg_mention}\n"
                f"🌍 দেশ: {user_input.capitalize()}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 Withdrawer Name: `{profile['full_name']}`\n"
                f"🏷️ Nickname: `{profile['nickname']}`\n"
                f"📘 Facebook ID: `{profile['facebook_id']}`\n"
                f"🔵 Google: `{profile['google']}`\n"
                f"💬 WhatsApp: `{profile['whatsapp']}`\n"
                f"📧 Email: `{profile['email']}`\n"
                f"📞 Mobile: `{profile['mobile']}`\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 তথ্যের ওপর ট্যাপ করলেই অটো-কপি হয়ে যাবে।"
            )
            bot.reply_to(message, response, parse_mode="Markdown")

        except Exception as e:
            bot.reply_to(message, "⚠️ দুঃখিত, প্রোফাইল ডাটা জেনারেট করা সম্ভব হয়নি।")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Entry Point
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
def run_web_server():
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    if bot:
        bot.remove_webhook()
        print(f"🚀 Profile Generator Bot Started | মোট সম্ভাব্য BD নাম: {TOTAL_COMBINATIONS:,}")
        t = Thread(target=run_web_server)
        t.daemon = True
        t.start()
        bot.infinity_polling()
    else:
        print("⚠️  BOT_TOKEN not set — running web dashboard only")
        run_web_server()
