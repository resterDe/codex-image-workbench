# Codex Image Workbench

A reusable Codex skill for image generation and editing with OpenAI-compatible image providers, focused on `gpt-image-2` style workflows.

It supports:

- text-to-image generation
- image editing with one or more local source images
- provider config stored inside the skill
- model probing and dry-run diagnostics
- a modern local preview window with history, zoom, pan, fullscreen, and thumbnails

## What This Repository Contains

- `SKILL.md`: the skill definition used by Codex
- `image-provider.toml`: local provider configuration template
- `scripts/codex_image_workbench.py`: the main image generation and editing runner
- `scripts/image_preview_window.py`: the singleton desktop preview window
- `references/runbook.md`: operational notes and output contract

## Install

Copy or clone this repository into your Codex skills directory. A common target is:

```text
$CODEX_HOME/skills/codex-image-workbench
```

If `CODEX_HOME` is unset, that is usually:

```text
~/.codex/skills/codex-image-workbench
```

On Windows, a typical path is:

```text
C:\Users\<you>\.codex\skills\codex-image-workbench
```

## Configure

Edit `image-provider.toml` and replace the placeholder values:

```toml
[provider]
base_url = "https://your-openai-compatible-endpoint.example.com/"
api_key = "YOUR_API_KEY_HERE"
model = "gpt-image-2"
wire_api = "responses"

[detection]
candidate_models = ["gpt-image-2", "gpt-image-1", "gpt-4.1-mini"]
```

Notes:

- `gpt-image-*` style models are sent to the Images API endpoints.
- other compatible models can fall back to the Responses API path.
- the script never prints the raw API key in normal output.

## Usage

From the skill directory:

### Generate an image

```powershell
python .\scripts\codex_image_workbench.py --prompt "A cinematic portrait of Sun Wukong" --quality high --size 1024x1536
```

### Edit an image

```powershell
python .\scripts\codex_image_workbench.py --prompt "Change only the hairstyle to long hair" --image "C:\path\avatar.png"
```

### Open or refresh the preview window

```powershell
python .\scripts\codex_image_workbench.py --prompt "A futuristic city skyline" --preview --ephemeral --skip-metadata
```

### Probe which image model works

```powershell
python .\scripts\codex_image_workbench.py --probe
```

### Inspect config and request shape without sending

```powershell
python .\scripts\codex_image_workbench.py --prompt "test" --dry-run
```

## Preview Window Features

The preview window is a singleton desktop viewer. If it is already open, new generations refresh the existing window instead of opening duplicates.

Features:

- recent-history browsing
- `Previous` / `Next`
- `Space` for next image
- `Shift+Space` for previous image
- mouse-wheel zoom
- click-drag pan
- double-click to toggle fit/100%
- `0` to fit image to viewport
- `F` or `F11` for fullscreen
- thumbnail strip for quick navigation
- download, open-folder, and copy-path actions

## Dependencies

Required:

- Python 3.11+ recommended

Optional but recommended for the preview window:

- Pillow

Install Pillow if needed:

```powershell
pip install pillow
```

## Publishing Notes

This repository is intentionally sanitized for public sharing:

- no real API key
- no private endpoint
- no machine-specific hardcoded home path
- no generated output files
- no `__pycache__`

## Suggested Repo Names

- `codex-image-workbench`
- `codex-image2-skill`
- `codex-gpt-image-workbench`

My recommendation is `codex-image-workbench` because it is short, descriptive, and still broad enough if you later support more than `image2`.
