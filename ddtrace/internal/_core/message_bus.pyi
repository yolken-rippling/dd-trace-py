from typing import Any
from typing import Callable

def reset() -> None:
    """Remove all registered listeners"""

def has_listeners(event_id: str) -> bool:
    """Returns ``True`` if there are registered listeners for the provided ``event_id``"""

def on(event_id: str, callback: Callable[..., Any]) -> None:
    """Add the listener ``callback`` for the provided ``event_id``"""

def on_all(callback: Callable[..., Any]) -> None: ...
def remove(event_id: str, callback: Callable[..., Any]) -> None:
    """Remove the listener ``callback`` for the provided ``event_id``"""

def dispatch(event_id: str, args: tuple[Any, ...]) -> None:
    """Call all listeners of ``event_id`` with the provided ``args`` ignoring
    the results and errors from the called listeners
    """

def dispatch_with_results(event_id: str, args: tuple[Any, ...]) -> tuple[list[Any], list[Exception]]:
    """Call all listeners of ``event_id`` with the provided ``args`` collecting
    and returning the results and errors from the called listeners
    """
