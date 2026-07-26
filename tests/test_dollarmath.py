import unittest
from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin


class TestDollarMath(unittest.TestCase):
    def test_dollarmath_parsing(self):
        md = MarkdownIt("commonmark").use(dollarmath_plugin, double_inline=True)
        tokens = md.parse("This is $a$ and $$b$$\n\n$$c$$")
        types = [t.type for t in tokens]
        self.assertIn("paragraph_open", types)
        self.assertIn("math_block", types)


if __name__ == "__main__":
    unittest.main()
