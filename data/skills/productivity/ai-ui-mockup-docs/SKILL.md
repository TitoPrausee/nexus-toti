---
name: ai-ui-mockup-docs
description: Generate realistic UI screenshots with AI image APIs and include them in LaTeX Beamer presentations for documentation
version: 1.0
---

# AI-Generated UI Mockup Documentation

Generate realistic UI screenshots with AI image APIs and include them in LaTeX Beamer presentations for documentation.

## Workflow

1. **Identify needed screenshots** — List each UI screen you need illustrated
2. **Generate via AI** — Use `grok-imagine-image` or `grok-2-image` with detailed prompts specifying the exact UI layout
3. **Download images** — Use curl with `User-Agent: Mozilla/5.0` header (xAI blocks default UA)
4. **Include in LaTeX** — `\includegraphics[width=0.9\textwidth]{screenshot-name.jpeg}`
5. **Build PDF** — `pdflatex` twice for cross-references

## API Call Format

```python
import json, subprocess

payload = {
    "model": "grok-imagine-image",  # or grok-imagine-image-pro
    "prompt": "Screenshot of GitLab issue list page showing 10 issues with labels Priority::High Type::Feature in dark theme, realistic UI mockup, web browser view",
    "n": 1,
    "size": "1024x1024"
}

with open("/tmp/payload.json", "w") as f:
    json.dump(payload, f)

result = subprocess.run([
    "curl", "-s", "https://api.x.ai/v1/images/generations",
    "-H", f"Authorization: Bearer {XAI_KEY}",
    "-H", "Content-Type: application/json",
    "-d", "@/tmp/payload.json"
], capture_output=True, text=True)

data = json.loads(result.stdout)
image_url = data["data"][0]["url"]

# Download with proper UA (xAI blocks default curl UA)
subprocess.run([
    "curl", "-L", "-o", f"screenshot-name.jpeg",
    "-H", "User-Agent: Mozilla/5.0",
    image_url
], check=True)
```

## Prompt Tips for UI Mockups

- Always include "screenshot" and "realistic UI mockup" in the prompt
- Specify the product name (e.g., "GitLab", "WordPress Dashboard")
- Include theme: "dark theme" or "light theme"
- Specify UI elements: "sidebar with navigation", "issue cards with labels", "top navbar"
- Mention specific data: "showing 5 issues with labels Prio::Hoch, Status::In Progress"
- For dashboards: "showing statistics cards, recent activity feed, burndown chart"
- For forms: "form opened in modal dialog, fields for title, description, labels dropdown"

## Dark Beamer Theme (Apple-style)

```latex
\definecolor{bg}{HTML}{0a0a0a}
\definecolor{surface}{HTML}{111113}
\definecolor{surface2}{HTML}{1c1c1e}
\definecolor{text1}{HTML}{f5f5f7}
\definecolor{text2}{HTML}{86868b}
\definecolor{text3}{HTML}{6e6e73}
\definecolor{accent}{HTML}{0a84ff}
\definecolor{purple}{HTML}{5e5ce6}
\definecolor{pink}{HTML}{bf5af2}
\definecolor{red}{HTML}{ff375f}
\definecolor{green}{HTML}{30d158}
\definecolor{orange}{HTML}{ff9f0a}
\definecolor{border}{HTML}{2c2c2e}
```

## Common Pitfalls

- **xAI blocks default curl User-Agent** — Always add `-H "User-Agent: Mozilla/5.0"` when downloading images
- **Image too small/low quality** — Use `grok-imagine-image-pro` for higher quality
- **LaTeX image paths** — Use `\graphicspath{{/path/to/screenshots/}}` to avoid path issues
- **`\end{frameframe}`** — Common typo; should be `\end{frame}`
- **fontawesome5 package** — Needs `texlive-fonts-extra` on Debian/Ubuntu
- **ARM architecture** — Puppeteer/Chrome won't work in ARM containers; use AI image generation instead

## Required Packages

```bash
sudo apt-get install -y texlive-full texlive-fonts-extra
```