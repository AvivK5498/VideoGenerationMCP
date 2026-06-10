# VideoGenerationMCP

A [FastMCP](https://github.com/jlowin/fastmcp) server that gives agents a validated
interface to **Kling Omni** + **Seedance 2** video generation (via PiAPI) and
**ElevenLabs** voiceover — with every provider constraint enforced locally (Pydantic)
*before* any paid API call.

## Tools

| Tool | Purpose |
|---|---|
| `generate_kling_video` | Kling Omni single- or multi-shot generation |
| `generate_seedance_video` | Seedance 2 generation; auto-chains the Hebrew BVAC lipsync pipeline |
| `generate_seedance_first_last` | Seedance first/last-frame interpolation |
| `verify_generated_audio` | Scribe QA gate on a finished task's video (async jobs) |
| `generate_elevenlabs_voiceover` | ElevenLabs TTS with character-level timestamps |
| `transliterate_hebrew` | Hebrew → Latin (LLM-backed) for lipsync prompts |
| `list_voices` | List ElevenLabs voices |
| `get_task` | Poll any PiAPI task |
| `upload_asset` · `list_assets` · `get_asset` · `delete_asset` | PiAPI private asset library (reusable `asset://` persona refs) |
| `split_audio` | Cut a master voiceover at timestamps → per-clip segments |
| `extract_frame` | Grab a frame (default: last) for first/last-frame clip bridging |
| `stitch_videos` | Concat clips (normalized) into the final multi-clip ad |
| `host_file` | Host a local file on a temporary public URL (non-persona refs) |
| `burn_captions` | Word-timed captions via Scribe (RTL-correct Hebrew) burned onto a video |

Highlights: Hebrew BVAC lipsync (ElevenLabs `eleven_v3` → ffmpeg black-video carrier →
Seedance `omni_reference`) with two Scribe audio gates; `@`-tag reference validation;
a content gate (blocks minor/real-person prompts); private-asset support on the
less-restriction tier; 720p default (1080p on request).

## Requirements

- Python ≥ 3.12 and [`uv`](https://docs.astral.sh/uv/)
- `ffmpeg` on PATH (`brew install ffmpeg` / `apt install ffmpeg`)
- `PIAPI_KEY` and `ELEVENLABS_KEY` (see `.env.example`)
- Optional: `OPENROUTER_API_KEY` (fallback for Hebrew transliteration; primary is a
  local [LMStudio](https://lmstudio.ai/) model, default `google/gemma-4-e4b`)

## Connect to Claude Code

No clone needed — `uvx` installs and runs the server straight from this repo:

```bash
claude mcp add video \
  --env PIAPI_KEY=your_piapi_key \
  --env ELEVENLABS_KEY=your_elevenlabs_key \
  --env OPENROUTER_API_KEY=your_openrouter_key \
  -- uvx --from git+https://github.com/AvivK5498/VideoGenerationMCP video-mcp
```

Or add it to a project `.mcp.json`:

```json
{
  "mcpServers": {
    "video": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/AvivK5498/VideoGenerationMCP", "video-mcp"],
      "env": { "PIAPI_KEY": "…", "ELEVENLABS_KEY": "…", "OPENROUTER_API_KEY": "…" }
    }
  }
}
```

Verify with `/mcp` inside Claude Code.

## Connect to Codex

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.video]
command = "uvx"
args = ["--from", "git+https://github.com/AvivK5498/VideoGenerationMCP", "video-mcp"]
env = { PIAPI_KEY = "…", ELEVENLABS_KEY = "…", OPENROUTER_API_KEY = "…" }
```

(or `codex mcp add video -- uvx --from git+https://github.com/AvivK5498/VideoGenerationMCP video-mcp`).
Codex MCP servers communicate over stdio; restart Codex to pick up the config.

## Local development

```bash
git clone git@github.com:AvivK5498/VideoGenerationMCP.git
cd VideoGenerationMCP
uv sync
cp .env.example .env   # fill in PIAPI_KEY + ELEVENLABS_KEY
uv run pytest -q       # 203 tests
```

Run standalone (stdio): `uv run video-mcp`. To wire a local checkout instead of the
git install, swap the command for
`uv run --directory /ABSOLUTE/PATH/TO/VideoGenerationMCP video-mcp`.

## More

- `CONTRACT.md` — full interface spec for every module.
- `samples/payloads.md` — ready-to-use tool-call examples.
- `scripts/` — live end-to-end drivers used to validate against PiAPI/ElevenLabs.
