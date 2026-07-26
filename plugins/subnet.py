"""
Subnet Calculator Plugin
------------------------
Calculates the start and end addresses of an IPv4 CIDR subnet.
"""

import logging
import struct
import socket

from core.message import Message
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

_name = "子网计算器"
_command = ["subnet", "cidr"]
_man = """CIDR 子网计算器。
用法: {0} <IP/CIDR>
例子: {0} 192.168.1.0/24
例子: {0} 10.0.0.0/8"""
_tool_description = """IPv4 CIDR 子网计算器。输入一个 CIDR 表示法的网段（如 192.168.1.0/24），返回该子网的起始地址、结束地址、子网掩码和可用主机数。"""
_enabled = 1


def _int_to_ip(i: int) -> str:
    """Convert a 32-bit integer to dotted-quad IPv4 string."""
    return socket.inet_ntoa(struct.pack(">I", i))


def calculate_subnet(cidr_str: str) -> str:
    """Calculate subnet details from a CIDR string."""
    cidr_str = cidr_str.strip()
    if "/" not in cidr_str:
        return "400: nemo: 请使用 CIDR 格式，如 192.168.1.0/24"

    ip_str, prefix_str = cidr_str.split("/", 1)
    try:
        prefix = int(prefix_str)
    except ValueError:
        return f"400: nemo: 无效的前缀长度: {prefix_str}"

    if not (0 <= prefix <= 32):
        return f"400: nemo: 前缀长度必须在 0-32 之间，收到: {prefix}"

    try:
        ip_int = struct.unpack(">I", socket.inet_aton(ip_str))[0]
    except OSError:
        return f"400: nemo: 无效的 IPv4 地址: {ip_str}"

    host_bits = 32 - prefix
    network = (ip_int >> host_bits) << host_bits
    broadcast = network | ((1 << host_bits) - 1)
    mask = ((1 << 32) - 1) ^ ((1 << host_bits) - 1)
    usable_hosts = max(0, (1 << host_bits) - 2) if prefix < 31 else (2 if prefix == 31 else 1)

    return f"""📡 子网计算结果: {cidr_str}
网络地址:   {_int_to_ip(network)}
广播地址:   {_int_to_ip(broadcast)}
子网掩码:   {_int_to_ip(mask)}
地址范围:   {_int_to_ip(network)} - {_int_to_ip(broadcast)}
可用主机数: {usable_hosts}"""


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    args = message.request.args.strip()
    if not args:
        message.reply("400: nemo: 未提供 CIDR 地址——请参照 manual page 以了解用法。")
        return
    result = calculate_subnet(args)
    message.reply(result)
