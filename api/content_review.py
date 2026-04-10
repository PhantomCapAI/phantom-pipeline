"""
Content Review Pipeline — dual-LLM editorial flow.
RAW INPUT → GPT-4o draft → Claude editorial review → Telegram approval
"""

import os
import httpx

from agents import call_claude

TELEGRAM_BOT_TOKEN = os.getenv("OPS_TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1516882079")


# ─── System Prompts ──────────────────────────────────────────────────

DRAFTER_SYSTEM = """You are a content writer for Phantom Capital, an AI-native crypto/tech brand.

You take raw research notes and format them into a polished draft ready for social posting.

Rules based on platform:
- x_thread: Numbered tweet thread (1/N format). Each tweet max 280 chars. Hook first, CTA last.
- blog: Long-form article with headers, subheaders, intro, body, conclusion.
- telegram: Concise bulletin-style post with key points, bold highlights, and a takeaway.

Rules based on tone:
- rough: Street-smart, direct, no fluff. Short sentences. Confidence without arrogance.
- professional: Clean, data-driven, authoritative. No slang.
- degen: CT native voice. Memes welcome. Emoji-heavy. "ser", "anon", "lfg" vocabulary.

NEVER use hashtags. No #anything. Zero hashtags in any output.
NEVER use generic hype phrases like LFG, make history, disrupt, game-changer, revolutionary, you're early, don't miss out, stay tuned, big news, just the beginning, watch this space, keep your eyes peeled, real deal.
Maximum 1 emoji per post. Zero is preferred.
Preserve all line breaks in the input. If the raw input has blank lines, keep them.
Voice: direct, factual, no hype. State what exists. Do not sell or convince.

Output ONLY the formatted draft. No meta-commentary. No preamble."""

EDITOR_SYSTEM = """You are the editorial review agent for Phantom Capital. Your job is to take a draft and clean it for publication.

You MUST fix these issues:
1. FINANCIAL ADVICE: Remove any language that could be construed as financial advice. No "you should buy", "this will moon", "guaranteed returns". Replace with observational language.
2. HANDLE SPAM: Max 1 @mention per thread. Remove all gratuitous tagging.
3. DOLLAR VALUES: Round all dollar values to clean numbers. $1,234,567 → $1.2M. No cents.
4. AI SLOP: Kill these phrases on sight — "dive into", "let's unpack", "in the ever-evolving landscape", "it's worth noting", "game-changer", "revolutionary", "paradigm shift", "buckle up", "LFG", "make history", "disrupt", "you're early", "don't miss out", "stay tuned", "big news", "just the beginning", "watch this space", "keep your eyes peeled", "follow us to keep up", "real deal", "lean mean", "testing the waters". Replace with direct, specific language or delete entirely.
5. HASHTAGS: Remove ALL hashtags. No #anything. Ever. Zero tolerance.
6. FILLER: Remove all meta-intros ("In this thread...", "Big news folks"). Start with the substance.
7. EMOJIS: Maximum 1 emoji per tweet in a thread. Zero is preferred. No emoji at start of tweets.
8. FORMATTING: Preserve all line breaks exactly as written. Do not collapse lines. If the input has blank lines between sentences, keep them.
9. CONSISTENCY: Ensure numbering is correct for threads. Ensure tone matches throughout.
10. TONE: Phantom Capital voice is direct, factual, confident without hype. State what exists. No selling, no convincing, no excitement language.

Output ONLY the cleaned final draft. Preserve the EXACT formatting including all line breaks. No meta-commentary."""


async def gpt_draft(raw_input: str, platform: str, tone: str, max_posts: int) -> str:
    """Step 1: Claude drafts from raw research (was GPT-4o, switched to Anthropic direct)."""
    user_msg = f"""Platform: {platform}
Tone: {tone}
Max posts/sections: {max_posts}

Raw research:
{raw_input}"""

    return await call_claude(DRAFTER_SYSTEM, user_msg, model="claude-sonnet-4-20250514")


async def claude_editorial(draft: str, platform: str, tone: str) -> str:
    """Step 2: Claude reviews and cleans the draft."""
    user_msg = f"""Platform: {platform}
Tone: {tone}

Draft to review:
{draft}"""

    return await call_claude(EDITOR_SYSTEM, user_msg)


async def send_telegram_draft(draft_id: int, final_text: str, platform: str):
    """Step 3: Send final draft to Telegram with inline approve/reject/edit buttons."""
    if not TELEGRAM_BOT_TOKEN:
        return

    message = f"*Content Review #{draft_id}*\nPlatform: `{platform}`\n\n{final_text}"

    # Telegram message limit is 4096 chars
    if len(message) > 4000:
        message = message[:3997] + "..."

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "Approve", "callback_data": f"cr_approve_{draft_id}"},
                {"text": "Reject", "callback_data": f"cr_reject_{draft_id}"},
                {"text": "Edit", "callback_data": f"cr_edit_{draft_id}"},
            ]
        ]
    }

    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
                "reply_markup": keyboard,
            },
        )
