from classes.message import Message

from utilities import generic_exception_handler

import argparse

_command = ["demo"]
_name = "いい子に贈るプレゼント、何がいいでしょう？"
_man = """メリークリスマス！救護騎士団のセリナです！特別なクリスマスにしましょうね！
用法: {0}
"""


def get_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="nemo_fake", description="", exit_on_error=False
    )
    parser.add_argument("-q", "--query", type=str, default="", help="query")
    parser.add_argument("-c", "--count", type=int, default=5, help="count")
    return parser.parse_args(argv)


def workload(args: argparse.Namespace) -> str:
    pass


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    args = get_args(message.request.args.split())
    message.reply(workload(args))
