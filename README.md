# Codex Image Workbench

A reusable Codex skill for image generation and editing with OpenAI-compatible image providers, focused on `gpt-image-2` style workflows.

> 中文用户可以直接参考 [中文快速开始](#中文快速开始) 和 [中文提示词模板](#中文提示词模板)。

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

## 中文快速开始

这是一个可复用的 Codex 图片生成 / 图片编辑 Skill，支持 OpenAI 兼容的图片模型接口。你可以用它完成文生图、基于本地图片的局部编辑、模型探测、请求预览和本地图片预览窗口。

### 安装到 Codex Skills

将本仓库复制或克隆到 Codex 的 skills 目录：

```powershell
git clone https://github.com/resterDe/codex-image-workbench.git "$env:USERPROFILE\.codex\skills\codex-image-workbench"
```

### 配置图片接口

编辑 `image-provider.toml`，把占位符替换为你的服务商信息：

```toml
[provider]
base_url = "https://你的-openai-compatible-endpoint.example.com/v1"
api_key = "你的 API Key"
model = "gpt-image-2"
wire_api = "responses"

[detection]
candidate_models = ["gpt-image-2", "gpt-image-1", "gpt-4.1-mini"]
```

也可以不改文件，改用环境变量，避免把真实密钥提交到仓库：

```powershell
$env:CODEX_IMAGE_BASE_URL = "https://你的服务商地址/v1"
$env:CODEX_IMAGE_API_KEY = "你的真实 API Key"
$env:CODEX_IMAGE_MODEL = "gpt-image-2"
```

### 常用命令

```powershell
# 文生图
python .\scripts\codex_image_workbench.py --prompt "一张电影感的孙悟空肖像" --quality high --size 1024x1536

# 编辑图片
python .\scripts\codex_image_workbench.py --prompt "只把发型改成长发，保持脸部不变" --image "C:\path\avatar.png"

# 打开预览窗口
python .\scripts\codex_image_workbench.py --prompt "未来城市天际线" --preview --ephemeral --skip-metadata

# 探测可用图片模型
python .\scripts\codex_image_workbench.py --probe

# 只检查配置和请求结构，不实际发送请求
python .\scripts\codex_image_workbench.py --prompt "test" --dry-run
```

## 中文提示词模板

你可以在 Codex 中这样调用本 Skill：

```text
使用 codex-image-workbench 生成图片：
主题：一只穿赛博朋克夹克的橘猫
风格：电影感、霓虹灯、浅景深
画幅：1024x1024
质量：high
要求：主体清晰，背景有城市夜景，不要文字水印
```

编辑已有图片时可以使用这个模板：

```text
使用 codex-image-workbench 编辑图片：
源图：C:\path\input.png
修改目标：把背景改成海边日落
保留内容：人物脸部、姿势、衣服颜色保持不变
风格：自然真实、柔和光线
输出要求：只改背景，不添加文字，不改变人物比例
```

更稳定的提示词写法：

- 明确 `主题`、`风格`、`画幅`、`质量` 和 `不要出现的内容`。
- 编辑图片时写清楚 `需要修改什么` 和 `必须保留什么`。
- 如果要连续迭代，说明“基于上一张继续调整”，并只描述本轮变化。
- 不要把真实 API Key 写进提示词；用 `image-provider.toml` 或环境变量配置。

## Configure

The repository ships with a sanitized `image-provider.toml` template. Replace the placeholders in your local skill copy before running the skill:

```toml
[provider]
base_url = "https://your-openai-compatible-endpoint.example.com/"
api_key = "YOUR_API_KEY_HERE"
model = "gpt-image-2"
wire_api = "responses"

[detection]
candidate_models = ["gpt-image-2", "gpt-image-1", "gpt-4.1-mini"]
```

### Provider Fields

- `base_url`: your OpenAI-compatible provider root URL. A plain root such as `https://example.com/` is normalized to `/v1` by the runner.
- `api_key`: your provider API key. Keep the checked-in value as `YOUR_API_KEY_HERE` for public repositories.
- `model`: the default model used for generation or editing, for example `gpt-image-2`.
- `wire_api`: force a request style when needed. Use `responses` for Responses API-compatible models, or leave the script to route `gpt-image-*` models to image endpoints.
- `candidate_models`: model names tried by `--probe` when discovering a working image-capable model.

### Safer Local Configuration

For public forks, do not commit real credentials. Prefer environment variables or command-line overrides:

```powershell
$env:CODEX_IMAGE_BASE_URL = "https://your-provider.example.com/v1"
$env:CODEX_IMAGE_API_KEY = "your-real-api-key"
$env:CODEX_IMAGE_MODEL = "gpt-image-2"
```

Or pass values for a single run:

```powershell
python .\scripts\codex_image_workbench.py --prompt "test" --base-url "https://your-provider.example.com/v1" --api-key "your-real-api-key" --model "gpt-image-2"
```

Configuration is resolved in this order:

1. Command-line flags: `--base-url`, `--api-key`, `--model`
2. Environment variables: `CODEX_IMAGE_BASE_URL`, `CODEX_IMAGE_API_KEY`, `CODEX_IMAGE_MODEL`
3. Skill-local `image-provider.toml`
4. Codex config/auth fallback when available

Security notes:

- `gpt-image-*` style models are sent to the Images API endpoints.
- other compatible models can fall back to the Responses API path.
- the script never prints the raw API key in normal output.
- if your local Codex gateway manages auth, `PROXY_MANAGED` can be used as the API key sentinel.
- before publishing changes, run a secret scan and confirm `image-provider.toml` still contains placeholders.

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
