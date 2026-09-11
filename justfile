set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]

uv := if os_family() == "windows" { ".tools/bin/uv.exe" } else { "uv" }
pnpm := if os_family() == "windows" { ".tools/bin/pnpm.cmd" } else { "pnpm" }

setup:
    {{uv}} sync --project backend
    {{pnpm}} --dir web install

lint:
    {{uv}} run --project backend ruff check backend/src backend/tests backend/scripts
    {{uv}} run --project backend ruff format --check backend/src backend/tests backend/scripts
    {{pnpm}} --dir web lint
    {{pnpm}} --dir web exec prettier --check .

fmt:
    {{uv}} run --project backend ruff format backend/src backend/tests backend/scripts
    {{pnpm}} --dir web exec prettier --write .

typecheck:
    {{uv}} run --project backend mypy backend/src backend/tests
    {{pnpm}} --dir web exec tsc -b

test:
    {{uv}} run --project backend pytest -c backend/pyproject.toml
    {{uv}} run --project backend python backend/scripts/check_package_coverage.py

test-web:
    {{pnpm}} --dir web test

check: lint typecheck test test-web

gen-api:
    @echo "API generation starts with M5.6."

dev:
    @echo "Development server starts with M5.1 and M6.1."

e2e:
    @echo "End-to-end tests start with M6.9."

bench:
    @echo "Benchmarks start with M2.6."

docker-build:
    @echo "Docker build starts with M8.1."

compose-up source="stream":
    @echo "Compose stack starts with M8.2."
