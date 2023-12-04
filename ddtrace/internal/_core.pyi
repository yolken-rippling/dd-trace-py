from typing import Any, Callable

class MessageBus:
    def reset(self) -> None:
        """Remove all registered listeners"""

    def has_listeners(self, event_id: str) -> bool:
        """Returns ``True`` if there are registered listeners for the provided ``event_id``"""

    def on(self, event_id: str, callback: Callable[..., Any]) -> None:
        """Add the listener ``callback`` for the provided ``event_id``"""

    def remove(self, event_id: str, callback: Callable[[tuple[Any, ...]], Any]) -> None:
        """Remove the listener ``callback`` for the provided ``event_id``"""

    def dispatch(self, event_id: str, args: tuple[Any, ...]) -> None:
        """Call all listeners of ``event_id`` with the provided ``args``"""
