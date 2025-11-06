"""ANSI color codes and emoji helpers for validator logging."""

# ANSI escape codes for terminal colors
ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_DIM = "\033[2m"

# Colors
ANSI_BLACK = "\033[30m"
ANSI_RED = "\033[31m"
ANSI_GREEN = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_BLUE = "\033[34m"
ANSI_MAGENTA = "\033[35m"
ANSI_CYAN = "\033[36m"
ANSI_WHITE = "\033[37m"

# Bright colors
ANSI_BRIGHT_BLACK = "\033[90m"
ANSI_BRIGHT_RED = "\033[91m"
ANSI_BRIGHT_GREEN = "\033[92m"
ANSI_BRIGHT_YELLOW = "\033[93m"
ANSI_BRIGHT_BLUE = "\033[94m"
ANSI_BRIGHT_MAGENTA = "\033[95m"
ANSI_BRIGHT_CYAN = "\033[96m"
ANSI_BRIGHT_WHITE = "\033[97m"

# Emojis
EMOJI_SUCCESS = "✅"
EMOJI_ERROR = "❌"
EMOJI_WARNING = "⚠️"
EMOJI_INFO = "ℹ️"
EMOJI_ROCKET = "🚀"
EMOJI_FIRE = "🔥"
EMOJI_CHART = "📊"
EMOJI_TROPHY = "🏆"
EMOJI_LOCK = "🔒"
EMOJI_COIN = "💰"
EMOJI_GEAR = "⚙️"
EMOJI_MAGNIFYING_GLASS = "🔍"
EMOJI_STOPWATCH = "⏱️"
EMOJI_BLOCK = "🧱"
EMOJI_NETWORK = "🌐"


def style(text: str, color: str = "", bold: bool = False, emoji: str = "") -> str:
    """Style text with ANSI codes and optional emoji."""
    parts = []
    if emoji:
        parts.append(emoji)
    if bold:
        parts.append(ANSI_BOLD)
    if color:
        parts.append(color)
    parts.append(text)
    parts.append(ANSI_RESET)
    return " ".join(parts)


__all__ = [
    "ANSI_RESET", "ANSI_BOLD", "ANSI_DIM",
    "ANSI_RED", "ANSI_GREEN", "ANSI_YELLOW", "ANSI_BLUE", 
    "ANSI_MAGENTA", "ANSI_CYAN",
    "ANSI_BRIGHT_RED", "ANSI_BRIGHT_GREEN", "ANSI_BRIGHT_YELLOW", 
    "ANSI_BRIGHT_BLUE", "ANSI_BRIGHT_MAGENTA", "ANSI_BRIGHT_CYAN",
    "EMOJI_SUCCESS", "EMOJI_ERROR", "EMOJI_WARNING", "EMOJI_INFO",
    "EMOJI_ROCKET", "EMOJI_FIRE", "EMOJI_CHART", "EMOJI_TROPHY",
    "EMOJI_LOCK", "EMOJI_COIN", "EMOJI_GEAR", "EMOJI_MAGNIFYING_GLASS",
    "EMOJI_STOPWATCH", "EMOJI_BLOCK", "EMOJI_NETWORK",
    "style",
]

