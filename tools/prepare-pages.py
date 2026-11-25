"""Add the public watch page to the generated Wasm shell before deploying GitHub Pages."""

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://github.com/canestudios/unrealpy-freedoom/tree/main/Python/doom"
LINKS = f'<a href="watch/">Watch gameplay</a><a href="{SOURCE}">Python source</a><a href="watch/#credits">Credits</a>'
NAV = f'<nav class="demo-links" aria-label="Demo resources">{LINKS}</nav>'


def prepare(site: Path) -> None:
    index = site / "index.html"
    html = index.read_bytes().decode("utf-8")
    # Apply the public title to prebuilt releases that still carry the original project label.
    html = html.replace(">Doom on UnrealPy<", ">Freedoom on UnrealPy<")
    additions = {
        "</head>": '<link rel="stylesheet" href="demo.css"></head>',
        '<pre id="error-text">': NAV + '<pre id="error-text">',
        '<p class="sub" data-i18n>The game has ended.': NAV + '<p class="sub" data-i18n>The game has ended.',
        '<script src="wasm-strings.js">': (
            f'<nav class="demo-links" id="demo-start-links" aria-label="Demo resources">{LINKS}</nav>'
            '<noscript><p style="position:fixed;inset:0;z-index:30;background:#17191b;padding:2rem">'
            'This game needs JavaScript. <a style="color:#ffe49d" href="watch/">Watch gameplay and read the source</a>.'
            '</p></noscript><script src="wasm-strings.js">'
        ),
        '<span data-i18n>Turn your phone sideways to play</span>': (
            '<span>Open the game on desktop, or watch it here.</span>' + NAV
        ),
    }
    for marker, replacement in additions.items():
        if html.count(marker) != 1:
            raise ValueError(f"Expected exactly one {marker!r} in the packaged Wasm shell")
        html = html.replace(marker, replacement)
    shutil.copytree(ROOT / "web", site, dirs_exist_ok=True)
    shutil.copyfile(ROOT / "LICENSE", site / "LICENSE.txt")
    shutil.copyfile(ROOT / "FREEDOOM-COPYING.txt", site / "FREEDOOM-COPYING.txt")
    index.write_bytes(html.encode("utf-8"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", type=Path)
    prepare(parser.parse_args().site)
