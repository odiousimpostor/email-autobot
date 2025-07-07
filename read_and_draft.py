#!/usr/bin/env python3
import os
import json
import imaplib
import email
import time
from openai import OpenAI

# ————— Настройки из окружения —————
IMAP_HOST        = os.getenv('IMAP_HOST')
IMAP_PORT        = int(os.getenv('IMAP_PORT', 993))
IMAP_USER        = os.getenv('IMAP_USER')
IMAP_PASS        = os.getenv('IMAP_PASS')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
# Папка для черновиков (должна существовать на сервере)
DRAFTS_FOLDER    = os.getenv('DRAFTS_FOLDER', 'Drafts')

SYSTEM_PROMPT = (
    "Ты — ассистент по email. Проанализируй письмо, "
    "определи суть и предложи вежливый и по делу черновик ответа."
)

PROCESSED_FILE = 'processed_ids.json'
# —————————————————————————

# Инициализируем клиент DeepSeek через OpenAI-совместимый SDK
client = OpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url="https://api.deepseek.com"
)

def load_processed():
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_processed(ids):
    with open(PROCESSED_FILE, 'w', encoding='utf-8') as f:
        json.dump(ids, f, ensure_ascii=False, indent=2)

def fetch_unread(limit=5):
    """
    Возвращает до `limit` непрочитанных писем (не меняет флаг UNSEEN).
    Каждый элемент: (message_id, from, subject, body_text).
    """
    M = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    M.login(IMAP_USER, IMAP_PASS)
    M.select('INBOX')
    _, data = M.search(None, 'UNSEEN')
    mids = data[0].split()[:limit]
    messages = []
    for mid in mids:
        _, md = M.fetch(mid, '(RFC822)')
        msg = email.message_from_bytes(md[0][1])
        # Достаём текстовую часть
        body = ""
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                body = part.get_payload(decode=True).decode(errors='ignore')
                break
        messages.append((mid.decode(), msg.get('From'), msg.get('Subject'), body))
    M.logout()
    return messages

def generate_reply(body, subject, sender):
    """
    Запрашивает черновик у DeepSeek через SDK.
    Возвращает строку с ответом или None, если ошибка.
    """
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

def create_draft_imap(to, subject, body):
    """
    Создаёт черновик в папке DRAFTS_FOLDER через IMAP APPEND.
    """
    msg = f"To: {to}\r\nSubject: Re: {subject}\r\n\r\n{body}"
    M = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    M.login(IMAP_USER, IMAP_PASS)
    # Флаг \Draft помечает сообщение как черновик
    date_time = imaplib.Time2Internaldate(time.time())
    M.append(DRAFTS_FOLDER, '\\Draft', date_time, msg.encode('utf-8'))
    M.logout()

def main():
    processed = load_processed()
    messages = fetch_unread()

    for mid, frm, subj, body in messages:
        if mid in processed:
            print(f"🔁 {mid} уже обработано, пропускаем.")
            continue

        print(f"✉️ Обрабатываем письмо {mid}: «{subj}» от {frm}")
        draft = generate_reply(body, subj, frm)
        if not draft:
            print(f"⚠️ Не удалось сгенерировать черновик для {mid}.")
            continue

        try:
            create_draft_imap(frm, subj, draft)
            print(f"📝 Черновик для {mid} сохранён в папку «{DRAFTS_FOLDER}».")
            processed.append(mid)
        except Exception as e:
            print(f"❌ Ошибка создания черновика для {mid}: {e}")

    save_processed(processed)

if __name__ == "__main__":
    main()
