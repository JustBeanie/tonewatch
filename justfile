set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"]

uv := if os_family() == "windows" { ".tools/bin/uv.exe" } else { "uv" }
uvx := if os_family() == "windows" { ".tools/bin/uvx.exe" } else { "uvx" }
pnpm := if os_family() == "windows" { ".tools/bin/pnpm.cmd" } else { "pnpm" }
export PLAYWRIGHT_CHANNEL := if os_family() == "windows" { "chrome" } else { "" }
export TONEWATCH_E2E_PORT := if os_family() == "windows" { "8790" } else { "8765" }

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
    {{pnpm}} --dir web exec tsc -p tsconfig.e2e.json --noEmit

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
    {{uv}} run --project backend python scripts/check_action_pins.py .github/workflows/*.yml
    {{pnpm}} --dir web audit --audit-level high
    {{pnpm}} --dir web licenses list --prod --json > .tools/web-licenses.json
    {{uv}} run --project backend python scripts/license_check.py --python-requirements .tools/security-requirements.txt --web-licenses .tools/web-licenses.json
    {{uv}} run --project backend python scripts/security_scorecard.py --check
    @echo "NOTICE: semgrep is CI-only (container required); skipped locally."
    @echo "NOTICE: osv-scanner is CI-only (container required); skipped locally."
    @echo "NOTICE: trivy config is CI-only (container required); skipped locally."
    @echo "NOTICE: gitleaks is CI-only (binary/container required); skipped locally."

check: lint typecheck test test-web security-scorecard

precommit:
    {{uvx}} --python 3.13.13 pre-commit run --all-files

# Local CI while GitHub Actions is disabled: run before every push. Container-only checks
# (image build/size, trivy, semgrep, osv-scanner, gitleaks history, ZAP) are paused until CI returns.
ci-local: precommit check security api-drift e2e

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
    {{pnpm}} --dir web exec playwright test

[unix]
windows-build:
    @echo "windows-build requires a Windows host with PyInstaller." >&2; exit 1

[windows]
windows-build:
    {{pnpm}} --dir web build
    if (Test-Path backend/src/tonewatch/web_dist) { Remove-Item -Recurse -Force backend/src/tonewatch/web_dist }
    Copy-Item -Recurse web/dist backend/src/tonewatch/web_dist
    {{uv}} run --project backend pyinstaller --clean --noconfirm packaging/windows/tonewatch.spec

bench:
    {{uv}} run --project backend python backend/scripts/run_pytest.py backend/tests/benchmarks --benchmark-only --no-cov

[unix]
docker-build:
    @command -v docker >/dev/null 2>&1 || { echo "Docker is required for docker-build; install Docker Engine." >&2; exit 1; }; docker buildx build --platform linux/amd64,linux/arm64 -f docker/Dockerfile .

[windows]
docker-build:
    @if (Get-Command docker -ErrorAction SilentlyContinue) { docker buildx build --platform linux/amd64,linux/arm64 -f docker/Dockerfile . } else { throw "Docker is required for docker-build; install Docker Desktop or Docker Engine." }

[unix]
compose-up source="stream":
    @requested="{{source}}"; case "$requested" in source=*) requested="${requested#source=}";; esac; case "$requested" in soundcard|stream|rtlsdr) ;; *) echo "source must be soundcard, stream, or rtlsdr" >&2; exit 2;; esac; command -v docker >/dev/null 2>&1 || { echo "Docker is required for compose-up; install Docker Engine." >&2; exit 1; }; docker compose -f "docker/compose.$requested.yml" up

[windows]
compose-up source="stream":
    @$requested = "{{source}}"; if ($requested.StartsWith("source=")) { $requested = $requested.Substring(7) }; if ("soundcard","stream","rtlsdr" -notcontains $requested) { throw "source must be soundcard, stream, or rtlsdr" } elseif (Get-Command docker -ErrorAction SilentlyContinue) { docker compose -f "docker/compose.$requested.yml" up } else { throw "Docker is required for compose-up; install Docker Desktop or Docker Engine." }
