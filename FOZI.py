import os
import re
import time
import asyncio
import logging
import requests
import threading
from datetime import datetime
from bs4 import BeautifulSoup
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase
from telegram import Bot

# ================================
# CONFIGURATION
# ================================
# Apni details yahan bharein
BOT_TOKEN = "8082347161:AAGj4CwsLctESyEZ1ZesyxNAYpwbFB7az7k"
GROUP_ID = "-1003862948715" 

# IVASMS Credentials
IVASMS_EMAIL = "your-email@example.com"
IVASMS_PASSWORD = "your-password"

# ================================
# DATABASE SETUP
# ================================
class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///bot.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db.init_app(app)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

class OTPLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    otp_code = db.Column(db.String(20))
    phone_number = db.Column(db.String(20))
    service_name = db.Column(db.String(100))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# ================================
# IVASMS SCRAPER LOGIC
# ================================
class IVASMSScraper:
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self.session = requests.Session()
        self.base_url = "https://www.ivasms.com/portal"
        self.is_logged_in = False

    def login(self):
        try:
            login_url = f"{self.base_url}/login"
            # Initial get to catch cookies
            self.session.get(login_url)
            payload = {'email': self.email, 'password': self.password}
            response = self.session.post(login_url, data=payload)
            if "dashboard" in response.url.lower() or response.status_code == 200:
                self.is_logged_in = True
                logger.info("✅ IVASMS Login Successful!")
                return True
            return False
        except Exception as e:
            logger.error(f"❌ Login Failed: {e}")
            return False

    def fetch_latest_otps(self):
        if not self.is_logged_in:
            self.login()
        
        try:
            # Live SMS page jahan OTP aate hain
            resp = self.session.get(f"{self.base_url}/live/my_sms")
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            # Yahan hum table rows (tr) dhund rahe hain
            messages = []
            rows = soup.find_all('tr')[1:] # Skip header
            
            for row in rows:
                cols = row.find_all('td')
                if len(cols) >= 3:
                    phone = cols[0].text.strip()
                    msg_text = cols[1].text.strip()
                    # OTP extract karne ke liye regex
                    otp_match = re.search(r'\b\d{4,6}\b', msg_text)
                    otp = otp_match.group(0) if otp_match else "N/A"
                    
                    messages.append({
                        'phone': phone,
                        'otp': otp,
                        'service': "IVASMS Service"
                    })
            return messages
        except Exception as e:
            logger.error(f"❌ Fetch Error: {e}")
            return []

# ================================
# TELEGRAM & BACKGROUND TASK
# ================================
telegram_bot = Bot(token=BOT_TOKEN)

async def send_to_telegram(otp_data):
    text = (
        f"🔐 *NEW OTP RECEIVED*\n\n"
        f"📱 *Number:* `{otp_data['phone']}`\n"
        f"🔢 *OTP Code:* `{otp_data['otp']}`\n"
        f"🌐 *Service:* {otp_data['service']}\n"
        f"⏰ *Time:* {datetime.now().strftime('%H:%M:%S')}"
    )
    try:
        await telegram_bot.send_message(chat_id=GROUP_ID, text=text, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Telegram Send Error: {e}")

def run_scraper_loop():
    scraper = IVASMSScraper(IVASMS_EMAIL, IVASMS_PASSWORD)
    processed_otps = set() # Duplicate se bachne ke liye

    while True:
        with app.app_context():
            new_msgs = scraper.fetch_latest_otps()
            for msg in new_msgs:
                identifier = f"{msg['phone']}_{msg['otp']}"
                if identifier not in processed_otps:
                    # Save to DB
                    new_entry = OTPLog(otp_code=msg['otp'], phone_number=msg['phone'], service_name=msg['service'])
                    db.session.add(new_entry)
                    db.session.commit()
                    
                    # Send to Telegram
                    asyncio.run(send_to_telegram(msg))
                    processed_otps.add(identifier)
            
        time.sleep(20) # 20 seconds ka wait

# ================================
# ROUTES
# ================================
@app.route('/')
def home():
    return "<h1>Bot is Active!</h1><p>Checking IVASMS for OTPs...</p>"

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
    # Background thread for scraper
    threading.Thread(target=run_scraper_loop, daemon=True).start()
    
    # Run Flask app
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
