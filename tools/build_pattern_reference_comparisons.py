"""Compose unaltered reference and live captures for visual review."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1] / "docs" / "clean-pattern-review-v1"
PAIRINGS = {
    "clean": "clean-approved.png",
    "sql-lab": "sql-lab-concept.png",
    "visualize": "visualize-concept.png",
}

for workspace, reference_name in PAIRINGS.items():
    with Image.open(ROOT / "references" / reference_name) as reference, Image.open(
        ROOT / "reference-comparisons" / f"{workspace}-current-1586x992.png"
    ) as current:
        if reference.size != current.size:
            raise ValueError(f"{workspace}: reference {reference.size}, capture {current.size}")
        width, height = reference.size
        combined = Image.new("RGB", (width * 2, height + 36), "#eef1f3")
        combined.paste(reference.convert("RGB"), (0, 36))
        combined.paste(current.convert("RGB"), (width, 36))
        draw = ImageDraw.Draw(combined)
        font = ImageFont.truetype("arial.ttf", 16)
        draw.text((12, 9), "APPROVED REFERENCE", fill="#17232a", font=font)
        draw.text((width + 12, 9), "LIVE FEATURE PREVIEW", fill="#17232a", font=font)
        combined.save(ROOT / "reference-comparisons" / f"{workspace}-side-by-side.png")
