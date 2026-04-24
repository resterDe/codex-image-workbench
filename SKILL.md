---
name: codex-image-workbench
description: Generate, edit, and iterate on images by using a skill-local image provider configuration first. Use when Codex needs to create images from a prompt, transform one or more local images, combine prompt plus image guidance, preview generated images, provide local files for download, or probe a custom endpoint for a working image model. Resolve base_url, model, and auth from the skill's image-provider.toml before falling back to Codex-wide config.
---

# Codex Image Workbench

Use this skill when the user wants image generation or image editing inside Codex and expects the run to prefer a dedicated image endpoint configured inside the skill itself.

Read [runbook.md](./references/runbook.md) only when you need the exact config-resolution order or the output contract.

## Workflow

1. Convert the user request into:
- a prompt or edit instruction
- zero or more local image paths
- optional quality, size, background, or format preferences
- optional previous response id when the user is iterating on a prior result

2. Run the script:

```powershell
python <skill-root>\scripts\codex_image_workbench.py --prompt "..." --output-dir ".\\codex-image-output"
```

Add `--image "C:\path\to\input.png"` one or more times for edits or style/reference-guided generation.

3. Prefer the skill-local config automatically. Edit this file when the provider changes:

```toml
<skill-root>\image-provider.toml
```

Only pass explicit overrides when you want a one-off request:

```powershell
python <skill-root>\scripts\codex_image_workbench.py --prompt "..." --base-url "https://..." --api-key "..." --model "gpt-image-2"
```

4. After a successful run:
- read the JSON output
- show inline previews with absolute local image paths using Markdown image syntax
- mention the absolute file paths so the user can download them
- if present, surface `response_id` because it enables iterative follow-up edits

5. After a failed run:
- do not guess that the prompt was wrong
- inspect the structured error JSON first
- if the provider returns 403/upstream errors, explain that the configured image provider rejected the image tool and suggest checking `image-provider.toml` or using `--probe`

## Common commands

Text-to-image:

```powershell
python <skill-root>\scripts\codex_image_workbench.py --prompt "A cinematic poster of a panda barista in a rainy neon alley" --quality high --size 1024x1536
```

Prompt plus image edit:

```powershell
python <skill-root>\scripts\codex_image_workbench.py --prompt "Turn this product photo into a clean ecommerce hero image on transparent background" --image "C:\path\product.png" --background transparent --format png
```

Inspect the resolved config without sending a request:

```powershell
python <skill-root>\scripts\codex_image_workbench.py --prompt "test" --dry-run
```

Probe the configured endpoint for a working image model:

```powershell
python <skill-root>\scripts\codex_image_workbench.py --probe
```

Open or refresh the modern preview window after generation:

```powershell
python <skill-root>\scripts\codex_image_workbench.py --prompt "..." --preview --ephemeral --skip-metadata
```

## Notes

- The script never prints a raw API key.
- If the user supplied only an image, the script uses a conservative default edit prompt. Prefer passing an explicit instruction whenever possible.
- The script reads the default provider from `image-provider.toml` in the skill root.
- The script normalizes a root URL like `https://host/` to `https://host/v1`.
- The script talks to the Images API for `gpt-image-*` style models and falls back to the Responses API for other compatible providers.
- The preview window title stays fixed to the skill name `Codex Image Workbench`.
- The preview window is a singleton: if it is already open, the next generation updates the existing window directly instead of closing and reopening it.
- The preview window keeps recent images in history so `Previous` and `Next` can browse recent generations.
- The preview window shows the current zoom percentage and supports mouse-wheel zoom, click-drag pan, and `0` to fit the image back to the viewport.
- The preview window also supports double-click toggling between fit-to-window and 100% view, and shows dimensions plus zoom in the bottom-right status area.
- Keyboard/viewer shortcuts: `Space` for next image, `Shift+Space` for previous image, `F` or `F11` for fullscreen, and a thumbnail strip at the bottom for quick recent-history jumps.
- On Windows, the preview window launches without an extra `cmd` console window.
- Save outputs into the current workspace unless the user requests another directory.
- When the user asks for preview, embed each result with Markdown image syntax using the absolute output path.
