# The Windows implementation relies on pywin32. Use a no-op jump list elsewhere
try:
    from ._windows import JumpList
except ImportError:
    from ._null import JumpList

__all__ = ["JumpList"]
