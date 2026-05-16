"""
Points Calculator
Handles all point arithmetic based on number of required channels.
"""
from config import MAX_POINTS_PER_REFERRAL


def calculate_point_per_channel(total_channels: int) -> float:
    """
    Return points awarded per channel joined.
    MAX_POINTS_PER_REFERRAL is split equally across all required channels.
    
    Examples:
        1 channel  → 1.0 point per channel
        2 channels → 0.5 point per channel
        5 channels → 0.2 point per channel
    """
    if total_channels <= 0:
        return 0.0
    return round(MAX_POINTS_PER_REFERRAL / total_channels, 4)


def format_points(points: float) -> str:
    """Human-friendly point string."""
    return f"{points:.2f}".rstrip("0").rstrip(".") or "0"
