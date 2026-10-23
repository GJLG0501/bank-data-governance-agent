"""Read-only infrastructure boundary. Provisioning remains an explicit operation."""
from scripts import new_bank_runtime_validation as runtime
from scripts import new_bank_publication as publication


def read_published(sql):
    """Internal fixed-query adapter, never exposed as an LLM tool."""
    runtime.active_guard()
    return publication.active_read(sql)
