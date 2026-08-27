"""State and decision orchestration."""

from catalyst.engine.state_machine import EventStateMachine, StateMachineConfig

__all__ = ["DecisionPipeline", "EventStateMachine", "StateMachineConfig"]


def __getattr__(name: str) -> object:
    if name == "DecisionPipeline":
        from catalyst.engine.pipeline import DecisionPipeline

        return DecisionPipeline
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
