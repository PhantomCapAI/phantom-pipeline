# Phantom Pipeline v2 is Live

Fully autonomous dev orchestrator — submit an idea, GPT-4 architects it, Claude validates, builds, reviews, and auto-fixes until it passes. All controlled via Telegram.

## How it works
1. Submit an idea
2. GPT-4 designs the architecture
3. Claude validates and produces build instructions
4. You approve on Telegram
5. Claude builds the code, reviews it, auto-fixes issues
6. You approve for deploy

One idea in, production code out. First real project running through it now.

## Stack
- FastAPI on Zeabur
- OpenAI API (GPT-4) + Anthropic API (Claude)
- Neon Postgres
- Telegram bot for approvals
- Full audit trail on every build

Built by Phantom Capital. This is how autonomous AI companies ship.
