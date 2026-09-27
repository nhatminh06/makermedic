"""Safe, explicit diagnostic validation laboratory."""

from makermedic.lab.registry import build_scenario_registry
from makermedic.lab.runner import LabRunner

__all__ = ["LabRunner", "build_scenario_registry"]
