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
from pynput import mouse
from typing import TYPE_CHECKING, Any
from ctypes import windll, create_unicode_buffer

from config import TOGGLE_KEYBIND, TOGGLE_AUTOCLIKER, WEAPON_ARGS

from macros import (
    PrimaryHyperburstMacro,
    PrimaryFirecapedHyperburstMacro,
    AutoclickerMacro
)
from base.macro import (
    RawMouseButtonEvent,
    MouseButtonEvent,
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


macro_databank: dict[int, BaseHyperburstMacro] = {}
active_macro: PrimaryHyperburstMacro


class RobloxWindowFocusedChecker(multiprocessing.Process):
    def __init__(
        self,
        is_roblox: Event,
        alive: Event
    ):
        super().__init__(
            name='pfhyperburstmacro-roblox-window-checker',
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


# noinspection PyShadowingNames
class ClickerThread(multiprocessing.Process):
    def __init__(
        self,
        is_clicking: Event,
        macro_queue: multiprocessing.Queue,
        macro_db: dict[int, BaseHyperburstMacro],
        alive: Event,
    ):
        super().__init__(name='pfhyperburstmacro-clicker-thread', daemon=True)
        self.is_clicking: Event = is_clicking
        self.macro_queue: multiprocessing.Queue = macro_queue
        self.program_alive: Event = alive

        self.macro_db = macro_db
        self.current_macro_index: int = 0
        self._active_macro: BaseHyperburstMacro = macro_db[0]
        self.active_macro = self._active_macro

        self.autoclicker_toggled: bool = False
        self.last_non_toggled_macro_index: int = 0

        # Inital macro args taken from the inital active_macro
        # TODO: make dynamic
        self.last_macro_args: dict[str, Any] = {
            k: v
            for (k, v) in (
                ('rpm', self.active_macro.rpm),
                ('shots', self.active_macro.shots),
                ('firecap', self.active_macro.firecap)
            )
        }

    @property
    def active_macro(self) -> Any:
        return self._active_macro

    @active_macro.setter
    def active_macro(self, value: Any):
        self._active_macro = value
        self.do_macro_steps = value.macro

    def macro_loop(self) -> None:
        while self.program_alive.is_set():
            self.is_clicking.wait()

            # Reset macro
            do_macro_steps = self.do_macro_steps()

            while self.is_clicking.is_set():
                print('do_macro_steps: next iter')
                next(do_macro_steps)

    def change_macro(self, idx):
        self.active_macro = self.macro_db.get(idx)
        self.current_macro_index = idx

        if not self.autoclicker_toggled:
            self.last_non_toggled_macro_index = idx

        for item in self.last_macro_args.items():
            setattr(self.active_macro, *item)

    def toggle_macro(self, idx):
        if self.autoclicker_toggled:
            self.change_macro(self.last_non_toggled_macro_index)
            self.autoclicker_toggled = False
            return

        self.change_macro(idx)
        self.autoclicker_toggled = True

    def macro_queue_worker(self, queue: multiprocessing.Queue, alive: Event):
        while alive.is_set():
            attr, *args = queue.get()

            if attr == 'change_macro':
                self.change_macro(args[0])
                continue

            elif attr == 'toggle_macro':
                self.toggle_macro(2)
                print('guh')
                continue

            setattr(self.active_macro, attr, args[0])
            self.last_macro_args.update({attr: args[0]})

    def run(self) -> None:
        threading.Thread(
            target=self.macro_queue_worker,
            args=(self.macro_queue, self.program_alive),
            name='pfhyperburstmacro-macro-queue-worker-thread',
            daemon=True
        ).start()

        self.macro_loop()


class StateControllerThread(threading.Thread):
    event: MouseButtonEvent

    def __init__(self, *args, **kwargs):
        super().__init__(name='pfhyperburstmacro-state-controller-thread', daemon=True, *args, **kwargs)
        self.queue: queue.Queue = mouse_event_queue
        self.toggle: bool = True
        self.last_macro: int = 0

        self.button_to_event: dict[str, callable] = {
            'left': self.set_clicking,
            TOGGLE_AUTOCLIKER: self.toggle_autocliker
        }

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

    def set_clicking(self):
        if self.event.pressed:
            do_clicking.set()
            print('Clicking: True')
        else:
            # if event.release:
            do_clicking.clear()
            print('Clicking: False')

    def toggle_autocliker(self):
        print('guh')
        if self.event.pressed:
            macro_queue.put_nowait(('toggle_macro', 2))

    def state_controller(self):
        while program_alive.is_set():
            self.event: MouseButtonEvent = self.queue.get()
            print('Got event:', self.event)

            # Skip processing events if toggled
            if self.should_ignore_event():
                continue

            event = self.button_to_event.get(self.event.button.name)
            if event is not None:
                event()

            self.queue.task_done()

    def run(self) -> None:
        self.state_controller()


class MouseListenerThread(mouse.Listener):
    def __init__(self, *args, **kwargs):
        super().__init__(
            name='pfhyperburstmacro-mouse-listener-thread',
            win32_event_filter=self.win32_event_filter,
            on_click=self.on_click,
            daemon=True,
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


def proc_command(cmd: str, args: tuple[Any]):
    def set_rpm(arg: Any):
        macro_queue.put_nowait(('rpm', float(arg)))
        print('RPM set!')

    def set_shots(arg: Any):
        macro_queue.put_nowait(('shots', int(arg)))
        print('Shots set!')

    def set_firecap(arg: Any):
        firecap = float(arg)

        if firecap <= 0:
            macro_queue.put_nowait(('change_macro', 0))
        else:
            macro_queue.put_nowait(('change_macro', 1))

        macro_queue.put_nowait(('firecap', float(arg)))
        print('Firecap set!')

    def _set(*_args: tuple[Any]):
        set_rpm(_args[0])
        set_shots(_args[1])

        # Optionals
        if len(_args) >= 3:
            set_firecap(_args[2])
            return

    def do_quit():
        program_alive.clear()

    def do_reset():
        print('Reseting...\nNote that this currently does not get rid of old instances.')
        program_alive.clear()
        os.execl(sys.executable, sys.executable, *sys.argv)

    # fmt: off
    commands: dict[str, callable] = {
        'rpm':     set_rpm,
        'shots':   set_shots,
        'firecap': set_firecap,
        'set':     _set,

        'q':    do_quit,
        'quit': do_quit,
        'exit': do_quit,

        'r':     do_reset,
        'reset': do_reset,
    }
    # fmt: on

    action = commands.get(cmd)

    if action is None:
        print('Unknown command.')
        return

    try:
        action(*args)
    except (ValueError, IndexError):
        print('Invalid input.')


def proc_input(cmd: str) -> None:
    cmd, *args = cmd.split(' ')
    cmd = cmd.lower()

    if not cmd:
        return

    proc_command(cmd, args)


def get_initial_weapon() -> tuple[float, int, float]:
    opt = {
        'firecap': 0.0
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
                    original_type: Any = type(opt_values[i])
                    opt_values[i] = original_type(optionals[i])

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
        primary_firecaped_macro = PrimaryFirecapedHyperburstMacro(macro_args)
        autocliker_macro = AutoclickerMacro()
        macro_databank.update({0: primary_macro, 1: primary_firecaped_macro, 2: autocliker_macro})

        # Start event processing threads
        mouse_listener_thread = MouseListenerThread()  # noqa
        state_controller_thread = StateControllerThread()  # noqa

        clicker_thread = ClickerThread(do_clicking, macro_queue, macro_databank, program_alive)
        clicker_thread.start()
        proc_command('set', macro_args)  # Cursed workaround

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
