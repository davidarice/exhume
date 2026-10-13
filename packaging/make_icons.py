"""Draw the Exhume app icons from the site's favicon (the 32-unit SVG in webapp/static/index.html):
a rounded violet square with film sprockets and a play triangle.

Run once when the logo changes and commit the results in packaging/icons/:
    pip install pillow && python packaging/make_icons.py
"""
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "icons")
SUPER = 4                     # draw 4x larger, then shrink: smooth edges
VIOLET = (0x6D, 0x4A, 0xFF, 255)
SPROCKET = (255, 255, 255, 178)   # white at the favicon's 0.7 opacity
WHITE = (255, 255, 255, 255)


def draw(size, square_px):
    """The icon at `size` px, its rounded square `square_px` wide and centred (macOS icons leave a
    margin around the shape; Windows and Linux icons fill the canvas)."""
    big = size * SUPER
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    unit = square_px * SUPER / 30.0          # the favicon's square spans 30 of its 32 units
    origin = (big - 30 * unit) / 2 - unit    # so that favicon x=1 lands on the square's edge

    def p(u):
        return origin + u * unit

    d.rounded_rectangle([p(1), p(1), p(31), p(31)], radius=7 * unit, fill=VIOLET)
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for x in (4.5, 24.5):
        for y in (5, 13.75, 22.5):
            ld.rounded_rectangle([p(x), p(y), p(x + 3), p(y + 4.5)], radius=1 * unit, fill=SPROCKET)
    img = Image.alpha_composite(img, layer)
    ImageDraw.Draw(img).polygon([(p(13), p(10.2)), (p(13), p(21.8)), (p(22.5), p(16))], fill=WHITE)
    return img.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(OUT, exist_ok=True)
    full = draw(1024, 1024 * 30 / 32)
    full.save(os.path.join(OUT, "exhume.png"))
    full.save(os.path.join(OUT, "exhume.ico"),
              sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    draw(1024, 824).save(os.path.join(OUT, "exhume.icns"))    # Apple's icon grid: 824 of 1024
    print("wrote", ", ".join(sorted(os.listdir(OUT))))


if __name__ == "__main__":
    main()
