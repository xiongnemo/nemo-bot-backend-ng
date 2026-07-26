import unittest
from io import BytesIO
from core.md2img import MarkdownRenderer


class TestMarkdownRenderer(unittest.TestCase):
    def test_render(self):
        md_text = r"""# 综合测试报告
## 1. 复杂 Emoji 渲染
这是一个复合 emoji：👨‍👩‍👧‍👦 🎯 测试。
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


if __name__ == "__main__":
    unittest.main()
