# 🏴‍☠️ Vegapunk — Agentic AI Coding Agent

> *"A man's dream will never die!"* — Dr. Vegapunk would agree, especially about autonomous coding.

**Vegapunk** is an AI coding agent that autonomously resolves GitHub issues by analyzing code, writing fixes, running tests, and creating pull requests — powered by **6 Satellite Agents** inspired by One Piece's Dr. Vegapunk.

## 🧬 The Six Satellites

| Satellite | Role | What It Does |
|---|---|---|
| 🧠 **Shaka** (Router) | Punk-01 | Classifies issues — bug fix, feature, refactor, etc. |
| 💡 **Edison** (Planner) | Punk-03 | Analyzes codebase and creates implementation plans |
| 💻 **Pythagoras** (Coder) | Punk-04 | Writes code changes using hybrid line-edit strategy |
| 🔨 **Atlas** (Tester) | Punk-05 | Runs tests with baseline comparison for pre-existing failures |
| 😈 **Lilith** (Reviewer) | Punk-02 | Self-reviews code quality, correctness, and security |
| 🎯 **York** (PR Creator) | Punk-06 | Commits, pushes, and creates GitHub pull requests |

**Stella** (the original body) = the orchestrator pipeline that coordinates all satellites.

## 🔄 Pipeline Flow

```
Stella → Shaka → Edison → Pythagoras → Atlas → Lilith → York → PR
           │         │          │          │        │
           ▼         ▼          ▼          ▼        ▼
        Classify   Plan      Code       Test    Review
```

## 🚀 Quick Start

```bash
# 1. Clone and setup
git clone <your-repo-url>
cd vegapunk
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Configure environment
cp .env.example .env
# Edit .env with your API keys

# 3. Run
uvicorn app.main:app --port 8000

# 4. Submit an issue
curl -X POST http://localhost:8000/api/tasks/from-url \
  -H "Content-Type: application/json" \
  -d '{"issue_url": "https://github.com/owner/repo/issues/1"}'
```

## ⚙️ Environment Variables

| Variable | Description | Required |
|---|---|---|
| `NVIDIA_API_KEY` | NVIDIA NIM API key | Yes (or Gemini) |
| `GEMINI_API_KEY` | Google Gemini API key | Yes (or NVIDIA) |
| `GITHUB_TOKEN` | GitHub PAT with repo access | Yes |
| `GITHUB_WEBHOOK_SECRET` | Webhook secret (optional) | No |

## 🏗️ Architecture

- **Backend:** FastAPI + LangGraph
- **LLM:** NVIDIA NIM (primary) + Gemini (fallback)
- **Execution:** Docker sandbox (local fallback)
- **Version Control:** GitPython + PyGithub

## 📜 License

MIT
