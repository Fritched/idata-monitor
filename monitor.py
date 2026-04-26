import asyncio
import hashlib
import imaplib
import email as email_lib
import json
import os
import smtplib
import base64
import re
from datetime import datetime
from email.mime.text import MIMEText

import httpx
from anthropic import Anthropic
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

IDATA_EMAIL    = os.environ["IDATA_EMAIL"]
IDATA_PASSWORD = os.environ["IDATA_PASSWORD"]
LOGIN_URL      = "https://it-tr-appointment.idata.com.tr/en/login"
APPT_URL       = "https://it-tr-appointment.idata.com.tr/en/appointment-form"

ANTHROPIC_KEY    = os.environ["ANTHROPIC_API_KEY"]
TELEGRAM_TOKEN   = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
GMAIL_USER       = os.environ["GMAIL_USER"]
GMAIL_PASS       = os.environ["GMAIL_APP_PASS"]

NO_SLOT_PHRASE = "Uygun randevu tarihi bulunmamaktadır"
KNOWN_CUTOFF   = "30.04.2026"

client = Anthropic(api_key=ANTHROPIC_KEY)


async def scrape_idata() -> tuple[str, bytes]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="tr-TR",
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        print("  → Going to login page...")
        await page.goto(LOGIN_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)
        await page.screenshot(path="step1_login_page.png", full_page=True)
        print("  → Saved step1_login_page.png")

        email_field = await page.query_selector(
            'input[type="email"], input[name="Email"], input[name="email"], #Email, #email'
        )
        if not email_field:
            await page.screenshot(path="error_no_email_field.png", full_page=True)
            await browser.close()
            raise Exception("Email field not found — check error_no_email_field.png")
        await email_field.fill(IDATA_EMAIL)
        print("  → Email filled")

        password_field = await page.query_selector(
            'input[type="password"], input[name="Password"], input[name="password"], #Password, #password'
        )
        if not password_field:
            await browser.close()
            raise Exception("Password field not found")
        await password_field.fill(IDATA_PASSWORD)
        print("  → Password filled")

        await page.screenshot(path="step2_before_login.png", full_page=True)

        submit = await page.query_selector(
            'button[type="submit"], input[type="submit"], button.login-btn, .btn-login'
        )
        if not submit:
            await browser.close()
            raise Exception("Submit button not found")
        await submit.click()
        print("  → Login button clicked")

        await page.wait_for_load_state("networkidle", timeout=15000)
        await page.wait_for_timeout(2000)
        await page.screenshot(path="step3_after_login.png", full_page=True)
        print(f"  → Now at: {page.url}")

        if "login" in page.url.lower():
            await browser.close()
            raise Exception("Still on login page — check step3_after_login.png")

        print("  → Login successful!")

        await page.goto(APPT_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(2000)
        await page.screenshot(path="step4_appointment_page.png", full_page=True)
        print("  → Saved step4_appointment_page.png")

        selects = await page.query_selector_all("select")
        print(f"  → Found {len(selects)} dropdowns")

        if len(selects) >= 1:
            await selects[0].select_option(label="İstanbul")
            await page.wait_for_timeout(1500)
            print("  → Selected Istanbul")

        selects = await page.query_selector_all("select")
        if len(selects) >= 2:
            await selects[1].select_option(label="İstanbul Ofis - Altunizade")
            await page.wait_for_timeout(1500)
            print("  → Selected Altunizade")

        selects = await page.query_selector_all("select")
        if len(selects) >= 3:
            await selects[2].select_option(label="Turistik")
            await page.wait_for_timeout(1500)
            print("  → Selected Turistik")

        selects = await page.query_selector_all("select")
        if len(selects) >= 4:
            await selects[3].select_option(label="STANDART")
            await page.wait_for_timeout(2500)
            print("  → Selected STANDART")

        await page.screenshot(path="step5_final.png", full_page=True)
        print("  → Saved step5_final.png")

        body_text  = await page.inner_text("body")
        screenshot = await page.screenshot(full_page=True)
        await browser.close()
        return body_text, screenshot


def fast_check(page_text: str) -> dict:
    no_slot      = NO_SLOT_PHRASE in page_text
    date_match   = re.search(r'\d{2}\.\d{2}\.\d{4}', page_text)
    found_date   = date_match.group(0) if date_match else None
    date_changed = found_date and found_date != KNOWN_CUTOFF

    positive_phrases = [
        "Randevu Oluştur",
        "randevunuzu onaylayın",
        "ödeme",
        "Confirm",
        "Book appointment",
    ]
    has_positive = any(p.lower() in page_text.lower() for p in positive_phrases)

    if not no_slot:
        return {"trigger": True,
                "reason": "No-slot message gone from page",
                "date": found_date}
    if date_changed:
        return {"trigger": True,
                "reason": f"Cutoff date changed: was {KNOWN_CUTOFF}, now {found_date}",
                "date": found_date}
    if has_positive:
        return {"trigger": True,
                "reason": "Booking phrase detected",
                "date": found_date}

    return {"trigger": False,
            "reason": f"Still no slots. Cutoff: {found_date or 'not found'}",
            "date": found_date}


def confirm_with_claude(screenshot: bytes) -> dict:
    b64 = base64.standard_b64encode(screenshot).decode()
    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64",
                            "media_type": "image/png",
                            "data": b64}},
                {"type": "text",
                 "text": (
                     "This is the iDATA visa appointment portal (Italian consulate, Turkey). "
                     "Is there an actual available appointment date or booking button visible? "
                     "Or does it still say no dates available "
                     "(Turkish: 'Uygun randevu tarihi bulunmamaktadır')? "
                     "Reply ONLY with JSON: "
                     '{"slot_available": true or false, "what_you_see": "one sentence"}'
                 )}
            ]
        }],
    )
    try:
        return json.loads(response.content[0].text)
    except Exception:
        return {"slot_available": True, "what_you_see": "Parse error — check screenshot"}


def check_gmail() -> dict:
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_PASS)
        mail.select("inbox")
        _, messages = mail.search(None, '(UNSEEN FROM "idata.com.tr")')
        ids = messages[0].split()
        if not ids:
            mail.logout()
            return {"found": False}
        _, msg_data = mail.fetch(ids[-1], "(RFC822)")
        msg     = email_lib.message_from_bytes(msg_data[0][1])
        subject = msg["subject"] or "(no subject)"
        mail.logout()
        return {"found": True, "subject": subject}
    except Exception as e:
        print(f"  → Gmail check error: {e}")
        return {"found": False}


def send_telegram(text: str):
    try:
        httpx.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID,
                  "text": text,
                  "parse_mode": "HTML"},
            timeout=10,
        )
        print("  → Telegram ✓")
    except Exception as e:
        print(f"  → Telegram failed: {e}")


def send_email(subject: str, body: str):
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"]    = GMAIL_USER
        msg["To"]      = GMAIL_USER
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_USER, GMAIL_PASS)
            s.send_message(msg)
        print("  → Email ✓")
    except Exception as e:
        print(f"  → Email failed: {e}")


def fire_alerts(reason: str, date: str = None, extra: str = ""):
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    tg = (
        f"🚨 <b>iDATA SLOT DETECTED</b>\n\n"
        f"📋 {reason}\n"
        + (f"📅 Date: {date}\n" if date else "")
        + (f"💬 {extra}\n" if extra else "")
        + f"\n→ <a href='{APPT_URL}'>Open iDATA NOW</a>\n"
        f"⏱ {timestamp}"
    )
    send_telegram(tg)
    send_email(
        "🚨 iDATA VISA SLOT ALERT",
        f"{reason}\n{date or ''}\n{extra}\n\n{APPT_URL}\n{timestamp}"
    )


async def main():
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  iDATA Monitor — {datetime.now():%d.%m.%Y %H:%M:%S}")
    print(f"  Known cutoff : {KNOWN_CUTOFF}")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    gmail = check_gmail()
    if gmail["found"]:
        print(f"  🔔 iDATA EMAIL FOUND: {gmail['subject']}")
        fire_alerts("Email from iDATA received", extra=f"Subject: {gmail['subject']}")
        return

    try:
        page_text, screenshot = await scrape_idata()
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return

    result = fast_check(page_text)
    print(f"  → {result['reason']}")

    if not result["trigger"]:
        print("  — No slots yet. Done.")
        return

    print("  ⚠ Change detected — asking Claude to confirm...")
    claude = confirm_with_claude(screenshot)
    print(f"  → Claude: {claude['what_you_see']}")

    if claude["slot_available"]:
        print("  🔔 CONFIRMED — firing alerts!")
        fire_alerts(
            reason=result["reason"],
            date=result.get("date"),
            extra=claude["what_you_see"]
        )
    else:
        print("  — False positive avoided.")


if __name__ == "__main__":
    asyncio.run(main())