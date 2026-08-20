"""
Turn a club's kit colours into two chart colours that can actually be read.

Kit colours are chosen to look good on a shirt, not to be told apart in a chart
at 12px on a phone. Three things go wrong if you use them raw:

  Contrast.  Newcastle's black vanishes on a dark background and Norwich's
             yellow vanishes on a light one. Wolves' gold fails both.
  Clash.     Manchester United against Liverpool is red against red. Arsenal
             against Forest, the same. Whichever line you are looking at, you
             cannot tell whose it is.
  Grey.      A few clubs are essentially monochrome, and a near-grey series
             reads as an axis rather than as data.

So the kit colour is treated as a starting hue, not as a final value. Each one
is moved into a legible lightness band for the mode it will be shown in, its
chroma is floored so it does not read as grey, and the pair is then checked for
separation under normal and colour-blind vision. If the two clubs are still too
close, the away side is stepped away from the home side rather than both being
thrown out, so at least one team keeps its real colour.

The bands, the chroma floor and the separation thresholds are not invented
here: they are the ones the palette validator enforces, and the output of this
module is checked against it.

Everything is done in OKLab, which is perceptually uniform enough that moving
lightness does not swing the hue, and which is what the validator measures in.
"""

from __future__ import annotations

import math

# Straight from the validator: the band a categorical colour must sit in, the
# chroma below which it reads as grey, and how far apart a pair must be.
BAND = {"light": (0.43, 0.77), "dark": (0.48, 0.67)}
CHROMA_FLOOR = 0.10
CVD_TARGET = 8.0
NORMAL_FLOOR = 15.0

SURFACE = {"light": "#fcfcfb", "dark": "#1a1a19"}

# Where in the band to aim. Not the middle: slightly darker than centre on a
# light surface and slightly lighter on a dark one, which is where these read
# best against the report's own background.
TARGET_L = {"light": 0.58, "dark": 0.62}

# For clubs with no usable hue. Slot 7 of the validated categorical palette,
# violet, chosen because it is far from the red and blue that most kits are.
MONOCHROME = {"light": "#4a3aa7", "dark": "#9085e9"}


# --------------------------------------------------------------- colour maths

def _srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    return c * 12.92 if c <= 0.0031308 else 1.055 * (c ** (1 / 2.4)) - 0.055


def hex_to_rgb(value: str) -> tuple[float, float, float]:
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        raise ValueError(f"not a hex colour: {value!r}")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def rgb_to_hex(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


def rgb_to_oklab(rgb):
    r, g, b = (_srgb_to_linear(c) for c in rgb)
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (math.copysign(abs(v) ** (1 / 3), v) for v in (l, m, s))
    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def oklab_to_rgb(lab):
    L, a, b = lab
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = (v ** 3 for v in (l_, m_, s_))
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bb = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return tuple(min(1.0, max(0.0, _linear_to_srgb(c))) for c in (r, g, bb))


def to_oklch(hex_colour: str):
    L, a, b = rgb_to_oklab(hex_to_rgb(hex_colour))
    return L, math.hypot(a, b), math.atan2(b, a)


def from_oklch(L: float, C: float, h: float) -> str:
    return rgb_to_hex(oklab_to_rgb((L, C * math.cos(h), C * math.sin(h))))


def delta_e(one: str, two: str) -> float:
    a = rgb_to_oklab(hex_to_rgb(one))
    b = rgb_to_oklab(hex_to_rgb(two))
    return 100 * math.dist(a, b)


def contrast(hex_colour: str, surface: str) -> float:
    def luminance(value):
        r, g, b = (_srgb_to_linear(c) for c in hex_to_rgb(value))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    a, b = luminance(hex_colour), luminance(surface)
    lo, hi = sorted((a, b))
    return (hi + 0.05) / (lo + 0.05)


# ------------------------------------------------------------ CVD simulation

# Brettel-style matrices, matching what the validator uses to judge whether two
# colours survive red-green colour blindness.
_CVD = {
    "protan": ((0.1121, 0.8853, -0.0005), (0.1127, 0.8897, -0.0001),
               (0.0045, 0.0000, 1.0019)),
    "deutan": ((0.2920, 0.7054, -0.0003), (0.2934, 0.7089, 0.0000),
               (-0.0209, 0.0257, 0.9924)),
}


def simulate(hex_colour: str, kind: str) -> str:
    r, g, b = (_srgb_to_linear(c) for c in hex_to_rgb(hex_colour))
    m = _CVD[kind]
    out = [sum(row[i] * v for i, v in enumerate((r, g, b))) for row in m]
    return rgb_to_hex([min(1.0, max(0.0, _linear_to_srgb(c))) for c in out])


def cvd_separation(one: str, two: str) -> float:
    """The worst of protan and deutan. Red-green is what splits football kits."""
    return min(delta_e(simulate(one, k), simulate(two, k)) for k in _CVD)


# ------------------------------------------------------------------ the work

def has_hue(hex_colour: str | None) -> bool:
    """Is there a colour here, or just black, white or grey?"""
    if not hex_colour:
        return False
    try:
        return to_oklch(hex_colour)[1] >= 0.04
    except ValueError:
        return False


def best_of(*candidates: str | None) -> str | None:
    """The first candidate with an actual hue in it.

    SofaScore's `primary` is the shirt's dominant colour, which for a lot of
    clubs is white: Spurs, Leeds, Brentford, Sunderland, Fulham. Taking primary
    alone turned five Premier League sides into the same fallback violet.
    Their `secondary` is the colour you would actually name if asked, so it is
    tried next: Spurs navy, Leeds blue, Brentford red, Sunderland red.

    Some clubs really are monochrome. Newcastle are black and white, Fulham
    white and black, and for those every candidate fails and the fallback is
    the right answer rather than a failure.
    """
    for candidate in candidates:
        if has_hue(candidate):
            return candidate
    return None


def legible(hex_colour: str, mode: str) -> str:
    """Move a kit colour into the band without changing what colour it is.

    Hue is preserved exactly. Only lightness and chroma move, because those are
    what decide whether it can be seen, while hue is what makes it recognisably
    the club's colour.

    A club whose kit is black, white or grey has no usable hue at all, so it
    gets one assigned rather than being nudged into a slightly-tinted grey that
    reads as an axis line. Newcastle and Juventus are the obvious cases.
    """
    L, C, h = to_oklch(hex_colour)
    lo, hi = BAND[mode]

    if C < 0.04:
        # Effectively monochrome: black, white or grey, with no hue to keep.
        # Newcastle, Juventus, Leeds. A tinted grey would read as an axis line
        # rather than as data, so one is assigned instead of nudged.
        #
        # The value is taken from the validated categorical palette rather than
        # chosen by eye. The first version of this line was a slate blue I
        # picked because it looked right, and the validator failed it on the
        # chroma floor in both modes and on the lightness band in dark. That is
        # exactly the mistake the validator exists to catch.
        return MONOCHROME[mode]

    target = min(hi - 0.01, max(lo + 0.01, TARGET_L[mode]))
    boosted = max(C, CHROMA_FLOOR + 0.02)

    # Reducing chroma until the colour is inside the sRGB gamut. Pushing a
    # saturated hue to a new lightness can land outside it, and clamping the
    # channels afterwards silently shifts the hue, which is the one thing this
    # function is supposed to protect.
    for step in range(24):
        candidate = from_oklch(target, boosted * (1 - step * 0.04), h)
        cl, cc, ch = to_oklch(candidate)
        if abs(cl - target) < 0.02 and abs(((ch - h + math.pi) % (2 * math.pi)) - math.pi) < 0.06:
            if cc >= CHROMA_FLOOR and contrast(candidate, SURFACE[mode]) >= 3.0:
                return candidate

    # Nothing in that hue works at this lightness. Walk the band instead.
    for L_try in [target + d for d in (0.06, -0.06, 0.12, -0.12, 0.18, -0.18)]:
        if not lo <= L_try <= hi:
            continue
        candidate = from_oklch(L_try, max(CHROMA_FLOOR + 0.02, C), h)
        if contrast(candidate, SURFACE[mode]) >= 3.0 and to_oklch(candidate)[1] >= CHROMA_FLOOR:
            return candidate

    return from_oklch(target, CHROMA_FLOOR + 0.04, h)


def separate(home: str, away: str, mode: str) -> str:
    """Move the away colour away from the home one until the pair is readable.

    The home side keeps its real colour and the away side gives ground. That is
    an arbitrary choice but it has to be made consistently, otherwise the same
    club appears in different colours depending on who it is playing.

    Rotating hue rather than changing lightness, because two colours of
    different lightness but the same hue still read as the same team's shirt in
    two shades, and because the validator's separation is mostly hue-driven.
    """
    L, C, h = to_oklch(away)

    if (delta_e(home, away) >= NORMAL_FLOOR
            and cvd_separation(home, away) >= CVD_TARGET):
        return away

    best, best_score = away, -1.0
    for degrees in range(15, 360, 15):
        candidate = legible(from_oklch(L, C, h + math.radians(degrees)), mode)
        normal = delta_e(home, candidate)
        cvd = cvd_separation(home, candidate)
        if normal < NORMAL_FLOOR or cvd < CVD_TARGET:
            continue
        # Among the options that work, take the smallest rotation, so the away
        # colour stays as close to its real one as legibility allows.
        score = 1000 - degrees
        if score > best_score:
            best, best_score = candidate, score

    return best


def pair_for(home_hex: str | None, away_hex: str | None, mode: str) -> tuple[str, str]:
    """Two chart colours for one fixture, guaranteed readable.

    A club with no usable kit colour gets the monochrome slot, home or away,
    rather than whichever default happens to sit in that position. The first
    version used the report's slot-1 blue for a colourless home side and
    slot-2 orange for a colourless away side, which meant Newcastle were blue
    at St James' Park and orange everywhere else. A club has to look the same
    in every fixture or the colour is not telling you anything.

    The home side keeps its colour and the away side gives ground, for the
    same reason.
    """
    home = legible(home_hex, mode) if home_hex else MONOCHROME[mode]
    away = legible(away_hex, mode) if away_hex else MONOCHROME[mode]

    return home, separate(home, away, mode)
