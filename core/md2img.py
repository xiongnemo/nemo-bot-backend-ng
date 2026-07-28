import os
import re
import uuid
from io import BytesIO
import logging

try:
    from PIL import Image, ImageDraw, ImageFont
    import matplotlib
    import matplotlib.pyplot as plt
    from markdown_it import MarkdownIt
    from mdit_py_plugins.dollarmath import dollarmath_plugin
except ImportError:
    pass # Will be handled if not installed

logger = logging.getLogger(__name__)

# matplotlib backend for headless
try:
    matplotlib.use('Agg')
    matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'PingFang SC', 'WenQuanYi Micro Hei', 'sans-serif']
    matplotlib.rcParams['axes.unicode_minus'] = False
    matplotlib.rcParams['mathtext.fontset'] = 'custom'
    matplotlib.rcParams['mathtext.rm'] = 'Microsoft YaHei'
    matplotlib.rcParams['mathtext.it'] = 'Microsoft YaHei:italic'
    matplotlib.rcParams['mathtext.bf'] = 'Microsoft YaHei:bold'
except Exception:
    pass

def get_default_font(is_bold=False):
    # Try finding common Chinese fonts in Windows
    font_paths = []
    if is_bold:
        font_paths = ["C:\\Windows\\Fonts\\msyhbd.ttc", "C:\\Windows\\Fonts\\simhei.ttf"]
    else:
        font_paths = ["C:\\Windows\\Fonts\\msyh.ttc", "C:\\Windows\\Fonts\\simsun.ttc"]
    
    for p in font_paths:
        if os.path.exists(p):
            return p
    # Fallback to default if not found
    return "arial.ttf"

def render_latex_to_image(math_expr: str, fontsize=14, dpi=200):
    """Renders a LaTeX math expression to a PIL Image using matplotlib."""
    fig = plt.figure(figsize=(0.01, 0.01))
    fig.text(0, 0, f'${math_expr}$', fontsize=fontsize, usetex=False)
    
    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=dpi, transparent=True, bbox_inches='tight', pad_inches=0.0)
    plt.close(fig)
    
    buf.seek(0)
    img = Image.open(buf).convert("RGBA")
    return img

def get_mono_font():
    font_paths = ["C:\\Windows\\Fonts\\simhei.ttf", "C:\\Windows\\Fonts\\msyh.ttc", "C:\\Windows\\Fonts\\consola.ttf"]
    for p in font_paths:
        if os.path.exists(p):
            return p
    return "arial.ttf"

class MarkdownRenderer:
    def __init__(self, max_width=800, padding=40, font_size=20, line_height=1.5):
        self.max_width = max_width
        self.padding = padding
        self.font_size = font_size
        self.line_height = int(font_size * line_height)
        
        self.md = MarkdownIt().enable('table').use(dollarmath_plugin, double_inline=True)
        
    def render(self, text: str) -> Image.Image:
        tokens = self.md.parse(text)
        
        # Pass 1: Measure height and layout
        draw_ops = []
        
        # State variables
        indent_level = 0
        indent_step = 25
        list_counters = []
        in_blockquote = False
        blockquote_start_y = 0
        font_size_multiplier = 1.0
        is_bold = False
        is_italic = False
        
        def get_current_font(mono=False):
            size = int(self.font_size * font_size_multiplier)
            if mono:
                return ImageFont.truetype(get_mono_font(), size)
            elif is_bold:
                return ImageFont.truetype(get_default_font(True), size)
            else:
                return ImageFont.truetype(get_default_font(False), size)

        cursor_x = self.padding
        cursor_y = self.padding
        
        def commit_newline(extra_spacing=0):
            nonlocal cursor_x, cursor_y
            cursor_x = self.padding + indent_level * indent_step
            cursor_y += int(self.line_height * font_size_multiplier) + extra_spacing
            
        def get_emoji_font():
            try:
                size = int(self.font_size * font_size_multiplier)
                return ImageFont.truetype("seguiemj.ttf", size)
            except:
                return get_current_font()

        import emoji

        def process_text_segment(text_content, font):
            nonlocal cursor_x, cursor_y
            
            # Split text into a list of single characters and contiguous emoji characters
            parts = []
            buffer = ""
            for char in text_content:
                if emoji.is_emoji(char):
                    if buffer:
                        parts.append(buffer)
                        buffer = ""
                    parts.append(char)
                else:
                    buffer += char
            if buffer:
                parts.append(buffer)
                
            for part in parts:
                if not part: continue
                is_emoji = emoji.is_emoji(part)
                current_font = get_emoji_font() if is_emoji else font
                
                if is_emoji:
                    if cursor_x + current_font.getlength(part) > self.max_width - self.padding:
                        commit_newline()
                    draw_ops.append(("text", (cursor_x, cursor_y, part, current_font)))
                    cursor_x += current_font.getlength(part)
                else:
                    buffer = ""
                    for char in part:
                        next_len = current_font.getlength(buffer + char)
                        if cursor_x + next_len > self.max_width - self.padding:
                            if buffer:
                                draw_ops.append(("text", (cursor_x, cursor_y, buffer, current_font)))
                            commit_newline()
                            buffer = char
                        else:
                            buffer += char
                    if buffer:
                        draw_ops.append(("text", (cursor_x, cursor_y, buffer, current_font)))
                        cursor_x += current_font.getlength(buffer)
                
        def process_math(expr, is_block=False):
            nonlocal cursor_x, cursor_y
            expr = expr.strip()
            
            if is_block:
                commit_newline()
                
            try:
                img = render_latex_to_image(expr)
            except Exception as e:
                logger.warning(f"Failed to render math '{expr}': {e}. Falling back to plain text.")
                font = get_current_font()
                process_text_segment(f"${expr}$" if not is_block else f"$${expr}$$", font)
                return
            
            # Scale down the high-DPI matplotlib image to match the text size
            # Matplotlib renders 14pt at 200dpi (approx 39px height for normal text). 
            # Our font size is 20px. So 20 / 39 = ~0.5 scale ratio.
            base_scale = 0.5
            scale_ratio = base_scale * (1.3 if is_block else 1.0)
            img = img.resize((int(img.width * scale_ratio), int(img.height * scale_ratio)), Image.LANCZOS)
            
            if img.width > self.max_width - 2 * self.padding:
                ratio = (self.max_width - 2 * self.padding) / img.width
                img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
                
            if cursor_x + img.width > self.max_width - self.padding and not is_block:
                commit_newline()
                
            # offset down by ~15% of font size to align with Chinese font visual baseline
            y_offset = int(self.font_size * 0.15) if not is_block else 0
            
            draw_ops.append(("image", (cursor_x, cursor_y - (img.height // 2 - self.font_size // 2) + y_offset, img)))
            
            if is_block:
                cursor_y += img.height + self.padding // 2
                commit_newline()
            else:
                cursor_x += img.width + 5

        # Traverse AST
        skip_until = -1
        
        def render_table(table_tokens):
            nonlocal cursor_x, cursor_y
            commit_newline(10)
            rows = []
            current_row = []
            for t in table_tokens:
                if t.type == 'tr_open':
                    current_row = []
                elif t.type == 'tr_close':
                    rows.append(current_row)
                elif t.type == 'inline':
                    # Extract text carefully to not miss elements
                    cell_text = ""
                    for child in t.children:
                        if child.type == 'text':
                            cell_text += child.content
                        elif child.type == 'code_inline':
                            cell_text += child.content
                    current_row.append(cell_text)
                    
            if not rows: return
            cols = len(rows[0])
            raw_col_widths = [0] * cols
            font = get_current_font()
            cell_padding = 10
            
            # calculate raw widths
            for row in rows:
                for i, cell in enumerate(row):
                    if i < cols:
                        w = font.getlength(cell) + cell_padding * 2
                        if w > raw_col_widths[i]: raw_col_widths[i] = w
            
            # shrink columns if table exceeds max width
            max_table_width = self.max_width - (self.padding * 2) - (indent_level * indent_step)
            col_widths = raw_col_widths[:]
            if sum(col_widths) > max_table_width:
                # Distribute proportionally but with min width
                total_raw = max(sum(col_widths), 1)
                col_widths = [max(40, int(max_table_width * (w / total_raw))) for w in col_widths]
                # Adjust rounding errors
                while sum(col_widths) > max_table_width:
                    col_widths[col_widths.index(max(col_widths))] -= 1

            # helper to wrap text inside cell
            def wrap_cell_text(text, font, max_w):
                lines = []
                current_line = []
                cx = 0
                
                parts = []
                buffer = ""
                for char in text:
                    if emoji.is_emoji(char):
                        if buffer:
                            parts.append(buffer)
                            buffer = ""
                        parts.append(char)
                    else:
                        buffer += char
                if buffer:
                    parts.append(buffer)
                    
                for part in parts:
                    if not part: continue
                    is_emoji = emoji.is_emoji(part)
                    current_font = get_emoji_font() if is_emoji else font
                    
                    if is_emoji:
                        w = current_font.getlength(part)
                        if cx + w > max_w and current_line:
                            lines.append(current_line)
                            current_line = []
                            cx = 0
                        current_line.append((cx, part, current_font))
                        cx += w
                    else:
                        buffer = ""
                        for char in part:
                            next_len = current_font.getlength(buffer + char)
                            if cx + next_len > max_w:
                                if buffer:
                                    current_line.append((cx, buffer, current_font))
                                if current_line:
                                    lines.append(current_line)
                                current_line = []
                                cx = 0
                                buffer = char
                            else:
                                buffer += char
                        if buffer:
                            current_line.append((cx, buffer, current_font))
                            cx += current_font.getlength(buffer)
                if current_line:
                    lines.append(current_line)
                return lines if lines else [[]]

            # render table
            start_x = cursor_x
            for r_idx, row in enumerate(rows):
                cx = start_x
                row_cells_lines = []
                max_lines = 1
                for c_idx, cell in enumerate(row):
                    if c_idx >= cols: break
                    cw = col_widths[c_idx] - cell_padding * 2
                    lines = wrap_cell_text(cell, font, max(10, cw))
                    row_cells_lines.append(lines)
                    max_lines = max(max_lines, len(lines))
                    
                row_h = max_lines * self.line_height + cell_padding
                
                for c_idx, lines in enumerate(row_cells_lines):
                    cw = col_widths[c_idx]
                    # Draw cell borders
                    draw_ops.append(("rect", (cx, cursor_y, cx + cw, cursor_y + row_h, None, (200, 200, 200))))
                    # Draw cell text
                    for l_idx, line in enumerate(lines):
                        y_pos = cursor_y + cell_padding/2 + l_idx * self.line_height
                        for (ox, text, current_font) in line:
                            draw_ops.append(("text", (cx + cell_padding + ox, y_pos, text, current_font)))
                    cx += cw
                cursor_y += row_h
            commit_newline(10)

        for i, token in enumerate(tokens):
            if i <= skip_until:
                continue

            if token.type == 'table_open':
                for j in range(i, len(tokens)):
                    if tokens[j].type == 'table_close':
                        skip_until = j
                        break
                render_table(tokens[i:skip_until+1])
                continue
                
            if token.type == 'heading_open':
                level = int(token.tag[1:])
                font_size_multiplier = 2.2 - (level * 0.2)
                is_bold = True
                commit_newline(10)
            elif token.type == 'heading_close':
                commit_newline(10)
                font_size_multiplier = 1.0
                is_bold = False
                
            elif token.type == 'blockquote_open':
                in_blockquote = True
                indent_level += 1
                commit_newline(5)
                blockquote_start_y = cursor_y
            elif token.type == 'blockquote_close':
                # Draw vertical bar. Note: paragraph_close adds self.line_height * 2, so we subtract it from cursor_y.
                rect_end_y = cursor_y - self.line_height * 2 if cursor_y > blockquote_start_y else cursor_y
                draw_ops.append(("rect", (self.padding + (indent_level-1)*indent_step, blockquote_start_y, self.padding + (indent_level-1)*indent_step + 4, rect_end_y, (200, 200, 200), None)))
                indent_level -= 1
                in_blockquote = False
                commit_newline(5)
                
            elif token.type == 'bullet_list_open':
                indent_level += 1
            elif token.type == 'bullet_list_close':
                indent_level -= 1
                commit_newline(5)
                
            elif token.type == 'ordered_list_open':
                indent_level += 1
                list_counters.append(1)
            elif token.type == 'ordered_list_close':
                indent_level -= 1
                list_counters.pop()
                commit_newline(5)
                
            elif token.type == 'list_item_open':
                commit_newline()
                font = get_current_font()
                if list_counters:
                    prefix = f"{list_counters[-1]}. "
                    list_counters[-1] += 1
                else:
                    prefix = "• "
                # Draw list prefix negatively offset from indent
                draw_ops.append(("text", (cursor_x - font.getlength(prefix), cursor_y, prefix, font)))
                
            elif token.type == 'fence' or token.type == 'code_block':
                commit_newline(10)
                font = get_current_font(mono=True)
                code_lines = token.content.rstrip().split('\n')
                # bg rect
                rect_start_y = cursor_y - 5
                for line in code_lines:
                    draw_ops.append(("text", (cursor_x + 5, cursor_y, line, font)))
                    cursor_y += self.line_height
                draw_ops.append(("rect", (cursor_x, rect_start_y, self.max_width - self.padding, cursor_y + 5, (235, 235, 235), (200, 200, 200))))
                commit_newline(10)
                
            elif token.type == 'math_block':
                process_math(token.content, is_block=True)

            elif token.type == 'paragraph_open':
                pass
            elif token.type == 'paragraph_close':
                commit_newline()
                cursor_y += int(self.line_height * 0.4) # Add a smaller gap for paragraph spacing instead of a full newline
            elif token.type == 'inline':
                for child in token.children:
                    if child.type == 'text':
                        font = get_current_font()
                        process_text_segment(child.content, font)
                    elif child.type in ('math_inline', 'math_inline_double'):
                        process_math(child.content, is_block=False)
                    elif child.type == 'strong_open' or child.type == 'em_open':
                        is_bold = True
                    elif child.type == 'strong_close' or child.type == 'em_close':
                        is_bold = False
                    elif child.type == 'softbreak' or child.type == 'hardbreak':
                        commit_newline()
                        
        # Create final image
        total_height = cursor_y + self.padding
        canvas = Image.new("RGB", (self.max_width, total_height), (245, 246, 250)) # slightly off-white for better reading
        draw = ImageDraw.Draw(canvas)
        
        # Pass 1: Draw backgrounds (rectangles)
        for op_type, args in draw_ops:
            if op_type == "rect":
                x1, y1, x2, y2, fill, outline = args
                draw.rectangle((x1, y1, x2, y2), fill=fill, outline=outline)
                
        # Pass 2: Draw foreground (text and images)
        for op_type, args in draw_ops:
            if op_type == "text":
                x, y, text, font = args
                try:
                    draw.text((x, y), text, fill=(40, 44, 52), font=font, embedded_color=True)
                except:
                    draw.text((x, y), text, fill=(40, 44, 52), font=font)
            elif op_type == "image":
                x, y, img = args
                x, y = int(x), int(y)
                if y < 0: y = 0
                canvas.paste(img, (x, y), mask=img.split()[3])
                
        return canvas

def markdown_to_image(text: str) -> str:
    """
    Renders markdown text to a temporary local image file, and returns the file:/// URL.
    """
    renderer = MarkdownRenderer()
    img = renderer.render(text)
    
    temp_dir = os.path.join(os.getcwd(), "data", "temp_images")
    os.makedirs(temp_dir, exist_ok=True)
    save_path = os.path.join(temp_dir, f"md_{uuid.uuid4().hex[:8]}.png")
    
    img.save(save_path)
    return f"file:///{save_path.replace(os.sep, '/')}"
