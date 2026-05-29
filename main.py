import os
import telebot
import random
import re
import ipaddress
from faker import Faker
from flask import Flask
from threading import Thread

# ১. ক্লাউড হোস্টিং ওয়েব সার্ভার (Keep Alive)
app = Flask('')

@app.route('/')
def home():
    return "Multi-Feature Bot is alive and running 24/7!"

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

BD_BOYS_FIRST_NAMES = [
    "Arif", "Sajid", "Tanvir", "Fahim", "Rifat", "Mehedi", "Asif", "Kamrul", "Sabbir", "Nayeem", 
    "Imran", "Sohan", "Tamim", "Emon", "Shakil", "Rony", "Hasan", "Rakib", "Mahfuz", "Anik", 
    "Alamin", "Rashed", "Zubair", "Rayhan", "Siam", "Nabil", "Saif", "Sani", "Tarek", "Munna", 
    "Abir", "Arafat", "Jahid", "Riyad", "Sourav", "Ashik", "Sujan", "Mizan", "Sumon", "Farhan",
    "Yeasin", "Sadman", "Salman", "Tasin", "Riaz", "Kawsar", "Niaz", "Sakib", "Mahi", "Ahamad",
    "Milon", "Biplob", "Shimul", "Rubel", "Rasel", "Shaheen", "Polash", "Sadek", "Saidul", "Sajjal",
    "Munir", "Nasir", "Anwar", "Zakir", "Kabir", "Habib", "Latif", "Tareq", "Mushfiq", "Mahmud",
    "Shuvo", "Nayan", "Apu", "Dipu", "Bappi", "Shanto", "Hridoy", "Shahin", "Shorif", "Niloy",
    "Raju", "Mithu", "Tushar", "Badhon", "Akash", "Sagar", "Joy", "Badal", "Utsob", "Aftab", 
    "Istiak", "Zaman", "Nafeez", "Adnan", "Sami", "Tahsin", "Wasi", "Raiyan", "Zayan", "Mim"
]

BD_BOYS_LAST_NAMES = [
    "Rahman", "Hasan", "Ahmed", "Faisal", "Hossain", "Islam", "Iqbal", "Chowdhury", "Khan", "Ali", 
    "Uddin", "Sarker", "Miah", "Patwary", "Bhuiyan", "Sheikh", "Talukder", "Akand", "Mullah", "Gazi",
    "Biswas", "Siddique", "Zaman", "Majumder", "Pal", "Das", "Roy", "Dev", "Munshi", "Kazi",
    "Mollah", "Dewan", "Khondoker", "Khandakar", "Pramanik", "Bepari", "Haq", "Haque", "Mir", "Bari", 
    "Sikder", "Mia", "Ullah", "Eahi", "Rana", "Howlader", "Golder", "Halder", "Sutradhar", "Karmakar", 
    "Malakar", "Bhowmik", "Adhikary", "Gain", "Saha", "Podder", "Arif", "Tahher", "Naser", "Huda", 
    "Chisti", "Arefin", "Kuddus", "Babu", "Moni", "Sora", "Abdin", "Nabi", "Rabbani", "Siddiqui"
]

USED_NAMES = set()

def generate_unique_bd_name():
    attempts = 0
    while attempts < 5000:
        prefix = random.choice(["Md. ", ""])
        first = random.choice(BD_BOYS_FIRST_NAMES)
        last = random.choice(BD_BOYS_LAST_NAMES)
        full_name = f"{prefix}{first} {last}".strip()
        
        if full_name not in USED_NAMES:
            USED_NAMES.add(full_name)
            return full_name
        attempts += 1
    return f"Md. {random.choice(BD_BOYS_FIRST_NAMES)} {random.choice(BD_BOYS_LAST_NAMES)}"

def generate_fake_phone(code, pattern):
    number = ""
    for char in pattern:
        if char == 'X':
            number += str(random.randint(0, 9))
        else:
            number += char
    return f"{code}{number}"

def clean_to_english(text):
    import unicodedata
    return "".join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')

def check_ip_version(ip_str):
    """আইপি চেক করার ফাংশন"""
    try:
        ip = ipaddress.ip_address(ip_str.strip())
        return f"IPv{ip.version}"
    except ValueError:
        return None

# ৩. স্টার্ট কমান্ড
@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = (
        "👋 **মাল্টি-ফিচার বক্সে স্বাগতম!**\n\n"
        "🤖 **এই বটের মাধ্যমে আপনি ২টি কাজ করতে পারবেন:**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "১️⃣ **ফেক প্রোফাইল:** যেকোনো দেশের নাম লিখুন (যেমন: `Bangladesh`, `USA`), বট আপনাকে ছেলেদের ১০০% ইউনিক ফেক প্রোফাইল দেবে।\n\n"
        "২️⃣ **IP চেকার:** যেকোনো আইপি অ্যাড্রেস সরাসরি পেস্ট করুন, বট সেটি **IPv4** নাকি **IPv6** তা তাৎক্ষণিক যাচাই করে দেবে।\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📝 *আইপি উদাহরণ:* `192.168.1.1` অথবা `2001:db8::1`"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

# ৪. অ্যাডমিন প্যানেল
@bot.message_handler(commands=['panel'])
def admin_panel(message):
    if message.from_user.id == ADMIN_ID:
        bot.reply_to(message, f"⚙️ **কন্ট্রোল প্যানেল:**\n\nবটটি বর্তমানে সচল আছে।\nডেভলপার: {DEVELOPER_NAME}\nমোট ব্যবহৃত ইউনিক নাম: {len(USED_NAMES)}")
    else:
        bot.reply_to(message, "❌ আপনি এই বটের অ্যাডমিন নন!")

# ৫. মেইন মেসেজ প্রসেসর (আইপি নাকি দেশের নাম - স্বয়ংক্রিয় ফিল্টার)
@bot.message_handler(func=lambda message: True)
def handle_all_messages(message):
    user_input = message.text.strip()
    
    # প্রথমে চেক করবে ইনপুটটি কোনো IP Address কি না
    ip_result = check_ip_version(user_input)
    
    if ip_result:
        # যদি আইপি হয়, তবে আইপির রেজাল্ট পাঠাবে
        bit_info = "৩২-বিট অ্যাড্রেস" if ip_result == "IPv4" else "১২৮-বিট অ্যাড্রেস"
        response = (
            "✅ **Valid IP Address Found!**\n\n"
            "🌐 **IP:** `{}`\n"
            "ℹ️ **Version:** `{}` ({})"
        ).format(user_input, ip_result, bit_info)
        bot.reply_to(message, response, parse_mode="Markdown")
        return

    # যদি আইপি না হয়, তবে দেশের নাম কি না তা চেক করবে (ফেক প্রোফাইলের জন্য)
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
                attempts = 0
                while attempts < 100:
                    potential_name = clean_to_english(fake.name_male())
                    if potential_name not in USED_NAMES:
                        USED_NAMES.add(potential_name)
                        full_name = potential_name
                        break
                    attempts += 1
                else:
                    full_name = clean_to_english(fake.name_male())
            
            clean_name = re.sub(r'[^a-zA-Z0-9]', '', full_name).lower()
            random_num = random.randint(1000, 9999) 
            
            username = f"{clean_name}{random_num}"
            email = f"{clean_name}{random_num}@gmail.com"
            phone = generate_fake_phone(details['code'], details['digits'])
            
            response = (
                f"👤 **Developer:** {DEVELOPER_NAME}\n"
                f"🆔 **Your Telegram:** {tg_mention}\n"
                f"🌍 **দেশ:** {user_input.capitalize()}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 **নাম (Boy):** `{full_name}`\n"
                f"🆔 **ইউজারনেম:** `{username}`\n"
                f"📧 **জিমেইল:** `{email}`\n"
                f"📞 **ফোন:** `{phone}`\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 *তথ্যের ওপর ট্যাপ করলেই সেটি অটো-কপি হয়ে যাবে।*"
            )
            bot.reply_to(message, response, parse_mode="Markdown")
        except Exception as e:
            bot.reply_to(message, "⚠️ দুঃখিত, প্রোফাইল ডাটা জেনারেট করা সম্ভব হয়নি।")
    else:
        # দেশের নাম বা আইপি কোনোটার সাথেই না মিললে এই মেসেজ দেবে
        bot.reply_to(message, "⚠️ দুঃখিত, এটি কোনো সঠিক দেশের নাম বা আইপি অ্যাড্রেস নয়।\n\nযেমন লিখুন: `Bangladesh` অথবা `192.168.1.1`")

if __name__ == '__main__':
    bot.remove_webhook()
    keep_alive()
    print("🚀 All-in-One Bot Engine Started on Cloud Successfully...")
    bot.infinity_polling()
    "Biswas", "Siddique", "Zaman", "Majumder", "Pal", "Das", "Roy", "Dev", "Munshi", "Kazi",
    "Mollah", "Dewan", "Khondoker", "Khandakar", "Pramanik", "Bepari", "Haq", "Haque", "Mir", "Bari", 
    "Sikder", "Mia", "Ullah", "Eahi", "Rana", "Howlader", "Golder", "Halder", "Sutradhar", "Karmakar", 
    "Malakar", "Bhowmik", "Adhikary", "Gain", "Saha", "Podder", "Arif", "Tahher", "Naser", "Huda", 
    "Chisti", "Arefin", "Kuddus", "Babu", "Moni", "Sora", "Abdin", "Nabi", "Rabbani", "Siddiqui"
]

# ব্যবহৃত নামগুলো ট্র্যাকিংয়ের জন্য মেমোরি সেট
USED_NAMES = set()

def generate_unique_bd_name():
    attempts = 0
    while attempts < 5000:
        prefix = random.choice(["Md. ", ""])
        first = random.choice(BD_BOYS_FIRST_NAMES)
        last = random.choice(BD_BOYS_LAST_NAMES)
        full_name = f"{prefix}{first} {last}".strip()
        
        if full_name not in USED_NAMES:
            USED_NAMES.add(full_name)
            return full_name
        attempts += 1
    return f"Md. {random.choice(BD_BOYS_FIRST_NAMES)} {random.choice(BD_BOYS_LAST_NAMES)}"

def generate_fake_phone(code, pattern):
    number = ""
    for char in pattern:
        if char == 'X':
            number += str(random.randint(0, 9))
        else:
            number += char
    return f"{code}{number}"

def clean_to_english(text):
    import unicodedata
    return "".join(c for c in unicodedata.normalize('NFD', text) if unicodedata.category(c) != 'Mn')

@bot.message_handler(commands=['start'])
def send_welcome(message):
    welcome_text = (
        "👋 **স্বাগতম!**\n\n"
        "🔹 যেকোনো সমর্থিত দেশের নাম লিখলে সেই দেশের ১০০% ইউনিক ফেক ছেলে প্রোফাইল পাবেন।\n"
        "🔹 একটি নাম একবার জেনারেট হলে তা চিরতরে লক হয়ে যায়, অন্য কেউ আর সেই নাম পাবে না।\n"
        "🔹 উদাহরণস্বরূপ চ্যাটে লিখুন: `Bangladesh` অথবা `USA`"
    )
    bot.reply_to(message, welcome_text, parse_mode="Markdown")

@bot.message_handler(commands=['panel'])
def admin_panel(message):
    if message.from_user.id == ADMIN_ID:
        bot.reply_to(message, f"⚙️ **কন্ট্রোল প্যানেল:**\n\nবটটি বর্তমানে ক্লাউডে সচল আছে।\nডেভলপার: {DEVELOPER_NAME}\nমোট ব্যবহৃত ইউনিক নাম: {len(USED_NAMES)}")
    else:
        bot.reply_to(message, "❌ আপনি এই বটের অ্যাডমিন নন!")

@bot.message_handler(func=lambda message: True)
def generate_full_profile(message):
    country_input = message.text.strip().lower()
    
    if country_input not in COUNTRY_DETAILS:
        bot.reply_to(message, "⚠️ দুঃখিত, অনুগ্রহ করে সঠিক দেশের নাম ইংরেজিতে লিখুন (যেমন: Bangladesh, India, USA)।")
        return

    details = COUNTRY_DETAILS[country_input]
    user_tg_username = message.from_user.username
    tg_mention = f"@{user_tg_username}" if user_tg_username else "Not Available"

    try:
        if details['is_bd']:
            full_name = generate_unique_bd_name()
        else:
            fake = Faker(details['locale'])
            attempts = 0
            while attempts < 100:
                potential_name = clean_to_english(fake.name_male())
                if potential_name not in USED_NAMES:
                    USED_NAMES.add(potential_name)
                    full_name = potential_name
                    break
                attempts += 1
            else:
                full_name = clean_to_english(fake.name_male())
        
        clean_name = re.sub(r'[^a-zA-Z0-9]', '', full_name).lower()
        random_num = random.randint(1000, 9999) 
        
        username = f"{clean_name}{random_num}"
        email = f"{clean_name}{random_num}@gmail.com"
        phone = generate_fake_phone(details['code'], details['digits'])
        
        response = (
            f"👤 **Developer:** {DEVELOPER_NAME}\n"
            f"🆔 **Your Telegram:** {tg_mention}\n"
            f"🌍 **দেশ:** {message.text.strip().capitalize()}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 **নাম (Boy):** `{full_name}`\n"
            f"🆔 **ইউজারনেম:** `{username}`\n"
            f"📧 **জিমেইল:** `{email}`\n"
            f"📞 **ফোন:** `{phone}`\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 *তথ্যের ওপর ট্যাপ করলেই সেটি অটো-কপি হয়ে যাবে।*"
        )
        
        bot.reply_to(message, response, parse_mode="Markdown")
        
    except Exception as e:
        bot.reply_to(message, "⚠️ দুঃখিত, ডাটা জেনারেট করা সম্ভব হয়নি।")

# ৩. মেইন এক্সিকিউশন লুপ
if __name__ == '__main__':
    bot.remove_webhook()
    # ব্যাকগ্রাউন্ড ওয়েব সার্ভার অন করা (যাতে হোস্টিং কোম্পানি বট স্লিপে না পাঠায়)
    keep_alive()
    print("🚀 Cloud Web Server & Bot Engine Started Successfully...")
    bot.infinity_polling()
