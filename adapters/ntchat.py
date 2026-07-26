import logging
logger = logging.getLogger(__name__)

import json
from typing import List
import requests

from pathlib import Path
from config import backend_config
from classes.message_context import MessageContext

NTCHAT_ENDPOINT = backend_config["message_backend"]["ntchat"]["endpoint"]

class MS:
    def __init__(self):
        self.data = []

    def append(self, wtf):
        self.data.append(wtf)

def send_msg(context: MessageContext, message: str | list = "Hello from nemo-bot-ng-backend", auto_escape: bool = False, reply: bool = False):
    endpoint = f"{NTCHAT_ENDPOINT}/send_msg"
    # normal send only
    images = []
    if isinstance(message, MS):
        data = message.data
        text_messages = ' '.join(i['data']['text'] for i in data if i['type'] == 'text')
        images = list(i['data']['file'] for i in data if i['type'] == 'image')
        message = text_messages
    elif isinstance(message, list):
        message = ' '.join(message)
    params = {
        "message": message,
        "auto_escape": auto_escape
    }
    if context.group_id:
        params["message_type"] = "group"
        params["group_id"] = context.group_id
    else:
        params["message_type"] = "private"
        params["user_id"] = context.user_id
    params["message_id"] = context.message_id
    params['images'] = images
    logger.debug("params: %s", params)
    r = requests.post(endpoint, json=params)
    logger.debug("response: %s", r.json())
    return r.json()

def send_photo(context: MessageContext, message: str = "", photo: str = '', reply: bool = False, *args, **kwargs):
    '''wrapper'''
    ms = MS()
    if message:
        ms.append({
            "type": "text",
            "data": {
                "text": message
            }
        })
    url_mode = isinstance(photo, str)
    if not url_mode:
        photo: Path
        with open(photo, 'rb') as f:
            photo_b = f.read()
            import base64
            photo_b = base64.b64encode(photo_b).decode('utf-8')
            ms.append({
                "type": "image",
                "data": {
                    "file": f"data:image/png;base64, {photo_b}"
                }
            })
    else:
        ms.append({
            "type": "image",
            "data": {
                "file": photo
            }
        })
    send_msg(context, ms, reply=reply)
