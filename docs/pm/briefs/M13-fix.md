# Brief: M13-fix — review findings + rebase conflicts

**From:** PM (Claude) · **To:** Codex engineer · **Model:** gpt-5.6-luna, high (resume of your M13 thread)
**Work dir:** worktree `tonewatch-m13`

## Situation
The PM reviewed M13 and found good work in these areas:
- The discovery tracker design and its memory caps
- The deterministic clustering
- An atomic clip replacement that writes the new file before deleting the old one
- `_safe_clip` tying a clip to exactly `recordings/discovered/<id>.mp3`
- Promote returning a draft without persisting it, plus audit rows
- The real `create_app` lifespan test
- The benchmark at about 1167× realtime

Seven findings must be fixed before landing.

The PM has stash-rebased this worktree onto current `main` (`15946af`). Since your base `f524529`, main gained:
- **M9:** Windows service and `selftest`, frozen `%PROGRAMDATA%`, mqtt close timeouts
- **M10a:** add-on mode, Supervisor MQTT credentials, `public_base_url`, the `db checkpoint` command, add-on target creation
- **PM docs:** `PLAN.md` and `PROGRESS.md`, including the new M12.5 line

These files have **conflict markers**:
- `docs/security/asvs/checklist.csv`
- `docs/security/threat-model/README.md`
- `web/src/api/openapi.json`
- `web/src/api/generated/schema.d.ts`

For the two generated files, don't hand-merge. Resolve them by regenerating with `just gen-api` after the backend merges.

## Required
1. **Resolve the rebase.** Keep both sides' behaviour.
   - M10a added `public_base_url`, so clip URLs in notifications must now be absolute when it is set, per brief M13.6. Drop the relative-only fallback where that setting exists, and test both cases.
   - Re-derive ASVS `path:line` evidence for every positive row (QUOTE_ALL, LF).
   - In `docs/PROGRESS.md`, keep main's lines and yours. Write the file with **LF** line endings; your working copy had CRLF.
2. **F1 (blocking): a repeat page of a KNOWN tone set within its cooldown is discovered as unknown.**
   - `_cooldown_allows` in `dsp/matcher.py` suppresses the `Detection`, so the tracker never sees a matched span and surfaces the second page as a new cluster.
   - Dispatchers routinely page twice, so this would create false "discovered" clusters for the user's own departments.
   - **Fix:** suppression must cover any segment run that *matches a configured tone set's definition*, whether or not a `Detection` was emitted (cooldown). Pick one design:
     - have the matcher report cooldown-suppressed matches as spans, or
     - check candidates against the configured tone sets before emitting.
   - Also suppress matches of **disabled** tone sets and of sets not assigned to that source. They are known to the user. Document this.
   - **Golden tests:**
     - The same known page twice within cooldown gives 0 candidates.
     - A known page from a disabled set gives 0 candidates.
     - A known page followed by an unknown page within cooldown still discovers only the unknown one.
3. **F2 (hardening; the PM confirmed the segmenter does populate the level): the level gate fails open.**
   - `ToneSegment.mean_level_dbfs` defaults to `-45.0`, which equals the gate threshold.
   - `_passes_gate` also uses `getattr(segment, "mean_level_dbfs", -45.0)`.
   - Any segment constructed without a level passes the gate. That covers test doubles and any future producer.
   - **Fix:**
     - Remove the getattr fallback.
     - Make the dataclass default fail closed, e.g. `-inf`, or make the field required and update the constructors.
   - **Test:** a regression test that a pure, stable tone at −60 dBFS with high purity gives 0 candidates, and the same tone at −30 dBFS gives 1. It may already be green; no red evidence is required for F2.
4. **F3: `DELETE /api/discovered-tones/{id}` returns 500 when the clip file is already gone.**
   - `_safe_clip` calls `path.resolve(strict=True)`, which raises `FileNotFoundError`, but only `ValueError` is caught.
   - Retention can remove clips, so the cluster then becomes undeletable.
   - **Fix:** a missing clip deletes the row and returns 200.
   - An invalid or foreign path must not unlink anything. Decide whether the row is still deleted and document the choice.
   - Test both cases, and assert no other file under the recordings root was touched.
5. **F4: `events: list[str]` on the MQTT, webhook and script targets accepts any string.**
   - A typo such as `pre-alert` silently disables that alert.
   - **Fix:** use `list[Literal["pre_alert", "recording_ready", "closed", "tone_discovered"]]` with de-duplication, plus a validation test.
   - Regenerate the API schema.
6. **F5: `?since=` accepts naive datetimes and imports inside the function.**
   - Require a timezone-aware ISO value, or treat a naive value as UTC explicitly. Normalize before comparison.
   - Move the import to module level.
   - Test that an offset value and a naive value give correct filtering.
7. **F6: `recording/discovery.py` calls `AudioEncoder._write`, a private method.**
   - Add a small public encoder API for encoding samples to a path, and use it here and wherever `_write` is reused.
   - Existing encoder tests stay green.
8. **F7: explain the skip count.** Your `just check` showed `4 skipped` where main shows 2. List every skipped test with its reason in the report. Any skip your change introduced must be removed or justified as environment-only, e.g. the private fixture being absent.

## Standing rules
- Never edit `docs/pm/**`.
- Never weaken a gate: no skips, deselects, exclusions, or lowered coverage. The 95% gate on `dsp/` and `pipeline/` still applies.
- Write the test first for `dsp/`, `pipeline/` and `alerts/`. Show the red failure for F1 and F2 in the report.
- Never fetch, commit or push.

## Definition of done
- No conflict markers remain: `rg -n "^(<<<<<<< |=======$|>>>>>>> )" backend web docs scripts .github docker` finds nothing.
- `just check` and `just test-slow` pass. Paste the tails.
- `just bench` still runs at ≥20× realtime. Paste the numbers.
- `api-drift` and e2e are host-only. The PM runs `ci-local` after you finish. You may leave the generated API files uncommitted; that is expected.
- The final message maps F1–F7 to fixes and tests, lists each conflicted file and how both sides were combined, and gives the skip list.
