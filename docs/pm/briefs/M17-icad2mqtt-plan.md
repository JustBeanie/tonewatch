# Brief: M17-plan — improvement plan for icad2mqtt (PLANNING ONLY)

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, medium
**Repo:** **`JustBeanie/icad2mqtt`** (Go), NOT ToneWatch. **Work dir:** the local clone `C:\Users\beanie\Documents\Proj\icad2mqtt` (branch `master`).
**This is a planning task.** It replaces the dispatcher's generic "verify with just check" instruction. **Do not modify, create or delete any file in any repository.** Your final message is the deliverable.

## Goal
The user wants icad2mqtt improved, "including parsing of the data and cleaning it up", so that ToneWatch can correlate CAD incidents with tone pages (ToneWatch `PLAN.md` M17). Produce a concrete, reviewable improvement plan. The PM will review it, and the user will see it before any code is written.

## Inputs to read
- Everything in the icad2mqtt clone: `main.go`, `main_test.go`, both Dockerfiles, `docker-compose.yml`, `icad2mqtt/` (the HA add-on: `config.yaml`, `run.sh`, its own `main.go`/`go.mod`), `.github/workflows/ci.yml`, `.golangci.yml`, `SECURITY_AUDIT.md`, `GITHUB_SETUP.md`, `repository.yaml`.
- ToneWatch's view of the integration (read-only): `C:\Users\beanie\Documents\Proj\tonewatch\PLAN.md` sections M16 and M17.
- The PM's **draft** contract in `C:\Users\beanie\Documents\Proj\tonewatch\docs\pm\briefs\M17a-icad2mqtt-json.md`. Critique it; don't treat it as settled.
- **The live source page.** You may fetch `https://911events.ongov.net/CADInet/app/events.jsp`, plus any category tab or "Closed Events" links it contains, **at most 6 requests in total, spaced at least 30 s apart**, using icad2mqtt's User-Agent. Also check for `robots.txt` or terms of use. Save nothing to disk.
- **Privacy:** never quote real incident contents (addresses, types, times) in your plan. Describe patterns abstractly, and use invented examples.

## The plan must cover
1. **Current-state audit.** Correctness, error handling, config, tests, CI, Docker images, the HA add-on (including the duplicated `main.go`/`go.mod` under `icad2mqtt/` and the two Dockerfiles), and security (from `SECURITY_AUDIT.md`). Rank each finding by severity.
2. **Source page analysis.**
   - The exact table and row structure, including the category tabs (County Fire, Syracuse Fire, Syracuse Police, County EMS, County Police) and whether they're separate URLs or parameters.
   - The Closed Events view, the "Updated:" timestamp, encoding (the server sends ISO-8859-1), and caching headers (ETag, Last-Modified).
   - How often the page actually changes.
3. **Parsing strategy.** Locate data by header labels, not table positions, and plan how to detect markup drift. Also cover how parse failures surface: metrics, an MQTT health/status topic, and logs without incident contents.
4. **Data cleaning and normalization spec** (the core of the request). For each field, give the raw form, the cleaned form, and the rules:
   - whitespace and case
   - agency canonical name and category (from the tabs, if they can be mapped reliably)
   - incident type (any code/description split, casing, a stable key)
   - address: whether the street can be reliably separated from a trailing place or business name; if not, keep `address_raw` plus a conservative cleaned form
   - municipality code to name: only from an authoritative source you can cite; otherwise mark unknown and leave it to the user
   - cross streets as a list
   - date/time to RFC 3339 in `America/New_York`, with DST handling
   - stable incident id and dedupe; what "updated" and "closed" mean
   - Say explicitly which rules are heuristics, and what their failure mode is.
5. **Output contract (schema v1).** MQTT topics, retained or not, QoS, and snapshot plus event payloads, with raw and clean fields side by side where cleaning is lossy.
   - Include LWT/availability, a health topic, and optional Home Assistant MQTT discovery (for example per-category active-incident counts), and say whether you recommend it.
   - Keep backwards compatibility for the current raw-HTML topic.
   - Give JSON examples with invented data.
6. **Polling etiquette and resilience.** Minimum interval, conditional requests, backoff with jitter on errors, a response size cap, a timeout, and what terms of use or robots require.
7. **Target code structure.** Go packages (fetch, parse, normalize, diff, publish, config), dependency choices (justify any new module; `golang.org/x/net/html` is pre-approved), and testability with fixture pages built from invented data.
8. **Packaging cleanup.** One source of truth for the binary, the add-on Dockerfile, multi-arch builds, `time/tzdata`, the non-root user, and CI (race tests, vet, gofmt, golangci-lint, govulncheck).
9. **Task breakdown.** Ordered, PR-sized tasks (ids `IC1`, `IC2`, …). Each has scope, files, acceptance criteria and tests, so the PM can turn them into engineer briefs.
10. **Risks and open questions for the user.** For example the page's terms of use, publishing addresses to a broker, retained data, and categories the page doesn't expose.

## Format
Markdown with the ten sections above, then the task table. Be specific: cite file:line for audit findings, and say what you observed on the live page (header labels, table nesting depth, number of rows, response headers). Don't include incident contents. State the date and time of your fetches.
