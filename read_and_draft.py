#!/usr/bin/env python3
import os
import json
import imaplib
import time
from email import policy
from email.message import EmailMessage
from openai import OpenAI

# ————— Настройки из окружения —————
IMAP_HOST        = os.getenv('IMAP_HOST')
IMAP_PORT        = int(os.getenv('IMAP_PORT', 993))
IMAP_USER        = os.getenv('IMAP_USER')
IMAP_PASS        = os.getenv('IMAP_PASS')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
# Название папки для черновиков. Обычно "Drafts" или "[Gmail]/Drafts", можно переопределить
DRAFTS_FOLDER    = os.getenv('DRAFTS_FOLDER', 'Drafts')
# Файл для хранения ID уже обработанных писем
PROCESSED_FILE   = 'processed_ids.json'

SYSTEM_PROMPT = (
    "Ты — ассистент по email. Проанализируй письмо, "
    "определи суть и предложи вежливый и по делу черновик ответа."
)

# DeepSeek-клиент через OpenAI-совместимый SDK
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")


def load_processed():
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE, 'r', encoding='utf-8') as f:
            return set(json.load(f))
    return set()

def save_processed(processed_ids):
    with open(PROCESSED_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(processed_ids), f, ensure_ascii=False, indent=2)

def fetch_unread(limit=5):
    """
    Берём до `limit` непрочитанных писем, но не снимаем флаг UNSEEN.
    PEEK гарантирует, что IMAP-сервер не пометит письмо как прочитанное.
    """
    M = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    M.login(IMAP_USER, IMAP_PASS)
    M.select('INBOX')
    typ, data = M.search(None, 'UNSEEN')
    mids = data[0].split()[:limit]
    result = []
    for mid in mids:
        # FETCH BODY.PEEK[] вместо RFC822
        typ, msg_data = M.fetch(mid, '(BODY.PEEK[])')
        raw = msg_data[0][1]
        msg = EmailMessage(policy=policy.default)
        msg = msg.policy.message_factory(raw)
        # получить текстовую часть
        text = ""
        for part in msg.walk():
            if part.get_content_type() == 'text/plain':
                text = part.get_content()
                break
        result.append((mid.decode(), msg['From'], msg['Subject'], text))
    M.logout()
    return result

def generate_reply(body, subject, sender):
    """
    Запрос в DeepSeek через SDK.
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
    Формируем EmailMessage и кладём в папку черновиков через APPEND.
    """
    msg = EmailMessage()
    msg['From'] = IMAP_USER
    msg['To']   = to
    msg['Subject'] = f"Re: {subject}"
    msg.set_content(body)
    date_time = imaplib.Time2Internaldate(time.time())
    raw_bytes = msg.as_bytes()

    M = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    M.login(IMAP_USER, IMAP_PASS)
    # Флаг \Draft помечает сообщение как черновик
    M.append(DRAFTS_FOLDER, '\\Draft', date_time, raw_bytes)
    M.logout()

def main():
    processed = load_processed()
    messages = fetch_unread()

    for mid, frm, subj, body in messages:
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
