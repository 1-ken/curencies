"""
Forex market hours utility.

The forex market operates 24 hours a day, 5 days a week:
- Opens: Sunday 5 PM EST (10 PM UTC) / Monday 00:00 UTC+2
- Closes: Friday 5 PM EST (10 PM UTC) / Friday 22:00 UTC

This module provides functions to check if the forex market is currently open.
"""
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


def is_forex_market_open(current_time: datetime = None) -> bool:
    """
    Check if the forex market is currently open.
    
    The forex market is open 24/5:
    - Opens: Sunday 22:00 UTC (5 PM EST)
    - Closes: Friday 22:00 UTC (5 PM EST)
    
    Args:
        current_time: Optional datetime to check. If None, uses current UTC time.
        
    Returns:
        bool: True if market is open, False if closed.
    """
    if current_time is None:
        current_time = datetime.now(timezone.utc)
    
    # Ensure we're working with UTC
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    else:
        current_time = current_time.astimezone(timezone.utc)
    
    # Get current day of week (0=Monday, 6=Sunday)
    weekday = current_time.weekday()
    hour = current_time.hour
    
    # Market is closed on Saturday (weekday=5)
    if weekday == 5:  # Saturday
        return False
    
    # Market is closed most of Sunday until 22:00 UTC
    if weekday == 6:  # Sunday
        if hour < 22:
            return False
        # Sunday 22:00 UTC and later - market is open
        return True
    
    # Market closes Friday at 22:00 UTC
    if weekday == 4:  # Friday
        if hour >= 22:
            return False
        # Before 22:00 on Friday - market is open
        return True
    
    # Monday through Thursday (weekday 0-3) - market is always open
    return True


def get_time_until_market_opens() -> timedelta:
    """
    Get the time remaining until the forex market opens.
    
    Returns:
        timedelta: Time until market opens. Returns timedelta(0) if already open.
    """
    now = datetime.now(timezone.utc)
    
    if is_forex_market_open(now):
        return timedelta(0)
    
    weekday = now.weekday()
    hour = now.hour
    
    # If it's Saturday or early Sunday, wait until Sunday 22:00 UTC
    if weekday == 5:  # Saturday
        # Calculate hours until Sunday 22:00
        days_until_sunday = 1
        target = now.replace(hour=22, minute=0, second=0, microsecond=0) + timedelta(days=days_until_sunday)
        return target - now
    
    if weekday == 6 and hour < 22:  # Sunday before 22:00
        target = now.replace(hour=22, minute=0, second=0, microsecond=0)
        return target - now
    
    # If it's Friday after 22:00, wait until Sunday 22:00
    if weekday == 4 and hour >= 22:  # Friday evening
        days_until_sunday = 2
        target = now.replace(hour=22, minute=0, second=0, microsecond=0) + timedelta(days=days_until_sunday)
        return target - now
    
    # Should not reach here if logic is correct
    return timedelta(0)


def get_time_until_market_closes() -> timedelta:
    """
    Get the time remaining until the forex market closes.
    
    Returns:
        timedelta: Time until market closes. Returns timedelta(0) if already closed.
    """
    now = datetime.now(timezone.utc)
    
    if not is_forex_market_open(now):
        return timedelta(0)
    
    weekday = now.weekday()
    
    # If it's any day Monday-Thursday, market closes on Friday at 22:00
    if weekday < 4:  # Monday-Thursday
        days_until_friday = 4 - weekday
        target = now.replace(hour=22, minute=0, second=0, microsecond=0) + timedelta(days=days_until_friday)
        return target - now
    
    # If it's Friday before 22:00
    if weekday == 4:
        target = now.replace(hour=22, minute=0, second=0, microsecond=0)
        return target - now
    
    # If it's Sunday after 22:00, closes on Friday
    if weekday == 6:
        days_until_friday = 5
        target = now.replace(hour=22, minute=0, second=0, microsecond=0) + timedelta(days=days_until_friday)
        return target - now
    
    # Should not reach here
    return timedelta(0)
