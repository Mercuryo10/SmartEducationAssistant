"""生成作业批改样例图（阶段三验收用）：打印体中文作业照片。

用法：python scripts/demo_data/make_homework_demo.py
输出：scripts/demo_data/homework_demo.jpg

样例作业共 4 题：Q1 选择（对）、Q2 判断（错）、Q3 填空（对）、Q4 主观（AI 评分），
参考答案见 README 或脚本末尾注释，供验收对照。
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# 作业内容（OCR 目标文本）
CONTENT = """《大模型导论》单元测验

1. Transformer 中，自注意力机制的三个核心矩阵是？（  ）
A. Q/K/V
B. Q/R/S
C. W/X/Y
D. A/B/C
答：B

2. Softmax 注意力权重需要归一化。（对/错）
答：错

3. Transformer 中，Positional Encoding 用于向序列注入位置___。
答：信息

4. 请简述 RAG 为什么能缓解大模型幻觉。
答：RAG 通过检索相关证据片段约束生成，降低了对参数化记忆的依赖，从而减少了模型编造事实的可能。
"""

# 配套参考答案（验收时作为 answer_key 传入）
ANSWER_KEY = """1: B
2: 对
3: 信息
4: RAG 通过检索相关证据片段约束生成，降低了对参数化记忆的依赖，从而减少了模型编造事实的可能。
"""

_FONT_CANDIDATES = [
    "C:/Windows/Fonts/msyh.ttc",   # 微软雅黑
    "C:/Windows/Fonts/simhei.ttf", # 黑体
    "C:/Windows/Fonts/simsun.ttc", # 宋体
]


def _find_font(size: int) -> ImageFont.FreeTypeFont:
    """查找系统中文字体。"""
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    raise FileNotFoundError("未找到中文字体，请指定可用字体路径")


def _wrap(draw: ImageDraw.ImageDraw, font: ImageFont.FreeTypeFont, text: str, max_width: int) -> list[str]:
    """按像素宽度对文本逐字换行。"""
    result: list[str] = []
    for para in text.splitlines():
        if not para:
            result.append("")
            continue
        cur = ""
        for ch in para:
            if cur and draw.textlength(cur + ch, font=font) > max_width:
                result.append(cur)
                cur = ch
            else:
                cur += ch
        result.append(cur)
    return result


def main() -> None:
    """生成样例图并打印配套参考答案。"""
    out = Path(__file__).resolve().parent / "homework_demo.jpg"
    font_size = 26
    line_h = int(font_size * 1.7)
    pad = 40
    width = 880
    draw_probe = ImageDraw.Draw(Image.new("RGB", (10, 10), "white"))
    font = _find_font(font_size)
    lines = _wrap(draw_probe, font, CONTENT, width - 2 * pad)

    height = pad * 2 + line_h * len(lines) + 40
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    y = pad
    for ln in lines:
        if ln:
            draw.text((pad, y), ln, fill="black", font=font)
        y += line_h
    img.save(out)
    print(f"样例图已生成：{out}（{img.size[0]}x{img.size[1]}）")
    print("配套参考答案（answer_key）：")
    print(ANSWER_KEY)


if __name__ == "__main__":
    main()
