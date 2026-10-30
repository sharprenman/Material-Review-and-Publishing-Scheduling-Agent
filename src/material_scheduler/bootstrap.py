import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver

from material_scheduler.application.context import ContextBuilder
from material_scheduler.application.service import Service
from material_scheduler.config import Settings
from material_scheduler.infrastructure.catalog import Catalog
from material_scheduler.infrastructure.model.deepseek import DeepSeek
from material_scheduler.infrastructure.model.mock import MockModel
from material_scheduler.infrastructure.persistence.memory import CaseMemory, UnavailableCaseMemory
from material_scheduler.infrastructure.persistence.repository import Repository
from material_scheduler.infrastructure.trace import Trace


def create_service(settings: Settings, model=None) -> Service:
    settings.runtime_dir.mkdir(parents=True, exist_ok=True)
    (settings.runtime_dir / "traces").mkdir(exist_ok=True)
    catalog = Catalog(settings.data_dir)
    selected = model or (DeepSeek() if settings.mode == "live" else MockModel())
    repo = Repository(settings.runtime_dir / "business.sqlite")
    repo.initialize(catalog.schedules())
    checkpoint_db = sqlite3.connect(
        settings.runtime_dir / "checkpoints.sqlite", check_same_thread=False
    )
    memory: CaseMemory | UnavailableCaseMemory
    try:
        memory = CaseMemory(settings.runtime_dir / "memory.sqlite")
    except (OSError, sqlite3.Error):
        memory = UnavailableCaseMemory()
    return Service(
        repo,
        catalog,
        selected,
        settings,
        checkpoint_db,
        SqliteSaver(checkpoint_db),
        Trace,
        memory,
        ContextBuilder(repo, catalog, memory, settings),
    )
