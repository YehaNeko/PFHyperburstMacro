# pylint: disable=missing-module-docstring, missing-class-docstring, missing-function-docstring,
# pylint: disable=invalid-name, trailing-whitespace
from __future__ import annotations

import time
import queue
import threading
import multiprocessing
from sys import exit
from typing import TYPE_CHECKING
from collections.abc import Iterator
from ctypes import windll, create_unicode_buffer

from pynput import mouse
from pynput.mouse import Button

from base.macro import (
    RawMouseButtonEvent,
    MouseButtonEvent,
    BaseMacro,
    BaseHyperburstMacro
)


if TYPE_CHECKING:
    from multiprocessing.synchronize import Event
    from multiprocessing.managers import SyncManager


__author__ = '@yeha.'
__copyright__ = 'my nuts'


# Pre-define thread-safe objects
# These are fully initialized in `main()`
do_clicking: Event
virtual_event: Event
program_alive: Event
is_rblx_focused: Event
mouse_event_queue: queue.Queue


macro_databank: dict[int, BaseMacro] = {}
active_macro: PrimaryHyperburstMacro


class PrimaryHyperburstMacro(BaseHyperburstMacro):
    def __init__(self, rpm: float, shots: int, vir_event: Event):
        self.virtual_event: Event = vir_event
        self.controller = mouse.Controller()
        self.button: Button = Button.left

        self._rpm: float = rpm
        self.shots: int = shots

        # Fine-tuning
        self.sleep_after_burst = 0.001
        self.add_delay_per_shot = 0.001

        self.delay_per_shot: float = 0.000
        self.calc_delay()

    @property
    def rpm(self) -> float:
        return self._rpm

    @rpm.setter
    def rpm(self, value: float) -> None:
        self._rpm = value
        self.calc_delay()

    @staticmethod
    def sleep(duration: float) -> None:
        """Higher precision version of `time.sleep()`"""
        start_time = time.perf_counter()
        remaining_time = duration

        # Low cost sleep till the remaining time is 5ms
        while remaining_time > 0.005:
            elapsed_time = time.perf_counter() - start_time
            remaining_time = duration - elapsed_time

            # Sleep for half of the remaining time or minimum sleep interval
            time.sleep(max(remaining_time / 2, 0.0001))

        # Switch to higher precision sleep
        while remaining_time > 0:
            elapsed_time = time.perf_counter() - start_time
            remaining_time = duration - elapsed_time

    def calc_delay(self) -> None:
        self.delay_per_shot = 1 / (self.rpm / 60)
        self.delay_per_shot += self.add_delay_per_shot

    def press(self):
        self.virtual_event.set()
        self.controller.press(self.button)
        print('virtual_event: True')

    def release(self):
        self.virtual_event.set()
        self.controller.release(self.button)
        print('virtual_event: True')

    def macro(self) -> Iterator[None]:
        while True:

            for _ in range(self.shots):
                self.sleep(self.delay_per_shot)
                yield

            self.release()
            yield

            time.sleep(self.sleep_after_burst)

            self.press()
            yield


class RobloxWindowFocusedChecker(multiprocessing.Process):
    def __init__(
        self,
        is_roblox: Event,
        alive: Event
    ):
        super().__init__(
            name='RobloxWindowFocusedCheckerThread',
            daemon=True
        )
        self.is_roblox: Event = is_roblox
        self.program_alive: Event = alive

    @staticmethod
    def get_foreground_window_title() -> str:
        """Get the title of the current focused foreground window."""
        h_wnd = windll.user32.GetForegroundWindow()
        length = windll.user32.GetWindowTextLengthW(h_wnd)
        buf = create_unicode_buffer(length + 1)
        windll.user32.GetWindowTextW(h_wnd, buf, length + 1)
        return buf.value

    def check_focused(self):
        # A local bool so we don't need to use the actual event
        _is_already_set: bool = False

        # Interval in seconds
        check_interval: float = 0.05  # 50ms

        while self.program_alive.is_set():
            current_win_title = self.get_foreground_window_title()

            # This is a bit of a clusterfuck
            if 'Roblox' in current_win_title:
                if not _is_already_set:
                    self.is_roblox.set()
                    _is_already_set = True
                    print('Roblox focused.')

            elif _is_already_set:
                self.is_roblox.clear()
                _is_already_set = False
                print('Roblox not focused.')

            # Limit frequency
            time.sleep(check_interval)

    def run(self) -> None:
        self.check_focused()


class ClickerThread(multiprocessing.Process):
    def __init__(
        self,
        is_clicking: Event,
        namespace: multiprocessing.Manager.Namespace,
        alive: Event,
    ):
        super().__init__(name='ClickerThread', daemon=True)
        self.is_clicking = is_clicking
        self.program_alive = alive
        self.do_macro_steps = namespace.active_macro.macro

    def do_macro_steps(self) -> Iterator[None]:
        """Placeholder"""
        ...

    def macro_loop(self) -> None:
        macro_step = self.do_macro_steps()

        while self.program_alive.is_set():
            self.is_clicking.wait()

            while self.is_clicking.is_set():
                print('do_macro_steps: next iter')
                next(macro_step)

            # If we are here, `do_clicking` is False,
            # so in return reset the macro
            macro_step = self.do_macro_steps()

    def run(self) -> None:
        self.macro_loop()


class StateControllerThread(threading.Thread):
    event: MouseButtonEvent

    def __init__(self, *args, **kwargs):
        super().__init__(name='StateControllerThread', daemon=True, *args, **kwargs)
        self.queue: queue.Queue = mouse_event_queue
        self.toggle: bool = True

        self.start()

    def should_ignore_event(self) -> bool:
        """Returns True if the event should be ignored, else False"""

        # Acknowledge virtual event and skip event processing
        if virtual_event.is_set():
            virtual_event.clear()
            print('Acknowledged virtual event.')
            return True

        # This only occurs when the user presses the script toggle key
        elif self.event.button.name == 'x1' and self.event.pressed:
            # Flip boolean
            self.toggle = not self.toggle
            print('Script toggled to', self.toggle)
            return True

        # Allow de-press event to pass
        elif not self.event.pressed:
            return False

        # Ignore events if roblox is not focused
        elif not is_rblx_focused.is_set():
            do_clicking.clear()
            print('Roblox not focused. Skipping.')
            return True

        # Stops events from being processed
        elif not self.toggle:
            print('Script is toggled False. Skipping.')
            return True

        # If we are here, the event should pass
        return False

    def state_controller(self):
        while program_alive.is_set():
            self.event: MouseButtonEvent = self.queue.get()
            print('Got event:', self.event)

            # Skip processing events if toggled
            if self.should_ignore_event():
                continue

            # Process events
            if self.event.pressed:
                do_clicking.set()
                print('Clicking: True')
            else:
                # if event.release:
                do_clicking.clear()
                print('Clicking: False')

            self.queue.task_done()

    def run(self) -> None:
        self.state_controller()


class MouseListenerThread(mouse.Listener):
    def __init__(self, *args, **kwargs):
        super().__init__(on_click=self.on_click, daemon=True, *args, **kwargs)
        self.start()

    @staticmethod
    def on_click(*args: *RawMouseButtonEvent) -> None:
        valid = ('left', 'x1')

        button, pressed = args[2:4]
        if button.name in valid:
            mouse_event_queue.put_nowait(MouseButtonEvent(button, pressed))


def proc_input(cmd: str) -> None:
    cmd, *args = cmd.split(' ')
    cmd = cmd.lower()

    try:
        if cmd == 'rpm':
            active_macro.rpm = float(args[0])
            print('RPM set!')

        elif cmd == 'shots':
            active_macro.shots = int(args[0])
            print('Shots set!')

        elif cmd == 'set':
            active_macro.rpm = float(args[0])
            active_macro.shots = int(args[1])
            print('RPM and Shots set!')

    except (ValueError, IndexError):
        print('Invalid input.')


def get_initial_weapon() -> tuple[float, int]:
    while True:
        try:
            rpm, shots, *_ = input('Input weapon stats (RPM, shots per burst): ').split(' ')
            rpm, shots = float(rpm), int(shots)
            return rpm, shots
        except Exception:  # noqa
            print('\nInvalid input. Try again.')


def main() -> None:
    global active_macro, mouse_event_queue, do_clicking, virtual_event, program_alive, is_rblx_focused

    with multiprocessing.Manager() as manager:
        manager: SyncManager

        # Thread-safe objects
        program_alive = multiprocessing.Event()
        program_alive.set()

        is_rblx_focused = manager.Event()
        mouse_event_queue = queue.Queue()
        virtual_event = manager.Event()
        namespace = manager.Namespace()
        do_clicking = manager.Event()

        # Macros
        # rpm, shots = get_initial_weapon()
        rpm, shots = 650, 2
        primary_macro = PrimaryHyperburstMacro(rpm, shots, virtual_event)
        active_macro = primary_macro
        namespace.active_macro = active_macro

        # Start event processing threads
        mouse_listener_thread = MouseListenerThread()  # noqa
        state_controller_thread = StateControllerThread()  # noqa

        clicker_thread = ClickerThread(do_clicking, namespace, program_alive)
        clicker_thread.start()

        window_checker_thread = RobloxWindowFocusedChecker(is_rblx_focused, program_alive)
        window_checker_thread.start()

        # Block till done
        try:
            while True:
                proc_input(input())
        except KeyboardInterrupt:
            print('Exiting...')
            program_alive.clear()
            exit()


if __name__ == '__main__':
    main()
