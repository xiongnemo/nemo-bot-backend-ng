"""
NSLookup Plugin
---------------
DNS query tool that compares results from Cloudflare (1.1.1.1) and AliDNS (223.5.5.5),
highlighting discrepancies that may indicate DNS pollution.
"""

import logging
import argparse

import dns.message
import dns.query
import dns.rdatatype

from core.message import Message
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

_name = "DNS 查询"
_command = ["nslookup"]
_man = """nslookup 实用程序。
用法: {0} <域名> [-t <记录类型>]
例子: {0} baidu.com
例子: {0} google.com -t AAAA
支持的记录类型: A, AAAA, CNAME, MX, NS, TXT, SOA, SRV, PTR 等"""
_tool_description = """DNS 查询工具，类似 nslookup。同时向境外 DNS (Cloudflare 1.1.1.1) 和境内 DNS (AliDNS 223.5.5.5) 发起查询并对比结果。
如果两边结果不同，会分别展示，便于检测 DNS 污染。支持 -t 参数指定记录类型（默认 A 记录）。
示例: "nslookup google.com" 或 "nslookup example.com -t AAAA"。"""
_enabled = 1


def _parse_args(argv: list[str]):
    """Parse nslookup arguments."""
    parser = argparse.ArgumentParser(
        prog="nslookup", description="DNS Query", exit_on_error=False
    )
    parser.add_argument("query", help="Domain name to look up")
    parser.add_argument("-t", "--type", type=str, default="A", help="DNS record type")
    return parser.parse_args(argv)


def do_dns_query(query: str, rdtype_str: str = "A") -> str:
    """Query DNS from both Cloudflare and AliDNS, compare results."""
    real_rdatatype = dns.rdatatype.from_text(rdtype_str)

    # Query Cloudflare (1.1.1.1) via DoH
    q = dns.message.make_query(query, real_rdatatype)
    r_cf = dns.query.https(q, "1.1.1.1")
    results_cf = [str(answer) for answer in r_cf.answer]

    # Query AliDNS (223.5.5.5) via DoH
    q = dns.message.make_query(query, real_rdatatype)
    r_ali = dns.query.https(q, "223.5.5.5")
    results_ali = [str(answer) for answer in r_ali.answer]

    # Compare and format output
    if r_cf.answer == r_ali.answer:
        # Results match — show once
        combined = "\n".join(results_cf)
        if not combined.strip():
            return f"404: nemo: 使用记录类型 {rdtype_str} 查询 {query} 没有返回任何结果"
        return combined
    else:
        # Results differ — show both (possible DNS pollution)
        cf_str = "\n".join(results_cf) if results_cf else "(无结果)"
        ali_str = "\n".join(results_ali) if results_ali else "(无结果)"
        return f"⚠️ 境内外 DNS 结果不一致:\n\n1.1.1.1 (Cloudflare):\n{cf_str}\n\n223.5.5.5 (AliDNS):\n{ali_str}"


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    args = message.request.args.strip()
    if not args:
        message.reply("400: nemo: 未提供域名——请参照 manual page 以了解用法。")
        return

    parsed = _parse_args(args.split())
    result = do_dns_query(parsed.query, parsed.type)
    message.reply(result)
