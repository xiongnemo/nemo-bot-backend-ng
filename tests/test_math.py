import unittest
from io import BytesIO
import matplotlib
import matplotlib.pyplot as plt


class TestMathRendering(unittest.TestCase):
    def test_matplotlib_mathtext(self):
        matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'SimSun', 'Arial']
        matplotlib.rcParams['axes.unicode_minus'] = False
        matplotlib.rcParams['mathtext.fontset'] = 'custom'
        matplotlib.rcParams['mathtext.rm'] = 'Microsoft YaHei'
        matplotlib.rcParams['mathtext.it'] = 'Microsoft YaHei:italic'
        matplotlib.rcParams['mathtext.bf'] = 'Microsoft YaHei:bold'

        fig = plt.figure(figsize=(0.01, 0.01))
        math_expr = r"测试 E=mc^2 测试"
        fig.text(0, 0, f'${math_expr}$', fontsize=14, usetex=False)

        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=200, transparent=True, bbox_inches='tight', pad_inches=0.0)
        plt.close(fig)
        self.assertGreater(len(buf.getvalue()), 0)


if __name__ == "__main__":
    unittest.main()
