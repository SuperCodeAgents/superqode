"""Print the theme's text colours as real terminal swatches.

Contrast changes are easy to argue about and hard to see in a diff, so this
renders the actual colours, with their measured WCAG ratio against the theme
background. Run it in a terminal:

    .venv/bin/python scripts/show_theme_contrast.py [theme]
"""

from __future__ import annotations

import sys


def _luminance(color: str) -> float:
    value = color.lstrip("#")
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in channels)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(foreground: str, background: str) -> float:
    first, second = _luminance(foreground), _luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def paint(color: str, text: str, background: str | None = None) -> str:
    value = color.lstrip("#")
    red, green, blue = (int(value[i : i + 2], 16) for i in (0, 2, 4))
    codes = f"38;2;{red};{green};{blue}"
    if background:
        back = background.lstrip("#")
        br, bg_, bb = (int(back[i : i + 2], 16) for i in (0, 2, 4))
        codes += f";48;2;{br};{bg_};{bb}"
    return f"\x1b[{codes}m{text}\x1b[0m"


def main() -> None:
    from superqode import design_system as ds
    from superqode.app.constants import GRADIENT
    from superqode.app.theme_bridge import _palette_to_theme, theme_names

    name = sys.argv[1] if len(sys.argv) > 1 else "superqode"
    if name not in theme_names():
        print(f"Unknown theme {name!r}. Available: {', '.join(theme_names())}")
        raise SystemExit(1)

    mapped = _palette_to_theme(ds.get_theme(name).colors)
    background = mapped["bg"]
    sample = "The quick brown fox jumps over the lazy dog"

    print()
    print(f"  theme: {name}   background: {background}")
    print("  " + "-" * 68)
    for token in ("text", "muted", "dim"):
        color = mapped[token]
        ratio = contrast(color, background)
        verdict = "body ok" if ratio >= 4.5 else ("large only" if ratio >= 3.0 else "TOO FAINT")
        print(f"  {token:<6} {color}  {ratio:5.2f}:1  {verdict:<11}")
        print("         " + paint(color, sample, background))
    print()
    print("  brand gradient (the logo, identical in every theme)")
    print("         " + "".join(paint(stop, "  ", stop) for stop in GRADIENT))
    print("         " + " ".join(GRADIENT))
    print()


if __name__ == "__main__":
    main()
