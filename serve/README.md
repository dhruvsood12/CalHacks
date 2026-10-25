# serve/ (A hosts it; B owns the Claude part)
- `app.py`, `classifier.py`, `tests/`, `requirements.txt`: A ([brief](../docs/roles/A-training.md))
- `claude_report.py`, `prompts/`: B ([brief](../docs/roles/B-eval-claude.md))
API shapes: [contracts/](../contracts/README.md). Runs on the GPU box behind a cloudflared HTTPS tunnel.
