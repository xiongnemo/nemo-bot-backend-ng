# -*- coding: utf-8 -*-
from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin

md = MarkdownIt("commonmark").use(dollarmath_plugin, double_inline=True)
tokens = md.parse("This is $a$ and $$b$$\n\n$$c$$")
for t in tokens:
    print(t.type, repr(t.content) if not getattr(t, "children", None) else "")
    if getattr(t, "children", None):
        for c in t.children:
            print("  ", c.type, repr(c.content))
