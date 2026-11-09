"""生成应用图标 assets/icon.ico 与 assets/app.png."""
import os
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
os.makedirs(ASSETS, exist_ok=True)

SIZE = 1024
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)

# 渐变背景（圆角方形）
top = (60, 132, 246)
bottom = (26, 62, 168)
grad = Image.new("RGBA", (SIZE, SIZE))
for y in range(SIZE):
    ratio = y / (SIZE - 1)
    color = tuple(int(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3)) + (255,)
    ImageDraw.Draw(grad).line([(0, y), (SIZE, y)], fill=color)
mask = Image.new("L", (SIZE, SIZE), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, SIZE - 1, SIZE - 1], radius=int(SIZE * 0.235), fill=255)
img.paste(grad, (0, 0), mask)
draw = ImageDraw.Draw(img)

# 高光
gloss = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
gd = ImageDraw.Draw(gloss)
gd.ellipse([-SIZE * 0.25, -SIZE * 0.55, SIZE * 0.9, SIZE * 0.25], fill=(255, 255, 255, 26))
img = Image.alpha_composite(img, Image.composite(gloss, Image.new("RGBA", (SIZE, SIZE)), mask))
draw = ImageDraw.Draw(img)

# 放大镜
cx, cy, r = SIZE * 0.44, SIZE * 0.42, SIZE * 0.235
stroke = int(SIZE * 0.062)
draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(255, 255, 255, 250), width=stroke)
handle_start = (cx + r * 0.70, cy + r * 0.70)
handle_end = (SIZE * 0.80, SIZE * 0.815)
draw.line([handle_start, handle_end], fill=(255, 255, 255, 250), width=int(stroke * 1.25))
for point in (handle_start, handle_end):
    draw.ellipse([point[0] - stroke * 0.62, point[1] - stroke * 0.62,
                  point[0] + stroke * 0.62, point[1] + stroke * 0.62], fill=(255, 255, 255, 250))

# 镜片里的“应用网格”
grid_origin = (cx - r * 0.52, cy - r * 0.52)
cell = r * 0.44
gap = r * 0.11
for row in range(2):
    for col in range(2):
        x0 = grid_origin[0] + col * (cell + gap)
        y0 = grid_origin[1] + row * (cell + gap)
        alpha = 235 if (row + col) % 2 == 0 else 165
        draw.rounded_rectangle([x0, y0, x0 + cell, y0 + cell], radius=int(cell * 0.3),
                               fill=(255, 255, 255, alpha))

img.save(os.path.join(ASSETS, "app.png"))
sizes = [16, 24, 32, 48, 64, 128, 256]
img.save(os.path.join(ASSETS, "icon.ico"), sizes=[(s, s) for s in sizes])
print("saved", ASSETS)
