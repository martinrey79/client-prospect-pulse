"""Client & Prospect Intelligence System (CPS)."""

from cps.cli import main
from cps.config import Settings, get_settings
from cps.graphs import Orchestrator
from cps.observability import configure_observability
from cps.simulator import CustomerDataSimulator, get_simulator, reset_simulator
from cps.store import DurableStore
from cps.workers import PrivateWorker, PublicWorker


def build_system(
    *,
    store_path: str | None = None,
    use_simulator: bool = True,
    public_worker: PublicWorker | None = None,
) -> tuple[Orchestrator, DurableStore, CustomerDataSimulator, PrivateWorker, PublicWorker]:
    """Wire a fully-local CPS stack."""
    settings = get_settings()
    configure_observability(settings)
    store = DurableStore(store_path or settings.store_path)
    sim = get_simulator() if use_simulator else reset_simulator()
    private = PrivateWorker(use_simulator=use_simulator, simulator=sim)
    public = public_worker or PublicWorker(settings)
    orch = Orchestrator(store, private, public)
    return orch, store, sim, private, public


__all__ = [
    "Orchestrator",
    "DurableStore",
    "CustomerDataSimulator",
    "PrivateWorker",
    "PublicWorker",
    "Settings",
    "get_settings",
    "build_system",
    "get_simulator",
    "reset_simulator",
    "configure_observability",
    "main",
]
