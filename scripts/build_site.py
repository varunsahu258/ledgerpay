"""Export the FastAPI schema and assemble the static GitHub Pages site."""

import json
import re
import shutil
from pathlib import Path

from app.main import app

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
REDOC_VERSION = "2.5.3"
REDOC_CDN_URL = f"https://cdn.redoc.ly/redoc/v{REDOC_VERSION}/bundles/redoc.standalone.js"


def main() -> None:
    SITE.mkdir(exist_ok=True)
    spec = app.openapi()
    encoded = json.dumps(spec, indent=2, sort_keys=True) + "\n"
    (ROOT / "openapi.json").write_text(encoded, encoding="utf-8")
    (SITE / "openapi.json").write_text(encoded, encoding="utf-8")
    shutil.copyfile(ROOT / "tests/results/invariants.json", SITE / "invariants.json")
    (SITE / ".nojekyll").touch()
    api_reference = SITE / "api.html"
    html = api_reference.read_text(encoding="utf-8")
    html = re.sub(
        r"https://cdn\.redoc\.ly/redoc/[^/]+/bundles/redoc\.standalone\.js",
        REDOC_CDN_URL,
        html,
    )
    api_reference.write_text(html, encoding="utf-8")
    print(f"Built static docs and results page in {SITE}")


if __name__ == "__main__":
    main()
