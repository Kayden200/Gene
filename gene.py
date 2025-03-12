from flask import Flask, request, jsonify
import imaplib
import smtplib
import pyotp
import email.message
import re
import random
from email_validator import validate_email, EmailNotValidError
from flask_sqlalchemy import SQLAlchemy
import time

app = Flask(__name__)

# Configure SQLite Database
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///otp_records.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# Yandex Mail Configuration
IMAP_SERVER = "imap.yandex.com"
IMAP_PORT = 993
SMTP_SERVER = "smtp.yandex.com"
SMTP_PORT = 465
USERNAME = "rylecohner@yandex.com"
PASSWORD = "your_yandex_password"  # Use an app password if 2FA is enabled

# OTP Storage Model
class OTPRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    otp = db.Column(db.String(6), nullable=False)
    timestamp = db.Column(db.Float, nullable=False)

with app.app_context():
    db.create_all()

# Function to generate Yandex email aliases with random numbers
def generate_random_yandex_alias(base_email):
    random_number = random.randint(1000, 9999)  # Generate a 4-digit random number
    return f"{base_email.split('@')[0]}+{random_number}@yandex.com"

# Function to send OTP via Yandex SMTP
def send_otp(email_alias, otp_code):
    try:
        msg = email.message.EmailMessage()
        msg["Subject"] = "Your Facebook OTP Code"
        msg["From"] = USERNAME
        msg["To"] = email_alias
        msg.set_content(f"Your Facebook OTP is: {otp_code}\nUse this to complete your signup.")

        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT) as server:
            server.login(USERNAME, PASSWORD)
            server.send_message(msg)

        return True
    except Exception as e:
        print(f"Error sending OTP: {e}")
        return False

@app.route('/generate_alias', methods=['GET'])
def generate_alias():
    alias = generate_random_yandex_alias(USERNAME)
    return jsonify({"alias": alias})

@app.route('/check_email', methods=['GET'])
def check_email():
    alias = request.args.get('alias')
    if not alias:
        return jsonify({"error": "Alias email is required"}), 400

    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(USERNAME, PASSWORD)
        mail.select("inbox")

        status, data = mail.search(None, f'TO "{alias}"')
        mail.logout()

        if data[0]:
            return jsonify({"message": f"✅ Email received at {alias}"})
        else:
            return jsonify({"message": f"❌ No emails found for {alias}"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/request_otp', methods=['POST'])
def request_otp():
    data = request.get_json()
    email_alias = data.get("email")

    # Validate email format
    try:
        validate_email(email_alias, check_deliverability=False)
    except EmailNotValidError:
        return jsonify({"error": "Invalid email format"}), 400

    # Generate OTP
    otp_code = pyotp.TOTP(pyotp.random_base32()).now()

    # Store OTP in database
    existing_record = OTPRecord.query.filter_by(email=email_alias).first()
    if existing_record:
        existing_record.otp = otp_code
        existing_record.timestamp = time.time()
    else:
        new_record = OTPRecord(email=email_alias, otp=otp_code, timestamp=time.time())
        db.session.add(new_record)
    
    db.session.commit()

    # Send OTP
    success = send_otp(email_alias, otp_code)

    if success:
        return jsonify({"message": f"OTP sent to {email_alias}"}), 200
    else:
        return jsonify({"error": "Failed to send OTP"}), 500

@app.route('/verify_otp', methods=['POST'])
def verify_otp():
    data = request.get_json()
    email_alias = data.get("email")
    entered_otp = data.get("otp")

    # Validate email
    try:
        validate_email(email_alias, check_deliverability=False)
    except EmailNotValidError:
        return jsonify({"error": "Invalid email format"}), 400

    # Retrieve stored OTP
    record = OTPRecord.query.filter_by(email=email_alias).first()
    if record and record.otp == entered_otp:
        # Check OTP expiry (5 minutes)
        if time.time() - record.timestamp > 300:
            return jsonify({"error": "OTP expired"}), 400
        return jsonify({"message": "OTP verified successfully"}), 200
    else:
        return jsonify({"error": "Invalid OTP"}), 400

if __name__ == '__main__':
    app.run(debug=True)
