#!/usr/bin/env python3
"""Assemble the claude.ai skill bundle.

    python tools/build_skill.py            # -> dist/marge/ and dist/marge.skill (zip)

The bundle is ``skill/`` (SKILL.md, references, launcher) plus a copy of the
``marge`` package, the example inputs, blank input templates and this
repository's README as the full user guide.
"""

from __future__ import annotations

import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "marge"
TEMPLATES = {
    "positions.csv": "symbol,quantity,price,type,basket,leverage,currency,underlying,put_call,strike,expiry,"
                     "implied_vol,multiplier\n",
    "securities.csv": "symbol,name,asset_id,issuer_id,country,sector,market_cap,adv,price,currency,is_etf,otc\n",
    "baskets.csv": "basket,symbol,weight\n",
    "config.toml": 'base_currency = "USD"\n\n[market]\nvix = 15.0\nvix_ema = 15.0\nrate = 0.04\n\n[fx_rates]\n',
}


def validate(skill_md: Path) -> None:
    text = skill_md.read_text()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        sys.exit("SKILL.md: missing YAML frontmatter")
    fields = dict(re.findall(r"^(\w[\w-]*):\s*(.*)$", m.group(1), re.MULTILINE))
    name, desc = fields.get("name", ""), fields.get("description", "")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name):
        sys.exit(f"SKILL.md: invalid name {name!r}")
    if not desc or len(desc) > 1024 or "<" in desc or ">" in desc:
        sys.exit(f"SKILL.md: description must be 1-1024 chars without angle brackets ({len(desc)})")


def build(out_dir: Path) -> Path:
    dest = out_dir / NAME
    if dest.exists():
        shutil.rmtree(dest)
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    shutil.copytree(ROOT / "skill", dest, ignore=ignore)
    shutil.copytree(ROOT / "marge", dest / "scripts" / "marge", ignore=ignore)
    shutil.copytree(ROOT / "examples", dest / "assets" / "examples", ignore=ignore)
    (dest / "assets" / "templates").mkdir(parents=True)
    for name, header in TEMPLATES.items():
        (dest / "assets" / "templates" / name).write_text(header)
    shutil.copy(ROOT / "README.md", dest / "references" / "guide.md")
    validate(dest / "SKILL.md")

    archive = out_dir / f"{NAME}.skill"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(dest.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(out_dir))
    return archive


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist"
    out.mkdir(parents=True, exist_ok=True)
    print(f"built {build(out)}")
