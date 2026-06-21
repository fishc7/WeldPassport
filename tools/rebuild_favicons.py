from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
FAVICON_DIR = ROOT / "docs" / "favicon"
MASTER_PATH = FAVICON_DIR / "weldpassport-web-icon-master.png"


def remove_connected_white_background(image: Image.Image) -> Image.Image:
    rgb = np.asarray(image.convert("RGB"))
    distance_from_white = 255 - rgb.min(axis=2)

    # Only near-white pixels connected to the canvas edge are background.
    candidate = distance_from_white <= 80
    height, width = candidate.shape
    exterior = np.zeros((height, width), dtype=bool)
    queue: deque[tuple[int, int]] = deque()

    def enqueue(y: int, x: int) -> None:
        if candidate[y, x] and not exterior[y, x]:
            exterior[y, x] = True
            queue.append((y, x))

    for x in range(width):
        enqueue(0, x)
        enqueue(height - 1, x)
    for y in range(height):
        enqueue(y, 0)
        enqueue(y, width - 1)

    while queue:
        y, x = queue.popleft()
        if y:
            enqueue(y - 1, x)
        if y + 1 < height:
            enqueue(y + 1, x)
        if x:
            enqueue(y, x - 1)
        if x + 1 < width:
            enqueue(y, x + 1)

    alpha = np.full((height, width), 255, dtype=np.uint8)
    soft_alpha = np.clip(
        (distance_from_white.astype(np.float32) - 5.0) * (255.0 / 50.0),
        0,
        255,
    ).astype(np.uint8)
    alpha[exterior] = soft_alpha[exterior]

    rgba = np.dstack((rgb, alpha))
    return Image.fromarray(rgba, mode="RGBA")


def resized(master: Image.Image, size: int) -> Image.Image:
    return master.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    FAVICON_DIR.mkdir(parents=True, exist_ok=True)
    transparent_master = remove_connected_white_background(Image.open(MASTER_PATH))
    transparent_master.save(MASTER_PATH, optimize=True)

    outputs = {
        "favicon-16x16.png": 16,
        "favicon-32x32.png": 32,
        "apple-touch-icon.png": 180,
        "icon-192.png": 192,
        "icon-512.png": 512,
    }
    for filename, size in outputs.items():
        resized(transparent_master, size).save(
            FAVICON_DIR / filename,
            optimize=True,
        )

    ico_images = [resized(transparent_master, size) for size in (16, 32, 48)]
    ico_images[-1].save(
        FAVICON_DIR / "favicon.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)],
        append_images=ico_images[:-1],
    )


if __name__ == "__main__":
    main()
