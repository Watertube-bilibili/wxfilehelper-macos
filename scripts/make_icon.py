"""Original geometric transfer icon; no Tencent trademarks."""
from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).resolve().parents[1]
destination = root / "build"
destination.mkdir(exist_ok=True)
image = Image.new("RGBA", (256, 256))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((0, 0, 255, 255), radius=54, fill="#0067c0")
for line in (((64, 94), (192, 94)), ((158, 61), (192, 94), (158, 128)),
             ((192, 166), (64, 166)), ((97, 133), (64, 166), (97, 200))):
    draw.line(line, fill="white", width=14, joint="curve")
image.save(destination / "app.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
image.save(destination / "app.png")
