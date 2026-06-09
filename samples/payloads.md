# Sample tool calls

Arguments shown as JSON objects (the MCP tool inputs). The server validates each
locally before any network call.

## 1. Single-shot Kling video

```json
{
  "tool": "generate_kling_video",
  "arguments": {
    "prompt": "Close-up, static camera, a woman in a summer dress near the sea introduces herself. @image_1",
    "images": ["https://example.com/ref.jpg"],
    "resolution": "1080p",
    "duration": 5,
    "aspect_ratio": "9:16",
    "enable_audio": true,
    "wait": false
  }
}
```

## 2a. Multi-shot Kling — SUCCESS

`shots` selects multi-shot mode; top-level `prompt`/`duration` are ignored.
Constraints: ≤6 shots, Σ duration ≤ 15s, each shot 1–14s.

```json
{
  "tool": "generate_kling_video",
  "arguments": {
    "shots": [
      { "prompt": "a dog stands near the sea", "duration": 2 },
      { "prompt": "the dog turns around and walks on the beach", "duration": 3 }
    ],
    "resolution": "1080p",
    "aspect_ratio": "16:9",
    "enable_audio": true
  }
}
```

## 2b. Multi-shot Kling — VALIDATION FAILURE

Raises `ToolError` before any HTTP call (7 shots > max 6, and Σ = 21 > 15s):

```json
{
  "tool": "generate_kling_video",
  "arguments": {
    "shots": [
      { "prompt": "s1", "duration": 3 }, { "prompt": "s2", "duration": 3 },
      { "prompt": "s3", "duration": 3 }, { "prompt": "s4", "duration": 3 },
      { "prompt": "s5", "duration": 3 }, { "prompt": "s6", "duration": 3 },
      { "prompt": "s7", "duration": 3 }
    ]
  }
}
```
Also fails: `shots` + `video` together (mutually exclusive); `video` set with >4 images.

## 3. Hebrew lipsync — transliteration + auto-chain to Seedance 2 + BVAC

Step 1 — transliterate the *visual* prompt (raw Hebrew is rejected by the video tool):

```json
{ "tool": "transliterate_hebrew", "arguments": { "text": "אישה צעירה מדברת אל המצלמה" } }
// LLM-backed (LMStudio gemma-4-e4b, OpenRouter fallback):
// -> { "input": "אישה צעירה מדברת אל המצלמה", "latin": "isha tze'ira medaberet el hamatzlema", "had_hebrew": true }
```

Step 2 — generate. `text` stays in **Hebrew** (it feeds TTS); `prompt` must be **Latin**:

```json
{
  "tool": "generate_seedance_video",
  "arguments": {
    "language": "he",
    "text": "שלום, קנו עכשיו את המוצר שלנו",
    "voice_id": "21m00Tcm4TlvDq8ikWAM",
    "prompt": "isha tze'ira medaberet el hamatzlema, close-up, soft daylight",
    "duration": 10,
    "resolution": "1080p",
    "wait": false
  }
}
```
The server forces `task_type="seedance-2"`, `mode="omni_reference"`, runs ElevenLabs
`eleven_v3`/`he`, builds the black carrier, uploads both files, and submits. Response
includes `task_id`, `audio_url`, `carrier_url`, `mode`, `task_type`.

> Passing raw Hebrew in `prompt` (instead of the Latin transliteration) raises a
> `ToolError` instructing you to call `transliterate_hebrew` first.

## 4. ElevenLabs voiceover (with timestamps)

```json
{
  "tool": "generate_elevenlabs_voiceover",
  "arguments": {
    "text": "Stop scrolling. This is the one product that actually works.",
    "voice_id": "21m00Tcm4TlvDq8ikWAM",
    "model_id": "eleven_multilingual_v2",
    "output_format": "mp3_44100_128",
    "with_timestamps": true
  }
}
// -> { "audio_path": "/tmp/....mp3", "output_format": "mp3_44100_128",
//      "model_id": "eleven_multilingual_v2", "alignment": { "characters": [...],
//      "character_start_times_seconds": [...], "character_end_times_seconds": [...] },
//      "characters": 58 }
```

`language="he"` auto-upgrades `model_id` to `eleven_v3` (only model supporting Hebrew).

## 5. Seedance first/last frame

```json
{
  "tool": "generate_seedance_first_last",
  "arguments": {
    "prompt": "smooth dolly-in from the wide shot to the close-up",
    "image_first": "https://example.com/first.jpg",
    "image_last": "https://example.com/last.jpg",
    "duration": 5
  }
}
```

## 6. Moderation bypass ladder (reference falsely flagged)

Clean first run with a model face reference (the chain composes `@image1`):
```json
{ "tool": "generate_seedance_video",
  "arguments": { "language":"he", "text":"היי, חייבת לספר לכם על המוצר", "voice_id":"<elevenlabs_voice_id>",
                 "prompt":"young woman talking to camera, cafe, UGC selfie",
                 "image_urls":["https://host/face.jpg"], "duration":10, "wait":true } }
```
If the response is a terminal moderation failure:
```json
{ "status":"failed", "failure_reason":"moderation",
  "provider_message":"Your content violated community guidelines.",
  "next_action":"apply_bypass", "next_method":"grid",
  "bypass_ladder":["grid","light_posterize","heavy_grid","heavy_posterize"],
  "instructions":"Run process_reference_for_moderation(image_url, method='grid') ... bypass_methods_used=['grid']" }
```
Process the reference and re-submit (same prompt, processed image, ladder state):
```json
{ "tool":"process_reference_for_moderation", "arguments":{ "image":"https://host/face.jpg", "method":"grid" } }
// -> { "processed_url":"https://tmpfiles.org/dl/.../modref_grid.png", "method":"grid", ... }

{ "tool":"generate_seedance_video",
  "arguments":{ "language":"he", "text":"...", "voice_id":"...", "prompt":"<same prompt>",
                "image_urls":["https://tmpfiles.org/dl/.../modref_grid.png"],
                "bypass_methods_used":["grid"], "duration":10, "wait":true } }
```
Escalate `grid → light_posterize → heavy_grid → heavy_posterize` on repeat failure; stop when `next_action=="stop"`.

## 7. Poll a task

```json
{ "tool": "get_task", "arguments": { "task_id": "5a9b4d8f-6f1c-460d-b295-ab1d663f9b90" } }
// -> { "task_id": "...", "status": "completed", "video_url": "https://.../out.mp4", "error": null }
```
