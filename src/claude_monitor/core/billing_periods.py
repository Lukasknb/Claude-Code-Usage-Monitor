"""Billing period calculations for Claude Monitor.

Handles different types of billing periods (daily, weekly, monthly, custom)
and provides utilities for calculating period boundaries and aggregating costs.
"""

import calendar
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from claude_monitor.core.models import (
    BillingPeriod,
    BillingPeriodType,
    BillingPeriodSummary,
    SessionBlock,
)
from claude_monitor.utils.time_utils import TimezoneHandler

logger = logging.getLogger(__name__)


def _ensure_timezone(dt: datetime, target_tz) -> datetime:
    """Helper function to ensure datetime has correct timezone."""
    if dt.tzinfo is None:
        if hasattr(target_tz, 'localize'):
            return target_tz.localize(dt)
        else:
            return dt.replace(tzinfo=target_tz)
    else:
        return dt.astimezone(target_tz)


class BillingPeriodCalculator:
    """Calculates billing period boundaries and aggregates usage data."""

    def __init__(
        self,
        period_type: BillingPeriodType = BillingPeriodType.DAILY,
        custom_start_date: Optional[datetime] = None,
        reset_day: Optional[int] = None,
        user_timezone: str = "UTC",
    ):
        """Initialize billing period calculator.

        Args:
            period_type: Type of billing period
            custom_start_date: Start date for custom periods
            reset_day: Day of week (0=Monday) or month (1-31) for resets
            user_timezone: User's timezone for period calculations
        """
        self.period_type = period_type
        self.custom_start_date = custom_start_date
        self.reset_day = reset_day
        self.timezone_handler = TimezoneHandler()
        
        # Set up timezone
        try:
            if user_timezone == "UTC":
                self.user_tz = timezone.utc
            else:
                import pytz
                self.user_tz = pytz.timezone(user_timezone)
        except Exception:
            logger.warning(f"Invalid timezone {user_timezone}, using UTC")
            self.user_tz = timezone.utc

    def get_current_period(self, reference_time: Optional[datetime] = None) -> BillingPeriod:
        """Get the current billing period.

        Args:
            reference_time: Reference time for calculations (defaults to now)

        Returns:
            BillingPeriod representing the current period
        """
        if reference_time is None:
            reference_time = datetime.now(self.user_tz)
        else:
            reference_time = _ensure_timezone(reference_time, self.user_tz)

        start_time, end_time = self._calculate_period_boundaries(reference_time)
        
        return BillingPeriod(
            period_type=self.period_type,
            start_time=start_time,
            end_time=end_time,
            is_current=True,
        )

    def get_period_for_timestamp(self, timestamp: datetime) -> BillingPeriod:
        """Get the billing period that contains the given timestamp.

        Args:
            timestamp: The timestamp to find the period for

        Returns:
            BillingPeriod containing the timestamp
        """
        timestamp = _ensure_timezone(timestamp, self.user_tz)
        start_time, end_time = self._calculate_period_boundaries(timestamp)
        
        now = datetime.now(self.user_tz)
        is_current = start_time <= now < end_time
        
        return BillingPeriod(
            period_type=self.period_type,
            start_time=start_time,
            end_time=end_time,
            is_current=is_current,
        )

    def get_recent_periods(
        self, 
        count: int = 7, 
        reference_time: Optional[datetime] = None
    ) -> List[BillingPeriod]:
        """Get recent billing periods including current one.

        Args:
            count: Number of periods to return
            reference_time: Reference time for calculations

        Returns:
            List of BillingPeriod objects, most recent first
        """
        if reference_time is None:
            reference_time = datetime.now(self.user_tz)
        else:
            reference_time = _ensure_timezone(reference_time, self.user_tz)

        periods = []
        current_ref = reference_time

        for i in range(count):
            period = self.get_period_for_timestamp(current_ref)
            periods.append(period)
            
            # Move to previous period
            current_ref = period.start_time - timedelta(seconds=1)

        return periods

    def create_period_summary(
        self, 
        period: BillingPeriod, 
        session_blocks: List[SessionBlock]
    ) -> BillingPeriodSummary:
        """Create a summary for a billing period from session blocks.

        Args:
            period: The billing period to summarize
            session_blocks: Session blocks to include in the summary

        Returns:
            BillingPeriodSummary with aggregated data
        """
        summary = BillingPeriodSummary(period=period)
        
        for session_block in session_blocks:
            summary.add_session_block(session_block)
        
        return summary

    def _calculate_period_boundaries(self, reference_time: datetime) -> Tuple[datetime, datetime]:
        """Calculate start and end times for a billing period containing reference_time.

        Args:
            reference_time: Time to calculate period boundaries for

        Returns:
            Tuple of (start_time, end_time) for the period
        """
        if self.period_type == BillingPeriodType.DAILY:
            return self._calculate_daily_boundaries(reference_time)
        elif self.period_type == BillingPeriodType.WEEKLY:
            return self._calculate_weekly_boundaries(reference_time)
        elif self.period_type == BillingPeriodType.MONTHLY:
            return self._calculate_monthly_boundaries(reference_time)
        elif self.period_type == BillingPeriodType.CUSTOM:
            return self._calculate_custom_boundaries(reference_time)
        else:
            raise ValueError(f"Unsupported period type: {self.period_type}")

    def _calculate_daily_boundaries(self, reference_time: datetime) -> Tuple[datetime, datetime]:
        """Calculate daily period boundaries."""
        # Reset at midnight or custom hour
        reset_hour = self.reset_day if self.reset_day is not None else 0
        
        # Start of day
        start_of_day = reference_time.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # If reset hour is specified and we haven't reached it today, use yesterday's reset
        if reset_hour > 0:
            reset_today = start_of_day.replace(hour=reset_hour)
            if reference_time < reset_today:
                # Use yesterday's reset time
                start_time = reset_today - timedelta(days=1)
            else:
                # Use today's reset time
                start_time = reset_today
            end_time = start_time + timedelta(days=1)
        else:
            # Standard midnight-to-midnight
            start_time = start_of_day
            end_time = start_time + timedelta(days=1)
            
        return start_time, end_time

    def _calculate_weekly_boundaries(self, reference_time: datetime) -> Tuple[datetime, datetime]:
        """Calculate weekly period boundaries."""
        # Reset on Monday (0) or custom day
        reset_weekday = self.reset_day if self.reset_day is not None else 0  # Monday
        
        # Find the start of the week containing reference_time
        days_since_reset = (reference_time.weekday() - reset_weekday) % 7
        start_of_week = reference_time - timedelta(days=days_since_reset)
        start_time = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = start_time + timedelta(days=7)
        
        return start_time, end_time

    def _calculate_monthly_boundaries(self, reference_time: datetime) -> Tuple[datetime, datetime]:
        """Calculate monthly period boundaries."""
        # Reset on 1st or custom day of month
        reset_day = self.reset_day if self.reset_day is not None else 1
        
        # Ensure reset_day is valid for the month
        max_day = calendar.monthrange(reference_time.year, reference_time.month)[1]
        actual_reset_day = min(reset_day, max_day)
        
        # If we're before the reset day this month, use last month's reset
        if reference_time.day < actual_reset_day:
            # Go to previous month
            if reference_time.month == 1:
                prev_year = reference_time.year - 1
                prev_month = 12
            else:
                prev_year = reference_time.year  
                prev_month = reference_time.month - 1
                
            # Ensure reset day is valid for previous month
            prev_max_day = calendar.monthrange(prev_year, prev_month)[1]
            prev_reset_day = min(reset_day, prev_max_day)
            
            start_time = reference_time.replace(
                year=prev_year, month=prev_month, day=prev_reset_day,
                hour=0, minute=0, second=0, microsecond=0
            )
        else:
            # Use this month's reset
            start_time = reference_time.replace(
                day=actual_reset_day, hour=0, minute=0, second=0, microsecond=0
            )
        
        # Calculate end time (next month's reset day)
        if start_time.month == 12:
            next_year = start_time.year + 1
            next_month = 1
        else:
            next_year = start_time.year
            next_month = start_time.month + 1
            
        next_max_day = calendar.monthrange(next_year, next_month)[1]
        next_reset_day = min(reset_day, next_max_day)
        
        end_time = start_time.replace(
            year=next_year, month=next_month, day=next_reset_day
        )
        
        return start_time, end_time

    def _calculate_custom_boundaries(self, reference_time: datetime) -> Tuple[datetime, datetime]:
        """Calculate custom period boundaries."""
        if not self.custom_start_date:
            # Fallback to daily if no custom start date
            logger.warning("No custom start date provided, falling back to daily periods")
            return self._calculate_daily_boundaries(reference_time)
        
        custom_start = _ensure_timezone(self.custom_start_date, self.user_tz)
        
        # For custom periods, we need to determine the period duration
        # Default to 30 days if not specified otherwise
        period_duration = timedelta(days=30)
        
        # Calculate how many periods have passed since the custom start
        time_since_start = reference_time - custom_start
        periods_elapsed = int(time_since_start.total_seconds() / period_duration.total_seconds())
        
        start_time = custom_start + (period_duration * periods_elapsed)
        end_time = start_time + period_duration
        
        return start_time, end_time

    def get_next_reset_time(self, reference_time: Optional[datetime] = None) -> datetime:
        """Get the next billing period reset time.

        Args:
            reference_time: Reference time for calculations

        Returns:
            Next reset time
        """
        current_period = self.get_current_period(reference_time)
        return current_period.end_time

    def get_time_until_reset(self, reference_time: Optional[datetime] = None) -> timedelta:
        """Get time remaining until next billing period reset.

        Args:
            reference_time: Reference time for calculations

        Returns:
            Time remaining until reset
        """
        if reference_time is None:
            reference_time = datetime.now(self.user_tz)
        else:
            reference_time = _ensure_timezone(reference_time, self.user_tz)
            
        next_reset = self.get_next_reset_time(reference_time)
        return next_reset - reference_time