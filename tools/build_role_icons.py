from pathlib import Path


OUT = Path(r"D:\WeldPassport\round_icons_corrected")
BLUE = "#123B91"


def svg(body: str) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <defs>
    <clipPath id="roundCrop">
      <circle cx="256" cy="256" r="238"/>
    </clipPath>
  </defs>
  <g clip-path="url(#roundCrop)">
    <circle cx="256" cy="256" r="238" fill="#fff"/>
    <g fill="none" stroke="{BLUE}" stroke-width="12" stroke-linecap="round" stroke-linejoin="round">
{body}
    </g>
  </g>
  <circle cx="256" cy="256" r="238" fill="none" stroke="{BLUE}" stroke-width="10"/>
</svg>
"""


WORKER = """
    <path d="M178 196v-18c0-43 35-78 78-78s78 35 78 78v18"/>
    <path d="M163 196h186"/>
    <path d="M205 197v24c0 34 23 62 51 62s51-28 51-62v-24"/>
    <path d="M221 276v28l35 27 35-27v-28"/>
    <path d="M221 299c-51 12-82 39-82 83v37h234v-37c0-44-31-71-82-83"/>
    <path d="M242 101v48h28v-48"/>
"""


ICONS = {
    "welder_512.svg": """
    <path d="M178 190v-12c0-43 35-78 78-78s78 35 78 78v12"/>
    <path d="M163 190h186"/>
    <path d="M198 194h116l-12 79c-3 21-22 37-46 37s-43-16-46-37z"/>
    <path d="M223 216h66v42h-66z"/>
    <path d="M218 303v24l38 25 38-25v-24"/>
    <path d="M218 319c-49 12-79 39-79 82v18h234v-18c0-43-30-70-79-82"/>
    <path d="M242 101v45h28v-45"/>
    <path d="M362 288l34-34"/>
    <path d="M397 237v-18M414 254h18M407 244l13-13"/>
""",
    "chief_welder_512.svg": WORKER + """
    <path d="M326 326l10 20 22 3-16 16 4 22-20-10-20 10 4-22-16-16 22-3z"/>
""",
    "quality_control_512.svg": WORKER + """
    <path d="M318 326l33 12v31c0 24-14 42-33 50-19-8-33-26-33-50v-31z"/>
    <path d="M300 369l13 13 25-29"/>
""",
    "warehouse_512.svg": """
    <path d="M130 126h38l34 211h174"/>
    <path d="M193 179l132-25 31 143-132 25z"/>
    <path d="M206 337h170"/>
    <circle cx="224" cy="376" r="30"/>
    <circle cx="351" cy="376" r="30"/>
    <path d="M259 168l8 44"/>
""",
    "pto_512.svg": WORKER + """
    <rect x="304" y="318" width="77" height="101" rx="7"/>
    <path d="M326 346h34M326 369h34M326 392h23"/>
    <path d="M327 318v-13h31v13"/>
""",
    "foreman_512.svg": WORKER + """
    <circle cx="326" cy="363" r="30"/>
    <path d="M326 318v15M326 393v15M281 363h15M356 363h15M294 331l11 11M347 384l11 11M358 331l-11 11M305 384l-11 11"/>
""",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, body in ICONS.items():
        (OUT / name).write_text(svg(body), encoding="utf-8")


if __name__ == "__main__":
    main()
