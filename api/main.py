"""
Phantom Pipeline v2 — Autonomous Dev Orchestrator
Full autonomous loop: Idea → Architecture → Validation → Build → Review → Fix → Deploy

Participants: Human (direction + gates), ChatGPT (design), Claude (architecture + review), Claude Code (execution)
"""

import os
import uuid
import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from orchestrator import (
    run_architecture, run_build,
    add_entry as orch_add_entry, set_phase as orch_set_phase,
)
from bot_monitor import BOTS, query_bot_metrics, get_all_bot_metrics, check_targets
from bot_iterator import generate_proposal, format_proposal_telegram


# ─── Config ───────────────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL", "")
TELEGRAM_BOT_TOKEN = os.getenv("OPS_TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1516882079")

PHASES = ["idea", "architecture", "export", "build", "review", "fix", "deploy", "done"]


# ─── DB Pool ──────────────────────────────────────────────────────────

pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    return pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    p = await get_pool()
    await p.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            phase TEXT NOT NULL DEFAULT 'idea',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    await p.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id),
            phase TEXT NOT NULL,
            author TEXT NOT NULL,
            content TEXT NOT NULL,
            entry_type TEXT NOT NULL DEFAULT 'input',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    await p.execute("""
        CREATE TABLE IF NOT EXISTS exports (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id),
            spec_bundle TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    await p.execute("""
        CREATE TABLE IF NOT EXISTS agent_logs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id),
            agent TEXT NOT NULL,
            model TEXT NOT NULL,
            input_tokens INTEGER,
            output_tokens INTEGER,
            cost_estimate NUMERIC(10, 6),
            latency_ms INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    await p.execute("""
        CREATE TABLE IF NOT EXISTS bot_iterations (
            id TEXT PRIMARY KEY,
            bot_name TEXT NOT NULL,
            proposal JSONB NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    """)
    asyncio.create_task(bot_monitor_loop(p))
    yield
    if pool:
        await pool.close()


# ─── App ──────────────────────────────────────────────────────────────

app = FastAPI(title="Phantom Pipeline — Dev Orchestrator", version="3.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Models ───────────────────────────────────────────────────────────

class CreateProject(BaseModel):
    name: str

class AddEntry(BaseModel):
    author: str = Field(..., description="human | chatgpt | claude | claude_code")
    content: str
    entry_type: str = Field("input", description="input | validation | review | fix | approval")

class AdvancePhase(BaseModel):
    force: bool = False

class GenerateExport(BaseModel):
    include_code_samples: bool = True


# ─── Telegram notify ─────────────────────────────────────────────────

async def notify(msg: str):
    """Fire-and-forget Telegram notification."""
    if not TELEGRAM_BOT_TOKEN:
        return
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
                timeout=5,
            )
    except Exception:
        pass


# ─── Routes: Projects ────────────────────────────────────────────────

@app.post("/projects")
async def create_project(body: CreateProject):
    p = await get_pool()
    project_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc)
    await p.execute(
        "INSERT INTO projects (id, name, phase, created_at, updated_at) VALUES ($1, $2, $3, $4, $5)",
        project_id, body.name, "idea", now, now,
    )
    await notify(f"🚀 *New Pipeline Project*\n`{project_id}` — {body.name}")
    return {"id": project_id, "name": body.name, "phase": "idea"}


@app.get("/projects")
async def list_projects():
    p = await get_pool()
    rows = await p.fetch("SELECT * FROM projects ORDER BY updated_at DESC")
    return [dict(r) for r in rows]


@app.get("/projects/{project_id}")
async def get_project(project_id: str):
    p = await get_pool()
    row = await p.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    if not row:
        raise HTTPException(404, "Project not found")
    entries = await p.fetch(
        "SELECT * FROM entries WHERE project_id = $1 ORDER BY created_at ASC", project_id
    )
    return {**dict(row), "entries": [dict(e) for e in entries]}


@app.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    p = await get_pool()
    await p.execute("DELETE FROM agent_logs WHERE project_id = $1", project_id)
    await p.execute("DELETE FROM entries WHERE project_id = $1", project_id)
    await p.execute("DELETE FROM exports WHERE project_id = $1", project_id)
    await p.execute("DELETE FROM projects WHERE id = $1", project_id)
    return {"deleted": project_id}


# ─── Routes: Entries ──────────────────────────────────────────────────

@app.post("/projects/{project_id}/entries")
async def add_entry(project_id: str, body: AddEntry):
    p = await get_pool()
    project = await p.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    entry_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc)
    await p.execute(
        "INSERT INTO entries (id, project_id, phase, author, content, entry_type, created_at) VALUES ($1, $2, $3, $4, $5, $6, $7)",
        entry_id, project_id, project["phase"], body.author, body.content, body.entry_type, now,
    )
    await p.execute(
        "UPDATE projects SET updated_at = $1 WHERE id = $2", now, project_id
    )

    phase_label = project["phase"].upper()
    await notify(
        f"📝 *{body.author}* added to `{project_id}` [{phase_label}]\n_{body.entry_type}_"
    )
    return {"id": entry_id, "phase": project["phase"], "author": body.author}


# ─── Routes: Phase Management ────────────────────────────────────────

@app.post("/projects/{project_id}/advance")
async def advance_phase(project_id: str, body: AdvancePhase = AdvancePhase()):
    p = await get_pool()
    project = await p.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    current = project["phase"]
    if current == "done":
        raise HTTPException(400, "Project already complete")

    idx = PHASES.index(current)
    next_phase = PHASES[idx + 1]

    # Gate checks (skip if force=True)
    if not body.force:
        entries = await p.fetch(
            "SELECT * FROM entries WHERE project_id = $1 AND phase = $2", project_id, current
        )
        if not entries:
            raise HTTPException(400, f"No entries in current phase '{current}'. Add input before advancing.")

        # Architecture phase requires at least a Claude validation entry
        if current == "architecture":
            has_validation = any(e["entry_type"] == "validation" for e in entries)
            if not has_validation:
                raise HTTPException(400, "Architecture phase requires Claude validation before advancing.")

        # Review phase requires approval entry
        if current == "review":
            has_approval = any(e["entry_type"] == "approval" for e in entries)
            if not has_approval:
                raise HTTPException(400, "Review phase requires approval before advancing.")

    now = datetime.now(timezone.utc)
    await p.execute(
        "UPDATE projects SET phase = $1, updated_at = $2 WHERE id = $3",
        next_phase, now, project_id,
    )

    await notify(f"⏩ `{project_id}` advanced: *{current}* → *{next_phase}*")
    return {"project_id": project_id, "previous_phase": current, "current_phase": next_phase}


@app.post("/projects/{project_id}/rollback")
async def rollback_phase(project_id: str):
    p = await get_pool()
    project = await p.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    current = project["phase"]
    idx = PHASES.index(current)
    if idx == 0:
        raise HTTPException(400, "Already at first phase")

    prev_phase = PHASES[idx - 1]
    now = datetime.now(timezone.utc)
    await p.execute(
        "UPDATE projects SET phase = $1, updated_at = $2 WHERE id = $3",
        prev_phase, now, project_id,
    )

    await notify(f"⏪ `{project_id}` rolled back: *{current}* → *{prev_phase}*")
    return {"project_id": project_id, "previous_phase": current, "current_phase": prev_phase}


# ─── Routes: Export (the key feature) ────────────────────────────────

@app.post("/projects/{project_id}/export")
async def generate_export(project_id: str, body: GenerateExport = GenerateExport()):
    """
    Generate a single structured spec bundle ready to paste into Claude Code.
    Collects all entries from idea + architecture phases into one document.
    """
    p = await get_pool()
    project = await p.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    entries = await p.fetch(
        "SELECT * FROM entries WHERE project_id = $1 AND phase IN ('idea', 'architecture') ORDER BY created_at ASC",
        project_id,
    )

    # Build the spec bundle
    sections = []
    sections.append(f"# BUILD SPEC: {project['name']}")
    sections.append(f"Project ID: {project_id}")
    sections.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    sections.append("")
    sections.append("---")
    sections.append("")

    # Group by phase
    for phase in ["idea", "architecture"]:
        phase_entries = [e for e in entries if e["phase"] == phase]
        if phase_entries:
            sections.append(f"## {phase.upper()}")
            sections.append("")
            for entry in phase_entries:
                label = f"[{entry['author']}] ({entry['entry_type']})"
                sections.append(f"### {label}")
                sections.append(entry["content"])
                sections.append("")

    sections.append("---")
    sections.append("")
    sections.append("## INSTRUCTIONS FOR CLAUDE CODE")
    sections.append("")
    sections.append("1. Build EXACTLY to the architecture spec above.")
    sections.append("2. Do NOT deviate from the defined structure.")
    sections.append("3. Commit to GitHub when complete.")
    sections.append("4. Return the repo link and any issues encountered.")
    sections.append("5. If anything is ambiguous, STOP and ask — do not assume.")

    spec_bundle = "\n".join(sections)

    export_id = str(uuid.uuid4())[:8]
    await p.execute(
        "INSERT INTO exports (id, project_id, spec_bundle, created_at) VALUES ($1, $2, $3, $4)",
        export_id, project_id, spec_bundle, datetime.now(timezone.utc),
    )

    # Also advance to export phase if still in architecture
    if project["phase"] == "architecture":
        await p.execute(
            "UPDATE projects SET phase = 'export', updated_at = $1 WHERE id = $2",
            datetime.now(timezone.utc), project_id,
        )

    await notify(f"📦 Export generated for `{project_id}`\nReady for Claude Code")
    return {"export_id": export_id, "spec_bundle": spec_bundle}


@app.get("/projects/{project_id}/exports")
async def list_exports(project_id: str):
    p = await get_pool()
    rows = await p.fetch(
        "SELECT * FROM exports WHERE project_id = $1 ORDER BY created_at DESC", project_id
    )
    return [dict(r) for r in rows]


# ─── Routes: Timeline ────────────────────────────────────────────────

@app.get("/projects/{project_id}/timeline")
async def get_timeline(project_id: str):
    """Full audit trail: every entry across all phases."""
    p = await get_pool()
    project = await p.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    entries = await p.fetch(
        "SELECT * FROM entries WHERE project_id = $1 ORDER BY created_at ASC", project_id
    )

    timeline = []
    for e in entries:
        timeline.append({
            "id": e["id"],
            "phase": e["phase"],
            "author": e["author"],
            "entry_type": e["entry_type"],
            "content_preview": e["content"][:200] + ("..." if len(e["content"]) > 200 else ""),
            "created_at": e["created_at"].isoformat(),
        })

    return {
        "project": dict(project),
        "current_phase": project["phase"],
        "total_entries": len(timeline),
        "timeline": timeline,
    }


# ─── Routes: Autonomous Loop ─────────────────────────────────────────

@app.post("/projects/{project_id}/auto")
async def auto_run(project_id: str):
    """Kick off autonomous pipeline from current phase."""
    p = await get_pool()
    project = await p.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    phase = project["phase"]

    if phase == "idea":
        entries = await p.fetch(
            "SELECT content FROM entries WHERE project_id = $1 AND phase = 'idea'", project_id
        )
        idea_text = "\n\n".join(e["content"] for e in entries)
        if not idea_text:
            raise HTTPException(400, "No idea entries found. Add an idea first.")

        now = datetime.now(timezone.utc)
        await p.execute(
            "UPDATE projects SET phase = 'architecture', updated_at = $1 WHERE id = $2", now, project_id
        )
        asyncio.create_task(run_architecture(p, project_id, idea_text, notify))
        return {"status": "started", "phase": "architecture", "message": "Architecture phase running..."}

    elif phase == "architecture":
        now = datetime.now(timezone.utc)
        await p.execute(
            "UPDATE projects SET phase = 'export', updated_at = $1 WHERE id = $2", now, project_id
        )
        asyncio.create_task(run_build(p, project_id, notify))
        return {"status": "started", "phase": "build", "message": "Build phase running..."}

    elif phase in ("review", "fix"):
        return {"status": "error", "message": "Use /approve or /reject via Telegram for review phases"}

    else:
        return {"status": "error", "message": f"Cannot auto-run from phase: {phase}"}


# ─── Routes: Telegram Webhook ───────────────────────────────────────

@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    """Handle Telegram text commands for the dev orchestrator (/approve, /reject, /retry, /status).

    Content-review inline button callbacks are handled by the phantom-content-engine
    service on its own bot — this webhook only handles text commands.
    """
    body = await request.json()

    message = body.get("message", {})
    text = message.get("text", "").strip()
    chat_id = str(message.get("chat", {}).get("id", ""))

    if chat_id != TELEGRAM_CHAT_ID:
        return {"ok": True}

    p = await get_pool()

    if text.startswith("/approve "):
        project_id = text.split(" ", 1)[1].strip()
        project = await p.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
        if not project:
            await notify(f"❌ Project `{project_id}` not found")
            return {"ok": True}

        phase = project["phase"]
        if phase == "architecture":
            await orch_add_entry(p, project_id, phase, "human", "APPROVED", "approval")
            asyncio.create_task(run_build(p, project_id, notify))
            await notify(f"👍 `{project_id}` approved. Build starting...")
        elif phase in ("review", "fix"):
            await orch_add_entry(p, project_id, phase, "human", "APPROVED FOR DEPLOY", "approval")
            await orch_set_phase(p, project_id, "deploy")
            await notify(f"🚀 `{project_id}` approved for deploy!")
        else:
            await notify(f"⚠️ `{project_id}` is in phase `{phase}` — nothing to approve right now")

    elif text.startswith("/reject "):
        project_id = text.split(" ", 1)[1].strip()
        await notify(f"↩️ `{project_id}` — Send your feedback, then /retry {project_id}")

    elif text.startswith("/retry "):
        project_id = text.split(" ", 1)[1].strip()
        project = await p.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
        if not project:
            await notify(f"❌ Project `{project_id}` not found")
            return {"ok": True}

        phase = project["phase"]
        if phase == "architecture":
            entries = await p.fetch(
                "SELECT content FROM entries WHERE project_id = $1 AND phase = 'idea'", project_id
            )
            idea_text = "\n\n".join(e["content"] for e in entries)
            asyncio.create_task(run_architecture(p, project_id, idea_text, notify))
            await notify(f"🔄 `{project_id}` — Re-running architecture...")
        elif phase in ("build", "review", "fix"):
            asyncio.create_task(run_build(p, project_id, notify))
            await notify(f"🔄 `{project_id}` — Re-running build...")
        else:
            await notify(f"⚠️ `{project_id}` is in phase `{phase}` — nothing to retry")

    elif text.startswith("/bot_status"):
        bp = await get_bot_pool()
        if bp:
            all_m = await get_all_bot_metrics(bp, 24)
            lines = ["🤖 *Phantom Fleet (24h)*\n"]
            for m in all_m:
                issues = check_targets(m)
                emoji = "✅" if not issues else "⚠️"
                lines.append(f"{emoji} *{m.get('bot','?')}*")
                for k, v in m.items():
                    if k not in ('bot', 'period_hours', 'since', 'error'):
                        lines.append(f"  {k}: `{v}`")
                lines.append("")
            await notify("\n".join(lines))
        else:
            await notify("❌ Bot DB not configured")

    elif text.startswith("/bot_iterate"):
        parts = text.split()
        target = parts[1] if len(parts) > 1 else "all"
        bp = await get_bot_pool()
        if bp:
            bots_to_check = [target] if target in BOTS else list(BOTS.keys())
            count = 0
            for bname in bots_to_check:
                metrics = await query_bot_metrics(bp, bname, 24)
                prop = generate_proposal(bname, metrics)
                if prop:
                    pid = uuid.uuid4().hex[:8]
                    prop["project_id"] = pid
                    await p.execute(
                        "INSERT INTO bot_iterations (id, bot_name, proposal, status) VALUES ($1, $2, $3::jsonb, $4)",
                        pid, bname, json.dumps(prop), "pending",
                    )
                    await notify(format_proposal_telegram(prop))
                    count += 1
            if count == 0:
                await notify("✅ All bots meeting targets")
        else:
            await notify("❌ Bot DB not configured")

    elif text.startswith("/status"):
        projects = await p.fetch("SELECT id, name, phase FROM projects ORDER BY updated_at DESC LIMIT 5")
        if projects:
            lines = [f"`{r['id']}` — {r['name']} [{r['phase']}]" for r in projects]
            await notify("📊 *Active Projects*\n" + "\n".join(lines))
        else:
            await notify("📊 No projects yet")

    return {"ok": True}


# ─── Routes: Agent Logs ─────────────────────────────────────────────

@app.get("/projects/{project_id}/logs")
async def get_agent_logs(project_id: str):
    """Get all agent API call logs for a project."""
    p = await get_pool()
    rows = await p.fetch(
        "SELECT * FROM agent_logs WHERE project_id = $1 ORDER BY created_at DESC", project_id
    )
    return [dict(r) for r in rows]


# ─── Debug: test agent calls directly ────────────────────────────────

@app.get("/debug/agents")
async def debug_agents():
    """Test that both API keys work. Returns success/error for each."""
    from agents import call_openai, call_claude
    results = {}
    try:
        r = await call_openai("You are a test.", "Say 'ok'", model="gpt-4o")
        results["openai"] = {"status": "ok", "response": r[:100]}
    except Exception as e:
        results["openai"] = {"status": "error", "error": str(e)}
    try:
        r = await call_claude("You are a test.", "Say 'ok'")
        results["claude"] = {"status": "ok", "response": r[:100]}
    except Exception as e:
        results["claude"] = {"status": "error", "error": str(e)}
    return results

# ─── Bot Fleet Monitoring ─────────────────────────────────────────────

BOT_DB_URL = os.getenv("BOT_DATABASE_URL", os.getenv("DATABASE_URL", ""))
_bot_pool: Optional[asyncpg.Pool] = None


async def get_bot_pool() -> Optional[asyncpg.Pool]:
    """Lazy pool for the bot fleet's shared metrics database."""
    global _bot_pool
    if _bot_pool is None and BOT_DB_URL:
        _bot_pool = await asyncpg.create_pool(BOT_DB_URL, min_size=1, max_size=3)
    return _bot_pool


async def bot_monitor_loop(pipeline_pool):
    """Background task: every 6 hours, query each bot's metrics and propose
    parameter adjustments for any bot below target. Proposals land in
    bot_iterations and are pushed to Telegram for approval."""
    await asyncio.sleep(60)
    while True:
        try:
            bp = await get_bot_pool()
            if not bp:
                await asyncio.sleep(3600)
                continue
            for bot_name in BOTS:
                metrics = await query_bot_metrics(bp, bot_name, hours=24)
                proposal = generate_proposal(bot_name, metrics)
                if proposal:
                    pid = uuid.uuid4().hex[:8]
                    proposal["project_id"] = pid
                    await pipeline_pool.execute(
                        "INSERT INTO bot_iterations (id, bot_name, proposal, status) VALUES ($1, $2, $3::jsonb, $4)",
                        pid, bot_name, json.dumps(proposal), "pending",
                    )
                    await notify(format_proposal_telegram(proposal))
        except Exception as e:
            logging.getLogger("pipeline.bot_monitor").error(f"Monitor error: {e}")
        await asyncio.sleep(6 * 3600)


@app.get("/bots/status")
async def bots_status(hours: int = Query(24)):
    """All bot fleet metrics for the last N hours."""
    bp = await get_bot_pool()
    if not bp:
        raise HTTPException(503, "Bot database not configured")
    return await get_all_bot_metrics(bp, hours)


@app.get("/bots/{bot_name}/metrics")
async def bot_metrics(bot_name: str, hours: int = Query(24)):
    """Single bot's metrics for the last N hours."""
    if bot_name not in BOTS:
        raise HTTPException(404, f"Unknown bot: {bot_name}")
    bp = await get_bot_pool()
    if not bp:
        raise HTTPException(503, "Bot database not configured")
    return await query_bot_metrics(bp, bot_name, hours)


@app.get("/bots/iterations")
async def list_iterations(status: str = Query("pending")):
    """List bot tuning proposals filtered by status."""
    p = await get_pool()
    rows = await p.fetch(
        "SELECT * FROM bot_iterations WHERE status = $1 ORDER BY created_at DESC LIMIT 20", status
    )
    return [dict(r) for r in rows]


# ─── Health ───────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "alive", "service": "phantom-pipeline", "version": "3.1.0"}
