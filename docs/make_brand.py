"""The project's logo, the award banner and the GitHub social preview, in the colours and type of docs/banner.png.

  python docs/make_brand.py        # docs/logo.svg, docs/logo.png, docs/award.png, docs/social_preview.png

Needs Pillow only. The logo is four piano keys, one per player of the quartet; the gold one is the key being played."""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
INK, IVORY, MUTED, GOLD = (24, 26, 32), (245, 242, 234), (176, 180, 192), (232, 184, 86)
hexc = lambda c: "#%02x%02x%02x" % c


def font(name, size):
    for p in (f"/usr/share/fonts/opentype/fira/FiraSans-{name}.otf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def serif(size):
    for p in ("/usr/share/fonts/truetype/msttcorefonts/Georgia_Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"):
        if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default()


# ---------------------------------------------------------------- logo: C D E F with C# and D#, E played
W_KEYS = [(96 + i * 82, 74) for i in range(4)]                 # x, width of the four white keys in a 512 box
B_KEYS = [174 - 22, 256 - 22]                                    # black keys over the gaps C|D and D|E
TOP, BOTTOM, B_BOTTOM, PLAYED = 136, 392, 284, 2


def logo_svg():
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">',
         f'<rect width="512" height="512" rx="112" fill="{hexc(INK)}"/>']
    for i, (x, w) in enumerate(W_KEYS):
        fill = hexc(GOLD) if i == PLAYED else hexc(IVORY)
        s.append(f'<path d="M{x} {TOP}h{w}v{BOTTOM - TOP - 16}a16 16 0 0 1 -16 16h-{w - 32}a16 16 0 0 1 -16 -16z" fill="{fill}"/>')
    for x in B_KEYS:
        s.append(f'<path d="M{x - 6} {TOP}h56v{B_BOTTOM - TOP - 10}a10 10 0 0 1 -10 10h-36a10 10 0 0 1 -10 -10z" fill="{hexc(INK)}"/>')
    s.append("</svg>")
    return "\n".join(s) + "\n"


def logo_png(size):
    k = size / 512
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    dr.rounded_rectangle((0, 0, size - 1, size - 1), radius=112 * k, fill=INK)
    for i, (x, w) in enumerate(W_KEYS):
        dr.rounded_rectangle((x * k, (TOP - 20) * k, (x + w) * k, BOTTOM * k), radius=16 * k, fill=GOLD if i == PLAYED else IVORY)
        dr.rectangle((x * k, (TOP - 20) * k, (x + w) * k, (TOP + 20) * k), fill=GOLD if i == PLAYED else IVORY)
    dr.rectangle((0, (TOP - 21) * k, size, (TOP - 1) * k), fill=INK)          # square tops, cut at the fallboard line
    for x in B_KEYS:
        dr.rounded_rectangle(((x - 6) * k, (TOP - 10) * k, (x + 50) * k, B_BOTTOM * k), radius=10 * k, fill=INK)
    return im


# ---------------------------------------------------------------- award banner, as wide as docs/banner.png
def award(w=1760, h=320):
    im = Image.new("RGB", (w, h), INK); dr = ImageDraw.Draw(im)
    for y in range(h):                                           # the banner's slate, a little lighter at the top
        c = tuple(int(a + (b - a) * y / h) for a, b in zip((40, 43, 52), INK)); dr.line((0, y, w, y), fill=c)
    ev = Image.open(os.path.join(HERE, "media/leukerbad_robotics_carnival_26.jpg")).convert("RGB").resize((232, 232), Image.LANCZOS)
    mask = Image.new("L", ev.size, 0); ImageDraw.Draw(mask).rounded_rectangle((0, 0, *ev.size), radius=22, fill=255)
    im.paste(ev, (44, 44), mask)
    x = 324
    dr.text((x, 52), "LEUKERBAD ROBOTICS CARNIVAL '26  ·  HACKATHON", font=font("Medium", 26), fill=GOLD)
    dr.text((x, 96), "Category winner", font=serif(66), fill=IVORY)
    tw = dr.textlength("Category winner", font=serif(66))
    dr.text((x + tw + 26, 112), "Elderly and Rehabilitation", font=font("Light", 46), fill=IVORY)
    dr.line((x + 2, 196, x + 98, 196), fill=GOLD, width=4)
    dr.text((x, 214), "3rd place overall", font=font("Regular", 40), fill=IVORY)
    dr.text((x, 266), "14 to 16 Nov 2026  ·  Leukerbad, Switzerland  ·  Simon, Henry, Sima, Sebas", font=font("Regular", 24), fill=MUTED)
    return im


# ---------------------------------------------------------------- social preview (GitHub: 1280 x 640)
def social(w=1280, h=640):
    im = Image.new("RGB", (w, h), INK); dr = ImageDraw.Draw(im)
    ban = Image.open(os.path.join(HERE, "banner.png")).convert("RGB")
    ban = ban.resize((w, int(ban.height * w / ban.width)), Image.LANCZOS); im.paste(ban, (0, 0))
    y0 = ban.height
    dr.rectangle((0, y0, w, h), fill=INK); dr.line((0, y0, w, y0), fill=(46, 49, 58), width=2)
    lg = logo_png(132); im.paste(lg, (64, y0 + (h - y0 - 132) // 2), lg)
    dr.text((228, y0 + 44), "Two robot hands play the piano, and teach it to your fingers.", font=font("Regular", 34), fill=IVORY)
    dr.text((228, y0 + 100), "Category winner, Elderly and Rehabilitation  ·  3rd place overall", font=font("Medium", 27), fill=GOLD)
    dr.text((228, y0 + 140), "Leukerbad Robotics Carnival '26  ·  github.com/simonkruelle/Wuji-Quartet", font=font("Regular", 24), fill=MUTED)
    return im


if __name__ == "__main__":
    open(os.path.join(HERE, "logo.svg"), "w").write(logo_svg())
    logo_png(512).save(os.path.join(HERE, "logo.png"))
    award().save(os.path.join(HERE, "award.png"), optimize=True)
    social().save(os.path.join(HERE, "social_preview.png"), optimize=True)
    print("logo.svg, logo.png, award.png, social_preview.png")
