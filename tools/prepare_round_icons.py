from __future__ import annotations

import base64
from collections import deque
import io
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


SOURCE_DIR = Path(r"C:\Users\Andrey\Downloads\иконки_без_надписи")
OUTPUT_DIR = Path(r"D:\WeldPassport\round_icons")
NAMES = [
    "сварщик",
    "главный_сварщик",
    "контроль_качества_СК",
    "МТО_кладовщик",
    "ПТО",
    "мастер_прораб",
]


def extract_png(svg_path: Path) -> Image.Image:
    text = svg_path.read_text(encoding="utf-8")
    match = re.search(r"data:image/png;base64,([^\"']+)", text)
    if not match:
        raise ValueError(f"Embedded PNG not found in {svg_path}")
    return Image.open(io.BytesIO(base64.b64decode(match.group(1)))).convert("RGBA")


def isolate_blue_art(image: Image.Image) -> Image.Image:
    source = image.convert("RGBA")
    output = Image.new("RGBA", source.size, (0, 0, 0, 0))
    source_pixels = source.load()
    output_pixels = output.load()
    for y in range(source.height):
        for x in range(source.width):
            red, green, blue, alpha = source_pixels[x, y]
            blue_strength = blue - max(red, green)
            if blue > 65 and blue_strength > 25 and blue > red * 1.25 and blue > green * 1.12:
                edge_alpha = min(alpha, max(0, blue_strength * 5))
                output_pixels[x, y] = (red, green, blue, edge_alpha)
    return output


def remove_large_background_components(image: Image.Image) -> Image.Image:
    width, height = image.size
    alpha = image.getchannel("A")
    pixels = alpha.load()
    visited = bytearray(width * height)
    keep_mask = Image.new("L", image.size, 0)
    keep_pixels = keep_mask.load()

    for start_y in range(height):
        for start_x in range(width):
            index = start_y * width + start_x
            if visited[index] or pixels[start_x, start_y] < 20:
                continue
            queue = deque([(start_x, start_y)])
            visited[index] = 1
            component = []
            min_x = max_x = start_x
            min_y = max_y = start_y
            while queue:
                x, y = queue.popleft()
                component.append((x, y))
                min_x, max_x = min(min_x, x), max(max_x, x)
                min_y, max_y = min(min_y, y), max(max_y, y)
                for ny in range(max(0, y - 1), min(height, y + 2)):
                    for nx in range(max(0, x - 1), min(width, x + 2)):
                        next_index = ny * width + nx
                        if not visited[next_index] and pixels[nx, ny] >= 20:
                            visited[next_index] = 1
                            queue.append((nx, ny))
            component_width = max_x - min_x + 1
            component_height = max_y - min_y + 1
            is_background_arc = (
                component_width > width * 0.48
                and component_height > height * 0.48
            )
            if len(component) >= 20 and not is_background_arc:
                for x, y in component:
                    keep_pixels[x, y] = 255

    cleaned = image.copy()
    cleaned.putalpha(Image.composite(alpha, Image.new("L", image.size, 0), keep_mask))
    return cleaned


def crop_upper_art(image: Image.Image) -> Image.Image:
    isolated = remove_large_background_components(isolate_blue_art(image))
    alpha = isolated.getchannel("A")
    cutoff = int(image.height * 0.68)
    upper_alpha = alpha.crop((0, 0, image.width, cutoff))
    bbox = upper_alpha.getbbox()
    if bbox is None:
        raise ValueError("No visible artwork found in upper image area")
    left, top, right, bottom = bbox
    padding = max(12, int(max(right - left, bottom - top) * 0.04))
    left = max(0, left - padding)
    top = max(0, top - padding)
    right = min(image.width, right + padding)
    bottom = min(cutoff, bottom + padding)
    return isolated.crop((left, top, right, bottom))


def make_round_icon(art: Image.Image, size: int = 512) -> Image.Image:
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(result)
    margin = 20
    draw.ellipse(
        (margin, margin, size - margin - 1, size - margin - 1),
        outline=(15, 57, 145, 255),
        width=10,
    )

    fitted = art.copy()
    fitted.thumbnail((360, 360), Image.Resampling.LANCZOS)
    x = (size - fitted.width) // 2
    y = (size - fitted.height) // 2
    result.alpha_composite(fitted, (x, y))
    return result


def png_data_uri(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def write_svg(path: Path, icon: Image.Image) -> None:
    uri = png_data_uri(icon)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" '
        'viewBox="0 0 512 512">\n'
        f'  <image width="512" height="512" href="{uri}"/>\n'
        "</svg>\n"
    )
    path.write_text(svg, encoding="utf-8")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    previews: list[tuple[str, Image.Image]] = []

    for name in NAMES:
        backup_path = SOURCE_DIR / "_backup_before_512" / f"{name}.svg"
        source_path = backup_path if backup_path.exists() else SOURCE_DIR / f"{name}.svg"
        image = extract_png(source_path)
        image.save(OUTPUT_DIR / f"{name}_source.png")
        art = crop_upper_art(image)
        icon = make_round_icon(art)
        icon.save(OUTPUT_DIR / f"{name}_round.png", optimize=True)
        write_svg(OUTPUT_DIR / f"{name}_round.svg", icon)
        preview = icon.copy()
        preview.thumbnail((360, 260), Image.Resampling.LANCZOS)
        previews.append((name, preview))

    sheet = Image.new("RGB", (800, 900), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    for index, (name, preview) in enumerate(previews):
        column = index % 2
        row = index // 2
        x = 20 + column * 390
        y = 20 + row * 290
        sheet.paste(preview, (x, y))
        draw.text((x, y + 265), name, fill="black", font=font)
    sheet.save(OUTPUT_DIR / "contact_sheet.png")


if __name__ == "__main__":
    main()
