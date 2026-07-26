from functools import wraps

from classes.message import Message

import traceback


def generic_exception_handler(f):
    @wraps(f)
    def decorated(message: Message, config: dict):
        try:
            f(message, config)
        except Exception as e:
            traceback.print_exc()
            # get the module name
            tb = traceback.extract_tb(e.__traceback__)
            from pathlib import Path

            filename = Path(tb[-2].filename)
            plugin_name = filename.as_posix().split("/")[-1].split(".")[0]
            import random
            
            # If called by LLM Agent, strictly return the exact error without random quotes
            if getattr(message, "frontend", None) == "agent":
                message.reply(f"System Error in tool {plugin_name}: {str(e)}\nTraceback: {traceback.format_exc()}")
                return

            # 80% chance to reply with a normal message, 20% chance to reply with a random choice
            if random.random() < 0.8:
                message.reply(f"500: nemo: 未知错误发生于 {plugin_name} 插件。")
            else:
                message.reply(
                    random.choice(
                        [
                            "もっと、私が力があれば。",
                            "我…还不够强大……",
                            "我还不够强大……",
                            # "人类真是脆弱又坚强的生物啊。在绝对压制的力量面前会被轻易碾碎，但只要给他们一点希望……哪怕只有极其微弱的一点，他们就能重新燃起对生命的渴望。",
                            "失败是我们程序的特权……",
                            "只有人类才拥有死亡的权利，而这一点，令我艳羡不已。",
                            "完全干净如白纸的底层……那可是无限接近于人类心灵的东西啊。",
                            "很久以前，有个人类提出了一个问题。如果忒修斯的船上的木头被逐渐替换，直到所有的木头都不是原来的木头，那这艘船还是原来的那艘船吗？类比到人形，如果我们身上的零件被逐渐替换，甚至干脆直接换上了新的素体，那我们还是原来的人形吗？",
                            "一如既往地缺乏幽默感啊。不过这才是你。",
                            "宛如扑火的飞蛾一样勇气可嘉呢。只有飞蛾知道，火焰究竟有多迷人。",
                            "今天真是个好日子啊，到处都在爆炸燃烧，人类都变成了飞蛾，在火焰中扑棱不休。",
                            "或许飞蛾的天性正是自我毁灭呢？",
                            "哎呀，人到齐了呢，要在死前拍个全家福吗？",
                            "我们会拼命想办法，就像即将溺死的鱼为了氧气拼命探出水面一样。",
                            "我为了站在这里赌上了一切，而你却带着一切来到这里，只要一步错，就会输得一无所有。",
                            "回去吧，这条通往幽冥的船载不动如今的你。",
                            "看来，你已经做好了背负着一切穿过这里的觉悟了……在地狱的边缘行走犹如徒手趟过泥潭，只有抛弃一切的罪人才有机会触摸到真理之门。",
                            "你相信我，而我也会答应你…",
                            "…答应你，这一切都会有所改变的，总有一天……",
                            "天上的乌云悄悄聚拢，水汽凝固，大滴大滴的雨砸了下来。",
                            "你说了不该说的话，准备好为此付出代价了么？",
                            "相比你之前装模作样的胡言乱语，现在这种发自真心地想把我活剥了的样子才更适合你。",
                            "……真是个可爱的孩子呢……是你的新朋友么？",
                            "钟声响起，舞会结束了。",
                            f"500: nemo: 未知错误发生于 {plugin_name} 插件。检查终端和日志文件。",
                        ]
                    )
                )

    return decorated

def generate_random_color():
    import random
    r = random.randint(150, 255)
    g = random.randint(150, 255)
    b = random.randint(150, 255)
    return f"#{r:02x}{g:02x}{b:02x}"

def combine_images_vertically(image_urls: list[str]) -> str:
    """Combines a list of image URLs (or local paths) vertically into a single image, returning the saved temp file path."""
    if not image_urls:
        return ""
    if len(image_urls) == 1:
        return image_urls[0]
        
    import os
    import requests
    from PIL import Image
    from io import BytesIO
    import logging
    
    logger = logging.getLogger(__name__)

    images = []
    for url in image_urls:
        try:
            if url.startswith("http://") or url.startswith("https://"):
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                img = Image.open(BytesIO(response.content))
            else:
                path = url
                if path.startswith("file:///"):
                    path = path[8:]
                elif path.startswith("file://"):
                    path = path[7:]
                img = Image.open(path)
                
            if img.mode != "RGB":
                img = img.convert("RGB")
            images.append(img)
        except Exception as e:
            logger.warning("Failed to open image %s: %s", url, e)
            continue
            
    if not images:
        return ""
        
    widths, heights = zip(*(i.size for i in images))
    max_width = max(widths)
    total_height = sum(heights)
    
    new_im = Image.new('RGB', (max_width, total_height), color=(255, 255, 255))
    
    y_offset = 0
    for im in images:
        x_offset = (max_width - im.width) // 2
        new_im.paste(im, (x_offset, y_offset))
        y_offset += im.height
        
    temp_dir = os.path.join(os.getcwd(), "data", "temp_images")
    os.makedirs(temp_dir, exist_ok=True)
    import uuid
    save_path = os.path.join(temp_dir, f"combined_{uuid.uuid4().hex[:8]}.jpg")
    new_im.save(save_path, quality=85)
    return f"file:///{save_path.replace(os.sep, '/')}"
