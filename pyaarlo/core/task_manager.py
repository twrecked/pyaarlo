import asyncio
import time
import traceback
from collections.abc import Callable
from typing import Any

from .logger import ArloLogger


class ArloTaskManager:
    """An asyncio-based task manager that supports both sync and async callbacks."""

    def __init__(self, log: ArloLogger) -> None:
        self._log: ArloLogger = log
        self._tasks: dict[str, asyncio.Task[Any] | asyncio.Future[Any]] = {}
        self._counter: int = 0
        self._loop = asyncio.get_running_loop()
        self._log.vdebug("tasks: manager created (asyncio-based)")

    def _next_id(self) -> str:
        self._counter += 1
        return f"{self._counter}:{time.monotonic()}"

    async def _execute_task(self, task_id: str, cb: Callable[..., Any], args: dict[str, Any]) -> None:
        """Wraps the task execution to handle errors and cleanup."""
        try:
            if asyncio.iscoroutinefunction(cb):
                await cb(**args)
            else:
                # Run sync callbacks in the default executor (thread pool)
                await self._loop.run_in_executor(None, lambda: cb(**args))
        except Exception as e:
            self._log.error(
                f"tasks: task-error={type(e).__name__}\n{traceback.format_exc()}"
            )
        finally:
            _ = self._tasks.pop(task_id, None)
            self._log.vdebug(f"tasks: task-completed (ID: {task_id})")

    async def _execute_delayed_task(
        self, task_id: str, seconds: float, cb: Callable[..., Any], args: dict[str, Any]
    ) -> None:
        """Wait for a specified delay before executing the task."""
        await asyncio.sleep(seconds)
        await self._execute_task(task_id, cb, args)

    async def _execute_periodic_task(
        self, task_id: str, seconds: float, cb: Callable[..., Any], args: dict[str, Any]
    ) -> None:
        """Execute the task periodically."""
        while True:
            await asyncio.sleep(seconds)
            # Periodic tasks shouldn't pop themselves from self._tasks until explicitly cancelled
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(**args)
                else:
                    await self._loop.run_in_executor(None, lambda: cb(**args))
            except Exception as e:
                self._log.error(
                    f"tasks: periodic-task-error={type(e).__name__}\n{traceback.format_exc()}"
                )
            _ = self._tasks.pop(task_id, None)
            self._log.vdebug(f"tasks: periodic-task-completed (ID: {task_id})")

    def _submit(self, coro: Any) -> asyncio.Task[Any] | asyncio.Future[Any]:
        """Safely submit a coroutine to the event loop from any thread."""
        try:
            # If we are in the thread running the loop, we can use create_task
            if asyncio.get_running_loop() is self._loop:
                return asyncio.create_task(coro)
        except RuntimeError:
            # No loop running in this thread
            pass

        # Otherwise, we must use run_coroutine_threadsafe to submit from an external thread
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def run_now(self, task_cb: Callable[..., Any], **kwargs: Any) -> str:
        """Executes a task immediately in the background."""
        task_id = self._next_id()
        self._tasks[task_id] = self._submit(self._execute_task(task_id, task_cb, kwargs))
        self._log.vdebug(f"tasks: task-scheduled (ID: {task_id})")
        return task_id

    def run_in(self, task_cb: Callable[..., Any], seconds: float, **kwargs: Any) -> str:
        """Executes a task after a specified delay."""
        task_id = self._next_id()
        self._tasks[task_id] = self._submit(self._execute_delayed_task(task_id, seconds, task_cb, kwargs))
        self._log.vdebug(f"tasks: later-task-scheduled (ID: {task_id})")
        return task_id

    def run_every(self, task_cb: Callable[..., Any], seconds: float, **kwargs: Any) -> str:
        """Executes a task repeatedly on a fixed interval."""
        task_id = self._next_id()
        self._tasks[task_id] = self._submit(self._execute_periodic_task(task_id, seconds, task_cb, kwargs))
        self._log.vdebug(f"tasks: periodic-task-scheduled (ID: {task_id})")
        return task_id

    def cancel(self, to_delete: str | None) -> bool:
        """Cancel a pending or periodic task by its ID."""
        if to_delete is not None and to_delete in self._tasks:
            task = self._tasks.pop(to_delete)
            _ = task.cancel()
            return True
        return False

    def stop(self) -> None:
        """Stop the task manager and cancel all managed tasks."""
        for task_id in list(self._tasks.keys()):
            _ = self.cancel(task_id)

    def print_active_tasks(self):
        """Debug utility to print all currently running tasks on the loop."""
        # 1. Get all tasks known to the running asyncio loop
        try:
            current_loop = self._loop
            all_loop_tasks = asyncio.all_tasks(current_loop)
        except RuntimeError:
            print("🔴 Debug Error: No event loop is currently running.")
            return

        print("\n" + "="*60)
        print(f"📊 EVENT LOOP STATUS DIANOSTICS (Active Tasks: {len(all_loop_tasks)})")
        print("="*60)

        # 2. Iterate and print details for every active task
        for i, task in enumerate(all_loop_tasks, 1):
            task_name = task.get_name()
            task_coro = task.get_coro()
            # Extract the actual function name inside the coroutine wrapper
            coro_name = getattr(task_coro, "__name__", str(task_coro))
            
            # Check if this task belongs to our ArloTaskManager tracking dict
            managed_id = None
            for tid, t_obj in self._tasks.items():
                if t_obj is task:
                    managed_id = tid
                    break

            status = f"MANAGED (ID: {managed_id})" if managed_id else "UNMANAGED / INTERNAL"
            
            print(f"Task #{i}:")
            print(f"  • Coroutine : {coro_name}")
            print(f"  • Loop Name : {task_name}")
            print(f"  • Ownership : {status}")
            print(f"  • State     : {'Cancelled' if task.cancelled() else 'Running/Pending'}")
            print("-" * 40)
            
        print("="*60 + "\n")


