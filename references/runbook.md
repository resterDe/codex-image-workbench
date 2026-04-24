# Runbook

## What this skill assumes

- Resolve `base_url`, `model`, and auth from a skill-local config file first.
- Treat `auth.json` value `PROXY_MANAGED` as a valid proxy credential for local Codex-compatible gateways.
- Never print a literal API key back to the user.

## Resolution order

1. Command-line overrides such as `--base-url`, `--api-key`, `--model`
2. Environment overrides: `CODEX_IMAGE_BASE_URL`, `CODEX_IMAGE_API_KEY`, `CODEX_IMAGE_MODEL`
3. Skill config: `image-provider.toml` in the skill root
4. Codex config: `config.toml` and `auth.json`
5. Fallback model: `gpt-image-1`

## Skill-local config

Default config file:

- `<skill-root>\image-provider.toml`

Recommended fields:

- `[provider].base_url`
- `[provider].api_key`
- `[provider].model`
- `[provider].wire_api`
- `[detection].candidate_models`

The script normalizes a plain root such as `https://example.com/` to `https://example.com/v1` for OpenAI-compatible providers.

## Output contract

The script prints JSON only. On success it returns:

- `image_paths`: absolute output files
- `metadata_path`: absolute metadata JSON path
- `response_id`: reusable for iterative edits with `--previous-response-id`
- `resolved_config`: sanitized config details with no raw secret disclosure

On failure it returns `ok: false` and a structured error payload.

When `--probe` is used it returns:

- `recommended_model`: first model that successfully returns image output
- `attempts`: each candidate model attempt with success or failure details

## Recommended assistant behavior

1. Infer the user prompt, attached image paths, and any requested size/quality/background preferences.
2. Run the script from the current workspace so outputs land in `./codex-image-output` unless the user asks for another directory.
3. If the request succeeds, preview each generated image directly in chat using its absolute path and provide the matching file path for download.
4. If the request fails with an HTTP 403 or upstream error, explain that the currently configured provider rejected image generation and suggest checking `image-provider.toml` or re-running with `--probe`.
5. For desktop preview flows, prefer `--preview --ephemeral --skip-metadata` so the singleton preview window updates in place, keeps recent history for browsing, supports wheel zoom, drag pan, double-click fit/100% toggling, keyboard navigation/fullscreen shortcuts, a thumbnail strip, and keeps the project directory clean.
