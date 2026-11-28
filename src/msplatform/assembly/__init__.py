"""Solver-neutral scientific assembly API."""

from .model import Assembly as Assembly
from .factory import assemble as assemble
from .port_mating import mate_ports as mate_ports
from .accelerator_interface import build_interface_proposal as build_interface_proposal
