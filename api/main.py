"""
Phantom Pipeline — Autonomous Dev Orchestrator
Standalone Zeabur service for managing the full build lifecycle:
Idea → Architecture → Export → Build → Review → Deploy

Participants: Human (direction), ChatGPT (design), Claude (architecture), Claude Code (execution)
"""

import os
import uuid
import json
from datetime import datetime, timezone
from typing import Optional
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


# ─── Config ───────────────────────────────────────────────────────────

DATABASE_URL = os.getenv("DATABASE_URL", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
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
    yield
    if pool:
        await pool.close()


# ─── App ──────────────────────────────────────────────────────────────

app = FastAPI(title="Phantom Pipeline", version="1.0.0", lifespan=lifespan)

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


# ─── Health ───────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "alive", "service": "phantom-pipeline", "version": "1.0.0"}
