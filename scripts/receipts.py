"""Renders SYNTHETIC transfer receipts for the demo. Fictional bank, watermarked DEMO DATA."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT_CANDIDATES = ["/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]


def _font(size: int, bold: bool = False):
    paths = (["/System/Library/Fonts/Supplemental/Arial Bold.ttf"] if bold else []) + FONT_CANDIDATES
    for p in paths:
        if Path(p).exists():
            return ImageFont.truetype(p, size)
    return ImageFont.load_default(size=size)


def render_receipt(path: Path, *, amount: str, when: str, sender: str, recipient: str,
                   reference: str, narration: str = "", bank: str = "Demo Bank") -> None:
    W, H = 720, 980
    img = Image.new("RGB", (W, H), "#f4f6f8")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 150], fill="#1f4e79")
    d.text((40, 40), bank, font=_font(40, True), fill="white")
    d.text((40, 95), "Mobile Banking", font=_font(24), fill="#cfe0f0")
    d.ellipse([W // 2 - 45, 190, W // 2 + 45, 280], fill="#2e9d5b")
    d.line([(W // 2 - 24, 236), (W // 2 - 6, 256), (W // 2 + 26, 216)], fill="white", width=10)
    d.text((W // 2, 320), "Transfer Successful", font=_font(34, True), fill="#1b1b1b", anchor="mm")
    d.text((W // 2, 390), amount, font=_font(56, True), fill="#1b1b1b", anchor="mm")
    rows = [("Date", when), ("From", sender), ("To", recipient), ("Reference", reference)]
    if narration:
        rows.append(("Narration", narration))
    y = 470
    for label, value in rows:
        d.line([40, y - 18, W - 40, y - 18], fill="#dde3ea", width=2)
        d.text((40, y), label, font=_font(24), fill="#6b7785")
        d.text((W - 40, y), value[:42], font=_font(24, True), fill="#1b1b1b", anchor="ra")
        y += 70
    # watermark so no one mistakes this for a real receipt
    mark = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    md = ImageDraw.Draw(mark)
    md.text((W // 2, H // 2), "DEMO DATA", font=_font(110, True), fill=(200, 30, 30, 50), anchor="mm")
    mark = mark.rotate(30, center=(W // 2, H // 2))
    img = Image.alpha_composite(img.convert("RGBA"), mark).convert("RGB")
    d = ImageDraw.Draw(img)
    d.text((W // 2, H - 40), "Synthetic receipt for the TrustLedger hackathon demo - not a real transaction",
           font=_font(18), fill="#8a94a0", anchor="mm")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG")


def render_not_a_receipt(path: Path) -> None:
    img = Image.new("RGB", (720, 720), "#fff7e6")
    d = ImageDraw.Draw(img)
    d.text((60, 60), "Market list", font=_font(44, True), fill="#6b3e00")
    for i, item in enumerate(["Tomatoes - 2 baskets", "Pepper - 1 bag", "Onions - 3 bags", "Palm oil - 5 litres"]):
        d.text((60, 160 + i * 70), "- " + item, font=_font(32), fill="#3b2a10")
    img.save(path, "PNG")
