import os
import telebot
import random
import re
from faker import Faker
from flask import Flask
from threading import Thread

# ১. ব্যাকগ্রাউন্ড ওয়েব সার্ভার (Render অন রাখার জন্য)
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
BOT_TOKEN = "8926328002:AAHXyZ_YWiuO2dtQxsgWua0ckP1iDLTQvy4"
bot = telebot.TeleBot(BOT_TOKEN)

ADMIN_ID = 7170129517
DEVELOPER_NAME = "Md Shahadut Hossain"

COUNTRY_DETAILS = {
    'bangladesh': {'locale': 'en_US', 'code': '+880', 'digits': '1XXXXXXXXX', 'is_bd': True},
    'bd': {'locale': 'en_US', 'code': '+880', 'digits': '1XXXXXXXXX', 'is_bd': True},
    'india': {'locale': 'en_IN', 'code': '+91', 'digits': 'XXXXXXXXXX', 'is_bd': False},
    'usa': {'locale': 'en_US', 'code': '+1', 'digits': 'XXXXXXXXXX', 'is_bd': False},
    'uk': {'locale': 'en_GB', 'code': '+44', 'digits': 'XXXXXXXXXX', 'is_bd': False},
    'canada': {'locale': 'en_CA', 'code': '+1', 'digits': 'XXXXXXXXXX', 'is_bd': False},
    'france': {'locale': 'fr_FR', 'code': '+33', 'digits': 'XXXXXXXXXX', 'is_bd': False},
    'germany': {'locale': 'de_DE', 'code': '+49', 'digits': 'XXXXXXXXXX', 'is_bd': False},
    'japan': {'locale': 'ja_JP', 'code': '+81', 'digits': 'XXXXXXXXXX', 'is_bd': False}
}

BD_BOYS_FIRST_NAMES = ["Arif", "Sajid", "Tanvir", "Fahim", "Rifat", "Mehedi", "Asif", "Sabbir", "Nayeem", "Imran", "Sohan", "Tamim", "Emon", "Shakil", "Rony", "Hasan", "Rakib", "Anik", "Alamin", "Rashed", "Zubair", "Rayhan", "Siam", "Abir", "Arafat", "Jahid", "Riyad", "Sourav", "Ashik", "Akash", "Sagar", "Joy"]
BD_BOYS_LAST_NAMES = ["Rahman", "Hasan", "Ahmed", "Faisal", "Hossain", "Islam", "Iqbal", "Chowdhury", "Khan", "Ali", "Uddin", "Sarker", "Miah", "Bhuiyan", "Sheikh", "Talukder", "Biswas", "Siddique", "Zaman", "Saha", "Rana", "Howlader", "Haq", "Haque", "Mia"]

USED_NAMES = set()

def generate_unique_bd_name():
    for _ in range(50):
        full_name = f"Md. {random.choice(BD_BOYS_FIRST_NAMES)} {random.choice(BD_BOYS_LAST_NAMES)}"
        if full_name not in USED_NAMES:
            USED_NAMES.add(full_name)
            return full_name
    return f"Md. {random.choice(BD_BOYS_FIRST_NAMES)} {random.choice(BD_BOYS_LAST_NAMES)}"

def generate_fake_phone(code, pattern):
    number = "".join(str(random.randint(0, 9)) if c == 'X' else c for c in pattern)
    return f"{code}{number}"

def clean_to_english(text):
    import unicodedata
    return "".join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')

# ③. স্টার্ট কমান্ড
@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = "👋 ফেক প্রোফাইল জেনারেটর বটে স্বাগতম!\n\nযেকোনো দেশের নাম লিখুন (যেমন: Bangladesh, USA বা India), বট আপনাকে ছেলেদের ১০০% ইউনিক ফেক প্রোফাইল দেবে।"
    bot.reply_to(message, welcome_text)

# ④. অ্যাডমিন প্যানেল
@bot.message_handler(commands=['panel'])
def admin_panel(message):
    if message.from_user.id == ADMIN_ID:
        msg = f"⚙️ কন্ট্রোল প্যানেল:\n\nবট চালু আছে।\nডেভলপার: {DEVELOPER_NAME}\nইউনিক নাম সংখ্যা: {len(USED_NAMES)}"
        bot.reply_to(message, msg)
    else:
        bot.reply_to(message, "❌ আপনি এই বটের অ্যাডমিন নন!")

# ⑤. মেইন মেসেজ হ্যান্ডলার
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_input = message.text.strip()
    country_input = user_input.lower()
    
    if country_input in COUNTRY_DETAILS:
        details = COUNTRY_DETAILS[country_input]
        user_tg_username = message.from_user.username
        tg_mention = f"@{user_tg_username}" if user_tg_username else "Not Available"

        try:
            if details['is_bd']:
                full_name = generate_unique_bd_name()
            else:
                fake = Faker(details['locale'])
                full_name = clean_to_english(fake.name_male())
                USED_NAMES.add(full_name)
            
            clean_name = re.sub(r'[^a-zA-Z0-9]', '', full_name).lower()
            random_num = random.randint(1000, 9999) 
            username = f"{clean_name}{random_num}"
            email = f"{clean_name}{random_num}@gmail.com"
            phone = generate_fake_phone(details['code'], details['digits'])
            
            # সিঙ্গেল লাইনে সাজানো টেক্সট, যেন কোনো ইনডেন্টেশন বা সিনট্যাক্স এরর না হয়
            line1 = f"👤 Developer: {DEVELOPER_NAME}\n🆔 Your Telegram: {tg_mention}\n🌍 দেশ: {user_input.capitalize()}\n"
            line2 = f"━━━━━━━━━━━━━━━━━━━━\n👤 নাম (Boy): `{full_name}`\n🆔 ইউজারনেম: `{username}`\n"
            line3 = f"📧 জিমেইল: `{email}`\n📞 ফোন: `{phone}`\n━━━━━━━━━━━━━━━━━━━━\n"
            line4 = f"💡 তথ্যের ওপর ট্যাপ করলেই অটো-কপি হয়ে যাবে।"
            
            response = line1 + line2 + line3 + line4
            bot.reply_to(message, response, parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, "⚠️ দুঃখিত, প্রোফাইল ডাটা জেনারেট করা সম্ভব হয়নি।")
    else:
        bot.reply_to(message, "⚠️ দুঃখিত, এটি কোনো সঠিক দেশের নাম নয়।\n\nযেমন লিখুন: Bangladesh, USA বা India")

if __name__ == '__main__':
    bot.remove_webhook()
    keep_alive()
    print("🚀 Profile Generator Bot Engine Started...")
    bot.infinity_polling()
