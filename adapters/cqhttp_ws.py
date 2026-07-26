import logging
logger = logging.getLogger(__name__)

import json
from typing import List
import requests

from pathlib import Path
from config import backend_config
from classes.message_context import MessageContext
import websocket

CQHTTP_WS_ENDPOINT = backend_config["message_backend"]["cqhttp_ws"]["endpoint"]


def send_msg(context: MessageContext, message: str = "Hello from nemo-bot-ng-backend", auto_escape: bool = True,reply: bool = True):
    if reply and context.message_id:
        message = f"[CQ:reply,id={context.message_id}]" + message
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
    logger.debug("params: %s", params)
    ws = websocket.WebSocket()
    ws.connect(CQHTTP_WS_ENDPOINT)
    ws.send(json.dumps(
        {
            "action": "send_msg",
            "params": params,
            "echo": "123"
        }
    ))
    r = json.loads(ws.recv())
    logger.debug("response: %s", r)
    ws.close()
    return r


def send_group_forward_msg(context: MessageContext, messages: List[str] = ["rua"]):
    endpoint = f"{CQHTTP_WS_ENDPOINT}/send_group_forward_msg"
    # construct nodes
    message_nodes = list({"type": "node", "data": {"name": "光光要杀我", "uin": "114514",
                         "content": "\n".join(grouped_message).strip()}} for grouped_message in messages)
    params = {
        "messages": json.dumps(message_nodes),
    }
    if context.group_id:
        params["group_id"] = context.group_id
    else:
        return
    ws = websocket.WebSocket()
    ws.connect(CQHTTP_WS_ENDPOINT)
    ws.send(json.dumps(
        {
            "action": "send_group_forward_msg",
            "params": params,
            "echo": "123"
        }
    ))
    r = json.loads(ws.recv())
    logger.debug("response: %s", r)
    ws.close()
    return r


def get_group_info(context: MessageContext, group_id: int = 114514):
    endpoint = f"{CQHTTP_WS_ENDPOINT}/get_group_info"
    params = {
        "group_id": group_id,
    }
    r = requests.get(endpoint, params=params)
    logger.debug("response: %s", r.json())
    return r.json()


def send_voice(context: MessageContext, message: str | Path = "子供たちに渡すプレゼントでお悩みですか？私と一緒に考えましょうか。ふふっ。", voice: str = 'https://cdnimg.gamekee.com/wiki2.0/images/w_0/h_0/829/223205/2022/11/14/450314.ogg', reply: bool = False, *args, **kwargs):
    '''wrapper'''
    send_msg(context, message, auto_escape=True)
    url_mode = isinstance(voice, str)
    if not url_mode:
        with open(voice, 'rb') as f:
            voice = f.read()
    else:
        r = requests.get(voice)
        voice = r.content
    import base64
    voice = base64.b64encode(voice).decode('utf-8')
    send_msg(context, f'[CQ:record,file=base64://{voice}]', auto_escape=True)


def send_photo(context: MessageContext, message: str = "", photo: str = '', reply: bool = False, *args, **kwargs):
    '''wrapper'''
    send_msg(context, message, auto_escape=True)
    url_mode = isinstance(photo, str)
    if not url_mode:
        with open(photo, 'rb') as f:
            photo = f.read()
            import base64
            photo = base64.b64encode(photo).decode('utf-8')
            send_msg(
                context, f'[CQ:image,file=base64://{photo}]', auto_escape=True)
    else:
        send_msg(context, f'[CQ:image,file={photo}]', auto_escape=True)
