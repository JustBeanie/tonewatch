set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]

uv := if os_family() == "windows" { ".tools/bin/uv.exe" } else { "uv" }
uvx := if os_family() == "windows" { ".tools/bin/uvx.exe" } else { "uvx" }
pnpm := if os_family() == "windows" { ".tools/bin/pnpm.cmd" } else { "pnpm" }

setup:
    {{uv}} sync --project backend
    {{pnpm}} --dir web install

lint:
    {{uv}} run --project backend ruff check backend/src backend/tests backend/scripts scripts
    {{uv}} run --project backend ruff format --check backend/src backend/tests backend/scripts scripts
    {{pnpm}} --dir web lint
    {{pnpm}} --dir web exec prettier --check .

fmt:
    {{uv}} run --project backend ruff format backend/src backend/tests backend/scripts
    {{pnpm}} --dir web exec prettier --write .

typecheck:
    {{uv}} run --project backend mypy backend/src backend/tests scripts
    {{pnpm}} --dir web exec tsc -b

test:
    {{uv}} run --project backend python backend/scripts/run_pytest.py
    {{uv}} run --project backend python backend/scripts/check_package_coverage.py

test-slow:
    {{uv}} run --project backend python backend/scripts/run_pytest.py -m slow --no-cov

test-web:
    {{pnpm}} --dir web test

security-scorecard:
    {{uv}} run --project backend python scripts/security_scorecard.py --check

security:
    {{uv}} run --project backend python -c "from pathlib import Path; Path('.tools').mkdir(exist_ok=True)"
    {{uv}} export --project backend --frozen --no-dev --no-emit-project --format requirements-txt > .tools/security-requirements.txt
    {{uv}} run --project backend --with pip-audit pip-audit -r .tools/security-requirements.txt --cache-dir .tools/pip-audit-cache
    {{uv}} run --project backend --with zizmor zizmor .github/workflows
    {{pnpm}} --dir web audit --audit-level high
    {{pnpm}} --dir web licenses list --prod --json > .tools/web-licenses.json
    {{uv}} run --project backend python scripts/license_check.py --python-requirements .tools/security-requirements.txt --web-licenses .tools/web-licenses.json
    {{uv}} run --project backend python scripts/security_scorecard.py --check
    @echo "NOTICE: semgrep is CI-only (container required); skipped locally."
    @echo "NOTICE: osv-scanner is CI-only (container required); skipped locally."
    @echo "NOTICE: trivy config is CI-only (container required); skipped locally."
    @echo "NOTICE: gitleaks is CI-only (binary/container required); skipped locally."

check: lint typecheck test test-web security-scorecard

gen-api:
    {{uv}} run --project backend python backend/scripts/export_openapi.py
    {{uv}} run --project backend python backend/scripts/generate_ws_messages.py
    {{pnpm}} --dir web exec openapi-typescript src/api/openapi.json -o src/api/generated/schema.d.ts

api-drift:
    just gen-api
    git diff --exit-code -- web/src/api

dev:
    @echo "Development server starts with M5.1 and M6.1."

e2e:
    @echo "End-to-end tests start with M6.9."

bench:
    {{uv}} run --project backend python backend/scripts/run_pytest.py backend/tests/benchmarks --benchmark-only --no-cov

docker-build:
    @echo "Docker build starts with M8.1."

compose-up source="stream":
    @echo "Compose stack starts with M8.2."
