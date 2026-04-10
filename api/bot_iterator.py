"""
Bot Iterator — Generates improvement proposals for Polymarket bots
based on performance metrics, then routes through Telegram approval.
"""
import logging
import json
from bot_monitor import BOTS, check_targets

logger = logging.getLogger("pipeline.bot_iterator")


def generate_proposal(bot_name: str, metrics: dict, agent_fn=None) -> dict | None:
    """
    Analyze metrics and propose parameter changes.
    Returns a proposal dict or None if no changes needed.
    """
    issues = check_targets(metrics)
    if not issues and metrics.get("total_trades", metrics.get("arbs_found", metrics.get("evaluations", 0))) > 0:
        return None  # Meeting targets, no changes needed

    bot = BOTS[bot_name]
    proposal = {
        "bot": bot_name,
        "repo": bot["repo"],
        "service_id": bot["service_id"],
        "issues": issues,
        "metrics_snapshot": {k: v for k, v in metrics.items() if k not in ("bot", "error")},
        "changes": [],
    }

    # Generate parameter adjustment proposals based on issues
    if bot_name == "phantom-shadow":
        wr = metrics.get("win_rate", 0)
        trades = metrics.get("total_trades", 0)
        if trades == 0:
            proposal["changes"].append({
                "type": "param",
                "param": "min_whale_score",
                "from": bot["tunable"]["min_whale_score"]["current"],
                "to": max(50, bot["tunable"]["min_whale_score"]["current"] - 10),
                "reason": "No trades — lower whale score threshold to get more signals",
            })
        elif wr < 0.55:
            proposal["changes"].append({
                "type": "param",
                "param": "min_whale_score",
                "from": bot["tunable"]["min_whale_score"]["current"],
                "to": min(90, bot["tunable"]["min_whale_score"]["current"] + 5),
                "reason": f"Win rate {wr:.1%} below 55% — raise score threshold for higher quality signals",
            })

    elif bot_name == "phantom-strike":
        arbs = metrics.get("arbs_per_day", 0)
        edge = metrics.get("net_edge_pct", 0)
        if arbs < 3:
            proposal["changes"].append({
                "type": "param",
                "param": "min_edge_pct",
                "from": bot["tunable"]["min_edge_pct"]["current"],
                "to": max(0.005, bot["tunable"]["min_edge_pct"]["current"] - 0.005),
                "reason": f"Only {arbs}/day arbs found — lower edge threshold to capture more",
            })
        if edge < 0.01 and arbs > 0:
            proposal["changes"].append({
                "type": "param",
                "param": "min_liquidity_usd",
                "from": bot["tunable"]["min_liquidity_usd"]["current"],
                "to": min(2000, bot["tunable"]["min_liquidity_usd"]["current"] + 200),
                "reason": f"Net edge {edge:.1%} below 1% — raise liquidity floor to filter noise",
            })

    elif bot_name == "phantom-sight":
        acc = metrics.get("eval_accuracy", 0)
        cost = metrics.get("cost_per_trade", 0)
        if acc < 0.6 and metrics.get("evaluations", 0) > 5:
            proposal["changes"].append({
                "type": "param",
                "param": "min_edge_pct",
                "from": bot["tunable"]["min_edge_pct"]["current"],
                "to": min(0.25, bot["tunable"]["min_edge_pct"]["current"] + 0.03),
                "reason": f"Accuracy {acc:.1%} below 60% — raise min edge to skip low-conviction picks",
            })
        if cost > 0.50:
            proposal["changes"].append({
                "type": "param",
                "param": "max_llm_calls_hour",
                "from": bot["tunable"]["max_llm_calls_hour"]["current"],
                "to": max(5, bot["tunable"]["max_llm_calls_hour"]["current"] - 3),
                "reason": f"Cost ${cost:.2f}/trade above $0.50 target — reduce LLM call rate",
            })

    elif bot_name == "phantom-pulse":
        spread = metrics.get("spread_earned_day", 0)
        fill_rate = metrics.get("fill_rate", 0)
        if fill_rate < 0.1 and metrics.get("quotes_placed", 0) > 10:
            proposal["changes"].append({
                "type": "param",
                "param": "target_spread_cents",
                "from": bot["tunable"]["target_spread_cents"]["current"],
                "to": max(1.5, bot["tunable"]["target_spread_cents"]["current"] - 0.5),
                "reason": f"Fill rate {fill_rate:.1%} below 10% — tighten spread to get more fills",
            })
        if spread < 1.0 and fill_rate > 0.1:
            proposal["changes"].append({
                "type": "param",
                "param": "quote_size_shares",
                "from": bot["tunable"]["quote_size_shares"]["current"],
                "to": min(100, bot["tunable"]["quote_size_shares"]["current"] + 10),
                "reason": f"Spread earned ${spread:.2f}/day below $1 — increase quote size",
            })

    if not proposal["changes"]:
        if issues:
            proposal["changes"].append({
                "type": "note",
                "reason": "Below targets but insufficient data for automated parameter tuning. Collecting more data.",
            })
        else:
            return None

    return proposal


def format_proposal_telegram(proposal: dict) -> str:
    """Format a proposal for Telegram notification."""
    bot = proposal["bot"]
    lines = [f"🔧 *{bot} Iteration Proposal*\n"]

    if proposal["issues"]:
        lines.append("*Issues:*")
        for issue in proposal["issues"]:
            lines.append(f"  ⚠️ {issue}")
        lines.append("")

    lines.append("*Proposed Changes:*")
    for c in proposal["changes"]:
        if c["type"] == "param":
            lines.append(f"  📐 `{c['param']}`: {c['from']} → {c['to']}")
            lines.append(f"     _{c['reason']}_")
        elif c["type"] == "note":
            lines.append(f"  📝 _{c['reason']}_")
    lines.append("")

    snap = proposal.get("metrics_snapshot", {})
    if snap:
        lines.append("*Metrics (24h):*")
        for k, v in snap.items():
            if k not in ("period_hours", "since"):
                lines.append(f"  {k}: `{v}`")
    lines.append("")

    pid = proposal.get("project_id", "?")
    lines.append(f"Reply `/approve {pid}` to apply or `/reject {pid}` to skip.")

    return "\n".join(lines)
