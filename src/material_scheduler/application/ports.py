from typing import Protocol


class Model(Protocol):
    name: str
    mode: str

    def choose(self, messages: list[dict], tools: list[dict], timeout: float) -> dict: ...
