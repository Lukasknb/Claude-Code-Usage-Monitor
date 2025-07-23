"""
Usage analysis functionality for Claude Monitor.
Contains the main analyze_usage function and related analysis components.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from claude_monitor.core.billing_periods import BillingPeriodCalculator
from claude_monitor.core.calculations import BurnRateCalculator
from claude_monitor.core.models import (
    BillingPeriodSummary,
    BillingPeriodType,
    CostMode,
    SessionBlock,
    UsageEntry,
)
from claude_monitor.data.analyzer import SessionAnalyzer
from claude_monitor.data.reader import load_usage_entries

logger = logging.getLogger(__name__)


def analyze_usage(
    hours_back: Optional[int] = 96,
    use_cache: bool = True,
    quick_start: bool = False,
    data_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Main entry point to generate response_final.json.

    Algorithm redesigned to:
    1. First divide all outputs into blocks
    2. Save data about outputs (tokens in/out, cache, tokens by model, entries)
    3. Only then check for limits
    4. If limit is detected, add information that it occurred

    Args:
        hours_back: Only analyze data from last N hours (None = all data)
        use_cache: Use cached data when available
        quick_start: Use minimal data for quick startup (last 24h only)
        data_path: Optional path to Claude data directory

    Returns:
        Dictionary with analyzed blocks
    """
    logger.info(
        f"analyze_usage called with hours_back={hours_back}, use_cache={use_cache}, "
        f"quick_start={quick_start}, data_path={data_path}"
    )

    if quick_start and hours_back is None:
        hours_back = 24
        logger.info("Quick start mode: loading only last 24 hours")
    elif quick_start:
        logger.info(f"Quick start mode: loading last {hours_back} hours")

    start_time = datetime.now()
    entries, raw_entries = load_usage_entries(
        data_path=data_path,
        hours_back=hours_back,
        mode=CostMode.AUTO,
        include_raw=True,
    )
    load_time = (datetime.now() - start_time).total_seconds()
    logger.info(f"Data loaded in {load_time:.3f}s")

    start_time = datetime.now()
    analyzer = SessionAnalyzer(session_duration_hours=5)
    blocks = analyzer.transform_to_blocks(entries)
    transform_time = (datetime.now() - start_time).total_seconds()
    logger.info(f"Created {len(blocks)} blocks in {transform_time:.3f}s")

    calculator = BurnRateCalculator()
    _process_burn_rates(blocks, calculator)

    limits_detected = 0
    if raw_entries:
        limit_detections = analyzer.detect_limits(raw_entries)
        limits_detected = len(limit_detections)

        for block in blocks:
            block_limits = [
                _format_limit_info(limit_info)
                for limit_info in limit_detections
                if _is_limit_in_block_timerange(limit_info, block)
            ]
            if block_limits:
                block.limit_messages = block_limits

    metadata: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "hours_analyzed": hours_back or "all",
        "entries_processed": len(entries),
        "blocks_created": len(blocks),
        "limits_detected": limits_detected,
        "load_time_seconds": load_time,
        "transform_time_seconds": transform_time,
        "cache_used": use_cache,
        "quick_start": quick_start,
    }

    result = _create_result(blocks, entries, metadata)
    logger.info(f"analyze_usage returning {len(result['blocks'])} blocks")
    return result


def analyze_usage_with_billing_periods(
    billing_period_type: str = "none",
    billing_start_date: Optional[str] = None,
    billing_reset_day: Optional[int] = None,
    user_timezone: str = "UTC",
    hours_back: Optional[int] = 96,
    use_cache: bool = True,
    quick_start: bool = False,
    data_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Analyze usage with billing period aggregation support.

    Args:
        billing_period_type: Type of billing period (none, daily, weekly, monthly, custom)
        billing_start_date: Start date for custom billing periods (YYYY-MM-DD)
        billing_reset_day: Reset day for weekly/monthly periods
        user_timezone: User's timezone for period calculations
        hours_back: Only analyze data from last N hours (None = all data)
        use_cache: Use cached data when available
        quick_start: Use minimal data for quick startup
        data_path: Optional path to Claude data directory

    Returns:
        Dictionary with analyzed blocks and optional billing period data
    """
    logger.info(
        f"analyze_usage_with_billing_periods called with billing_period={billing_period_type}, "
        f"hours_back={hours_back}, use_cache={use_cache}"
    )

    # First get the standard session block analysis
    result = analyze_usage(
        hours_back=hours_back,
        use_cache=use_cache,
        quick_start=quick_start,
        data_path=data_path,
    )

    # If billing period tracking is disabled, return standard result
    if billing_period_type == "none":
        return result

    # Extract session blocks from the result (they're already processed as dicts)
    blocks_data = result.get("blocks", [])

    if not blocks_data:
        logger.info("No session blocks to analyze for billing periods")
        return result

    # Set up billing period calculator
    try:
        period_type_enum = BillingPeriodType(billing_period_type)
    except ValueError:
        logger.warning(f"Invalid billing period type: {billing_period_type}")
        return result

    # Parse custom start date if provided
    custom_start_date = None
    if billing_start_date:
        try:
            custom_start_date = datetime.strptime(billing_start_date, "%Y-%m-%d")
        except ValueError:
            logger.warning(f"Invalid billing start date format: {billing_start_date}")

    calculator = BillingPeriodCalculator(
        period_type=period_type_enum,
        custom_start_date=custom_start_date,
        reset_day=billing_reset_day,
        user_timezone=user_timezone,
    )

    # For now, just add basic billing period information without full integration
    # TODO: Implement proper session block to billing period conversion
    current_period = calculator.get_current_period()
    next_reset = calculator.get_next_reset_time()
    time_until_reset = calculator.get_time_until_reset()

    # Calculate total cost from blocks data
    total_cost = sum(block.get("costUSD", 0) for block in blocks_data)

    billing_summaries = [{
        "period": {
            "type": current_period.period_type.value,
            "start_time": current_period.start_time.isoformat(),
            "end_time": current_period.end_time.isoformat(),
            "is_current": current_period.is_current,
            "duration_days": current_period.duration_days,
        },
        "usage": {
            "total_cost": total_cost,
            "total_tokens": sum(block.get("totalTokens", 0) for block in blocks_data),
            "entries_count": sum(len(block.get("entries", [])) for block in blocks_data),
            "session_blocks_count": len(blocks_data),
        }
    }]

    # Add billing period data to result
    result["billing_periods"] = {
        "enabled": True,
        "period_type": billing_period_type,
        "current_period": billing_summaries[0] if billing_summaries else None,
        "recent_periods": billing_summaries,
        "next_reset": next_reset.isoformat(),
        "time_until_reset": time_until_reset.total_seconds(),
    }

    logger.info(f"Added {len(billing_summaries)} billing period summaries to result")
    return result


def _format_billing_period_summary(summary: BillingPeriodSummary) -> Dict[str, Any]:
    """Format billing period summary for JSON serialization."""
    return {
        "period": {
            "type": summary.period.period_type.value,
            "start_time": summary.period.start_time.isoformat(),
            "end_time": summary.period.end_time.isoformat(),
            "is_current": summary.period.is_current,
            "duration_days": summary.period.duration_days,
            "custom_label": summary.period.custom_label,
        },
        "usage": {
            "total_cost": summary.total_cost,
            "total_tokens": summary.total_tokens_calculated,
            "entries_count": summary.entries_count,
            "session_blocks_count": len(summary.session_blocks),
            "models_used": summary.models_used,
            "per_model_costs": summary.per_model_costs,
            "average_cost_per_day": summary.average_cost_per_day,
            "cost_percentage_of_period": summary.cost_percentage_of_period,
        },
        "tokens": {
            "input_tokens": summary.token_counts.input_tokens,
            "output_tokens": summary.token_counts.output_tokens,
            "cache_creation_tokens": summary.token_counts.cache_creation_tokens,
            "cache_read_tokens": summary.token_counts.cache_read_tokens,
            "total_tokens": summary.token_counts.total_tokens,
        },
        "timestamps": {
            "first_usage": summary.first_usage.isoformat() if summary.first_usage else None,
            "last_usage": summary.last_usage.isoformat() if summary.last_usage else None,
        },
    }


def _process_burn_rates(
    blocks: List[SessionBlock], calculator: BurnRateCalculator
) -> None:
    """Process burn rate data for active blocks."""
    for block in blocks:
        if block.is_active:
            burn_rate = calculator.calculate_burn_rate(block)
            if burn_rate:
                block.burn_rate_snapshot = burn_rate
                projection = calculator.project_block_usage(block)
                if projection:
                    block.projection_data = {
                        "totalTokens": projection.projected_total_tokens,
                        "totalCost": projection.projected_total_cost,
                        "remainingMinutes": projection.remaining_minutes,
                    }


def _create_result(
    blocks: List[SessionBlock], entries: List[UsageEntry], metadata: Dict[str, Any]
) -> Dict[str, Any]:
    """Create the final result dictionary."""
    blocks_data = _convert_blocks_to_dict_format(blocks)

    total_tokens = sum(b.total_tokens for b in blocks)
    total_cost = sum(b.cost_usd for b in blocks)

    return {
        "blocks": blocks_data,
        "metadata": metadata,
        "entries_count": len(entries),
        "total_tokens": total_tokens,
        "total_cost": total_cost,
    }


def _is_limit_in_block_timerange(
    limit_info: Dict[str, Any], block: SessionBlock
) -> bool:
    """Check if limit timestamp falls within block's time range."""
    limit_timestamp = limit_info["timestamp"]

    if limit_timestamp.tzinfo is None:
        limit_timestamp = limit_timestamp.replace(tzinfo=timezone.utc)

    return block.start_time <= limit_timestamp <= block.end_time


def _format_limit_info(limit_info: Dict[str, Any]) -> Dict[str, Any]:
    """Format limit info for block assignment."""
    return {
        "type": limit_info["type"],
        "timestamp": limit_info["timestamp"].isoformat(),
        "content": limit_info["content"],
        "reset_time": (
            limit_info["reset_time"].isoformat()
            if limit_info.get("reset_time")
            else None
        ),
    }


def _convert_blocks_to_dict_format(blocks: List[SessionBlock]) -> List[Dict[str, Any]]:
    """Convert blocks to dictionary format for JSON output."""
    blocks_data: List[Dict[str, Any]] = []

    for block in blocks:
        block_dict = _create_base_block_dict(block)
        _add_optional_block_data(block, block_dict)
        blocks_data.append(block_dict)

    return blocks_data


def _create_base_block_dict(block: SessionBlock) -> Dict[str, Any]:
    """Create base block dictionary with required fields."""
    return {
        "id": block.id,
        "isActive": block.is_active,
        "isGap": block.is_gap,
        "startTime": block.start_time.isoformat(),
        "endTime": block.end_time.isoformat(),
        "actualEndTime": (
            block.actual_end_time.isoformat() if block.actual_end_time else None
        ),
        "tokenCounts": {
            "inputTokens": block.token_counts.input_tokens,
            "outputTokens": block.token_counts.output_tokens,
            "cacheCreationInputTokens": block.token_counts.cache_creation_tokens,
            "cacheReadInputTokens": block.token_counts.cache_read_tokens,
        },
        "totalTokens": block.token_counts.input_tokens
        + block.token_counts.output_tokens,
        "costUSD": block.cost_usd,
        "models": block.models,
        "perModelStats": block.per_model_stats,
        "sentMessagesCount": block.sent_messages_count,
        "durationMinutes": block.duration_minutes,
        "entries": _format_block_entries(block.entries),
        "entries_count": len(block.entries),
    }


def _format_block_entries(entries: List[UsageEntry]) -> List[Dict[str, Any]]:
    """Format block entries for JSON output."""
    return [
        {
            "timestamp": entry.timestamp.isoformat(),
            "inputTokens": entry.input_tokens,
            "outputTokens": entry.output_tokens,
            "cacheCreationTokens": entry.cache_creation_tokens,
            "cacheReadInputTokens": entry.cache_read_tokens,
            "costUSD": entry.cost_usd,
            "model": entry.model,
            "messageId": entry.message_id,
            "requestId": entry.request_id,
        }
        for entry in entries
    ]


def _add_optional_block_data(block: SessionBlock, block_dict: Dict[str, Any]) -> None:
    """Add optional burn rate, projection, and limit data to block dict."""
    if hasattr(block, "burn_rate_snapshot") and block.burn_rate_snapshot:
        block_dict["burnRate"] = {
            "tokensPerMinute": block.burn_rate_snapshot.tokens_per_minute,
            "costPerHour": block.burn_rate_snapshot.cost_per_hour,
        }

    if hasattr(block, "projection_data") and block.projection_data:
        block_dict["projection"] = block.projection_data

    if hasattr(block, "limit_messages") and block.limit_messages:
        block_dict["limitMessages"] = block.limit_messages
