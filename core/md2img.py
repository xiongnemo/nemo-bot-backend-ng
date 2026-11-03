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


EMOJI_CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "emoji_cache")

def get_emoji_image(emoji_str: str, target_size: int):
    """
    Fetch and return a PIL Image for an emoji (specifically ZWJ / composite emojis).
    Caches downloaded emojis locally in data/emoji_cache/.
    """
    if not emoji_str:
        return None
    try:
        os.makedirs(EMOJI_CACHE_DIR, exist_ok=True)
        hex_full = '-'.join(f'{ord(c):x}' for c in emoji_str)
        hex_no_vs = '-'.join(f'{ord(c):x}' for c in emoji_str if c != '\ufe0f')
        
        path_full = os.path.join(EMOJI_CACHE_DIR, f"{hex_full}.png")
        path_no_vs = os.path.join(EMOJI_CACHE_DIR, f"{hex_no_vs}.png")
        
        img_path = None
        if os.path.exists(path_full):
            img_path = path_full
        elif os.path.exists(path_no_vs):
            img_path = path_no_vs
        else:
            import httpx
            urls = [
                f"https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/{hex_full}.png",
                f"https://cdn.jsdelivr.net/gh/twitter/twemoji@14.0.2/assets/72x72/{hex_no_vs}.png",
                f"https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/{hex_full}.png",
                f"https://cdnjs.cloudflare.com/ajax/libs/twemoji/14.0.2/72x72/{hex_no_vs}.png"
            ]
            for u in urls:
                try:
                    resp = httpx.get(u, timeout=2.0)
                    if resp.status_code == 200:
                        chosen_path = path_full if u.endswith(f"{hex_full}.png") else path_no_vs
                        with open(chosen_path, "wb") as f:
                            f.write(resp.content)
                        img_path = chosen_path
                        break
                except Exception:
                    continue
                    
        if img_path and os.path.exists(img_path):
            img = Image.open(img_path).convert("RGBA")
            return img.resize((target_size, target_size), Image.LANCZOS)
    except Exception as e:
        logger.debug(f"Failed to resolve emoji image for {emoji_str!r}: {e}")
    return None

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

        try:
            import emoji
            has_emoji = True
        except ImportError:
            emoji = None
            has_emoji = False

        def split_text_and_emojis(text_content):
            """
            Split text cleanly into alternating (substring, is_emoji) tuples.
            Uses emoji.emoji_list() to accurately match full Unicode graphemes
            (including multi-codepoint sequences, skin tones, etc.), while preserving
            full sequences so composite emojis can be rendered as images, and stripping
            stray variation selector \ufe0f and zero-width joiner \u200d from normal text
            that cause missing-glyph tofu boxes (\u25af) in FreeType / Pillow on Windows.
            """
            parts = []
            if has_emoji:
                matches = emoji.emoji_list(text_content)
                last_idx = 0
                for m in matches:
                    start, end = m['match_start'], m['match_end']
                    if start > last_idx:
                        clean_text = text_content[last_idx:start].replace('\ufe0f', '').replace('\u200d', '').replace('➔', '→')
                        if clean_text:
                            parts.append((clean_text, False))
                    e_str = m['emoji']
                    if e_str:
                        parts.append((e_str, True))
                    last_idx = end
                if last_idx < len(text_content):
                    clean_text = text_content[last_idx:].replace('\ufe0f', '').replace('\u200d', '').replace('➔', '→')
                    if clean_text:
                        parts.append((clean_text, False))
            else:
                parts.append((text_content.replace('\ufe0f', '').replace('\u200d', '').replace('➔', '→'), False))
            return parts

        def process_text_segment(text_content, font):
            nonlocal cursor_x, cursor_y
            
            parts = split_text_and_emojis(text_content)
            current_font_size = int(self.font_size * font_size_multiplier)
            emoji_target_size = int(current_font_size * 1.05)
                
            for part, is_emoji in parts:
                if not part: continue
                
                if is_emoji:
                    # Check if this is a composite emoji (ZWJ sequence or multi-codepoint)
                    is_composite = ('\u200d' in part) or (len([c for c in part if c != '\ufe0f']) > 1)
                    emoji_img = None
                    if is_composite:
                        emoji_img = get_emoji_image(part, emoji_target_size)
                    
                    if emoji_img:
                        if cursor_x + emoji_img.width > self.max_width - self.padding:
                            commit_newline()
                        y_offset = int(current_font_size * 0.15)
                        draw_ops.append(("image", (cursor_x, cursor_y + y_offset, emoji_img)))
                        cursor_x += emoji_img.width + 2
                    else:
                        current_font = get_emoji_font()
                        clean_e = part.replace('\ufe0f', '').replace('\u200d', '')
                        if not clean_e: continue
                        if cursor_x + current_font.getlength(clean_e) > self.max_width - self.padding:
                            commit_newline()
                        draw_ops.append(("text", (cursor_x, cursor_y, clean_e, current_font)))
                        cursor_x += current_font.getlength(clean_e)
                else:
                    buffer = ""
                    for char in part:
                        next_len = font.getlength(buffer + char)
                        if cursor_x + next_len > self.max_width - self.padding:
                            if buffer:
                                draw_ops.append(("text", (cursor_x, cursor_y, buffer, font)))
                            commit_newline()
                            buffer = char
                        else:
                            buffer += char
                    if buffer:
                        draw_ops.append(("text", (cursor_x, cursor_y, buffer, font)))
                        cursor_x += font.getlength(buffer)
                
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
                
                parts = split_text_and_emojis(text)
                cell_font_size = int(self.font_size * font_size_multiplier)
                emoji_target_size = int(cell_font_size * 1.05)
                    
                for part, is_emoji in parts:
                    if not part: continue
                    
                    if is_emoji:
                        is_composite = ('\u200d' in part) or (len([c for c in part if c != '\ufe0f']) > 1)
                        emoji_img = None
                        if is_composite:
                            emoji_img = get_emoji_image(part, emoji_target_size)
                            
                        if emoji_img:
                            w = emoji_img.width + 2
                            if cx + w > max_w and current_line:
                                lines.append(current_line)
                                current_line = []
                                cx = 0
                            current_line.append((cx, emoji_img, "image"))
                            cx += w
                        else:
                            current_font = get_emoji_font()
                            clean_e = part.replace('\ufe0f', '').replace('\u200d', '')
                            if not clean_e: continue
                            w = current_font.getlength(clean_e)
                            if cx + w > max_w and current_line:
                                lines.append(current_line)
                                current_line = []
                                cx = 0
                            current_line.append((cx, clean_e, "text", current_font))
                            cx += w
                    else:
                        buffer = ""
                        for char in part:
                            next_len = font.getlength(buffer + char)
                            if cx + next_len > max_w:
                                if buffer:
                                    current_line.append((cx, buffer, "text", font))
                                if current_line:
                                    lines.append(current_line)
                                current_line = []
                                cx = 0
                                buffer = char
                            else:
                                buffer += char
                        if buffer:
                            current_line.append((cx, buffer, "text", font))
                            cx += font.getlength(buffer)
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
                    # Draw cell text and inline emoji images
                    for l_idx, line in enumerate(lines):
                        y_pos = cursor_y + cell_padding/2 + l_idx * self.line_height
                        for item in line:
                            if len(item) == 3 and item[2] == "image":
                                ox, img_val, _ = item
                                draw_ops.append(("image", (cx + cell_padding + ox, y_pos + int(self.font_size * 0.15), img_val)))
                            else:
                                ox = item[0]
                                content = item[1]
                                current_font = item[3] if len(item) >= 4 else item[2]
                                draw_ops.append(("text", (cx + cell_padding + ox, y_pos, content, current_font)))
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
