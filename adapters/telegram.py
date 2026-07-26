import requests
import telegramify_markdown
import logging

logger = logging.getLogger(__name__)

s = requests.Session()

from pathlib import Path
from config import backend_config
from classes.message_context import MessageContext

TELEGRAM_API_ENDPOINT = backend_config["message_backend"]["telegram"]["endpoint"]
TELEGRAM_BOT_TOKEN = backend_config["message_backend"]["telegram"]["token"]

def _safe_json(r):
    try:
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.error(f"Telegram API Error: {r.status_code} - {r.text}")
        return {"ok": False, "error": str(e), "status_code": r.status_code}

def send_msg(context: MessageContext, message: str = "Hello from nemo-bot-ng-backend", auto_escape: bool = False, reply: bool = False, *args, **kwargs):
    endpoint = f"{TELEGRAM_API_ENDPOINT}{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    text_plain, entities = telegramify_markdown.convert(message)
    chunks = telegramify_markdown.split_markdownv2(text_plain, entities, max_utf16_len=4000)
    
    last_result = {"ok": False, "error": "No chunks generated"}
    
    for chunk in chunks:
        data = {
            "text": chunk,
            "parse_mode": "MarkdownV2"
        }
        if context.group_id:
            data["chat_id"] = context.group_id
        else:
            data["chat_id"] = context.user_id
        if reply and context.message_id:
            data["reply_to_message_id"] = context.message_id
            
        r = s.post(endpoint, json=data)
        last_result = _safe_json(r)
        logger.debug(f"Telegram send_msg chunk result: {last_result}")
        
    return last_result
    
def send_voice(context: MessageContext, message: str = "子供たちに渡すプレゼントでお悩みですか？私と一緒に考えましょうか。ふふっ。", voice: str = 'https://cdnimg.gamekee.com/wiki2.0/images/w_0/h_0/829/223205/2022/11/14/450314.ogg', reply: bool = False, *args, **kwargs):
    endpoint = f"{TELEGRAM_API_ENDPOINT}{TELEGRAM_BOT_TOKEN}/sendVoice"
    
    formatted_msg = telegramify_markdown.markdownify(message)
    url_mode = isinstance(voice, str)
    if url_mode:
        data = {
            "voice": voice,
            'caption': formatted_msg,
            "parse_mode": "MarkdownV2"
        }
    else:
        data = {
            'caption': formatted_msg,
            "parse_mode": "MarkdownV2"
        }
    if context.group_id:
        data["chat_id"] = context.group_id
    else:
        data["chat_id"] = context.user_id
    if reply:
        data["reply_to_message_id"] = context.message_id
    if url_mode:
        r = s.post(endpoint, json=data)
    else:
        with open(voice, 'rb') as f:
            r = s.post(endpoint, data=data, files={'voice': ('voice.ogg', f.read())})
    result = _safe_json(r)
    logger.debug(f"Telegram send_voice result: {result}")
    return result

def send_photo(context: MessageContext, message: str = "", photo: str | Path = '', reply: bool = False, *args, **kwargs):
    endpoint = f"{TELEGRAM_API_ENDPOINT}{TELEGRAM_BOT_TOKEN}/sendPhoto"
    logger.debug("photo: %s", photo)
    
    formatted_msg = telegramify_markdown.markdownify(message)
    url_mode = isinstance(photo, str)
    if url_mode:
        data = {
            "photo": photo,
            'caption': formatted_msg,
            "parse_mode": "MarkdownV2"
        }
    else:
        data = {
            'caption': formatted_msg,
            "parse_mode": "MarkdownV2"
        }
    if context.group_id:
        data["chat_id"] = context.group_id
    else:
        data["chat_id"] = context.user_id
    if reply:
        data["reply_to_message_id"] = context.message_id
    if url_mode:
        r = s.post(endpoint, json=data)
    else:
        with open(photo, 'rb') as f:
            r = s.post(endpoint, data=data, files={'photo': (f'photo.{photo.as_posix().split('/')[-1].split('.')[-1]}', f.read())})
    result = _safe_json(r)
    logger.debug(f"Telegram send_photo result: {result}")
    return result