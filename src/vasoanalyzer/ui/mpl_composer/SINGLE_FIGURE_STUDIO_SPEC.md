# Single Figure Studio — Design Contract (Document-first)

## Purpose
Single Figure Studio produces figures intended for insertion into Word/PDF manuscripts and PowerPoint slides/posters.

## Core Principle
The figure is a document object with a physical size (inches). The on-screen preview is a scaled representation.

## Non-negotiable rules
1) Inches-first: Figure size is specified in inches. DPI is export quality only (vector exports ignore DPI).
2) Preview never drives window size:
   - The preview must never exceed its viewport/container.
   - The preview must never cause the dialog/window to resize or grow.
3) Always-fit preview:
   - Preview scales down as needed to fully fit (preserve aspect ratio).
   - Preview centers horizontally and vertically.
   - If scaled down, show “Preview scaled to fit: XX%”.
4) Single source of truth:
   - Preview and export MUST render through the same FigureSpec/build_figure path.
5) Robust UX:
   - Box select must fail gracefully (disable tool) rather than crash.
