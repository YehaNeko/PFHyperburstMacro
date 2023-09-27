from __future__ import annotations

from pynput import mouse
from collections.abc import Iterator
from typing import Protocol, NamedTuple, Tuple


RawMouseButtonEvent = Tuple[int, int, mouse.Button, bool]


class MouseButtonEvent(NamedTuple):
    button: mouse.Button
    pressed: bool


class BaseMacro(Protocol):
    """A base macro."""
    def macro(self) -> Iterator[None]:
        ...


class BaseHyperburstMacro(BaseMacro, Protocol):
    """Base hyperburst macro."""

    def calc_delay(self) -> None:
        ...

    def press(self) -> None:
        ...

    def release(self) -> None:
        ...
