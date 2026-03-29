"""
Orchestrator — runs the autonomous pipeline loop as background tasks.
Triggered when user approves a gate or when auto-advance is enabled.
"""

import uuid
import asyncpg
from datetime import datetime, timezone

from agents import architect, validate, build, review


async def add_entry(pool: asyncpg.Pool, project_id: str, phase: str, author: str, content: str, entry_type: str):
    """Helper to insert an entry and update project timestamp."""
    entry_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc)
    await pool.execute(
        "INSERT INTO entries (id, project_id, phase, author, content, entry_type, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7)",
        entry_id, project_id, phase, author, content, entry_type, now,
    )
    await pool.execute("UPDATE projects SET updated_at = $1 WHERE id = $2", now, project_id)
    return entry_id


async def set_phase(pool: asyncpg.Pool, project_id: str, phase: str):
    """Helper to update project phase."""
    now = datetime.now(timezone.utc)
    await pool.execute(
        "UPDATE projects SET phase = $1, updated_at = $2 WHERE id = $3",
        phase, now, project_id,
    )


async def run_architecture(pool: asyncpg.Pool, project_id: str, idea_text: str, notify_fn):
    """
    Auto-run architecture phase:
    1. Call GPT-4 for system design
    2. Call Claude for validation
    3. Notify user to approve
    """
    try:
        await notify_fn(f"🏗️ `{project_id}` — Running architecture phase...")

        # GPT-4 designs
        arch = await architect(idea_text)
        await add_entry(pool, project_id, "architecture", "chatgpt", arch, "input")
        await notify_fn(f"✅ `{project_id}` — ChatGPT architecture complete")

        # Claude validates
        validation = await validate(arch)
        await add_entry(pool, project_id, "architecture", "claude", validation, "validation")
        await notify_fn(
            f"✅ `{project_id}` — Claude validation complete\n\n"
            f"Reply /approve {project_id} to advance to build\n"
            f"Reply /reject {project_id} to request changes"
        )

    except Exception as e:
        await notify_fn(f"❌ `{project_id}` architecture failed: {str(e)[:200]}")


async def run_build(pool: asyncpg.Pool, project_id: str, notify_fn):
    """
    Auto-run build phase:
    1. Generate export spec from all architecture entries
    2. Call Claude build agent
    3. Auto-advance to review
    """
    try:
        await notify_fn(f"🔨 `{project_id}` — Running build phase...")

        # Gather all architecture entries for the spec
        entries = await pool.fetch(
            "SELECT * FROM entries WHERE project_id = $1 AND phase IN ('idea', 'architecture') ORDER BY created_at ASC",
            project_id,
        )
        spec = "\n\n---\n\n".join(
            f"[{e['author']}] ({e['entry_type']}):\n{e['content']}" for e in entries
        )

        # Claude builds
        code = await build(spec)
        await set_phase(pool, project_id, "build")
        await add_entry(pool, project_id, "build", "claude_code", code, "input")
        await notify_fn(f"✅ `{project_id}` — Build complete. Running review...")

        # Auto-advance to review
        await run_review(pool, project_id, code, spec, notify_fn)

    except Exception as e:
        await notify_fn(f"❌ `{project_id}` build failed: {str(e)[:200]}")


async def run_review(pool: asyncpg.Pool, project_id: str, code: str, spec: str, notify_fn):
    """
    Auto-run review phase:
    1. Call Claude reviewer
    2. If PASS → notify user for deploy approval
    3. If NEEDS_FIX → auto-run fix cycle
    """
    try:
        await set_phase(pool, project_id, "review")
        review_result = await review(code, spec)
        await add_entry(pool, project_id, "review", "claude", review_result, "review")

        if "PASS" in review_result.upper().split("\n")[0]:
            await notify_fn(
                f"✅ `{project_id}` — Review PASSED\n\n"
                f"Reply /approve {project_id} to ship it\n"
                f"Reply /reject {project_id} to request changes"
            )
        else:
            await notify_fn(f"🔧 `{project_id}` — Review found issues. Running fix cycle...")
            await run_fix(pool, project_id, code, review_result, spec, notify_fn)

    except Exception as e:
        await notify_fn(f"❌ `{project_id}` review failed: {str(e)[:200]}")


async def run_fix(pool: asyncpg.Pool, project_id: str, original_code: str, review_result: str, spec: str, notify_fn, max_cycles: int = 3):
    """
    Fix cycle: send review issues back to build agent, re-review.
    Max 3 cycles to prevent infinite loops.
    """
    try:
        await set_phase(pool, project_id, "fix")

        fix_prompt = (
            f"## ORIGINAL CODE\n{original_code}\n\n"
            f"## REVIEW ISSUES\n{review_result}\n\n"
            f"Fix ALL issues listed above. Output the COMPLETE corrected code for every file that changed."
        )

        fixed_code = await build(fix_prompt)
        await add_entry(pool, project_id, "fix", "claude_code", fixed_code, "fix")

        # Re-review
        re_review = await review(fixed_code, spec)
        await add_entry(pool, project_id, "fix", "claude", re_review, "review")

        if "PASS" in re_review.upper().split("\n")[0]:
            await notify_fn(
                f"✅ `{project_id}` — Fix applied, review PASSED\n\n"
                f"Reply /approve {project_id} to ship it"
            )
        elif max_cycles > 1:
            await notify_fn(f"🔄 `{project_id}` — Still has issues, running fix cycle {4 - max_cycles}/3...")
            await run_fix(pool, project_id, fixed_code, re_review, spec, notify_fn, max_cycles - 1)
        else:
            await notify_fn(
                f"⚠️ `{project_id}` — Fix cycles exhausted (3/3). Manual intervention needed.\n"
                f"Check the timeline in the dashboard."
            )

    except Exception as e:
        await notify_fn(f"❌ `{project_id}` fix failed: {str(e)[:200]}")
