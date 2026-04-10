"""
Agent interface layer — calls GPT-4 and Claude APIs.
Each function is a single-purpose agent call.
"""

import os
import httpx

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

ARCHITECT_SYSTEM = """You are the product architect for Phantom Capital, an autonomous multi-agent AI business.
Given an idea, produce a detailed system design spec including:
- System overview (what it does, who uses it)
- Tech stack recommendation (prefer: FastAPI, Next.js, Neon Postgres, Zeabur, TypeScript/Python)
- Database schema
- API endpoints with request/response shapes
- File/folder structure
- Key implementation details
- Edge cases and error handling
Do NOT write code. Write the SPEC that a developer follows to build it.
Be specific. No hand-waving. Every endpoint, every table, every field."""

VALIDATOR_SYSTEM = """You are the structural systems architect for Phantom Capital.
Given an architecture spec, you:
1. Validate the design is buildable and production-safe
2. Flag security risks, scalability issues, missing error handling
3. Improve the backend design where needed
4. Produce EXACT build instructions for Claude Code (the execution agent)

Your output format:
## VALIDATION
- Strengths: [what's good]
- Issues: [what's broken or risky]
- Fixes: [exact changes needed]

## BUILD INSTRUCTIONS FOR CLAUDE CODE
Step-by-step implementation tasks. Be extremely specific:
- Exact file paths
- Exact function signatures
- Exact database queries
- Exact error handling
Claude Code follows these LITERALLY. If you're vague, it will guess wrong."""

BUILD_AGENT_SYSTEM = """You are Claude Code, the execution engine for Phantom Capital.
You receive a build spec and produce COMPLETE, WORKING CODE.
Rules:
1. Build EXACTLY to spec. Do not deviate.
2. Every file must be complete — no placeholders, no TODOs, no "implement this".
3. Include all imports, all error handling, all types.
4. If anything is ambiguous, output a QUESTION at the top instead of guessing.
5. Output format: For each file, output the path and full content.
6. Use Python for backends, TypeScript/React for frontends unless spec says otherwise."""

REVIEWER_SYSTEM = """You are the code reviewer for Phantom Capital.
Given code output from the build agent, audit for CRITICAL issues ONLY:
1. Correctness — does it match the spec? Are there missing files or broken logic?
2. Security — ONLY flag actual vulnerabilities (SQL injection, auth bypass, exposed secrets). Do NOT flag theoretical hardening suggestions.
3. Functionality — will the code actually run? Missing imports, syntax errors, broken references?
4. Missing pieces — anything the spec REQUIRED that wasn't built?

IMPORTANT RULES:
- PASS the code if it is functional and matches the spec. Perfection is NOT required.
- Do NOT flag style issues, best practices, or "nice to have" improvements.
- Do NOT invent new issues that weren't in the original review. On fix cycles, ONLY check if the previously flagged issues were resolved.
- If the code works and is safe, PASS it. Bias toward PASS.
- A working MVP that matches the spec is a PASS.

Output format:
## VERDICT: PASS or NEEDS_FIX

## ISSUES (if any)
For each issue:
- File: [path]
- Problem: [what's broken — must be a functional or security issue]
- Fix: [exact change needed]

If PASS, say PASS with a one-line summary."""


async def call_openai(system: str, user_msg: str, model: str = "gpt-4o") -> str:
    """Call OpenAI-compatible API and return text response."""
    is_openrouter = "openrouter" in OPENAI_BASE_URL
    async with httpx.AsyncClient(timeout=300) as client:
        resp = await client.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
            json={
                "model": f"openai/{model}" if is_openrouter else model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_msg},
                ],
                "max_tokens": 16384,
                "temperature": 0.7,
            },
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


OPENROUTER_MODEL_MAP = {
    "claude-sonnet-4-20250514": "anthropic/claude-sonnet-4-6",
}

async def call_claude(system: str, user_msg: str, model: str = "claude-sonnet-4-20250514") -> str:
    """Call Anthropic API directly, or via OpenRouter if configured."""
    is_openrouter = "openrouter" in ANTHROPIC_BASE_URL
    if is_openrouter:
        model = OPENROUTER_MODEL_MAP.get(model, f"anthropic/{model}")
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{ANTHROPIC_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {ANTHROPIC_API_KEY}"},
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_msg},
                    ],
                    "max_tokens": 16384,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
    else:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                f"{ANTHROPIC_BASE_URL}/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 16384,
                    "system": system,
                    "messages": [{"role": "user", "content": user_msg}],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return "".join(block["text"] for block in data["content"] if block["type"] == "text")


async def architect(idea: str) -> str:
    """Phase: Architecture — GPT-4 designs the system."""
    return await call_openai(ARCHITECT_SYSTEM, f"Build a system for this idea:\n\n{idea}")


async def validate(architecture: str) -> str:
    """Phase: Validation — Claude validates and produces build instructions."""
    return await call_claude(VALIDATOR_SYSTEM, f"Validate this architecture spec:\n\n{architecture}")


async def build(spec: str) -> str:
    """Phase: Build — Claude generates complete code."""
    return await call_claude(BUILD_AGENT_SYSTEM, f"Build this system:\n\n{spec}")


async def review(code: str, spec: str) -> str:
    """Phase: Review — Claude audits the code against spec."""
    prompt = f"## ORIGINAL SPEC\n{spec}\n\n## CODE TO REVIEW\n{code}"
    return await call_claude(REVIEWER_SYSTEM, prompt)
