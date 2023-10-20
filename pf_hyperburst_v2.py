# pylint: disable=missing-module-docstring, missing-class-docstring, missing-function-docstring,
# pylint: disable=invalid-name, trailing-whitespace
from __future__ import annotations

import os
import sys
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

from config import TOGGLE_KEYBIND, WEAPON_ARGS
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
program_alive: Event
is_rblx_focused: Event
mouse_event_queue: queue.Queue
macro_queue: multiprocessing.Queue


macro_databank: dict[int, BaseMacro] = {}
active_macro: PrimaryHyperburstMacro


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


class PrimaryHyperburstMacro(BaseHyperburstMacro):
    def __init__(self, args: tuple[float, int, float]):
        from config import (
            ADD_DELAY_PER_SHOT,
            SLEEP_AFTER_BURST,
            THE_LITO_FACTOR
        )

        self.controller = mouse.Controller()
        self.button: Button = Button.left
        rpm, shots, firecap = args

        self._firecap: float = 0.0
        self._rpm: float = rpm
        self.shots: int = shots

        # Defaults
        self.the_lito_factor = THE_LITO_FACTOR

        # Fine-tuning
        self.default_sleep_after_burst = SLEEP_AFTER_BURST
        self.add_delay_per_shot = ADD_DELAY_PER_SHOT

        # Determined automatically
        self.sleep_after_burst = self.default_sleep_after_burst
        self.delay_per_shot: float = 0.000
        self.rpm = self._rpm

    @property
    def rpm(self) -> float:
        return self._rpm

    @rpm.setter
    def rpm(self, value: float) -> None:
        self._rpm = value

        self.delay_per_shot = 1 / (self._rpm / 60)
        self.delay_per_shot = round(self.delay_per_shot, 6)
        self.delay_per_shot += self.add_delay_per_shot

    @property
    def firecap(self) -> float:
        return self._firecap

    @firecap.setter
    def firecap(self, value: float) -> None:
        self._firecap = value

        if not value == 0:
            val = 60 / value
            val = round(val, 6)
            val += self.the_lito_factor
            self.sleep_after_burst = val
        else:
            self.sleep_after_burst = self.default_sleep_after_burst

    @staticmethod
    def sleep(duration: float) -> None:
        """Higher precision version of `time.sleep()`"""
        start_time = time.perf_counter()
        remaining_time = duration

        # Low cost sleep till the remaining time is 5ms
        while remaining_time > 0.005:

            # Sleep for half of the remaining time or minimum sleep interval
            time.sleep(max(remaining_time / 2, 0.0001))

            elapsed_time = time.perf_counter() - start_time
            remaining_time = duration - elapsed_time

        # Switch to higher precision sleep
        while remaining_time > 0:
            elapsed_time = time.perf_counter() - start_time
            remaining_time = duration - elapsed_time

    @staticmethod
    def sleep_generator(duration: float) -> Iterator[None]:
        """Higher precision version of `time.sleep()`
        This function also yields for every haft of remaining duration
        """
        start_time = time.perf_counter()
        remaining_time = duration

        # Low cost sleep till the remaining time is 5ms
        while remaining_time > 0.005:

            # Sleep for half of the remaining time or minimum sleep interval
            time.sleep(max(remaining_time / 2, 0.0001))
            yield

            elapsed_time = time.perf_counter() - start_time
            remaining_time = duration - elapsed_time

        # Switch to higher precision sleep
        while remaining_time > 0:
            elapsed_time = time.perf_counter() - start_time
            remaining_time = duration - elapsed_time

    def press(self):
        self.controller.press(self.button)
        print('virtual_event: press')

    def release(self):
        self.controller.release(self.button)
        print('virtual_event: release')

    def macro(self) -> Iterator[None]:
        while True:

            for _ in range(self.shots):
                self.sleep(self.delay_per_shot)
                yield

            self.release()
            yield

            self.sleep(self.sleep_after_burst)
            # for _ in self.sleep_generator(self.sleep_after_burst):
            #     yield

            self.press()


# noinspection PyShadowingNames
class ClickerThread(multiprocessing.Process):
    def __init__(
        self,
        is_clicking: Event,
        macro_queue: multiprocessing.Queue,
        starting_macro: PrimaryHyperburstMacro,
        alive: Event,
    ):
        super().__init__(name='ClickerThread', daemon=True)
        self.is_clicking: Event = is_clicking
        self.macro_queue: multiprocessing.Queue = macro_queue
        self.active_macro: BaseHyperburstMacro = starting_macro
        self.program_alive: Event = alive
        self.do_macro_steps = starting_macro.macro

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

    @staticmethod
    def macro_queue_worker(self, queue: multiprocessing.Queue, alive):
        while alive:
            attr, *args = queue.get()
            setattr(self.active_macro, attr, args[0])

    def run(self) -> None:
        threading.Thread(
            target=self.macro_queue_worker,
            args=(self, self.macro_queue, self.program_alive),
            daemon=True
        ).start()

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

        # This only occurs when the user presses the script toggle key
        if self.event.button.name == TOGGLE_KEYBIND and self.event.pressed:
            # Flip boolean
            self.toggle = not self.toggle
            print('Script toggled to', self.toggle)
            return True

        # Allow release event to pass
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
        super().__init__(
            on_click=self.on_click,
            daemon=True,
            win32_event_filter=self.win32_event_filter,
            *args,
            **kwargs
        )
        # self.valid = ('left', TOGGLE_KEYBIND)
        self.start()

    @staticmethod
    def on_click(*args: *RawMouseButtonEvent) -> None:
        mouse_event_queue.put_nowait(MouseButtonEvent(*args[2:4]))

    @staticmethod
    def win32_event_filter(msg, data):
        if data.flags or msg not in (513, 514, 523, 524):
            return False
        # print(msg, data.mouseData, data.flags, data.time)


def proc_input(cmd: str) -> None:
    cmd, *args = cmd.split(' ')
    cmd = cmd.lower()

    if not cmd:
        return

    try:
        if cmd == 'rpm':
            macro_queue.put_nowait(('rpm', float(args[0])))
            print('RPM set!')

        elif cmd == 'shots':
            macro_queue.put_nowait(('shots', float(args[0])))
            print('Shots set!')

        elif cmd == 'firecap':
            macro_queue.put_nowait(('firecap', float(args[0])))
            print('Firecap set!')

        elif cmd == 'set':
            macro_queue.put_nowait(('rpm', float(args[0])))
            macro_queue.put_nowait(('shots', int(args[1])))

            # Optionals
            if len(args) >= 3:
                macro_queue.put_nowait(('firecap', float(args[2])))
                print('RPM, Shots and Firecap set!')
                return

            print('RPM and Shots set!')

        elif cmd in ('q', 'quit', 'exit'):
            program_alive.clear()

        elif cmd in ('r', 'reset'):
            print('Reseting...\nNote that this currently does not get rid of old instances.')
            program_alive.clear()
            os.execl(sys.executable, sys.executable, *sys.argv)

        else:
            print('Unknown command.')

    except (ValueError, IndexError):
        print('Invalid input.')


def get_initial_weapon() -> tuple[float, int, float]:
    opt = {
        'firecap': 0
    }

    opt_values = list(opt.values())
    opt_fmt = ' '.join(f'[{key}]' for key in opt.keys())

    while True:
        try:
            rpm, shots, *optionals = input(f'Input weapon stats:\n(RPM) (shots per burst) {opt_fmt}\n').split(' ')
            rpm, shots = float(rpm), int(shots)

            # Optionals
            if optionals:
                given = len(optionals)

                for i in range(given):
                    opt_values[i] = optionals[i]

            return rpm, shots, *opt_values
        except Exception:  # noqa
            print('\nInvalid input. Try again.')


def main() -> None:
    global active_macro, mouse_event_queue, do_clicking, program_alive, is_rblx_focused, macro_queue

    with multiprocessing.Manager() as manager:
        manager: SyncManager

        # Thread-safe objects
        program_alive = multiprocessing.Event()
        program_alive.set()

        mouse_event_queue = queue.Queue()
        is_rblx_focused = manager.Event()
        macro_queue = multiprocessing.Queue()
        do_clicking = multiprocessing.Event()

        # Macros
        macro_args = WEAPON_ARGS or get_initial_weapon()
        primary_macro = PrimaryHyperburstMacro(macro_args)
        active_macro = primary_macro

        # Start event processing threads
        mouse_listener_thread = MouseListenerThread()  # noqa

        state_controller_thread = StateControllerThread()  # noqa

        clicker_thread = ClickerThread(do_clicking, macro_queue, active_macro, program_alive)
        clicker_thread.start()

        window_checker_thread = RobloxWindowFocusedChecker(is_rblx_focused, program_alive)
        window_checker_thread.start()

        print('Ready!')

        # Block till done
        try:
            while program_alive.is_set():
                proc_input(input())
            raise KeyboardInterrupt
        except KeyboardInterrupt:
            print('Exiting...')
            program_alive.clear()

            clicker_thread.kill()
            window_checker_thread.kill()
            exit()


if __name__ == '__main__':
    main()
