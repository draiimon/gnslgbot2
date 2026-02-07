"""
Rate limiting handler for Discord API with exponential backoff
"""
import time
import random
import logging

class RateLimiter:
    """
    A sophisticated rate limiting handler with exponential backoff
    for safe Discord API interaction during temporary rate limits.
    """
    def __init__(self):
        """Initialize the rate limiter with default values"""
        # Tracking the last time we encountered a rate limit
        self.last_rate_limit = 0
        
        # Current backoff time in seconds (starts at 60s to be safe)
        self.current_backoff = 60
        
        # Maximum backoff time in seconds (30 minutes)
        self.max_backoff = 30 * 60
        
        # Flag to indicate if we're currently in a backoff state
        self.is_backing_off = False
        
        # Counter for consecutive rate limit encounters
        self.consecutive_limits = 0
        
        # Logger
        self.logger = logging.getLogger('discord.rate_limiter')
    
    def record_rate_limit(self):
        """Record that we encountered a rate limit and calculate new backoff time"""
        self.consecutive_limits += 1
        self.last_rate_limit = time.time()
        self.is_backing_off = True
        
        # Calculate exponential backoff with jitter (randomization)
        # Base: 60s, 120s, 240s...
        self.current_backoff = min(
            self.current_backoff * 2,
            self.max_backoff
        )
        
        # Add jitter (10-20%) to prevent thundering herd problem
        jitter = random.uniform(0.1, 0.2) * self.current_backoff
        self.current_backoff = max(60, self.current_backoff + jitter)
        
        self.logger.warning(
            f"Rate limit encountered ({self.consecutive_limits} consecutive). "
            f"Backing off for {self.current_backoff:.1f} seconds."
        )
        
        return self.current_backoff
    
    def check_backoff(self):
        """
        Check if we need to wait before making API requests
        
        Returns:
            tuple: (should_wait, wait_time_remaining)
        """
        if not self.is_backing_off:
            return False, 0
        
        elapsed = time.time() - self.last_rate_limit
        remaining = self.current_backoff - elapsed
        
        if remaining <= 0:
            # We've waited long enough
            self.is_backing_off = False
            self.logger.info("Backoff period completed, resuming normal operations")
            return False, 0
        
        return True, remaining
    
    def reset(self):
        """Reset the rate limiter if operations succeed"""
        if self.consecutive_limits > 0:
            self.logger.info("Rate limiting state reset - operations successful")
        
        self.consecutive_limits = 0
        self.current_backoff = 60
        self.is_backing_off = False
    
    def get_status(self):
        """Get the current status of the rate limiter for logging"""
        if self.is_backing_off:
            elapsed = time.time() - self.last_rate_limit
            remaining = max(0, self.current_backoff - elapsed)
            return {
                "state": "backing_off",
                "consecutive_limits": self.consecutive_limits,
                "backoff_seconds": self.current_backoff,
                "remaining_seconds": remaining
            }
        elif self.consecutive_limits > 0:
            return {
                "state": "recovering",
                "consecutive_limits": self.consecutive_limits
            }
        else:
            return {"state": "normal"}