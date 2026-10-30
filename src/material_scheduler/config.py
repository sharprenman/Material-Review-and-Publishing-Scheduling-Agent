from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    data_dir: Path = Path("data")
    runtime_dir: Path = Path("var")
    mode: str = "mock"
    max_model_calls: int = Field(default=16, ge=1, le=40)
    max_tool_calls: int = Field(default=20, ge=1, le=60)
    max_active_seconds: float = Field(default=180, gt=0, le=600)
    network_timeout: float = Field(default=25, gt=0, le=60)

    context_enabled: bool = True
    context_max_estimate: int = Field(default=16000, ge=512, le=128000)
    context_recent_turns: int = Field(default=2, ge=0, le=6)
    memory_top_k: int = Field(default=3, ge=0, le=5)
    memory_ttl_days: int = Field(default=30, ge=1, le=365)
