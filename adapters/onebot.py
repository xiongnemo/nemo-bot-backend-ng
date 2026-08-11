import logging
logger = logging.getLogger(__name__)

import json
from typing import List
import requests

from pathlib import Path
from config import backend_config
from classes.message_context import MessageContext

CQHTTP_ENDPOINT = backend_config["message_backend"]["onebot"]["endpoint"]

import re

def _parse_cq_to_segments(text: str) -> list:
    segments = []
    pattern = r'(\[CQ:[^\]]+\])'
    parts = re.split(pattern, text)
    for part in parts:
        if not part: continue
        if part.startswith('[CQ:') and part.endswith(']'):
            cq_parts = part[4:-1].split(',')
            data = {}
            for kv in cq_parts[1:]:
                if '=' in kv:
                    k, v = kv.split('=', 1)
                    data[k] = v.replace('&amp;', '&').replace('&#91;', '[').replace('&#93;', ']')
            segments.append({'type': cq_parts[0], 'data': data})
        else:
            part = part.replace('&amp;', '&').replace('&#91;', '[').replace('&#93;', ']')
            segments.append({'type': 'text', 'data': {'text': part}})
    return segments


def send_msg(context: MessageContext, message: str | list = "Hello from nemo-bot-ng-backend", auto_escape: bool = False, reply: bool = False):
    '''
    https://whitechi73.github.io/OpenShamrock/api/message.html#发送消息
    '''
    endpoint = f"{CQHTTP_ENDPOINT}/send_msg"
    if isinstance(message, str):
        if not auto_escape:
            message = _parse_cq_to_segments(message)
        else:
            message = [{
                "type": "text",
                "data": {
                    "text": message
                }
            }]
    if reply and context.message_id:
            message.insert(0, {
                "type": "reply",
                "data": {
                    "id": context.message_id
                }
            }
        )
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
    r = requests.post(endpoint, json=params)
    logger.debug("response: %s", r.json())
    if r.json().get('status') != 'ok':
        # Fallback: Render text to image if sending failed (likely QQ risk control)
        original_text = ""
        # The 'message' parameter here might have been modified to a list earlier in the function
        # Let's extract all text segments
        if isinstance(message, str):
            original_text = message
        elif isinstance(message, list):
            for item in message:
                if item.get("type") == "text":
                    original_text += item.get("data", {}).get("text", "") + "\n"
                    
        if original_text.strip():
            logger.warning(f"OneBot message failed (Risk control? {r.json().get('message')}). Falling back to image rendering.")
            try:
                from core.md2img import markdown_to_image
                img_url = markdown_to_image(original_text.strip())
                # call send_photo
                send_photo(context, message="", photo=img_url, reply=reply)
                return r.json()
            except Exception as e:
                logger.error(f"Failed to render fallback image: {e}")
        
        # If all else fails, send the standard 502 error
        params['message'] = [
            {
                "type": "reply",
                "data": {
                    "id": context.message_id
                }
            } if context.message_id else None,
            {
            "type": "text",
            "data": {
                "text": f"502: nemo: 发送的时候爆了 ({r.json().get('message')})"
            }
        }
        ]
        params['message'] = [m for m in params['message'] if m]
        requests.post(endpoint, json=params)
    return r.json()


def send_group_forward_msg(context: MessageContext, messages: List[str | list] = ["rua"]):
    endpoint = f"{CQHTTP_ENDPOINT}/send_group_forward_msg"
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
        send_msg(context, {
            "type": "text",
            "data": {
                "text": message
            }
        })

    url_mode = isinstance(voice, str)
    if not url_mode:
        with open(voice, 'rb') as f:
            voice = f.read()
    else:
        r = requests.get(voice)
        voice = r.content
    import base64
    voice = base64.b64encode(voice).decode('utf-8')
    send_msg(context, {
        "type": "record",
        "data": {
            "file": f"base64://{voice}"
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
            # if len(photo_b) > 200 * 1024:
            #     import cv2
            #     import numpy as np
            #     print('大')
            #     img = cv2.imdecode(np.fromstring(photo_b, np.uint8), cv2.IMREAD_COLOR)
            #     img = cv2.resize(img, (0, 0), fx=0.5, fy=0.5)
            #     encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 70]
            #     result, encimg = cv2.imencode('.jpg', img, encode_param)
            #     if not result:
            #         send_msg(context, "编码爆炸了", auto_escape=True)
            #         return
            #     photo_b = encimg.tobytes()
            import base64
            photo_b = base64.b64encode(photo_b).decode('utf-8')
            messages.append({
                "type": "image",
                "data": {
                    "file": f"base64://{photo_b}"
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
