# -*- encoding: utf-8 -*-
import typing  # noqa:F401

import attr

from ddtrace.internal import core
from ddtrace.internal import service


class PeriodicThread(core.Task):
    """Periodic thread.

    This class can be used to instantiate a worker thread that will run its `run_periodic` function every `interval`
    seconds.

    """

    _ddtrace_profiling_ignore = True

    def start(self):
        core.register_task(self)

    def stop(self):
        """Stop the thread."""
        core.unregister_task(self)


class AwakeablePeriodicThread(PeriodicThread):
    """Periodic thread that can be awakened on demand.

    This class can be used to instantiate a worker thread that will run its
    `run_periodic` function every `interval` seconds, or upon request.
    """

    def awake(self):
        """Awake the thread."""
        self._target()


@attr.s(eq=False)
class PeriodicService(service.Service):
    """A service that runs periodically."""

    _interval = attr.ib(type=float)
    _worker = attr.ib(default=None, init=False, repr=False)

    __thread_class__ = PeriodicThread

    @property
    def interval(self):
        # type: (...) -> float
        return self._interval

    def _start_service(self, *args, **kwargs):
        # type: (typing.Any, typing.Any) -> None
        """Start the periodic service."""
        self._worker = self.__thread_class__(
            self.interval,
            target=self.periodic,
            name="%s:%s" % (self.__class__.__module__, self.__class__.__name__),
            on_shutdown=self.on_shutdown,
        )
        self._worker.start()

    def _stop_service(self, *args, **kwargs):
        # type: (typing.Any, typing.Any) -> None
        """Stop the periodic collector."""
        self._worker.stop()
        super(PeriodicService, self)._stop_service(*args, **kwargs)

    def join(
        self,
        timeout=None,  # type: typing.Optional[float]
    ):
        # type: (...) -> None
        pass
        # if self._worker:
        #     self._worker.join(timeout)

    @staticmethod
    def on_shutdown():
        pass

    def periodic(self):
        # type: (...) -> None
        pass


class AwakeablePeriodicService(PeriodicService):
    """A service that runs periodically but that can also be awakened on demand."""

    __thread_class__ = AwakeablePeriodicThread

    def awake(self):
        # type: (...) -> None
        self._worker.awake()
