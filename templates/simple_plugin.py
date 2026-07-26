from classes.message import Message
from utilities import generic_exception_handler

import traceback

# _allowed_groups = ['485541033'] # uncomment to set allowed groups, superusers will always be allowed
# _allowed_users = ['1234567890'] # uncomment to set allowed users, superusers will always be allowed
# _disallowed_users = ['1234567890'] # uncomment to set disallowed users, superusers will always be allowed
# _disallowed_groups = ['485541033'] # uncomment to set disallowed groups, superusers will always be allowed

_command = ["demo"]
_name = "いい子に贈るプレゼント、何がいいでしょう？"
_man = """メリークリスマス！救護騎士団のセリナです！特別なクリスマスにしましょうね！
用法: {0}
"""


def workload(args: str) -> str:
    pass


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    args = message.request.args.strip()
    # IF NEED ARGS
    if args == "":
        message.reply("未提供参数———请参照 manual page 以了解用法。")
        return
    result = workload(args)
    message.reply(result)
