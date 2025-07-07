#!/usr/bin/env python3
import os
import json
import smtplib
import imaplib
import email
import requests

# ————— Настройки из окружения —————
IMAP_HOST        = os.getenv('IMAP_HOST')
IMAP_PORT        = int(os.getenv('IMAP_PORT', 993))
IMAP_USER        = os.getenv('IMAP_USER')
IMAP_PASS        = os.getenv('IMAP_PASS')
SMTP_HOST        = os.getenv('SMTP_HOST')
SMTP_PORT        = int(os.getenv('SMTP_PORT', 587))
SMTP_USER        = os.getenv('SMTP_USER')
SMTP_PASS        = os.getenv('SMTP_PASS')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')

SYSTEM_PROMPT = (
    "Ты — ассистент по email. Проанализируй письмо, "
    "определи суть и предложи вежливый и по делу черновик ответа."
)

PROCESSED_FILE = 'processed_ids.json'
# —————————————————————————

def load_processed():
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, 'r') as f:
            return json.load(f)
    return []

def save_processed(processed_ids):
    with open(PROCESSED_FILE, 'w') as f:
        json.dump(processed_ids, f)

def fetch_unread(max_count=5):
    """Возвращает до max_count непрочитанных писем (не меняет флаг UNSEEN)."""
    M = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    M.login(IMAP_USER, IMAP_PASS)
    M.select('INBOX')
    _, data = M.search(None, 'UNSEEN')
    ids = data[0].split()[:max_count]
    out = []
    for mid in ids:
        _, msg_data = M.fetch(mid, '(RFC822)')
        msg = email.message_from_bytes(msg_data[0][1])
        # достаём чистый текст
        text = ""
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                text = part.get_payload(decode=True).decode(errors='ignore')
                break
        out.append((mid.decode(), msg['From'], msg['Subject'], text))
    M.logout()
    return out

def generate_reply(body, subject, sender):
    """Запрос к Deepseek (правильный хост и путь)."""
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "X-API-Key": DEEPSEEK_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": f"Тема: {subject}\nОт: {sender}\n\n{body}"}
        ],
        "max_tokens": 500,
        "temperature": 0.2
    }
    resp = requests.post(url, headers=headers, json=payload)
    print("Status:", resp.status_code, "Response:", resp.text)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()

def send_reply(to, subject, body):
    srv = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
    srv.starttls()
    srv.login(SMTP_USER, SMTP_PASS)
    message = f"Subject: Re: {subject}\n\n{body}"
    srv.sendmail(SMTP_USER, to, message)
    srv.quit()

def main():
    processed = load_processed()
    messages = fetch_unread()

    for mid, frm, subj, body in messages:
        if mid in processed:
            print(f"🔁 Письмо {mid} уже обработано — пропускаем.")
            continue

        try:
            draft = generate_reply(body, subj, frm)
        except Exception as e:
            print(f"❌ Ошибка при генерации для письма {mid}: {e}")
            continue

        try:
            send_reply(frm, subj, draft)
            print(f"✅ Отправлен ответ на {mid} («{subj}»).")
        except Exception as e:
            print(f"❌ Ошибка при отправке ответа для {mid}: {e}")
            continue

        processed.append(mid)

    save_processed(processed)

if __name__ == "__main__":
    main()
