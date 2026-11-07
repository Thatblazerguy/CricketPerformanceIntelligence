"""
CPI FastAPI Application
Entry point for the backend API server.
"""
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.routes import health, players, matches, analytics, scouting, ingestion, teams, matchups, auction, auction_extras

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Cricket analytics and scouting platform powered by Cricsheet ball-by-ball data.",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000",
                   "http://127.0.0.1:5173", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

prefix = settings.API_V1_PREFIX
app.include_router(health.router, prefix=prefix, tags=["Health"])
app.include_router(players.router, prefix=prefix, tags=["Players"])
app.include_router(matches.router, prefix=prefix, tags=["Matches"])
app.include_router(analytics.router, prefix=prefix, tags=["Analytics"])
app.include_router(scouting.router, prefix=prefix, tags=["Scouting"])
app.include_router(ingestion.router, prefix=prefix, tags=["Ingestion"])
app.include_router(teams.router, prefix=prefix, tags=["Teams"])
app.include_router(matchups.router, prefix=prefix, tags=["Matchups"])
app.include_router(auction.router, prefix=prefix)
app.include_router(auction_extras.router, prefix=prefix)
