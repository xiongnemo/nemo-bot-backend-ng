"""
Encodings Plugin
----------------
Encodes/decodes text using various algorithms (base64, md5, sha, rot13, etc.)
with support for chained pipeline operations using the pipe operator.
"""

import logging
from hashlib import md5, sha1, sha256, sha512
from base64 import b64encode, b64decode, b32encode, b32decode, b16encode, b16decode

from core.message import Message
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

_name = "编码工具"
_command = ["编码", "encodings"]
_man = """编码: 将文本以指定编码或哈希处理方式转换为另一种文本，使用 -d 参数进行解码。同时，也可按顺序指定多个进行变换，使用管道操作符 | 连接。
用法: {0} [-d: 解码] （第一行）
[文本] （任意行数）
[编码] （最后一行）
如：{0}
你好
base64
如：{0} -d
5L2g5aW9
base64
如：{0}
你好
base64 | md5
"""
_tool_description = """文本编码/解码/哈希工具。支持的算法: base64, base32, base16, md5, sha1, sha256, sha512, rot13, binary(二进制ASCII), hex(十六进制ASCII)。
支持管道链式操作（用 | 连接多个算法依次处理）。用 -d 标志切换为解码模式。注意: md5/sha 等哈希算法不可逆，不支持解码。
示例: "encodings\n你好\nbase64" 会返回 base64 编码结果; "encodings\n你好\nbase64 | md5" 会先 base64 编码再取 md5。"""
_enabled = 1


# ======================================================================
# Codec Functions
# ======================================================================

def md5_encode(text: str) -> str:
    return md5(text.encode("utf-8")).hexdigest()

def sha1_encode(text: str) -> str:
    return sha1(text.encode("utf-8")).hexdigest()

def sha256_encode(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()

def sha512_encode(text: str) -> str:
    return sha512(text.encode("utf-8")).hexdigest()

def rot13_encode(text: str) -> str:
    import codecs
    return codecs.encode(text, "rot13")

def rot13_decode(text: str) -> str:
    return rot13_encode(text)  # ROT13 is self-inverse

def base64_encode(text: str) -> str:
    return b64encode(text.encode("utf-8")).decode("utf-8")

def base64_decode(text: str) -> str:
    return b64decode(text.encode("utf-8")).decode("utf-8")

def base32_encode(text: str) -> str:
    return b32encode(text.encode("utf-8")).decode("utf-8")

def base32_decode(text: str) -> str:
    return b32decode(text.encode("utf-8")).decode("utf-8")

def base16_encode(text: str) -> str:
    return b16encode(text.encode("utf-8")).decode("utf-8")

def base16_decode(text: str) -> str:
    return b16decode(text.encode("utf-8")).decode("utf-8")

def binary_encode(text: str) -> str:
    """将文本转换为二进制 ASCII 码"""
    return "".join(f"{ord(i):08b}" for i in text)

def binary_decode(text: str) -> str:
    """将二进制 ASCII 码转换为文本"""
    return "".join(chr(int(text[i : i + 8], 2)) for i in range(0, len(text), 8))

def hex_encode(text: str) -> str:
    """将文本转换为十六进制 ASCII 码"""
    return "".join(f"{ord(i):02x}" for i in text)

def hex_decode(text: str) -> str:
    """将十六进制 ASCII 码转换为文本"""
    return "".join(chr(int(text[i : i + 2], 16)) for i in range(0, len(text), 2))


# ======================================================================
# Core Logic
# ======================================================================

# Registry of all available codecs for safe lookup
_ENCODERS = {
    "base64": base64_encode, "base32": base32_encode, "base16": base16_encode,
    "md5": md5_encode, "sha1": sha1_encode, "sha256": sha256_encode, "sha512": sha512_encode,
    "rot13": rot13_encode, "binary": binary_encode, "hex": hex_encode,
}
_DECODERS = {
    "base64": base64_decode, "base32": base32_decode, "base16": base16_decode,
    "rot13": rot13_decode, "binary": binary_decode, "hex": hex_decode,
}
_HASH_ONLY = {"md5", "sha1", "sha256", "sha512"}


def workload(args: str) -> str:
    lines = args.splitlines()
    if not lines:
        return "400: nemo: 未提供参数"

    decode = False
    if lines[0].strip() == "-d":
        decode = True
        lines.pop(0)

    if len(lines) < 2:
        return "400: nemo: 至少需要两行：第一行为文本，最后一行为编码方式"

    # Everything except the last line is the input text
    target = "\n".join(lines[:-1])
    pipeline = lines[-1]

    for step in pipeline.split("|"):
        operation = step.strip().lower()
        if not operation:
            continue

        if decode:
            if operation in _HASH_ONLY:
                return f"400: nemo: {operation} 是单向哈希算法，不支持解码"
            func = _DECODERS.get(operation)
            if not func:
                return f"404: nemo: 解码器 \"{operation}\" 不存在。可用: {', '.join(_DECODERS.keys())}"
        else:
            func = _ENCODERS.get(operation)
            if not func:
                return f"404: nemo: 编码器 \"{operation}\" 不存在。可用: {', '.join(_ENCODERS.keys())}"

        target = func(target)

    return target


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    args = message.request.args.strip()
    if args == "":
        message.reply("400: nemo: 未提供参数——请参照 manual page 以了解用法。")
        return
    result = workload(args)
    message.reply(result)
