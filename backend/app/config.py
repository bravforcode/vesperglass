"""
Application Configuration for Stocknomist Backend.
Complies with ADR-014 resource limits and VPS directory layout.
"""

from pathlib import Path
from pydantic import BaseModel
import os


class AppConfig(BaseModel):
    APP_NAME: str = "Stocknomist API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    # File paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    DATA_DIR: Path = Path(os.getenv("DATA_DIR", "c:/data" if Path("c:/data").exists() else str(Path(__file__).resolve().parent.parent.parent / "data")))
    SEEDS_DIR: Path = Path(__file__).resolve().parent / "data_seeds"
    FRONTEND_DIST: Path = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

    # CORS
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:18800",
        "https://stocknomist.168-222-27-36.sslip.io",
        "*"
    ]


settings = AppConfig()
