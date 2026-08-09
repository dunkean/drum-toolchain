"""Pure domain model shared by sampler, bank builder, and profile tooling."""

from .events import LogicalEvent
from .physical import PhysicalInstrument, PhysicalKit
from .profiles import SetupProfile, load_setup
from .project import KitProject, ProjectError
from .validation import validate_document, validate_yaml

__all__ = [
    "KitProject",
    "LogicalEvent",
    "PhysicalInstrument",
    "PhysicalKit",
    "ProjectError",
    "SetupProfile",
    "load_setup",
    "validate_document",
    "validate_yaml",
]
