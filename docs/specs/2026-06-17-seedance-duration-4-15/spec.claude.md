# Seedance duration: accept any integer 4–15, and auto-derive BVAC clip length from the audio

- **Work type:** `refactor/migration`
- **Status:** `draft` → awaiting Aviv approval (do NOT dispatch until approved)
- **Review surface:** [`spec.human.md`](./spec.human.md)

## 1. Problem / Context
The MCP restricts Seedance `duration` to the set `(5, 10, 15)`, but PiAPI's `seedance-2` API accepts **any integer 4–15** in every mode. The restriction is the MCP's own invention, not an API constraint. Confirmed this session: PiAPI docs declare `duration: integer, minimum 4, maximum 15, default 5`; a live `seedance-2-less-restriction` / `omni_reference` job with an image + 6.6s driving audio and `duration: 7` completed and produced a **7.08s** clip (task `88d341f0-73fd-4bc2-89b7-fb765ab518c7`).

Two coupled effects of the artificial restriction:
1. English/text callers can't request 4,6,7,8,9,11–14s.
2. On the Hebrew/BVAC lip-sync path the clip length is the caller's `duration` snapped up to 5/10/15, so a 6.6s VO wastefully yields a 10s clip and the caller must guess a `duration` ≥ their speech.

## 2. Root Cause / Mechanism   <!-- refactor: "what enforces the old behavior + where it's consumed" -->
- The hard set lives in the schema: `ALLOWED_DURATIONS = (5, 10, 15)` — `video_mcp/schemas/seedance.py:21`; enforced at `video_mcp/schemas/seedance.py:46-47` (`if self.duration not in ALLOWED_DURATIONS: raise ValueError`).
- The snap-up helper: `round_duration_to_allowed(seconds)` returns 5/10/15 — `video_mcp/routing.py:12-25`.
- It is consumed **only** on the Hebrew/BVAC chain, on the caller's `duration` arg (NOT the audio length), at two sites:
  - `video_mcp/tools/seedance.py:341` — `resolved_for_audio = round_duration_to_allowed(duration)`, then audio-fit guard at `seedance.py:345-350` raises if `audio_len > resolved_for_audio` (the cutoff guard).
  - `video_mcp/tools/seedance.py:428` — `resolved_duration = round_duration_to_allowed(duration)`, used to build the black carrier at `seedance.py:436-438` and passed to `SeedanceVideoRequest(duration=resolved_duration)` at `seedance.py:448`.
- The BVAC audio is either caller-supplied (`audio_path` branch, `seedance.py:337-350`) or freshly TTS'd to a temp mp3 (`seedance.py:398-420`). The TTS branch does **not** currently probe its output; `probe_duration` is only called in the `audio_path` branch at `seedance.py:342`.
- Kling has its own `duration` param (`video_mcp/tools/kling.py:29,53`) and does **not** import `round_duration_to_allowed` (grep: only `tools/seedance.py:28` imports it) — out of scope, unaffected.
- Confirmed by repro: yes — live 7s job (above). Behavior under test is the API's, already observed.

## 3. Acceptance Criteria
- [ ] `generate_seedance_video` accepts any integer `duration` 4–15 on the English path; `duration=7` submits successfully. → (ask: "duration can be anywhere from 4-15")
- [ ] `duration=3` and `duration=16` raise a clear validation error. → (ask: "4-15")
- [ ] BVAC clip duration is set to `ceil(spoken-audio length)` clamped to [4,15], independent of the caller's `duration` arg. → (ask: "BVAC should just round to the closest full integer … a 12.6 MP4 should be rounded to 13 seconds" + AskUserQuestion: auto-derive)
- [ ] Ceil cases verified: 6.6→7, 12.4→13, 12.6→13, 2.1→4 (min clamp), 15.0→15; audio >15s after ceil raises a `split_audio` error. → (ask: "round to the closest full integer")
- [ ] Spoken audio is never truncated by the carrier (clip length ≥ audio length, by construction). → (ask: prior decision — ceil, never nearest-round)
- [ ] `uv run pytest` fully green. → (always-on: verify before done)

## 4. Scope & Non-Goals
**In scope:** `video_mcp/schemas/seedance.py` (duration validation), `video_mcp/routing.py` (the helper), `video_mcp/tools/seedance.py` (BVAC duration derivation, both branches), `tests/test_routing.py`, `tests/test_tools_seedance.py`.
**Non-goals (explicitly NOT doing):**
- No change to Kling (`tools/kling.py`, `schemas/kling.py`) — separate duration handling.
- No change to the content gate, the scribe/QA gates, mode inference, aspect-ratio, resolution, or the carrier-build mechanism itself.
- The `duration` arg keeps its `int` type and default `5` on the tool signature (`seedance.py:105`) — it simply stops being authoritative on the Hebrew path. Not removing it (English path still uses it).
- No new "derive duration from audio" behavior on the **English** path — there `duration` stays caller-set.

## 5. Key Decisions & Constraints
- **Decided:** BVAC clip length = `ceil(audio_len)` clamped [4,15], `duration` arg ignored on the Hebrew path (Aviv AskUserQuestion: "Auto-derive from audio (ceil)").
- **Decided:** round UP (ceil), never nearest-round (Aviv AskUserQuestion) — guarantees clip ≥ audio.
- **Decided:** rename `round_duration_to_allowed` → `ceil_audio_to_duration` (semantics changed from snap-to-set to ceil-clamp; the old name would mislead). Update the import at `seedance.py:28` and both call sites.
- **Constraint / must-not-break:** the `>15s audio → split_audio` error must survive (`seedance.py:348` message references `split_audio`; test asserts the substring at `tests/test_tools_seedance.py:313`). After ceil-derivation, audio with `ceil(len) > 15` is the trigger.
- **Constraint:** the audio length must be known **before** the carrier is built (`seedance.py:436`). For the TTS branch, probe the generated temp mp3 after it's written (`seedance.py:418-420`); for the `audio_path` branch, the probe already exists (`seedance.py:342`). Unify to a single probe → `ceil_audio_to_duration` just before carrier build.
- **Mirror existing:** the `audio_path`-branch probe call `media_mod.probe_duration(path, ffprobe_bin=deps.settings.ffprobe_bin)` (`seedance.py:342`) is the exact form to reuse for the TTS branch.

## 6. Code Surface Map
- `video_mcp/schemas/seedance.py:21,46-47` — replace `ALLOWED_DURATIONS` membership with `isinstance int and 4 ≤ duration ≤ 15`. (Keep a named constant, e.g. `DURATION_MIN, DURATION_MAX = 4, 15`.)
- `video_mcp/routing.py:12-25` — rename + rewrite to `ceil_audio_to_duration`.
- `video_mcp/tools/seedance.py:28` — update import name.
- `video_mcp/tools/seedance.py:337-350` — `audio_path` branch: keep file-exists check + probe; derive duration via `ceil_audio_to_duration(audio_len)`; the old `audio_len > resolved_for_audio` cutoff guard (`:345-350`) is removed (the ceil error in the helper covers >15; ceil guarantees fit otherwise).
- `video_mcp/tools/seedance.py:418-430` — after TTS writes the temp mp3, probe it; compute `resolved_duration = ceil_audio_to_duration(probe_duration(audio_path))`. Single derivation point shared by both branches is cleanest (probe `audio_path` once at ~`:427`, after both branches guarantee `audio_path` is set on disk).
- `video_mcp/tools/seedance.py:436-438,448` — build carrier and `SeedanceVideoRequest` with the derived `resolved_duration` (unchanged wiring).
- `tests/test_routing.py:16-36` — rewrite boundary/reject params + import name for ceil semantics.
- `tests/test_tools_seedance.py:50-58` — add a default `media_mod.probe_duration` mock to `_patch_chain` (e.g. `return_value=6.6`) so TTS-branch tests don't hit real ffprobe.
- `tests/test_tools_seedance.py:302-314` — `too_long_errors`: change probe `12.4 → 16.0` (12.4 now valid). Keep `split_audio` assertion.
- `tests/test_tools_seedance.py:413-416` — `invalid_duration`: `duration=7` now valid; change to `duration=16` (or `3`) to keep expecting a `ToolError`, and add a positive case asserting `7` submits.

## 7. Ultracode Dispatch Notes
**Build first (sequential):** the whole change is ~30 lines across 3 source files + 2 test files, tightly coupled (schema constant ↔ helper rename ↔ tool call sites ↔ tests all move together). **No fan-out** — implement in the main loop as one sequential edit, then run the suite once. Fanning this out would create pure collision (every slice touches `seedance.py` / the shared rename).

**Parallel slices:** none — see above.

**⛓ Collision audit:** N/A (single sequential edit).

**Each agent must:** N/A. The orchestrator (main loop) implements + runs `uv run pytest` + verifies §3, then reports the new HEAD SHA for the `MCP_PIN` bump.

```yaml
dispatch:
  frozen: []
  slices: []            # intentionally empty — coupled change, implement sequentially in main loop
  testRunner: "uv run pytest tests/test_routing.py tests/test_tools_seedance.py -q"
```

## 8. Assumptions & Open Questions
- **ASSUMPTION:** PiAPI enforces the documented 4–15 integer range in *all* modes/tiers we call (not just the omni_reference case tested). Couldn't verify every tier live; docs are uniform and one live omni_reference 7s job passed. Impact if wrong: an out-of-range value the MCP now allows could be rejected by PiAPI at submit (caught as a `PiapiError`, refunded — no silent failure).
- **ASSUMPTION:** `media_mod.probe_duration` on a freshly-TTS'd ElevenLabs mp3 returns the true speech length usable for ceil. It's the same probe already trusted for `audio_path` (`seedance.py:342`). Impact if wrong: derived clip could be off by the probe's error; mitigated by ceil + the carrier being silent-padded.
