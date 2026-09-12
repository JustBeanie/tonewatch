"""Consistency checks for the code-grounded STRIDE threat model."""

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).parents[3]
MODEL = ROOT / "docs/security/threat-model/tonewatch.json"
README = ROOT / "docs/security/threat-model/README.md"
GAPS = ROOT / "docs/security/gaps.md"


def _threat_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    in_table = False
    for line in README.read_text(encoding="utf-8").splitlines():
        if line.startswith("| ID | STRIDE |"):
            in_table = True
            continue
        if not in_table or line.startswith("| ---") or not line.startswith("|"):
            continue
        values = [value.strip().strip("`") for value in line.strip("|").split("|")]
        if len(values) == 9 and re.fullmatch(r"TM-\d{3}", values[0]):
            rows.append(
                dict(
                    zip(
                        (
                            "id",
                            "category",
                            "element",
                            "description",
                            "likelihood",
                            "impact",
                            "status",
                            "evidence",
                            "owner",
                        ),
                        values,
                        strict=True,
                    )
                )
            )
    assert rows
    return rows


def _test_functions() -> set[str]:
    functions: set[str] = set()
    for path in (ROOT / "backend/tests").rglob("test_*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions.update(
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        )
    return functions


def test_threat_model_schema_and_inventory_are_consistent() -> None:
    model = json.loads(MODEL.read_text(encoding="utf-8"))
    assert {"version", "summary", "detail", "owner", "reviewer", "diagrams"} <= model.keys()
    assert model["version"] == "2.0"
    assert len(model["diagrams"]) == 1
    diagram = model["diagrams"][0]
    assert {"diagramType", "id", "title", "diagramJson", "threats"} <= diagram.keys()
    assert diagram["diagramType"] == "STRIDE"
    assert {"cells"} <= diagram["diagramJson"].keys()
    kinds = {cell["type"] for cell in diagram["diagramJson"]["cells"]}
    assert {"tm.Actor", "tm.Process", "tm.Store", "tm.Flow", "tm.Boundary"} <= kinds
    readme_rows = _threat_rows()
    readme_ids = {row["id"] for row in readme_rows}
    json_ids = {threat["id"] for threat in diagram["threats"]}
    assert readme_ids == json_ids


def test_threat_evidence_is_real_and_mitigations_have_proving_tests() -> None:
    functions = _test_functions()
    for row in _threat_rows():
        refs = re.findall(r"([A-Za-z0-9_./-]+):(\d+)", row["evidence"])
        assert refs, row["id"]
        for relative, line_text in refs:
            path = ROOT / relative
            assert path.is_file(), (row["id"], relative)
            assert len(path.read_text(encoding="utf-8").splitlines()) >= int(line_text), row["id"]
        if row["status"] == "mitigated":
            named = [
                name
                for name in re.findall(r"test_[A-Za-z0-9_]+", row["evidence"])
                if name in functions
            ]
            assert named and named[0] in functions, row["id"]


def test_unresolved_threats_are_recorded_as_security_gaps() -> None:
    gaps = GAPS.read_text(encoding="utf-8")
    for row in _threat_rows():
        if row["status"] in {"open", "partial"}:
            assert row["id"] in gaps, row["id"]
