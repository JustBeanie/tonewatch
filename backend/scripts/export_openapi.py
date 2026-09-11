"""Export the FastAPI schema without starting a server."""

from __future__ import annotations

import json
from pathlib import Path

from tonewatch.api.app import create_app
from tonewatch.settings import Settings


def main() -> None:
    """Export the application schema to the committed frontend path."""
    app = create_app(Settings(data_dir=Path(".tools/api-gen-data")))
    output = Path(__file__).parents[2] / "web/src/api/openapi.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )


if __name__ == "__main__":
    main()
