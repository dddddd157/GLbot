import imaplib
import email
from email import policy
from telegram import Bot
import asyncio
from datetime import datetime
import re
import os
from dotenv import load_dotenv

# === Загрузка переменных из .env ===
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

FILTER_SENDER = 'lia-compensations@mail.samokat.ru'
CHECK_INTERVAL = 60  # секунд

bot = Bot(token=TELEGRAM_BOT_TOKEN)

# === Список аккаунтов: email берём из .env, пароль тоже из .env ===
ACCOUNTS = [
    {
        'email': os.getenv('EMAIL_1'),
        'password': os.getenv('PASSWORD_1'),
        'imap_host': 'imap.mail.ru',
        'imap_port': 993,
        'chat_id': '-1002104898038',
        'thread_id': 21649,
        'uid_file': 'last_uid_1.txt'
    },
    {
        'email': os.getenv('EMAIL_2'),
        'password': os.getenv('PASSWORD_2'),
        'imap_host': 'imap.mail.ru',
        'imap_port': 993,
        'chat_id': '-1002187630843',
        'thread_id': 14235,
        'uid_file': 'last_uid_2.txt'
    },
    {
        'email': os.getenv('EMAIL_3'),
        'password': os.getenv('PASSWORD_3'),
        'imap_host': 'imap.mail.ru',
        'imap_port': 993,
        'chat_id': '-1002692236762',
        'thread_id': 398,
        'uid_file': 'last_uid_3.txt'
    },
    # Добавь другие аккаунты по той же схеме
]


def save_last_uid(uid_file, uid):
    with open(uid_file, "w") as f:
        f.write(str(uid))

def load_last_uid(uid_file):
    if not os.path.exists(uid_file):
        return None
    with open(uid_file, "r") as f:
        return f.read().strip()

def clean_html(raw_html):
    clean_text = re.sub('<[^<]+?>', '', raw_html)
    return re.sub(r'\s+', ' ', clean_text).strip()

def format_body_text(text):
    text = re.sub(r',\s*', ',\n', text)
    text = re.sub(r';\s*', ';\n', text)
    return text

def fetch_new_emails(account):
    mail = imaplib.IMAP4_SSL(account['imap_host'], account['imap_port'])
    mail.login(account['email'], account['password'])
    mail.select('INBOX')

    last_uid = load_last_uid(account['uid_file'])

    if last_uid is None:
        result, data = mail.uid('search', None, f'(FROM "{FILTER_SENDER}")')
        uids = data[0].split()
        if uids:
            latest_uid = int(uids[-1].decode())
            save_last_uid(account['uid_file'], latest_uid)
            print(f"[{datetime.now()}] 🟡 [{account['email']}] Первый запуск. UID сохранён: {latest_uid}")
        else:
            print(f"[{datetime.now()}] 🟡 [{account['email']}] Нет писем от {FILTER_SENDER}")
        mail.logout()
        return []

    last_uid_int = int(last_uid)
    search_criteria = f'(FROM "{FILTER_SENDER}" UID {last_uid_int + 1}:*)'
    result, data = mail.uid('search', None, search_criteria)
    uids = data[0].split()

    if not uids:
        print(f"[{datetime.now()}] ✅ [{account['email']}] Новых писем нет.")
        mail.logout()
        return []

    new_last_uid = int(uids[-1].decode())
    save_last_uid(account['uid_file'], new_last_uid)

    emails = []
    for uid_bytes in uids:
        uid = int(uid_bytes.decode())
        if uid <= last_uid_int:
            continue

        result, msg_data = mail.uid('fetch', uid_bytes, '(RFC822)')
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email, policy=policy.default)

        sender = msg['from']
        subject = msg['subject']
        date = msg['date']

        print(f"[{datetime.now()}] 📬 [{account['email']}] Письмо от {sender} — тема: {subject}")

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                if content_type == "text/html" and "attachment" not in content_disposition:
                    try:
                        html_body = part.get_payload(decode=True).decode()
                        body = clean_html(html_body)
                    except:
                        body = "[Ошибка при декодировании HTML]"
                    break
                elif content_type == "text/plain" and "attachment" not in content_disposition:
                    try:
                        body = part.get_payload(decode=True).decode()
                    except:
                        body = "[Ошибка при декодировании текста]"
                    break
        else:
            try:
                body = msg.get_payload(decode=True).decode()
                if "<html" in body.lower():
                    body = clean_html(body)
            except:
                body = "[Ошибка при декодировании тела письма]"

        body = format_body_text(body)

        emails.append({
            'sender': sender,
            'subject': subject,
            'date': date,
            'body': body[:3000]
        })

    mail.logout()
    return emails

async def send_to_telegram(account, email_data):
    text = (
        f"📩 Письмо от: {email_data['sender']}\n"
        f"📅 Дата: {email_data['date']}\n"
        f"🔤 Тема: {email_data['subject']}\n\n"
        f"{email_data['body']}"
    )
    try:
        await bot.send_message(
            chat_id=account['chat_id'],
            text=text,
            message_thread_id=account['thread_id']
        )
        print(f"[{datetime.now()}] ✅ [{account['email']}] Письмо переслано")
    except Exception as e:
        print(f"[{datetime.now()}] ❌ [{account['email']}] Ошибка при отправке в Telegram: {e}")

async def process_account(account):
    fetch_new_emails(account)
    await asyncio.sleep(5)

    while True:
        print(f"[{datetime.now()}] 🔄 [{account['email']}] Проверка почты...")
        emails = fetch_new_emails(account)
        if emails:
            print(f"[{datetime.now()}] 📥 [{account['email']}] Новых писем: {len(emails)}")
        for email_data in emails[:5]:
            await send_to_telegram(account, email_data)
            await asyncio.sleep(2)
        await asyncio.sleep(CHECK_INTERVAL)

async def main():
    print(f"[{datetime.now()}] 🚀 Запуск бота...")
    tasks = [process_account(account) for account in ACCOUNTS]
    await asyncio.gather(*tasks)

if __name__ == '__main__':
    asyncio.run(main())
