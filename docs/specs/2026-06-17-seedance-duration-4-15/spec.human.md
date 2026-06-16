# Seedance duration: accept any integer 4–15, and auto-derive BVAC clip length from the audio

**Type:** `refactor/migration`  ·  **Full spec:** [`spec.claude.md`](./spec.claude.md)

## ✅ What you'll see when this is done
- `generate_seedance_video` accepts any integer `duration` from **4 to 15** (today only 5/10/15). A `duration=7` English job submits and returns a 7s clip.
- On the **Hebrew/BVAC** path the `duration` arg is **ignored** — the clip length is set automatically to `ceil(spoken-audio length)`, clamped to 4–15. A 6.6s VO → 7s clip; a 12.6s VO → 13s clip; a 12.4s VO → 13s clip (never truncated). Audio longer than 15s still errors and tells you to `split_audio`.

## ⚠️ Decisions you're approving
- **BVAC clip length auto-derives from the audio (`ceil`), `duration` arg ignored on the Hebrew path** — chose this over *keeping `duration` caller-set* (your AskUserQuestion answer). The carrier now always matches the speech; you never guess a duration for Hebrew.
- **Round UP (ceil), never nearest-round** — chose this over *nearest-integer* so the last fraction of a second of speech is never cut off (≤1s of trailing silent pad instead).
- **Rename `round_duration_to_allowed` → `ceil_audio_to_duration`** — the old name describes the old 5/10/15-snap semantics; keeping it would be a lie. Pure rename, same two call sites.

## 🎲 Riding on these assumptions
- **PiAPI accepts any integer 4–15 in every mode we use** — verified this session: docs say `integer, min 4, max 15`, and a live `duration=7` omni_reference job (image + audio) completed at 7.08s. (High confidence.)
- **Nothing outside the two known call sites depends on the 5/10/15 snap** — grep found only `schemas/seedance.py:46` (the hard check) and `seedance.py:341,428` (the helper). Kling has its own separate duration handling and is untouched.
- **`probe_duration` on a fresh ElevenLabs mp3 gives a usable speech length to ceil** — it's the same probe already trusted for caller-supplied `audio_path`. If it's off, the derived clip is off by that error (softened by ceil + silent padding).

## 🪤 Gotchas
- The TTS branch of the BVAC chain currently never probes its generated mp3 — auto-derive means it now must. Tests that stub the chain (`_patch_chain`) don't mock `probe_duration`; they'll hit real ffprobe on fake bytes and blow up unless the stub gains a default `probe_duration` mock.
- Two existing tests assert the *old* behavior and must flip, not just pass: `duration=7` must stop being an error; the "audio too long" case must move from 12.4s to >15s (12.4 is now valid).

## Done when
- [ ] `duration=7` (and any int 4–15) submits on the English path; `duration=3` and `duration=16` raise.
- [ ] BVAC clip duration = `ceil(audio_len)` clamped [4,15] — verified for 6.6→7, 12.4→13, 2.1→4, and >15→`split_audio` error.
- [ ] Spoken audio is never truncated by the carrier (clip ≥ audio length, always).
- [ ] Full `uv run pytest` suite green (updated + new cases).

## The plan
1. `schemas/seedance.py`: replace the `ALLOWED_DURATIONS` membership check with `4 ≤ duration ≤ 15` (int). Default stays 5.
2. `routing.py`: replace `round_duration_to_allowed` with `ceil_audio_to_duration(seconds)` → `clamp(ceil(seconds), 4, 15)`, `>15`→ValueError(split), `≤0`→ValueError.
3. `tools/seedance.py`: derive `resolved_duration` from the **audio length** (probe the supplied or TTS-generated mp3) for both BVAC branches; drop the now-redundant cutoff guard (replaced by the ≤15 ceil error).
4. Update `test_routing.py` + `test_tools_seedance.py` (flip the two old-behavior tests, add a default `probe_duration` mock to `_patch_chain`, add 4–15 + ceil cases).
5. One sequential edit — too small/coupled to fan out. Run suite, then bump `MCP_PIN`.

## ✂️ Not asked for — cut?
- *(none — rename + the two coupled changes all trace to your ask.)*
