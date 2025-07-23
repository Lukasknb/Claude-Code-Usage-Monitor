"""Billing period display components for Claude Monitor.

Handles formatting and display of billing period cost information.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from claude_monitor.ui.progress_bars import CostProgressBar
from claude_monitor.utils.formatting import format_currency, format_number
from claude_monitor.utils.time_utils import format_display_time, format_duration


@dataclass
class BillingPeriodDisplayData:
    """Data container for billing period display information."""

    period_type: str
    is_current: bool
    start_time: str
    end_time: str
    total_cost: float
    total_tokens: int
    entries_count: int
    models_used: List[str]
    per_model_costs: Dict[str, float]
    average_cost_per_day: float
    cost_percentage_of_period: float
    duration_days: float
    first_usage: Optional[str] = None
    last_usage: Optional[str] = None
    next_reset: Optional[str] = None
    time_until_reset: Optional[float] = None


class BillingPeriodDisplayComponent:
    """Component for displaying billing period cost information."""

    def __init__(self):
        """Initialize billing period display component."""
        self.cost_progress = CostProgressBar()

    def format_billing_period_summary(
        self, 
        data: BillingPeriodDisplayData,
        timezone: str = "UTC",
    ) -> List[str]:
        """Format billing period summary for display.

        Args:
            data: Billing period display data
            timezone: User timezone for time formatting

        Returns:
            List of formatted display lines
        """
        lines = []
        
        # Header
        period_type_display = data.period_type.title()
        status = "Current" if data.is_current else "Past"
        lines.append(f"📊 {status} {period_type_display} Billing Period")
        lines.append("")

        # Period information
        start_time = self._format_time(data.start_time, timezone)
        end_time = self._format_time(data.end_time, timezone)
        lines.append(f"📅 Period: {start_time} → {end_time}")
        lines.append(f"⏱️  Duration: {data.duration_days:.1f} days")
        
        if data.is_current and data.time_until_reset:
            time_remaining = self._format_time_remaining(data.time_until_reset)
            lines.append(f"⏰ Time until reset: {time_remaining}")
        
        lines.append("")

        # Cost summary
        lines.append("💰 Cost Summary:")
        lines.append(f"   Total cost: {format_currency(data.total_cost)}")
        lines.append(f"   Daily average: {format_currency(data.average_cost_per_day)}")
        
        if data.is_current:
            progress_bar = self._render_period_progress(data.cost_percentage_of_period)
            lines.append(f"   Period progress: {progress_bar} {data.cost_percentage_of_period:.1f}%")
        
        lines.append("")

        # Usage statistics
        lines.append("📈 Usage Statistics:")
        lines.append(f"   Total tokens: {format_number(data.total_tokens)}")
        lines.append(f"   API calls: {format_number(data.entries_count)}")
        lines.append(f"   Models used: {len(data.models_used)}")
        
        if data.first_usage and data.last_usage:
            first_usage = self._format_time(data.first_usage, timezone)
            last_usage = self._format_time(data.last_usage, timezone)
            lines.append(f"   First usage: {first_usage}")
            lines.append(f"   Last usage: {last_usage}")
        
        lines.append("")

        # Per-model breakdown if multiple models used
        if len(data.per_model_costs) > 1:
            lines.append("🤖 Cost by Model:")
            sorted_costs = sorted(
                data.per_model_costs.items(), 
                key=lambda x: x[1], 
                reverse=True
            )
            for model, cost in sorted_costs:
                percentage = (cost / data.total_cost * 100) if data.total_cost > 0 else 0
                lines.append(f"   {model}: {format_currency(cost)} ({percentage:.1f}%)")
            lines.append("")

        return lines

    def format_recent_periods_summary(
        self,
        periods_data: List[BillingPeriodDisplayData],
        timezone: str = "UTC",
    ) -> List[str]:
        """Format summary of recent billing periods.

        Args:
            periods_data: List of recent billing period data
            timezone: User timezone for time formatting

        Returns:
            List of formatted display lines
        """
        if not periods_data:
            return ["No billing period data available."]

        lines = []
        current_period = next((p for p in periods_data if p.is_current), None)
        
        if current_period:
            lines.append("📊 Current Billing Period")
            lines.append(f"   Cost: {format_currency(current_period.total_cost)}")
            lines.append(f"   Tokens: {format_number(current_period.total_tokens)}")
            
            if current_period.time_until_reset:
                time_remaining = self._format_time_remaining(current_period.time_until_reset)
                lines.append(f"   Resets in: {time_remaining}")
            
            lines.append("")

        # Recent periods summary
        past_periods = [p for p in periods_data if not p.is_current and p.total_cost > 0]
        if past_periods:
            lines.append("📈 Recent Periods:")
            
            for period in past_periods[:5]:  # Show last 5 periods
                period_label = self._get_period_label(period, timezone)
                lines.append(f"   {period_label}: {format_currency(period.total_cost)}")
            
            lines.append("")

        return lines

    def format_billing_period_compact(
        self, 
        data: BillingPeriodDisplayData
    ) -> str:
        """Format compact billing period info for status display.

        Args:
            data: Billing period display data

        Returns:
            Compact formatted string
        """
        if not data.is_current:
            return f"{data.period_type.title()}: {format_currency(data.total_cost)}"
        
        progress = f"{data.cost_percentage_of_period:.0f}%"
        cost = format_currency(data.total_cost)
        
        if data.time_until_reset:
            time_remaining = self._format_time_remaining(data.time_until_reset)
            return f"{data.period_type.title()}: {cost} ({progress}, resets in {time_remaining})"
        else:
            return f"{data.period_type.title()}: {cost} ({progress})"

    def _render_period_progress(self, percentage: float) -> str:
        """Render progress bar for period completion.

        Args:
            percentage: Percentage of period completed

        Returns:
            Formatted progress bar
        """
        # Use a simple character-based progress bar
        width = 20
        filled = int(width * percentage / 100)
        empty = width - filled
        
        if percentage < 50:
            fill_char = "▓"
        elif percentage < 80:
            fill_char = "▓"
        else:
            fill_char = "▓"
        
        bar = fill_char * filled + "░" * empty
        return f"[{bar}]"

    def _format_time(self, timestamp_str: str, timezone: str) -> str:
        """Format timestamp for display.

        Args:
            timestamp_str: ISO format timestamp string
            timezone: User timezone

        Returns:
            Formatted time string
        """
        try:
            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            return format_display_time(timestamp, timezone, "auto")
        except (ValueError, AttributeError):
            return timestamp_str

    def _format_time_remaining(self, seconds: float) -> str:
        """Format time remaining until reset.

        Args:
            seconds: Seconds remaining

        Returns:
            Formatted duration string
        """
        if seconds <= 0:
            return "expired"
        
        delta = timedelta(seconds=seconds)
        return format_duration(delta)

    def _get_period_label(self, period: BillingPeriodDisplayData, timezone: str) -> str:
        """Get a readable label for a billing period.

        Args:
            period: Billing period data
            timezone: User timezone

        Returns:
            Period label string
        """
        try:
            start_time = datetime.fromisoformat(period.start_time.replace('Z', '+00:00'))
            
            if period.period_type == "daily":
                return start_time.strftime("%b %d")
            elif period.period_type == "weekly":
                end_time = datetime.fromisoformat(period.end_time.replace('Z', '+00:00'))
                return f"{start_time.strftime('%b %d')} - {end_time.strftime('%b %d')}"
            elif period.period_type == "monthly":
                return start_time.strftime("%b %Y")
            else:
                return start_time.strftime("%b %d")
        except (ValueError, AttributeError):
            return f"{period.period_type.title()} Period"