import matplotlib
import matplotlib.pyplot as plt
from io import BytesIO

matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'SimSun', 'Arial']
matplotlib.rcParams['axes.unicode_minus'] = False

# Try custom fontset mapping
matplotlib.rcParams['mathtext.fontset'] = 'custom'
matplotlib.rcParams['mathtext.rm'] = 'Microsoft YaHei'
matplotlib.rcParams['mathtext.it'] = 'Microsoft YaHei:italic'
matplotlib.rcParams['mathtext.bf'] = 'Microsoft YaHei:bold'

fig = plt.figure(figsize=(0.01, 0.01))
# Without \text{}, matplotlib mathtext will try to parse Chinese as symbols
math_expr = r"测试 E=mc^2 测试"
fig.text(0, 0, f'${math_expr}$', fontsize=14, usetex=False)

buf = BytesIO()
fig.savefig('test_math_chinese.png', format='png', dpi=200, transparent=True, bbox_inches='tight', pad_inches=0.0)
print("Saved to test_math_chinese.png")
