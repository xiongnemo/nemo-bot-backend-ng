import logging
logger = logging.getLogger(__name__)

import json
from typing import List
import requests

from pathlib import Path
from config import backend_config
from classes.message_context import MessageContext
import os
from html import escape

SATORI_HTTP_ENDPOINT = backend_config["message_backend"]["satori_http"]["endpoint"]


def send_msg(context: MessageContext, message: str | list = "Hello from nemo-bot-ng-backend", auto_escape: bool = False, reply: bool = False):
    '''
    https://satori.js.org/zh-CN/resources/message.html
    '''
    endpoint = f"{SATORI_HTTP_ENDPOINT}/message.create"
    if isinstance(message, str):
        content = message
    else:
        if isinstance(message, dict):
            message = [message]
        # construct nodes
        content = ''
        for segement in message:
            if segement["type"] == "text":
                content += escape(escape(segement["data"]["text"], quote=True))
                continue
            if segement["type"] == "image":
                content += f'<img src="{segement['data']['file']}"/>'
                continue
            if segement["type"] == "record":
                content += f'<audio src="{segement['data']['file']}"/>'
                continue
    # if reply:
    #         message.insert(0, {
    #             "type": "reply",
    #             "data": {
    #                 "id": context.message_id
    #             }
    #         }
    #     )
    params = {
        "content": content,
    }
    if context.group_id:
        params["channel_id"] = context.group_id
    else:
        params["channel_id"] = f'private:{context.user_id}'
    logger.debug("params: %s", params)
    r = requests.post(endpoint, json=params, headers={"Content-Type": "application/json", "Authorization": f"Bearer {backend_config['message_backend']['satori_http']['token']}"})
    logger.debug("response: %s", r.json())
    # if r.json()['status'] != 'ok':
    #     params['message'] = [
    #         {
    #             "type": "reply",
    #             "data": {
    #                 "id": context.message_id
    #             }
    #         },
    #         {
    #         "type": "text",
    #         "data": {
    #             "text": f'502: nemo: 发送的时候爆了 ({r.json()['message']})'
    #         }
    #     }
    #     ]
    #     requests.post(endpoint, json=params)
    return r.json()


def send_group_forward_msg(context: MessageContext, messages: List[str | list] = ["rua"]):
    endpoint = f"{SATORI_HTTP_ENDPOINT}/send_group_forward_msg"
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
    logger.debug("params: %s", params)
    r = requests.post(endpoint, json=params)
    logger.debug("response: %s", r.json())
    return r.json()


def get_group_info(context: MessageContext, group_id: int = 114514):
    endpoint = f"{SATORI_HTTP_ENDPOINT}/get_group_info"
    params = {
        "group_id": group_id,
    }
    r = requests.get(endpoint, params=params)
    logger.debug("response: %s", r.json())
    return r.json()


def send_voice(context: MessageContext, message: str | Path = "子供たちに渡すプレゼントでお悩みですか？私と一緒に考えましょうか。ふふっ。", voice: str = 'https://cdnimg.gamekee.com/wiki2.0/images/w_0/h_0/829/223205/2022/11/14/450314.ogg', reply: bool = False, *args, **kwargs):
    '''wrapper'''
    if message:
        send_msg(context, {
            "type": "text",
            "data": {
                "text": message
            }
        })

    url_mode = isinstance(voice, str)
    if not url_mode:
        voice = 'file://' + os.getcwd() + '/' + voice.as_posix()
    # else:
    #     r = requests.get(voice)
    #     voice = r.content
    # import base64
    # voice = base64.b64encode(voice).decode('utf-8')
    send_msg(context, {
        "type": "record",
        "data": {
            "file": voice
        }
    })


def send_photo(context: MessageContext, message: str = "", photo: str = '', reply: bool = False, *args, **kwargs):
    '''wrapper'''
    messages = []
    if message:
        messages.append({
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
            messages.append({
                "type": "image",
                "data": {
                    "file": f"data:image/png;base64, {photo_b}"
                }
            })
    else:
        messages.append({
            "type": "image",
            "data": {
                "file": photo
            }
        })
    send_msg(context, messages, reply=reply)
