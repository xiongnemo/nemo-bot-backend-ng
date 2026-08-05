import logging
logger = logging.getLogger(__name__)

import json
from typing import List
import requests

from pathlib import Path
from config import backend_config
from classes.message_context import MessageContext

CQHTTP_ENDPOINT = backend_config["message_backend"]["cqhttp"]["endpoint"]

def send_msg(context: MessageContext, message: str = "Hello from nemo-bot-ng-backend", auto_escape: bool = False, reply: bool = True):
    endpoint = f"{CQHTTP_ENDPOINT}/send_msg"
    if reply and context.message_id:
        message = f"[CQ:reply,id={context.message_id}]" + message
    params = {
        "message": message,
        # go-cqhttp workaround
        # "auto_escape": "<function+true+at+0x00000182364DFDC0>" if auto_escape else False
        "auto_escape": True if auto_escape else False
    }
    if context.group_id:
        params["message_type"] = "group"
        params["group_id"] = context.group_id
    else:
        params["message_type"] = "private"
        params["user_id"] = context.user_id
    logger.debug("params: %s", params)
    r = requests.post(endpoint, json=params)
    logger.debug("response: %s", r.json())
    return r.json()

def send_group_forward_msg(context: MessageContext, messages: List[str] = ["rua"]):
    endpoint = f"{CQHTTP_ENDPOINT}/send_group_forward_msg"
    # construct nodes
    message_nodes = list({"type":"node","data":{"name": "光光要杀我","uin": "114514","content": "\n".join(grouped_message).strip()}} for grouped_message in messages)
    params = {
        "messages": json.dumps(message_nodes),
    }
    if context.group_id:
        params["group_id"] = context.group_id
    else:
        return
    logger.debug("params: %s", params)
    r = requests.get(endpoint, params=params)
    logger.debug("response: %s", r.json())
    return r.json()

def get_group_info(context: MessageContext, group_id: int = 114514):
    endpoint = f"{CQHTTP_ENDPOINT}/get_group_info"
    params = {
        "group_id": group_id,
    }
    r = requests.get(endpoint, params=params)
    logger.debug("response: %s", r.json())
    return r.json()

def send_voice(context: MessageContext, message: str | Path = "子供たちに渡すプレゼントでお悩みですか？私と一緒に考えましょうか。ふふっ。", voice: str = 'https://cdnimg.gamekee.com/wiki2.0/images/w_0/h_0/829/223205/2022/11/14/450314.ogg', reply: bool = False, *args, **kwargs):
    '''wrapper'''
    if message:
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
    if message:
        send_msg(context, message, auto_escape=True)
    url_mode = isinstance(photo, str)
    if not url_mode:
        with open(photo, 'rb') as f:
            photo = f.read()
            import base64
            photo = base64.b64encode(photo).decode('utf-8')
            send_msg(context, f'[CQ:image,file=base64://{photo}]', auto_escape=True)
    else:
        send_msg(context, f'[CQ:image,file={photo}]', auto_escape=True)

def withdraw(context: MessageContext, target_id: str):
    endpoint = f"{CQHTTP_ENDPOINT}/delete_msg"
    params = {"message_id": int(target_id)}
    r = requests.post(endpoint, json=params)
    resp = r.json()
    if resp.get("status") != "ok":
        raise Exception(f"API Error: {resp}")
    return "撤回成功"

def pin(context: MessageContext, target_id: str):
    endpoint = f"{CQHTTP_ENDPOINT}/set_essence_msg"
    params = {"message_id": int(target_id)}
    r = requests.post(endpoint, json=params)
    resp = r.json()
    if resp.get("status") != "ok":
        raise Exception(f"API Error: {resp}")
    return "置顶精华成功"

def unpin(context: MessageContext, target_id: str):
    endpoint = f"{CQHTTP_ENDPOINT}/delete_essence_msg"
    params = {"message_id": int(target_id)}
    r = requests.post(endpoint, json=params)
    resp = r.json()
    if resp.get("status") != "ok":
        raise Exception(f"API Error: {resp}")
    return "取消置顶精华成功"
    