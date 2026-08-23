"""Pure domain model shared by sampler, bank builder, and profile tooling."""

from .events import LogicalEvent
from .physical import PhysicalInstrument, PhysicalKit
from .profiles import SetupProfile, load_setup
from .project import KitProject, ProjectError
from .rig_project import (LogicalRouteVariant, RigProject, RigProjectError,
                          load_rig_project, logical_route_variants)
from .validation import validate_document, validate_yaml

__all__ = [
    "KitProject",
    "LogicalEvent",
    "LogicalRouteVariant",
    "PhysicalInstrument",
    "PhysicalKit",
    "ProjectError",
    "RigProject",
    "RigProjectError",
    "SetupProfile",
    "load_setup",
    "load_rig_project",
    "logical_route_variants",
    "validate_document",
    "validate_yaml",
]
