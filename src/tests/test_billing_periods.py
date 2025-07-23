"""Tests for billing period functionality."""

import pytest
from datetime import datetime, timezone, timedelta
from claude_monitor.core.billing_periods import BillingPeriodCalculator
from claude_monitor.core.models import BillingPeriodType, SessionBlock, UsageEntry, TokenCounts


class TestBillingPeriodCalculator:
    """Test billing period calculations."""

    def test_daily_period_calculation(self):
        """Test daily billing period boundaries."""
        calculator = BillingPeriodCalculator(
            period_type=BillingPeriodType.DAILY,
            user_timezone="UTC"
        )
        
        # Test with a specific reference time
        reference_time = datetime(2024, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
        period = calculator.get_current_period(reference_time)
        
        assert period.period_type == BillingPeriodType.DAILY
        assert period.start_time.day == 15
        assert period.start_time.hour == 0
        assert period.start_time.minute == 0
        assert period.end_time.day == 16
        assert period.end_time.hour == 0

    def test_weekly_period_calculation(self):
        """Test weekly billing period boundaries."""
        calculator = BillingPeriodCalculator(
            period_type=BillingPeriodType.WEEKLY,
            user_timezone="UTC"
        )
        
        # Test with a Wednesday (weekday 2)
        reference_time = datetime(2024, 1, 17, 14, 30, 0, tzinfo=timezone.utc)  # Wednesday
        period = calculator.get_current_period(reference_time)
        
        assert period.period_type == BillingPeriodType.WEEKLY
        assert period.start_time.weekday() == 0  # Monday
        assert period.duration_days == 7.0

    def test_monthly_period_calculation(self):
        """Test monthly billing period boundaries."""
        calculator = BillingPeriodCalculator(
            period_type=BillingPeriodType.MONTHLY,
            user_timezone="UTC"
        )
        
        # Test with mid-month date
        reference_time = datetime(2024, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
        period = calculator.get_current_period(reference_time)
        
        assert period.period_type == BillingPeriodType.MONTHLY
        assert period.start_time.day == 1
        assert period.start_time.month == 1

    def test_custom_period_calculation(self):
        """Test custom billing period boundaries."""
        custom_start = datetime(2024, 1, 10, 0, 0, 0, tzinfo=timezone.utc)
        calculator = BillingPeriodCalculator(
            period_type=BillingPeriodType.CUSTOM,
            custom_start_date=custom_start,
            user_timezone="UTC"
        )
        
        # Test with a date within the first custom period
        reference_time = datetime(2024, 1, 20, 14, 30, 0, tzinfo=timezone.utc)
        period = calculator.get_current_period(reference_time)
        
        assert period.period_type == BillingPeriodType.CUSTOM
        assert period.start_time == custom_start

    def test_period_summary_creation(self):
        """Test creation of billing period summary from session blocks."""
        calculator = BillingPeriodCalculator(
            period_type=BillingPeriodType.DAILY,
            user_timezone="UTC"
        )
        
        # Create a test period
        reference_time = datetime(2024, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
        period = calculator.get_current_period(reference_time)
        
        # Create test session blocks with usage entries
        entry1 = UsageEntry(
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.05,
            model="claude-3-sonnet"
        )
        
        entry2 = UsageEntry(
            timestamp=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
            input_tokens=200,
            output_tokens=100,
            cost_usd=0.10,
            model="claude-3-sonnet"
        )
        
        # Create session block
        session_block = SessionBlock(
            id="test-session",
            start_time=datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc),
            end_time=datetime(2024, 1, 15, 15, 0, 0, tzinfo=timezone.utc),
            entries=[entry1, entry2],
            token_counts=TokenCounts(input_tokens=300, output_tokens=150),
            cost_usd=0.15
        )
        
        # Create period summary
        summary = calculator.create_period_summary(period, [session_block])
        
        assert abs(summary.total_cost - 0.15) < 0.001  # Handle floating point precision
        assert summary.total_tokens_calculated == 450
        assert summary.entries_count == 2
        assert len(summary.session_blocks) == 1
        assert "claude-3-sonnet" in summary.models_used

    def test_recent_periods(self):
        """Test getting recent billing periods."""
        calculator = BillingPeriodCalculator(
            period_type=BillingPeriodType.DAILY,
            user_timezone="UTC"
        )
        
        # Use current time for this test so we get a current period
        periods = calculator.get_recent_periods(count=3)
        
        assert len(periods) == 3
        # The first period should contain the current time and be marked as current
        assert periods[0].is_current  # Current period
        assert not periods[1].is_current  # Previous period
        assert not periods[2].is_current  # Period before that

    def test_next_reset_time(self):
        """Test calculation of next billing period reset."""
        calculator = BillingPeriodCalculator(
            period_type=BillingPeriodType.DAILY,
            user_timezone="UTC"
        )
        
        reference_time = datetime(2024, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
        next_reset = calculator.get_next_reset_time(reference_time)
        
        assert next_reset.day == 16
        assert next_reset.hour == 0
        assert next_reset.minute == 0

    def test_time_until_reset(self):
        """Test calculation of time remaining until reset."""
        calculator = BillingPeriodCalculator(
            period_type=BillingPeriodType.DAILY,
            user_timezone="UTC"
        )
        
        reference_time = datetime(2024, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
        time_until_reset = calculator.get_time_until_reset(reference_time)
        
        # Should be about 9.5 hours until midnight
        expected_seconds = 9.5 * 3600
        assert abs(time_until_reset.total_seconds() - expected_seconds) < 60  # Within 1 minute

    def test_period_contains_timestamp(self):
        """Test period timestamp containment check."""
        calculator = BillingPeriodCalculator(
            period_type=BillingPeriodType.DAILY,
            user_timezone="UTC"
        )
        
        reference_time = datetime(2024, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
        period = calculator.get_current_period(reference_time)
        
        # Timestamp within period
        within_timestamp = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        assert period.contains_timestamp(within_timestamp)
        
        # Timestamp outside period (previous day)
        outside_timestamp = datetime(2024, 1, 14, 10, 0, 0, tzinfo=timezone.utc)
        assert not period.contains_timestamp(outside_timestamp)
        
        # Timestamp outside period (next day)
        future_timestamp = datetime(2024, 1, 16, 10, 0, 0, tzinfo=timezone.utc)
        assert not period.contains_timestamp(future_timestamp)

    def test_custom_reset_day_daily(self):
        """Test daily periods with custom reset hour."""
        calculator = BillingPeriodCalculator(
            period_type=BillingPeriodType.DAILY,
            reset_day=6,  # 6 AM reset
            user_timezone="UTC"
        )
        
        # Test before reset time (should use previous day's reset)
        reference_time = datetime(2024, 1, 15, 4, 30, 0, tzinfo=timezone.utc)
        period = calculator.get_current_period(reference_time)
        
        assert period.start_time.day == 14
        assert period.start_time.hour == 6
        
        # Test after reset time (should use today's reset)
        reference_time = datetime(2024, 1, 15, 8, 30, 0, tzinfo=timezone.utc)
        period = calculator.get_current_period(reference_time)
        
        assert period.start_time.day == 15
        assert period.start_time.hour == 6

    def test_custom_reset_day_weekly(self):
        """Test weekly periods with custom reset day."""
        # Reset on Wednesday (weekday 2)
        calculator = BillingPeriodCalculator(
            period_type=BillingPeriodType.WEEKLY,
            reset_day=2,  # Wednesday
            user_timezone="UTC"
        )
        
        # Test on a Friday (should start from previous Wednesday)
        reference_time = datetime(2024, 1, 19, 14, 30, 0, tzinfo=timezone.utc)  # Friday
        period = calculator.get_current_period(reference_time)
        
        assert period.start_time.weekday() == 2  # Wednesday
        assert period.duration_days == 7.0