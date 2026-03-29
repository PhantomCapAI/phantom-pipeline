# Phantom Pipeline — Autonomous Dev Orchestrator

Standalone Zeabur service for managing the full build lifecycle:

**Idea → Architecture → Export → Build → Review → Deploy**

## Participants
- **Human** — Equal partner, steers direction at every phase
- **ChatGPT** — Design thinking, product logic, system structure
- **Claude** — Architecture validation, risk assessment, build specs
- **Claude Code** — Execution engine, builds exactly to spec

## Deploy to Zeabur

### 1. Create Neon Postgres database
- Go to Neon (neon.tech), create a new project
- Copy the connection string

### 2. Push to GitHub
```bash
cd phantom-pipeline
git init
git add .
git commit -m "Phantom Pipeline v1.0"
git remote add origin https://github.com/PhantomCapAI/phantom-pipeline.git
git push -u origin main
```

### 3. Deploy on Zeabur
- Create new service from GitHub repo
- Set environment variables:
  - `DATABASE_URL` — Neon Postgres connection string
  - `TELEGRAM_BOT_TOKEN` — (optional) for phase notifications
  - `TELEGRAM_CHAT_ID` — `1516882079`
  - `PORT` — `8080`
- Bind a domain (e.g., `pipeline.zeabur.app`)

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/projects` | Create new project |
| GET | `/projects` | List all projects |
| GET | `/projects/{id}` | Get project + entries |
| DELETE | `/projects/{id}` | Delete project |
| POST | `/projects/{id}/entries` | Add entry (input/validation/review/fix/approval) |
| POST | `/projects/{id}/advance` | Advance to next phase |
| POST | `/projects/{id}/rollback` | Go back one phase |
| POST | `/projects/{id}/export` | Generate Claude Code spec bundle |
| GET | `/projects/{id}/exports` | List all exports |
| GET | `/projects/{id}/timeline` | Full audit trail |
| GET | `/health` | Health check |

## Workflow

1. **Create project** — name it (e.g., "Sullivan Rebuild")
2. **IDEA phase** — Add your concept as an entry
3. **ARCHITECTURE phase** — Paste ChatGPT's design, then Claude's validation
4. **EXPORT** — Hit export to generate a spec bundle for Claude Code
5. **BUILD** — Paste export to Claude Code, it builds to spec
6. **REVIEW** — Paste output back, Claude reviews
7. **FIX** — If needed, Claude Code applies fixes
8. **DEPLOY** — Ship it

Every entry is logged with author, phase, type, and timestamp. Full audit trail always available.
