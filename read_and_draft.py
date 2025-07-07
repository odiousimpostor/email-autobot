#!/usr/bin/env python3
import os
import json
import imaplib
import time
import email
from email import policy
from email.header import decode_header, Header
from email.message import EmailMessage
from openai import OpenAI

# ————— Настройки из окружения —————
IMAP_HOST        = os.getenv('IMAP_HOST')
IMAP_PORT        = int(os.getenv('IMAP_PORT', 993))
IMAP_USER        = os.getenv('IMAP_USER')
IMAP_PASS        = os.getenv('IMAP_PASS')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
DRAFTS_FOLDER    = os.getenv('DRAFTS_FOLDER', 'Drafts')
PROCESSED_FILE   = 'processed_ids.json'
SYSTEM_PROMPT    = (
    "Ты — ассистент по email. Проанализируй письмо, "
    "определи суть и предложи вежливый и по делу черновик ответа."
)

# DeepSeek-клиент через OpenAI-совместимый SDK
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")


def decode_mime(header_value: str) -> str:
    parts = decode_header(header_value or "")
    decoded = ""
    for text, charset in parts:
        if isinstance(text, bytes):
            decoded += text.decode(charset or 'utf-8', errors='ignore')
        else:
            decoded += text
    return decoded


def load_processed() -> set:
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, 'r', encoding='utf-8') as f:
            return set(json.load(f))
    return set()


def save_processed(processed_ids: set):
    with open(PROCESSED_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(processed_ids), f, ensure_ascii=False, indent=2)


def fetch_unread(limit: int = 5) -> list[tuple[str,str,str,str]]:
    M = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    M.login(IMAP_USER, IMAP_PASS)
    M.select('INBOX')
    _, data = M.search(None, 'UNSEEN')
    mids = data[0].split()[:limit]
    messages = []
    for mid in mids:
        _, msg_data = M.fetch(mid, '(BODY.PEEK[])')
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw, policy=policy.default)

        frm  = decode_mime(msg['From'])
        subj = decode_mime(msg['Subject'])

        # Извлекаем текст
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == 'text/plain' and not part.get_content_disposition():
                    payload = part.get_payload(decode=True)
                    charset = part.get_content_charset() or 'utf-8'
                    body = payload.decode(charset, errors='ignore')
                    break
        else:
            payload = msg.get_payload(decode=True)
            charset = msg.get_content_charset() or 'utf-8'
            body = payload.decode(charset, errors='ignore')

        messages.append((mid.decode(), frm, subj, body))
    M.logout()
    return messages


def generate_reply(body: str, subject: str, sender: str) -> str | None:
    try:
        resp = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": f"Тема: {subject}\nОт: {sender}\n\n{body}"}
            ],
            max_tokens=500,
            temperature=0.2,
            stream=False
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ DeepSeek error: {e}")
        return None


def create_draft_imap(to: str, subject: str, body: str):
    msg = EmailMessage()
    # Используем Header для правильной UTF-8 кодировки
    msg['From']    = IMAP_USER
    msg['To']      = Header(to, 'utf-8')
    msg['Subject'] = Header(f"Re: {subject}", 'utf-8')
    msg.set_content(body, charset='utf-8')

    date_time = imaplib.Time2Internaldate(time.time())
    raw_bytes = msg.as_bytes()

    M = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    M.login(IMAP_USER, IMAP_PASS)
    M.append(DRAFTS_FOLDER, '\\Draft', date_time, raw_bytes)
    M.logout()


def main():
    processed = load_processed()
    for mid, frm, subj, body in fetch_unread():
        if mid in processed:
            print(f"🔁 Письмо {mid} уже обработано, пропускаем.")
            continue

        print(f"✉️ Обрабатываем {mid}: «{subj}» от {frm}")
        draft = generate_reply(body, subj, frm)
        if not draft:
            print(f"⚠️ Не удалось сгенерировать черновик для {mid}.")
            continue

        try:
            create_draft_imap(frm, subj, draft)
            print(f"📝 Черновик {mid} сохранён в «{DRAFTS_FOLDER}».")
            processed.add(mid)
        except Exception as e:
            print(f"❌ Ошибка создания черновика для {mid}: {e}")

    save_processed(processed)


if __name__ == "__main__":
    main()
