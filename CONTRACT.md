# FROZEN CONTRACT — video_mcp

Every module is implemented against the interfaces below. Do **not** change a
signature, field name, or import path defined here. The spine modules
(`errors.py`, `config.py`, `logging_config.py`, `schemas/common.py`) are already
written and verified — import from them, do not modify them.

Python 3.14, pydantic v2, httpx (async), fastmcp 3.4.2. Tests use `pytest`,
`pytest-asyncio` (asyncio_mode=auto), and `respx` for HTTP mocking.

## Package layout

```
video_mcp/
  __init__.py            [done]
  errors.py              [done]  VideoMCPError, ConfigError, ProviderError,
                                 PiapiError, ElevenLabsError, UploadError, CarrierError
  config.py              [done]  Settings, get_settings()
  logging_config.py      [done]  get_logger(name), redact(obj)
  schemas/
    common.py            [done]  ServiceMode, WebhookConfig, TaskResult, TERMINAL_STATUSES
    kling.py             [BUILD]
    seedance.py          [BUILD]
    elevenlabs.py        [BUILD]
  clients/
    __init__.py          [BUILD] empty
    piapi.py             [BUILD]  PiapiClient
    elevenlabs.py        [BUILD]  ElevenLabsClient
  utils/
    __init__.py          [BUILD] empty
    transliterate.py     [BUILD]  transliterate_hebrew, has_hebrew
    carrier.py           [BUILD]  make_black_carrier
    uploader.py          [BUILD]  upload_file
  routing.py             [BUILD]  duration helpers + Hebrew routing
  tools/
    __init__.py          [BUILD] empty
    kling.py             [BUILD]  register_kling_tools(mcp, deps)
    seedance.py          [BUILD]  register_seedance_tools(mcp, deps)
    seedance_flf.py      [BUILD]  register_seedance_flf_tools(mcp, deps)
    elevenlabs.py        [BUILD]  register_elevenlabs_tools(mcp, deps)
    misc.py              [BUILD]  register_misc_tools(mcp, deps)
  server.py              [BUILD]  build_server() -> FastMCP, main()
tests/
  conftest.py            [BUILD]  shared fixtures
  test_*.py              [BUILD]  one per module
```

---

## errors.py  (DONE — reference only)

```python
VideoMCPError(Exception)
ConfigError(VideoMCPError)
ProviderError(VideoMCPError): __init__(message, *, code=None, raw=None, provider="")
    .message .code .raw .provider
PiapiError(ProviderError)        # provider="piapi"
ElevenLabsError(ProviderError)   # provider="elevenlabs"
UploadError(VideoMCPError)
CarrierError(VideoMCPError)
```

## config.py  (DONE — reference only)

```python
@dataclass Settings:
    piapi_key: str|None; elevenlabs_key: str|None
    piapi_base="https://api.piapi.ai/api/v1"
    elevenlabs_base="https://api.elevenlabs.io/v1"
    tmpfiles_upload_url="https://tmpfiles.org/api/v1/upload"
    poll_interval_s=5.0; poll_timeout_s=1800.0; ffmpeg_bin="ffmpeg"
    require_piapi() -> str        # raises ConfigError if unset
    require_elevenlabs() -> str   # raises ConfigError if unset
get_settings() -> Settings
```

## logging_config.py  (DONE — reference only)

```python
get_logger(name: str) -> logging.Logger   # namespaced under "video_mcp"
redact(obj) -> obj                         # masks x-api-key/xi-api-key/secret/etc
```

## schemas/common.py  (DONE — reference only)

```python
ServiceMode = Literal["public","private"]
TERMINAL_STATUSES = {"completed","failed"}
class WebhookConfig(BaseModel): endpoint: str; secret: str = ""
class TaskResult(BaseModel):
    task_id, status, model, task_type, output: dict|None, error: dict|None, raw: dict
    .normalized_status -> str        # lowercased
    .is_terminal -> bool             # completed/failed
    .is_failed -> bool
    .video_url -> str|None           # output["video"] or None
    .error_message -> str|None
    classmethod from_piapi(body: dict) -> TaskResult   # parses both envelopes
```

---

# MODULES TO BUILD

## schemas/kling.py

Pydantic models for `generate_kling_video`. Enforce ALL constraints in validators
(raise pydantic ValueError so tools convert to ToolError).

```python
KlingResolution = Literal["720p","1080p"]
KlingAspectRatio = Literal["16:9","9:16","1:1"]

class KlingShot(BaseModel):
    prompt: str (min_length 1)
    duration: int = 3            # ge=1, le=14

class KlingVideoRequest(BaseModel):
    prompt: str|None = None              # ignored if shots set; may contain @image_1.., @video
    shots: list[KlingShot]|None = None   # multi-shot; ≤6 items; sum(durations) ≤ 15
    version: Literal["3.0"] = "3.0"
    resolution: KlingResolution = "1080p"     # skill production default
    duration: int = 5                    # ge=3, le=15 ; single-shot only
    aspect_ratio: KlingAspectRatio = "16:9"
    enable_audio: bool = True
    images: list[str]|None = None        # HTTP url strings
    video: str|None = None               # HTTP url
    keep_original_audio: bool = False    # only meaningful with video reference
    service_mode: ServiceMode|None = None
```

Cross-field validation (model_validator):
- shots and video are MUTUALLY EXCLUSIVE -> ValueError.
- if shots: len 1..6, sum(shot.duration) <= 15. prompt/duration are ignored (allowed but documented).
- if not shots and not prompt -> ValueError ("prompt or shots required").
- images: if video is set -> max 4 images; else max 7. (>limit -> ValueError)
- if video set: force enable_audio handling is the TOOL's job, but model should
  allow keep_original_audio only when video set (keep_original_audio=True without
  video -> ValueError).

Method to build the PiAPI body:
```python
def to_piapi_input(self) -> dict   # builds the "input" dict per Kling Omni docs
# top-level body assembled by client/tool: model="kling", task_type="omni_video_generation"
```
`to_piapi_input` rules:
- always include version, resolution, aspect_ratio, enable_audio.
- if shots: include "multi_shots": [{"prompt","duration"}...]; do NOT include prompt/duration.
- else: include "prompt" and "duration".
- include "images" / "video" / "keep_original_audio" only when set/truthy.

## schemas/seedance.py

```python
SeedanceTaskType = Literal["seedance-2","seedance-2-fast"]   # NO -less-restriction
SeedanceMode = Literal["text_to_video","first_last_frames","omni_reference"]
SeedanceResolution = Literal["480p","720p","1080p"]
SeedanceAspectRatio = Literal["21:9","16:9","4:3","1:1","3:4","9:16","auto"]
ALLOWED_DURATIONS = (5, 10, 15)     # UGC operational contract (provider allows 4-15)

class SeedanceVideoRequest(BaseModel):
    prompt: str                          # ≤4000 chars
    task_type: SeedanceTaskType = "seedance-2"
    mode: SeedanceMode|None = None       # auto-inferred if None (see routing)
    duration: int = 5                    # MUST be in {5,10,15} -> else ValueError
    resolution: SeedanceResolution = "720p"
    aspect_ratio: SeedanceAspectRatio = "16:9"
    image_urls: list[str]|None = None    # ≤12
    video_urls: list[str]|None = None    # omni_reference only
    audio_urls: list[str]|None = None    # omni_reference only; must accompany image/video
    service_mode: ServiceMode|None = None
```

Validation:
- duration in {5,10,15} else ValueError listing allowed values.
- prompt length ≤ 4000.
- resolution "1080p" with task_type "seedance-2-fast" -> ValueError (fast has no 1080p).
- mode inference when None: no refs -> text_to_video; exactly 1-2 images & no video/audio
  -> first_last_frames; otherwise -> omni_reference.
- text_to_video must have NO refs (image/video/audio) -> else ValueError.
- first_last_frames: 1-2 images, no video, no audio.
- omni_reference: 1..12 total refs; audio present requires >=1 image or video (audio-only rejected).
- image_urls length ≤ 12.

```python
def to_piapi_input(self) -> dict     # resolves mode, builds Seedance input dict
```

## schemas/elevenlabs.py

```python
TextNormalization = Literal["auto","on","off"]
HEBREW_MODEL = "eleven_v3"           # only model supporting Hebrew

class VoiceSettings(BaseModel):
    stability: float = 0.5
    similarity_boost: float = 0.75
    style: float = 0.0
    use_speaker_boost: bool = True
    speed: float = 1.0

class VoiceoverRequest(BaseModel):
    text: str (min_length 1)
    voice_id: str (min_length 1)
    language: str|None = None            # ISO 639-1; "he" forces model_id=eleven_v3
    model_id: str = "eleven_multilingual_v2"
    voice_settings: VoiceSettings|None = None
    output_format: str = "mp3_44100_128"
    seed: int|None = None                # 0..4294967295
    previous_text: str|None = None
    next_text: str|None = None
    with_timestamps: bool = True         # default ON -> use the /with-timestamps endpoint
```

Validation (model_validator):
- if language == "he": model_id MUST be "eleven_v3". If caller left default
  ("eleven_multilingual_v2"), AUTO-SET model_id="eleven_v3". If caller explicitly
  set a non-v3 model with language "he" -> ValueError (Hebrew needs eleven_v3).
- seed if set in 0..4294967295.

```python
def to_body(self) -> dict   # request JSON body (text, model_id, voice_settings as
                            # dict, language_code from language, seed, previous/next_text)
```
Note: ElevenLabs body field is `language_code` (value from `language`).

## utils/transliterate.py  (LLM-backed — UPDATED post-build)

Rule-based letter mapping CANNOT recover the unwritten vowels of an abjad
(שלום has no letter for the `a` in "shalom"), so transliteration is delegated to an
LLM: local LMStudio first (default `google/gemma-4-e4b`), OpenRouter fallback.

```python
def has_hebrew(text: str) -> bool          # pure; U+0590..U+05FF or U+FB1D..U+FB4F
async def transliterate_hebrew(text, settings=None, client=None) -> str
    # If no Hebrew -> return text unchanged (no network call).
    # 1) POST {lmstudio_base_url}/chat/completions (no auth) with few-shot system prompt;
    # 2) on httpx error / empty / still-Hebrew result, fall back to OpenRouter
    #    (Authorization: Bearer OPENROUTER_API_KEY) if a key is set;
    # 3) if both fail or result still contains Hebrew -> raise TransliterationError.
    # Output is cleaned: strip <think>..</think>, surrounding quotes, whitespace.
```
Config (config.py): lmstudio_base_url, lmstudio_model, openrouter_base_url,
openrouter_api_key, openrouter_model, transliterate_max_tokens (512),
transliterate_timeout_s (60). Recommended LMStudio context length: 4096.

## utils/carrier.py

```python
def make_black_carrier(duration_s: int|float, out_path: str, *,
                       ffmpeg_bin: str = "ffmpeg",
                       width: int = 720, height: int = 1280, fps: int = 24) -> str
    # Generate a black silent MP4 of duration_s seconds at out_path using ffmpeg
    # lavfi color source. duration_s must be > 0 and <= 15 (else CarrierError).
    # Runs ffmpeg via subprocess; on non-zero exit raise CarrierError with stderr tail.
    # Returns out_path. Command shape:
    #   ffmpeg -y -f lavfi -i color=c=black:s={w}x{h}:r={fps}:d={dur} \
    #          -f lavfi -i anullsrc=r=44100:cl=stereo -t {dur} \
    #          -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest {out}
```

## utils/uploader.py

```python
async def upload_file(path: str, *, upload_url: str, client: httpx.AsyncClient|None = None) -> str
    # POST multipart file to tmpfiles.org api. Response JSON:
    #   {"status":"success","data":{"url":"https://tmpfiles.org/<id>/<name>"}}
    # tmpfiles returns a page URL; convert to DIRECT-download form by inserting
    # "/dl/" after the host:  https://tmpfiles.org/dl/<id>/<name>
    # Return the direct URL. Raise UploadError on failure / missing url.
    # If client is None, create a temporary httpx.AsyncClient.
```

## routing.py

Pure functions — no I/O. The Hebrew orchestration policy lives here.

```python
def round_duration_to_allowed(seconds: float) -> int
    # <=5 ->5 ; >5 and <=10 ->10 ; >10 and <=15 ->15 ; >15 -> ValueError.

def infer_seedance_mode(*, n_images, n_videos, n_audios) -> str
    # mirrors schemas/seedance.py inference: 0 refs->text_to_video;
    # 1-2 images & no video/audio -> first_last_frames; else omni_reference.

def is_hebrew_request(language: str|None) -> bool
    # True iff language is not None and language.lower() in {"he","heb","hebrew","iw"}.
```

The Hebrew lipsync auto-chain is orchestrated in tools/seedance.py using these
helpers + clients + utils. Policy (enforce in the tool):
1. language is Hebrew -> force task_type="seedance-2", mode="omni_reference".
2. the VISUAL prompt must be Latin: if has_hebrew(prompt) -> ToolError telling the
   caller to use transliterate_hebrew first. (The spoken `text` is exempt — Hebrew OK.)
3. synthesize speech via ElevenLabsClient (model eleven_v3, language_code "he"),
   write audio to temp file.
4. duration = round_duration_to_allowed(measured/declared audio length). If audio
   length unknown, use provided duration (must be 5/10/15).
5. make_black_carrier(duration) -> temp mp4.
6. upload audio + carrier via upload_file -> URLs.
7. submit Seedance omni_reference with audio_urls=[audio], video_urls=[carrier].

---

## clients/piapi.py

```python
class PiapiClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient|None = None)
    async def create_task(self, *, model: str, task_type: str, input: dict,
                          config: dict|None = None) -> TaskResult
        # POST {base}/task  headers {"x-api-key": settings.require_piapi(),
        #   "Content-Type":"application/json"}
        # body {"model","task_type","input", optional "config"}
        # log redacted payload. On HTTP>=400 OR body code not in (200,None)+error
        # -> PiapiError(message from body.code/message/error). Else TaskResult.from_piapi.
    async def get_task(self, task_id: str) -> TaskResult
        # GET {base}/task/{task_id}. Parse with TaskResult.from_piapi.
    async def wait_for_task(self, task_id: str, *, interval: float|None = None,
                            timeout: float|None = None) -> TaskResult
        # poll get_task until is_terminal or timeout (PiapiError on timeout).
        # interval/timeout default to settings.poll_interval_s/poll_timeout_s.
        # Use asyncio.sleep. Treat transient non-JSON / parse errors as keep-polling.
```
Error parsing: PiAPI success body has `code==200`. Treat `code` present and != 200
as error (message = body["message"] or body["data"]["error"]["message"]).

## clients/elevenlabs.py

```python
class ElevenLabsClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient|None = None)
    async def tts(self, req: VoiceoverRequest) -> bytes
        # POST {base}/text-to-speech/{voice_id}?output_format=...  headers {"xi-api-key":...}
        # body req.to_body(); returns raw audio bytes. ElevenLabsError on >=400
        # (parse JSON detail if present).
    async def tts_with_timestamps(self, req: VoiceoverRequest) -> tuple[bytes, dict]
        # POST {base}/text-to-speech/{voice_id}/with-timestamps?output_format=...
        # Response JSON: {"audio_base64": "...", "alignment": {...},
        #   "normalized_alignment": {...}}. Decode audio_base64 -> bytes.
        # Return (audio_bytes, full_json_dict). ElevenLabsError on failure.
    async def list_voices(self) -> list[dict]
        # GET {base}/voices ; return body["voices"] (list of {voice_id,name,labels,...}).
```

---

## tools/*  — FastMCP tool registration

Each module exposes `register_<area>_tools(mcp: FastMCP, deps: Deps)`. A `Deps`
dataclass (define in tools/__init__.py) bundles constructed clients + settings so
tests can inject mocks:

```python
# tools/__init__.py
@dataclass
class Deps:
    settings: Settings
    piapi: PiapiClient
    eleven: ElevenLabsClient
```

Tools are async. Each tool:
- builds the pydantic request model from primitive args (catch pydantic
  ValidationError -> raise fastmcp.exceptions.ToolError(str(e))).
- on success returns a JSON-able dict.
- catch VideoMCPError/ProviderError -> ToolError(str(err)).

### tools/kling.py -> tool `generate_kling_video`
Args mirror KlingVideoRequest (shots passed as list[dict]). Rule: if `video` set,
force enable_audio=False unless keep_original_audio (per skill). Submit via
piapi.create_task(model="kling", task_type="omni_video_generation",
input=req.to_piapi_input(), config=...). If wait: poll. Return
{task_id, status, video_url, request_echo}.

### tools/seedance.py -> tool `generate_seedance_video`
Args: prompt, language="en", task_type, mode, duration, resolution, aspect_ratio,
image_urls, video_urls, audio_urls, text (Hebrew speech, optional), voice_id
(for Hebrew TTS), wait. If is_hebrew_request(language): run the Hebrew auto-chain
(see routing.py policy). Else: build SeedanceVideoRequest and submit. Return
{task_id, status, video_url, mode, task_type, ...}. For Hebrew also include
{audio_url, carrier_url, transliteration_required note}.

### tools/seedance_flf.py -> tool `generate_seedance_first_last`
Args: prompt, image_first (url), image_last (url|None), duration in {5,10,15},
resolution, task_type. Builds SeedanceVideoRequest(mode="first_last_frames",
image_urls=[first, last?]) — aspect_ratio omitted/auto. Submit. Return same shape.

### tools/elevenlabs.py -> tool `generate_elevenlabs_voiceover`
Args mirror VoiceoverRequest. Calls tts_with_timestamps when with_timestamps else
tts. Writes audio to a temp file (output dir configurable, default tempfile).
Returns {audio_path, output_format, model_id, alignment (or None), characters: len(text)}.

### tools/misc.py
- tool `list_voices` -> {"voices": [...]} via eleven.list_voices()
- tool `get_task` -> piapi.get_task(task_id) -> {task_id,status,video_url,error,output}
- tool `transliterate_hebrew` -> {"input":..., "latin":..., "had_hebrew":bool}

## server.py
```python
def build_server(settings: Settings|None = None) -> FastMCP
    # construct Settings, clients, Deps; mcp=FastMCP("video-mcp"); register all 5
    # groups; return mcp.
def main() -> None
    # build_server(); mcp.run()  (stdio transport)
if __name__ == "__main__": main()
```

## tests/conftest.py
Provide fixtures: `settings` (Settings with dummy keys + base urls),
`anyio_backend`/asyncio config, a `respx_mock` usage pattern, and a `deps` fixture
with PiapiClient/ElevenLabsClient over a respx-mocked httpx.AsyncClient.
Set asyncio_mode=auto via pytest config (already in pyproject [tool.pytest.ini_options]).

## Testing requirements per module
- schemas: every validation gate (pass + fail) — Seedance duration {5,10,15} & reject
  4/7/20; Kling shots>6, sum>15, shots+video, video+>4 images, no prompt/shots;
  Hebrew->eleven_v3 forcing & reject non-v3.
- transliterate: has_hebrew true/false; transliterate strips all Hebrew (result has
  no Hebrew); Latin/punct passthrough.
- routing: round_duration_to_allowed boundaries (5,5.0,6->10,10,11->15,15,16->error);
  infer_seedance_mode cases; is_hebrew_request.
- carrier: build a 1s carrier with real ffmpeg, assert file exists & non-empty,
  ffprobe duration ~1s (skip if ffmpeg/ffprobe absent). Reject duration 0 / >15.
- uploader: respx-mock tmpfiles -> assert direct /dl/ URL.
- clients: respx-mock create_task (200 + error code), get_task, wait_for_task
  (pending then completed), elevenlabs tts/with_timestamps/list_voices + error.
- tools: use injected Deps with mocked clients (monkeypatch client methods or
  respx). Single-shot Kling success; multi-shot success; multi-shot FAIL (>6/sum>15)
  -> ToolError; Hebrew lipsync chain (mock ElevenLabs+upload+carrier+seedance) asserts
  task_type seedance-2 & omni_reference & Latin prompt enforcement; raw Hebrew prompt
  -> ToolError; elevenlabs voiceover returns audio_path+alignment; list_voices; get_task.
```

---

# POST-BUILD ADDITIONS (implemented after the initial build)

These extend the frozen contract; they are live and tested.

## utils/references.py
`extract_tags(text, *, style)` and `validate_references(text, *, n_images, n_videos,
n_audios, style, require_referenced=True)`. Styles: `kling` (`@image_1` + bare `@video`),
`seedance` (`@image1`/`@video1`/`@audio1`). Raises ValueError on dangling tags or (unless
exempt) unreferenced supplied refs. Wired into KlingVideoRequest (scans prompt + all shot
prompts) and SeedanceVideoRequest (first_last_frames passes require_referenced=False).

## moderation.py
`BYPASS_LADDER = ["grid","light_posterize","heavy_grid","heavy_posterize"]`,
`is_moderation_failure(message)`, `next_bypass_method(used)`. A failure counts only at
terminal `status=="failed"`.

## utils/image_ops.py
`process_reference(input_path, out_path, method, *, magick_bin, width=900, height=1200)`.
Methods = BYPASS_LADDER. ImageMagick recipes; raises ImageOpsError. `utils/download.py`
provides `download(url, path)`.

## tools/moderation.py -> tool `process_reference_for_moderation`
Args: image (url|path), method, width, height. Downloads if URL, processes, uploads to
tmpfiles, returns {processed_url, method, local_path, bypass_ladder}.

## generate_seedance_video / get_task additions
- Hebrew chain accepts `image_urls` (face) -> `@image1..` + carrier `@video1`; runs two
  Scribe gates (source + generated-video) with bands 100% pass / 85-99% warning / <85% fail.
- New args: `verify_speech: bool=True`, `bypass_methods_used: list[str]|None`,
  `aspect_ratio` defaults to 9:16 for Hebrew, 16:9 otherwise.
- On terminal moderation failure both tools return `failure_reason`, `provider_message`,
  and (generate) `next_action`/`next_method`/`bypass_ladder`/`instructions`.

## clients/elevenlabs.py addition
`transcribe(audio_path, *, language_code="he", model_id="scribe_v2",
timestamps_granularity="word")` -> Scribe speech-to-text JSON.

## config additions
`magick_bin` (MAGICK_BIN), `lmstudio_*`, `openrouter_*`, `transliterate_*`.
