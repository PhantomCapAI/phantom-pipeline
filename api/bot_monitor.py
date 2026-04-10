"""
Bot Monitor — Queries Neon DB for Polymarket bot performance metrics.
Each bot writes to its own tables in the shared wraith_shadow database.
"""
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("pipeline.bot_monitor")

# Bot registry — maps bot name to its DB tables and metrics
BOTS = {
    "phantom-shadow": {
        "service_id": "69d119ed8e44c178f4114cb5",
        "repo": "PhantomCapAI/phantom-shadow",
        "tables": {"trades": "shadow_trades", "signals": "shadow_signals"},
        "metrics": ["paper_pnl", "win_rate", "signal_quality"],
        "tunable": {
            "min_whale_score": {"current": 70, "range": [50, 90], "config_path": "config.py:RiskConfig.min_whale_score"},
            "poll_interval_sec": {"current": 30, "range": [15, 120], "env": "POLL_INTERVAL_SEC"},
        },
        "targets": {"win_rate": 0.55, "signal_quality": 0.6},
    },
    "phantom-strike": {
        "service_id": "69d122dd8c8ae29c687e8bb9",
        "repo": "PhantomCapAI/phantom-strike",
        "tables": {"arbs": "sniper_arbs", "signals": "sniper_signals"},
        "metrics": ["arbs_per_day", "net_edge_pct", "dump_signals"],
        "tunable": {
            "min_edge_pct": {"current": 0.02, "range": [0.005, 0.05], "config_path": "config.py:SniperConfig.min_edge_pct"},
            "min_liquidity_usd": {"current": 500, "range": [100, 2000], "config_path": "config.py:SniperConfig.min_liquidity_usd"},
        },
        "targets": {"arbs_per_day": 3, "net_edge_pct": 0.01},
    },
    "phantom-sight": {
        "service_id": "69d128268c8ae29c687e8cd6",
        "repo": "PhantomCapAI/phantom-sight",
        "tables": {"evals": "oracle_evaluations", "trades": "oracle_trades"},
        "metrics": ["eval_accuracy", "cost_per_trade", "llm_calls"],
        "tunable": {
            "min_edge_pct": {"current": 0.12, "range": [0.05, 0.25], "config_path": "config.py:OracleConfig.min_edge_pct"},
            "max_llm_calls_hour": {"current": 15, "range": [5, 30], "env": "MAX_LLM_CALLS_HOUR"},
        },
        "targets": {"eval_accuracy": 0.6, "cost_per_trade": 0.50},
    },
    "phantom-pulse": {
        "service_id": "69d129a48c8ae29c687e8d3c",
        "repo": "PhantomCapAI/phantom-pulse",
        "tables": {"quotes": "maker_quotes", "fills": "maker_fills", "inventory": "maker_inventory"},
        "metrics": ["spread_earned_day", "fill_rate", "inventory_imbalance"],
        "tunable": {
            "target_spread_cents": {"current": 3.0, "range": [1.5, 8.0], "config_path": "config.py:QuotingConfig.target_spread_cents"},
            "quote_size_shares": {"current": 25, "range": [10, 100], "config_path": "config.py:QuotingConfig.quote_size_shares"},
            "max_markets": {"current": 5, "range": [1, 10], "config_path": "config.py:InventoryConfig.max_markets"},
        },
        "targets": {"spread_earned_day": 1.0, "fill_rate": 0.1},
    },
}


async def query_bot_metrics(pool, bot_name: str, hours: int = 24) -> dict:
    """Query last N hours of performance data for a bot."""
    bot = BOTS[bot_name]
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    metrics = {"bot": bot_name, "period_hours": hours, "since": since.isoformat()}

    try:
        if bot_name == "phantom-shadow":
            trades = await pool.fetch(
                f"SELECT * FROM {bot['tables']['trades']} WHERE created_at > $1 ORDER BY created_at DESC",
                since,
            )
            if trades:
                total = len(trades)
                wins = sum(1 for t in trades if (t.get("pnl") or 0) > 0)
                total_pnl = sum(t.get("pnl") or 0 for t in trades)
                metrics.update({
                    "total_trades": total,
                    "wins": wins,
                    "win_rate": round(wins / total, 3) if total else 0,
                    "paper_pnl": round(total_pnl, 2),
                    "signal_quality": round(wins / total, 3) if total else 0,
                })
            else:
                metrics.update({"total_trades": 0, "win_rate": 0, "paper_pnl": 0, "signal_quality": 0})

        elif bot_name == "phantom-strike":
            arbs = await pool.fetch(
                f"SELECT * FROM {bot['tables']['arbs']} WHERE created_at > $1",
                since,
            )
            arb_count = len(arbs) if arbs else 0
            profitable = sum(1 for a in (arbs or []) if (a.get("net_edge") or 0) > 0)
            metrics.update({
                "arbs_found": arb_count,
                "arbs_per_day": round(arb_count * 24 / max(hours, 1), 1),
                "net_edge_pct": round(profitable / arb_count, 3) if arb_count else 0,
                "dump_signals": sum(1 for a in (arbs or []) if a.get("type") == "dump"),
            })

        elif bot_name == "phantom-sight":
            evals = await pool.fetch(
                f"SELECT * FROM {bot['tables']['evals']} WHERE created_at > $1",
                since,
            )
            eval_count = len(evals) if evals else 0
            correct = sum(1 for e in (evals or []) if e.get("correct"))
            total_cost = sum(e.get("llm_cost") or 0 for e in (evals or []))
            metrics.update({
                "evaluations": eval_count,
                "eval_accuracy": round(correct / eval_count, 3) if eval_count else 0,
                "llm_calls": eval_count,
                "llm_cost": round(total_cost, 4),
                "cost_per_trade": round(total_cost / max(eval_count, 1), 4),
            })

        elif bot_name == "phantom-pulse":
            quotes = await pool.fetch(
                f"SELECT * FROM {bot['tables']['quotes']} WHERE created_at > $1",
                since,
            )
            fills = await pool.fetch(
                f"SELECT * FROM {bot['tables']['fills']} WHERE created_at > $1",
                since,
            )
            quote_count = len(quotes) if quotes else 0
            fill_count = len(fills) if fills else 0
            spread_earned = sum(f.get("spread_captured") or 0 for f in (fills or []))
            metrics.update({
                "quotes_placed": quote_count,
                "fills": fill_count,
                "fill_rate": round(fill_count / max(quote_count, 1), 3),
                "spread_earned_day": round(spread_earned * 24 / max(hours, 1), 2),
            })

    except Exception as e:
        # Tables may not exist yet in paper mode — that's fine
        logger.warning(f"Metrics query for {bot_name}: {e}")
        metrics["error"] = str(e)

    return metrics


async def get_all_bot_metrics(pool, hours: int = 24) -> list[dict]:
    """Get metrics for all 4 bots."""
    results = []
    for name in BOTS:
        m = await query_bot_metrics(pool, name, hours)
        results.append(m)
    return results


def check_targets(metrics: dict) -> list[str]:
    """Check if bot metrics meet targets. Returns list of issues."""
    bot_name = metrics.get("bot")
    if bot_name not in BOTS:
        return []

    targets = BOTS[bot_name]["targets"]
    issues = []

    for metric_name, target_val in targets.items():
        actual = metrics.get(metric_name, 0)
        if actual < target_val:
            issues.append(f"{metric_name}: {actual} (target: {target_val})")

    return issues
