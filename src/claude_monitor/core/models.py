"""Data models for Claude Monitor.
Core data structures for usage tracking, session management, and token calculations.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


class CostMode(Enum):
    """Cost calculation modes for token usage analysis."""

    AUTO = "auto"
    CACHED = "cached"
    CALCULATED = "calculate"


class BillingPeriodType(Enum):
    """Types of billing periods for cost tracking."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


@dataclass
class UsageEntry:
    """Individual usage record from Claude usage data."""

    timestamp: datetime
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    message_id: str = ""
    request_id: str = ""


@dataclass
class TokenCounts:
    """Token aggregation structure with computed totals."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Get total tokens across all types."""
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_tokens
            + self.cache_read_tokens
        )


@dataclass
class BurnRate:
    """Token consumption rate metrics."""

    tokens_per_minute: float
    cost_per_hour: float


@dataclass
class UsageProjection:
    """Usage projection calculations for active blocks."""

    projected_total_tokens: int
    projected_total_cost: float
    remaining_minutes: float


@dataclass
class SessionBlock:
    """Aggregated session block representing a 5-hour period."""

    id: str
    start_time: datetime
    end_time: datetime
    entries: List[UsageEntry] = field(default_factory=list)
    token_counts: TokenCounts = field(default_factory=TokenCounts)
    is_active: bool = False
    is_gap: bool = False
    burn_rate: Optional[BurnRate] = None
    actual_end_time: Optional[datetime] = None
    per_model_stats: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    models: List[str] = field(default_factory=list)
    sent_messages_count: int = 0
    cost_usd: float = 0.0
    limit_messages: List[Dict[str, Any]] = field(default_factory=list)
    projection_data: Optional[Dict[str, Any]] = None
    burn_rate_snapshot: Optional[BurnRate] = None

    @property
    def total_tokens(self) -> int:
        """Get total tokens from token_counts."""
        return self.token_counts.total_tokens

    @property
    def total_cost(self) -> float:
        """Get total cost - alias for cost_usd."""
        return self.cost_usd

    @property
    def duration_minutes(self) -> float:
        """Get duration in minutes."""
        if self.actual_end_time:
            duration = (self.actual_end_time - self.start_time).total_seconds() / 60
        else:
            duration = (self.end_time - self.start_time).total_seconds() / 60
        return max(duration, 1.0)


@dataclass
class BillingPeriod:
    """Represents a billing period with its boundaries and metadata."""

    period_type: BillingPeriodType
    start_time: datetime
    end_time: datetime
    is_current: bool = False
    custom_label: Optional[str] = None

    @property
    def duration_days(self) -> float:
        """Get duration in days."""
        return (self.end_time - self.start_time).total_seconds() / (24 * 3600)

    @property
    def duration_hours(self) -> float:
        """Get duration in hours."""
        return (self.end_time - self.start_time).total_seconds() / 3600

    def contains_timestamp(self, timestamp: datetime) -> bool:
        """Check if timestamp falls within this billing period."""
        return self.start_time <= timestamp < self.end_time


@dataclass
class BillingPeriodSummary:
    """Summary of usage and costs within a billing period."""

    period: BillingPeriod
    total_cost: float = 0.0
    total_tokens: int = 0
    token_counts: TokenCounts = field(default_factory=TokenCounts)
    session_blocks: List[SessionBlock] = field(default_factory=list)
    entries_count: int = 0
    models_used: List[str] = field(default_factory=list)
    per_model_costs: Dict[str, float] = field(default_factory=dict)
    first_usage: Optional[datetime] = None
    last_usage: Optional[datetime] = None

    @property
    def average_cost_per_day(self) -> float:
        """Calculate average cost per day in this period."""
        if self.period.duration_days > 0:
            return self.total_cost / self.period.duration_days
        return 0.0

    @property
    def cost_percentage_of_period(self) -> float:
        """Calculate what percentage of the period has been used (by time)."""
        if not self.period.is_current:
            return 100.0
        
        now = datetime.now(self.period.start_time.tzinfo or timezone.utc)
        if now <= self.period.start_time:
            return 0.0
        if now >= self.period.end_time:
            return 100.0
            
        elapsed = (now - self.period.start_time).total_seconds()
        total = (self.period.end_time - self.period.start_time).total_seconds()
        return (elapsed / total) * 100.0

    def add_session_block(self, session_block: SessionBlock) -> None:
        """Add a session block to this billing period summary."""
        # Only include entries that fall within the billing period
        relevant_entries = [
            entry for entry in session_block.entries
            if self.period.contains_timestamp(entry.timestamp)
        ]
        
        if not relevant_entries:
            return
            
        self.session_blocks.append(session_block)
        
        # Aggregate costs and tokens from relevant entries
        period_cost = 0.0
        period_tokens = TokenCounts()
        
        for entry in relevant_entries:
            period_cost += entry.cost_usd
            period_tokens.input_tokens += entry.input_tokens
            period_tokens.output_tokens += entry.output_tokens
            period_tokens.cache_creation_tokens += entry.cache_creation_tokens
            period_tokens.cache_read_tokens += entry.cache_read_tokens
            
            # Track model usage
            if entry.model and entry.model not in self.models_used:
                self.models_used.append(entry.model)
                
            # Track per-model costs
            if entry.model in self.per_model_costs:
                self.per_model_costs[entry.model] += entry.cost_usd
            else:
                self.per_model_costs[entry.model] = entry.cost_usd
        
        self.total_cost += period_cost
        self.token_counts.input_tokens += period_tokens.input_tokens
        self.token_counts.output_tokens += period_tokens.output_tokens
        self.token_counts.cache_creation_tokens += period_tokens.cache_creation_tokens
        self.token_counts.cache_read_tokens += period_tokens.cache_read_tokens
        self.entries_count += len(relevant_entries)
        
        # Update first/last usage timestamps
        entry_timestamps = [entry.timestamp for entry in relevant_entries]
        if entry_timestamps:
            earliest = min(entry_timestamps)
            latest = max(entry_timestamps)
            
            if self.first_usage is None or earliest < self.first_usage:
                self.first_usage = earliest
            if self.last_usage is None or latest > self.last_usage:
                self.last_usage = latest

    @property
    def total_tokens_calculated(self) -> int:
        """Get total tokens from token_counts."""
        return self.token_counts.total_tokens


def normalize_model_name(model: str) -> str:
    """Normalize model name for consistent usage across the application.

    Handles various model name formats and maps them to standard keys.
    (Moved from utils/model_utils.py)

    Args:
        model: Raw model name from usage data

    Returns:
        Normalized model key

    Examples:
        >>> normalize_model_name("claude-3-opus-20240229")
        'claude-3-opus'
        >>> normalize_model_name("Claude 3.5 Sonnet")
        'claude-3-5-sonnet'
    """
    if not model:
        return ""

    model_lower = model.lower()

    if (
        "claude-opus-4-" in model_lower
        or "claude-sonnet-4-" in model_lower
        or "claude-haiku-4-" in model_lower
        or "sonnet-4-" in model_lower
        or "opus-4-" in model_lower
        or "haiku-4-" in model_lower
    ):
        return model_lower

    if "opus" in model_lower:
        if "4-" in model_lower:
            return model_lower
        return "claude-3-opus"
    if "sonnet" in model_lower:
        if "4-" in model_lower:
            return model_lower
        if "3.5" in model_lower or "3-5" in model_lower:
            return "claude-3-5-sonnet"
        return "claude-3-sonnet"
    if "haiku" in model_lower:
        if "3.5" in model_lower or "3-5" in model_lower:
            return "claude-3-5-haiku"
        return "claude-3-haiku"

    return model
