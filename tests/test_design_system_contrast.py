"""Contrast guarantees for the accessibility theme."""

from __future__ import annotations

from superqode.design_system import THEMES, get_theme


def _luminance(hex_color: str) -> float:
    """Relative luminance per WCAG 2.1."""
    value = hex_color.lstrip("#")
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    adjusted = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * adjusted[0] + 0.7152 * adjusted[1] + 0.0722 * adjusted[2]


def _contrast_ratio(foreground: str, background: str) -> float:
    light, dark = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def test_high_contrast_theme_is_registered():
    assert "high-contrast" in THEMES


def test_high_contrast_text_clears_wcag_aaa():
    """Every text tone must stay readable, including the muted and dim ones.

    The decorative themes use low-contrast greys for de-emphasis, which is
    exactly what fails for low vision. This theme trades that styling away, so
    the guarantee needs to be enforced rather than assumed.
    """
    colors = get_theme("high-contrast").colors
    background = colors.bg_void

    for attribute in ("text_primary", "text_secondary", "text_muted", "text_dim"):
        ratio = _contrast_ratio(getattr(colors, attribute), background)
        assert ratio >= 7.0, f"{attribute} contrast {ratio:.1f}:1 is below WCAG AAA (7:1)"


def test_high_contrast_semantic_colors_stay_distinguishable():
    """Success, warning, and error must not collapse into each other."""
    colors = get_theme("high-contrast").colors
    background = colors.bg_void

    for attribute in ("success", "warning", "error", "info"):
        ratio = _contrast_ratio(getattr(colors, attribute), background)
        assert ratio >= 4.5, f"{attribute} contrast {ratio:.1f}:1 is below WCAG AA (4.5:1)"
