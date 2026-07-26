# -*- coding: utf-8 -*-
import sys
sys.path.append('.')
from core.md2img import MarkdownRenderer

md_text = r'''# 综合测试报告

## 1. 复杂 Emoji 渲染
这是一个复合 emoji：👨‍👩‍👧‍👦 🎯 测试。希望能一次性画出来。
还有这些 BMP emoji：📊 ➡️ ⚠️ ⚡
中文在公式里： $\text{当前状态} E=mc^2 \text{测试}$

## 2. 表格与宽度测试表格 (防吞噬测试)
| 配置 | 详情 |
|---|---|
| 轮询频率 | **每 5 分钟** |
| 突破目标 | 价格站稳 **EMA169 （$4,085~4,090** 上方 |
| 当前价格 | `$4,071.2`（距隧道上沿约 **~$15~20**） |
| 极端测试 | $4,104.5** | 24H +1.96% | 🔴 $4,016.7 ~ $4,111.9 |
| 当前状态 | 价格在 4h Vegas 隧道下方，正在向上试探。这一段文字非常长，目的是测试表格列宽自动换行逻辑，不能超过画布宽度！！ |

当前价格紧贴 EMA144，差一点点就摸到隧道了 🐻。一旦 4h 收盘站上 EMA169，立刻会提醒你 🐻

## 3. 数学公式 (行内与块级)
行内公式测试：质能方程是 $E=mc^2$，而且它的变体也可以写成 $ E = m c^2 $ 甚至是双层 $$E=mc^2$$ 吗？
块级公式测试：
$$
\int_0^\infty e^{-x^2} dx = \frac{\sqrt{\pi}}{2}
$$
'''

r = MarkdownRenderer()
try:
    img = r.render(md_text)
    img.save('test_md2img_final.png')
    print('SUCCESS: Image saved to test_md2img_final.png', img.size)
except Exception as e:
    import traceback
    print('ERROR:', e)
    traceback.print_exc()
