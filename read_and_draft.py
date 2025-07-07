#!/usr/bin/env python3
import os, base64, json, smtplib
import imaplib, email
import requests

# Настройки из окружения
IMAP_HOST       = os.getenv('IMAP_HOST')
IMAP_PORT       = int(os.getenv('IMAP_PORT', 993))
IMAP_USER       = os.getenv('IMAP_USER')
IMAP_PASS       = os.getenv('IMAP_PASS')
SMTP_HOST       = os.getenv('SMTP_HOST')
SMTP_PORT       = int(os.getenv('SMTP_PORT', 587))
SMTP_USER       = os.getenv('SMTP_USER')
SMTP_PASS       = os.getenv('SMTP_PASS')
DEEPSEEK_API_KEY= os.getenv('DEEPSEEK_API_KEY')

SYSTEM_PROMPT   = (
    "Ты — ассистент по email. Проанализируй письмо, "
    "определи суть и предложи вежливый и по делу черновик ответа."
)

def fetch_unread():
    M = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    M.login(IMAP_USER, IMAP_PASS)
    M.select('INBOX')
    _, data = M.search(None, 'UNSEEN')
    ids = data[0].split()
    out = []
    for mid in ids[:5]:
        _, msg_data = M.fetch(mid, '(RFC822)')
        msg = email.message_from_bytes(msg_data[0][1])
        text = ""
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                text = part.get_payload(decode=True).decode(errors='ignore')
                break
        out.append((mid, msg['From'], msg['Subject'], text))
    M.logout()
    return out

def generate_reply(body, subject, sender):
    """Запрос к Deepseek API"""
    url = "https://api.deepseek.ai/v1/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "deepseek-gpt",    # или модель из документации Deepseek
        "prompt": f"{SYSTEM_PROMPT}\n\nТема: {subject}\nОт: {sender}\n\n{body}",
        "max_tokens": 500,
        "temperature": 0.2
    }
    resp = requests.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    data = resp.json()
    # в зависимости от схемы ответа Deepseek:
    return data["choices"][0]["text"].strip()

def send_draft(to, subject, body):
    srv = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
    srv.starttls()
    srv.login(SMTP_USER, SMTP_PASS)
    srv.sendmail(SMTP_USER, to,
        f"Subject: Re: {subject}\n\n{body}"
    )
    srv.quit()

def main():
    for mid, frm, subj, body in fetch_unread():
        try:
            draft = generate_reply(body, subj, frm)
        except Exception as e:
            print(f"❌ Ошибка генерации для письма {mid}: {e}")
            continue
        send_draft(frm, subj, draft)
        print(f"Answered {frm} – «{subj}»")

if __name__ == "__main__":
    main()
