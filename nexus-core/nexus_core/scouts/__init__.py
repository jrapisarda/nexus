"""NEXUS external data source scouts.

Each scout implements BaseScout and searches a specific external API.
"""

from nexus_core.scouts.base import BaseScout, ScoutFinding
from nexus_core.scouts.pubmed import PubMedScout
from nexus_core.scouts.clinicaltrials import ClinicalTrialsScout
from nexus_core.scouts.biorxiv import BioRxivScout
from nexus_core.scouts.patents_uspto import USPTOScout
from nexus_core.scouts.patents_google import GooglePatentsScout

__all__ = [
    "BaseScout",
    "ScoutFinding",
    "PubMedScout",
    "ClinicalTrialsScout",
    "BioRxivScout",
    "USPTOScout",
    "GooglePatentsScout",
]
