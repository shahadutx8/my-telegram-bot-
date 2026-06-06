import os
import telebot
import random
import re
import json
import unicodedata
from faker import Faker
from flask import Flask
from threading import Thread

# ১. ব্যাকগ্রাউন্ড ওয়েব সার্ভার (Render অন রাখার জন্য)
app = Flask('')

@app.route('/')
def home():
    return "Boy Profile Generator Bot is alive 24/7!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web_server)
    t.start()

# ২. টেলিগ্রাম বট কনফিগারেশন
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8926328002:AAHXyZ_YWiuO2dtQxsgWua0ckP1iDLTQvy4")
bot = telebot.TeleBot(BOT_TOKEN)

ADMIN_ID = 7170129517
DEVELOPER_NAME = "Shahadut Hossain"

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
# রিয়েল বাংলাদেশি ছেলেদের নামের বিশাল লিস্ট
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
    "Masud", "Robiul", "Shohag", "Babul", "Dulal", "Mithu", "Rubel", "Nurul",
    "Riaz", "Sirajul", "Alamgir", "Mintu", "Shamsul", "Masum", "Wahid", "Rasel",
    "Saiful", "Tomal", "Nirob", "Redwan", "Jabed", "Kawsar", "Mahfuz", "Ismail",
    "Faisal", "Morshed", "Shorif", "Habib", "Farid", "Mamun", "Billal", "Ahad",
    "Salman", "Samiul", "Yasin", "Iqbal", "Motiur", "Saddam", "Alam", "Badal",
    "Mainul", "Mostafa", "Abul", "Shafiul", "Shafiur", "Tarikul", "Atikur", "Iftekharul",
    "Golam", "Delwar", "Jalal", "Khairul", "Obaidul", "Tofazzal", "Lutfur", "Nazrul",
    "Rashidul", "Mujibur", "Forhad", "Anwar", "Ashraful", "Khaled", "Murad", "Sajedul",
    "Bazlur", "Azizul", "Nasrul", "Tajul", "Shajahan", "Enayet", "Hafizur", "Joynal",
    "Quamrul", "Jahangir", "Faruk", "Feroz", "Giash", "Haroon", "Idris", "Jakir",
    "Kamal", "Lokman", "Monir", "Nadir", "Omar", "Parvez", "Quader", "Rabiul",
    "Sultan", "Titu", "Umar", "Vashkar", "Wali", "Yusuf", "Zahirul", "Abubakar",
    "Biplob", "Chanchal", "Deepu", "Emdad", "Fuad", "Gulzar", "Hanif", "Iqramul",
    "Jasim", "Khalid", "Liaquat", "Minhazul", "Nasim", "Obaid", "Prodip", "Rafiq",
    "Sajjad", "Tarek", "Ujjal", "Varun", "Wasim", "Xahed", "Yeakub", "Ziaul",
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

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Persistent Used Names — JSON ফাইলে সেভ থাকে
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

# সম্ভাব্য মোট কম্বিনেশন = prefixes × first × last
TOTAL_COMBINATIONS = len(BD_PREFIXES) * len(BD_FIRST_NAMES) * len(BD_LAST_NAMES)

def generate_unique_bd_name():
    """
    সব সম্ভাব্য নামের কম্বিনেশন শেষ হলে ফাইল রিসেট করে আবার শুরু করে।
    বাস্তবে এটি কখনো হবে না (কম্বিনেশন সংখ্যা বিশাল)।
    """
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
        # অনেক চেষ্টার পরও না পেলে সব সম্ভাব্য নাম শেষ — রিসেট করো
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

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# কমান্ড হ্যান্ডলার
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.message_handler(commands=['start'])
def send_welcome(message):
    total_possible = TOTAL_COMBINATIONS
    used_count = len(USED_NAMES)
    remaining = total_possible - used_count
    welcome_text = (
        "👋 ফেক প্রোফাইল জেনারেটর বটে স্বাগতম!\n\n"
        "যেকোনো দেশের নাম লিখুন (যেমন: Bangladesh, USA বা India)\n"
        "বট আপনাকে ১০০% ইউনিক ফেক প্রোফাইল দেবে।\n\n"
        f"🇧🇩 Bangladesh-এর জন্য এখন পর্যন্ত {used_count:,} টি নাম ব্যবহৃত হয়েছে।\n"
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

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# মেইন মেসেজ হ্যান্ডলার
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_input = message.text.strip()
    country_input = user_input.lower()

    if country_input not in COUNTRY_DETAILS:
        bot.reply_to(
            message,
            "⚠️ দুঃখিত, এটি কোনো সঠিক দেশের নাম নয়।\n\n"
            "যেমন লিখুন: Bangladesh, USA বা India"
        )
        return

    details = COUNTRY_DETAILS[country_input]
    user_tg_username = message.from_user.username
    tg_mention = f"@{user_tg_username}" if user_tg_username else "Not Available"

    try:
        if details['is_bd']:
            full_name = generate_unique_bd_name()
        else:
            fake = Faker(details['locale'])
            full_name = clean_to_english(fake.name_male())

        clean_name = re.sub(r'[^a-zA-Z0-9]', '', full_name).lower()
        random_num  = random.randint(1000, 9999)
        username    = f"{clean_name}{random_num}"
        email       = f"{clean_name}{random_num}@gmail.com"
        phone       = generate_fake_phone(details['code'], details['digits'])

        response = (
            f"👤 Developer: {DEVELOPER_NAME}\n"
            f"🆔 Your Telegram: {tg_mention}\n"
            f"🌍 দেশ: {user_input.capitalize()}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 নাম (Boy): `{full_name}`\n"
            f"🆔 ইউজারনেম: `{username}`\n"
            f"📧 জিমেইল: `{email}`\n"
            f"📞 ফোন: `{phone}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 তথ্যের ওপর ট্যাপ করলেই অটো-কপি হয়ে যাবে।"
        )
        bot.reply_to(message, response, parse_mode="Markdown")

    except Exception as e:
        bot.reply_to(message, "⚠️ দুঃখিত, প্রোফাইল ডাটা জেনারেট করা সম্ভব হয়নি।")


if __name__ == '__main__':
    bot.remove_webhook()
    keep_alive()
    print(f"🚀 Profile Generator Bot Started | মোট সম্ভাব্য BD নাম: {TOTAL_COMBINATIONS:,}")
    bot.infinity_polling()
    
