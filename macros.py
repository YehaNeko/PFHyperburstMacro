from __future__ import annotations

import time
from typing import TYPE_CHECKING

from pynput import mouse
from pynput.mouse import Button
from base.macro import BaseHyperburstMacro, BaseMacro

if TYPE_CHECKING:
    from collections.abc import Iterator


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
        remaining_time = max(duration, 0.0001)

        # Low cost sleep till the remaining time is 5ms
        while remaining_time > 0.005:

            # Sleep for half of the remaining time or minimum sleep interval
            time.sleep(remaining_time / 2)

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
        remaining_time = max(duration, 0.0001)

        # Low cost sleep till the remaining time is 5ms
        while remaining_time > 0.005:

            # Sleep for half of the remaining time or minimum sleep interval
            time.sleep(remaining_time / 2)
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

            self.sleep(self.sleep_after_burst)
            yield

            # for _ in self.sleep_generator(self.sleep_after_burst):
            #     yield

            self.press()


class PrimaryFirecapedHyperburstMacro(PrimaryHyperburstMacro):
    def __init__(self, *args):
        super().__init__(*args)
        self._shots: int = 1
        self._sleep_after_burst: float = 0.000
        self.half_sleep_after_burst: float = 0.000

    @property
    def sleep_after_burst(self) -> float:
        return self._sleep_after_burst

    @sleep_after_burst.setter
    def sleep_after_burst(self, value) -> None:
        self._sleep_after_burst = value
        self.half_sleep_after_burst = value / 2

    @property
    def shots(self) -> int:
        return self._shots

    @shots.setter
    def shots(self, value: int) -> None:
        self._shots = value - 1

    def macro(self) -> Iterator[None]:
        while True:

            for _ in range(self.shots):
                self.sleep(self.delay_per_shot)
                yield

            self.sleep(self.half_sleep_after_burst)
            self.release()
            self.sleep(self.half_sleep_after_burst)
            yield

            self.press()


class AutoclickerMacro(BaseMacro):
    def __init__(self):
        self.controller = mouse.Controller()

    @staticmethod
    def sleep(duration: float) -> None:
        """Higher precision version of `time.sleep()`"""
        start_time = time.perf_counter()
        remaining_time = max(duration, 0.0001)

        # Low cost sleep till the remaining time is 5ms
        while remaining_time > 0.005:

            # Sleep for half of the remaining time or minimum sleep interval
            time.sleep(remaining_time / 2)

            elapsed_time = time.perf_counter() - start_time
            remaining_time = duration - elapsed_time

        # Switch to higher precision sleep
        while remaining_time > 0:
            elapsed_time = time.perf_counter() - start_time
            remaining_time = duration - elapsed_time

    def macro(self) -> Iterator[None]:
        while True:
            self.sleep(0.001)
            self.controller.release(Button.left)
            self.sleep(0.001)
            yield
            self.controller.press(Button.left)
