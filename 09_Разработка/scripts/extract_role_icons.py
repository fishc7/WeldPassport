from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PIL import Image


ICONS = {
    "01_pto": (105, 38, 207, 133),
    "02_master_foreman": (389, 31, 480, 133),
    "03_welder": (625, 34, 736, 133),
    "04_chief_welder": (924, 34, 1007, 133),
    "05_quality_control": (1168, 36, 1262, 133),
    "06_storekeeper": (1409, 35, 1518, 133),
}


def make_transparent(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            red, green, blue, _ = pixels[x, y]
            minimum = min(red, green, blue)
            maximum = max(red, green, blue)
            saturation = maximum - minimum

            if minimum >= 242 and saturation <= 10:
                alpha = max(0, min(255, (255 - minimum) * 20))
                pixels[x, y] = (red, green, blue, alpha)
    return rgba


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: extract_role_icons.py SOURCE_IMAGE OUTPUT_DIR")
        return 2

    source = Path(sys.argv[1]).resolve()
    output_dir = Path(sys.argv[2]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    image = Image.open(source)
    if image.size != (1649, 196):
        print(f"Unexpected source size: {image.size}; expected (1649, 196)")
        return 1

    shutil.copy2(source, output_dir / "source-role-strip.png")

    for name, box in ICONS.items():
        cropped = image.crop(box)
        transparent = make_transparent(cropped)

        canvas = Image.new("RGBA", (160, 160), (255, 255, 255, 0))
        offset = (
            (canvas.width - transparent.width) // 2,
            (canvas.height - transparent.height) // 2,
        )
        canvas.alpha_composite(transparent, offset)
        canvas.save(output_dir / f"{name}.png", optimize=True)

    print(f"Saved {len(ICONS)} icons to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
