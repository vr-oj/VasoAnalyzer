"""Data-only template presets for the Matplotlib Figure Composer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

DEFAULT_TEMPLATE_ID = "single_column"
WIDE_MULTIPLIER = 1.35
TALL_MULTIPLIER = 1.35


@dataclass(frozen=True)
class TemplatePreset:
    """Physical layout + style defaults for a template."""

    layout_defaults: Dict[str, Any]
    style_defaults: Dict[str, Dict[str, Any]]


_TEMPLATES: Dict[str, TemplatePreset] = {
    "single_column": TemplatePreset(
        layout_defaults={
            "width_in": 3.35,
            "height_in": 2.6,
            "min_margin_in": 0.35,
            "left_margin_in": 0.70,
            "right_margin_in": 0.20,
            "top_margin_in": 0.20,
            "bottom_margin_in": 0.50,
        },
        style_defaults={
            "axes": {
                "xlabel_fontsize": 8.0,
                "ylabel_fontsize": 8.0,
                "tick_label_fontsize": 6.0,
                "event_label_fontsize": 6.0,
            },
            "figure": {
                "legend_fontsize": 8.0,
            },
        },
    ),
    "double_column": TemplatePreset(
        layout_defaults={
            "width_in": 7.0,
            "height_in": 3.8,
            "min_margin_in": 0.40,
            "left_margin_in": 0.90,
            "right_margin_in": 0.15,
            "top_margin_in": 0.20,
            "bottom_margin_in": 0.60,
        },
        style_defaults={
            "axes": {
                "xlabel_fontsize": 11.0,
                "ylabel_fontsize": 11.0,
                "tick_label_fontsize": 9.0,
                "event_label_fontsize": 9.0,
            },
            "figure": {
                "legend_fontsize": 9.0,
            },
        },
    ),
    "slide": TemplatePreset(
        layout_defaults={
            "width_in": 10.0,
            "height_in": 5.625,  # 16:9
            "min_margin_in": 0.45,
            "left_margin_in": 1.00,
            "right_margin_in": 0.20,
            "top_margin_in": 0.25,
            "bottom_margin_in": 0.60,
        },
        style_defaults={
            "axes": {
                "xlabel_fontsize": 14.0,
                "ylabel_fontsize": 14.0,
                "tick_label_fontsize": 12.0,
                "event_label_fontsize": 12.0,
            },
            "figure": {
                "legend_fontsize": 12.0,
            },
        },
    ),
}


def get_template_preset(template_id: str) -> TemplatePreset:
    """Return the preset for template_id (fallback to default)."""
    return _TEMPLATES.get(template_id, _TEMPLATES[DEFAULT_TEMPLATE_ID])


def preset_dimensions_from_base(base_w: float, base_h: float, preset: str) -> tuple[float, float]:
    """
    Derive preset width/height (inches) from a base template size.

    Wide: width * k, height / k
    Tall: width / k, height * k
    Square: side = sqrt(base_w * base_h)
    Area stays constant; aspect changes by k (wide) or 1/k (tall).
    """
    try:
        base_w = float(base_w)
        base_h = float(base_h)
    except Exception:
        return base_w, base_h
    if base_w <= 0 or base_h <= 0:
        return base_w, base_h
    k = WIDE_MULTIPLIER
    p = (preset or "wide").lower()
    if p == "square":
        side = (base_w * base_h) ** 0.5
        return side, side
    if p == "tall":
        return base_w / k, base_h * k
    return base_w * k, base_h / k


def apply_template_preset(
    fig_spec: Any,
    template_id: str,
    previous_defaults: Dict[str, Dict[str, Any]] | None = None,
    *,
    respect_overrides: bool = True,
) -> Dict[str, Dict[str, Any]]:
    """
    Apply template defaults to the given FigureSpec in-place.

    Fields are updated unless `respect_overrides` is True and the current value
    differs from the previous defaults (treat differing values as user overrides).

    Returns the defaults used so callers can cache them for the next template switch.
    """
    preset = get_template_preset(template_id)
    prev = previous_defaults or {"page": {}, "axes": {}, "figure": {}}
    size_mode = getattr(fig_spec, "size_mode", "template")

    def _apply_section(obj: Any, defaults: Dict[str, Any], section: str) -> None:
        for field, new_val in defaults.items():
            current = getattr(obj, field, None)
            should_apply = not respect_overrides
            if respect_overrides:
                if current is None:
                    should_apply = True
                elif prev.get(section, {}).get(field) == current:
                    should_apply = True
            if should_apply:
                try:
                    setattr(obj, field, new_val)
                except Exception:
                    continue

    if hasattr(fig_spec, "page"):
        layout_defaults = dict(preset.layout_defaults)
        if size_mode in ("preset", "custom"):
            layout_defaults.pop("width_in", None)
            layout_defaults.pop("height_in", None)
        _apply_section(fig_spec.page, layout_defaults, "page")
        page = fig_spec.page
        if size_mode == "template":
            try:
                page.width_in = float(preset.layout_defaults.get("width_in", page.width_in))
                page.height_in = float(preset.layout_defaults.get("height_in", page.height_in))
                if hasattr(fig_spec, "figure_width_in"):
                    fig_spec.figure_width_in = page.width_in
                if hasattr(fig_spec, "figure_height_in"):
                    fig_spec.figure_height_in = page.height_in
                if hasattr(fig_spec, "size_mode"):
                    fig_spec.size_mode = "template"
            except Exception:
                pass
        left = getattr(page, "left_margin_in", None)
        right = getattr(page, "right_margin_in", None)
        top = getattr(page, "top_margin_in", None)
        bottom = getattr(page, "bottom_margin_in", None)
        if all(v is not None for v in (left, right, top, bottom)):
            # Compute axes dimensions from explicit figure + margins.
            axes_w = max(page.width_in - float(left) - float(right), 0.1)
            axes_h = max(page.height_in - float(top) - float(bottom), 0.1)
            if (not respect_overrides) or prev.get("page", {}).get(
                "axes_width_in"
            ) == getattr(page, "axes_width_in", None):
                page.axes_width_in = axes_w
            if (not respect_overrides) or prev.get("page", {}).get(
                "axes_height_in"
            ) == getattr(page, "axes_height_in", None):
                page.axes_height_in = axes_h
        if getattr(fig_spec, "figure_width_in", None) is None:
            try:
                fig_spec.figure_width_in = float(page.width_in)
            except Exception:
                pass
        if getattr(fig_spec, "figure_height_in", None) is None:
            try:
                fig_spec.figure_height_in = float(page.height_in)
            except Exception:
                pass
    if hasattr(fig_spec, "axes"):
        axes_defaults = preset.style_defaults.get("axes", {})
        _apply_section(fig_spec.axes, axes_defaults, "axes")
    figure_defaults = preset.style_defaults.get("figure", {})
    _apply_section(fig_spec, figure_defaults, "figure")

    return {
        "page": dict(preset.layout_defaults),
        "axes": dict(preset.style_defaults.get("axes", {})),
        "figure": dict(preset.style_defaults.get("figure", {})),
    }
