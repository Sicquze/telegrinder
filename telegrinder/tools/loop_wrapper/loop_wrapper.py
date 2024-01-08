import asyncio
import contextlib
import dataclasses
import typing

from telegrinder.modules import logger

from .abc import ABCLoopWrapper, CoroutineFunc, CoroutineTask

ExceptionT = typing.TypeVar("ExceptionT", bound=BaseException)
ErrorHandler = typing.Callable[[ExceptionT], CoroutineTask]


async def keyboard_interrupt_handler(_: KeyboardInterrupt):
    print()  # blank print for ^C
    logger.info("KeyboardInterrupt")


async def system_exit_handler(exc: SystemExit):
    logger.info(f"System exit with code {exc.code}")


DEFAULT_ERROR_HANDLERS: dict[type[BaseException], list[ErrorHandler]] = {
    KeyboardInterrupt: [keyboard_interrupt_handler],
    SystemExit: [system_exit_handler],
}


@dataclasses.dataclass
class DelayedTask:
    handler: CoroutineFunc
    seconds: float
    repeat: bool = dataclasses.field(default=False, kw_only=True)
    _cancelled: bool = dataclasses.field(default=False, init=False, repr=False)

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        if not self._cancelled:
            self._cancelled = True

    async def __call__(self, *args, **kwargs) -> None:
        while not self._cancelled:
            await asyncio.sleep(self.seconds)
            if self._cancelled:
                break
            await self.handler(*args, **kwargs)
            if not self.repeat:
                break


class LoopWrapper(ABCLoopWrapper):
    def __init__(
        self,
        tasks: list[CoroutineTask] | None = None,
        error_handlers: dict[type[BaseException], list[ErrorHandler]] | None = None,
    ):
        self.on_startup: list[CoroutineTask] = []
        self.on_shutdown: list[CoroutineTask] = []
        self.tasks = tasks or []
        self.error_handlers = DEFAULT_ERROR_HANDLERS | (error_handlers or {})
        self._loop = asyncio.new_event_loop()
        
    def run_error_handler(self, exception: BaseException) -> None:
        if exception.__class__ not in self.error_handlers:
            return
        
        for handler in self.error_handlers[exception.__class__]:
            try:
                self._loop.run_until_complete(handler(exception))
            except BaseException as exc:
                logger.exception(
                    "Exception {!r} occurred during running error handler {!r} "
                    "in loop wrapper.",
                    exc.__class__.__name__,
                    handler.__name__,
                )
    
    def run_event_loop(self) -> None:
        if not self.tasks:
            logger.warning("You run loop with 0 tasks!")

        for startup_task in self.on_startup:
            self._loop.run_until_complete(startup_task)
        for task in self.tasks:
            self._loop.create_task(task)
        
        self.tasks.clear()
        tasks = asyncio.all_tasks(self._loop)
        try:
            while tasks:
                tasks_results, _ = self._loop.run_until_complete(
                    asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
                )
                for task_result in tasks_results:
                    try:
                        task_result.result()
                    except BaseException as ex:
                        logger.exception(ex)
                tasks = asyncio.all_tasks(self._loop)
        except BaseException as exc:
            if self.error_handlers:
                self.run_error_handler(exc)
            self.complete_tasks(tasks)
        finally:
            for shutdown_task in self.on_shutdown:
                self._loop.run_until_complete(shutdown_task)
            if self._loop.is_running():
                self._loop.close()
        
    def add_task(self, task: CoroutineFunc | CoroutineTask | DelayedTask):
        if asyncio.iscoroutinefunction(task) or isinstance(task, DelayedTask):
            task = task()
        elif not asyncio.iscoroutine(task):
            raise TypeError("Task should be coroutine or coroutine function.")

        if self._loop and self._loop.is_running():
            self._loop.create_task(task)
        else:
            self.tasks.append(task)
    
    def complete_tasks(self, tasks: set[asyncio.Task[typing.Any]]) -> None:
        tasks = tasks | asyncio.all_tasks(self._loop)
        task_to_cancel = asyncio.gather(*tasks, return_exceptions=True)
        task_to_cancel.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            self._loop.run_until_complete(task_to_cancel)

    def timer(
        self,
        *,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
        seconds: float = 0,
    ) -> typing.Callable[[typing.Callable], DelayedTask]:
        seconds += minutes * 60
        seconds += hours * 60 * 60
        seconds += days * 24 * 60 * 60

        def decorator(func: typing.Callable) -> DelayedTask:
            delayed_task = DelayedTask(func, seconds, repeat=False)
            self.add_task(delayed_task)
            return delayed_task

        return decorator

    def interval(
        self,
        *,
        days: int = 0,
        hours: int = 0,
        minutes: int = 0,
        seconds: float = 0,
    ) -> typing.Callable[[typing.Callable], DelayedTask]:
        seconds += minutes * 60
        seconds += hours * 60 * 60
        seconds += days * 24 * 60 * 60

        def decorator(func: typing.Callable) -> DelayedTask:
            delayed_task = DelayedTask(func, seconds, repeat=True)
            self.add_task(delayed_task)
            return delayed_task

        return decorator
    