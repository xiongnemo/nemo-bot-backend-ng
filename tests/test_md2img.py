import unittest
from io import BytesIO
from core.md2img import MarkdownRenderer, get_emoji_image


class TestMarkdownRenderer(unittest.TestCase):
    def test_render(self):
        md_text = r"""# 综合测试报告
## 1. 复杂 Emoji 渲染
这是一个复合 emoji：👨‍👩‍👧‍👦 🎯 ⚠️ 🐻‍❄️ ❤️ ➔ 测试。
中文在公式里： $\text{当前状态} E=mc^2 \text{测试}$

## 2. 表格与宽度测试表格
| 配置 | 详情 |
|---|---|
| 轮询频率 | **每 5 分钟** |
| 当前价格 | `$4,071.2` |
"""
        renderer = MarkdownRenderer()
        img = renderer.render(md_text)
        self.assertIsNotNone(img)
        self.assertGreater(img.width, 0)
        self.assertGreater(img.height, 0)
        
        buf = BytesIO()
        img.save(buf, format="PNG")
        self.assertGreater(len(buf.getvalue()), 0)

    def test_composite_emoji(self):
        # Test polar bear ZWJ composite emoji resolution
        img = get_emoji_image("🐻‍❄️", 22)
        self.assertIsNotNone(img)
        self.assertEqual(img.size, (22, 22))

        # Test rendering in markdown sentence
        renderer = MarkdownRenderer()
        img_out = renderer.render('结合 🐻‍❄️ 说的"有大把内幕"')
        self.assertIsNotNone(img_out)
        self.assertGreater(img_out.height, 0)


if __name__ == "__main__":
    unittest.main()
