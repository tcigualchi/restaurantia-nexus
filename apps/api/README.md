# RestaurantIA Nexus API

FastAPI application with the REST API, the live feed, the deterministic simulator, the event worker, the agents
(LangGraph) and the approval flow. The repository root `README.md` has the full guide, and `docs/` has the
architecture notes and ADRs.

```bash
uv sync                       # install
uv run alembic upgrade head   # migrate
uv run nexus-seed             # create the synthetic restaurants
uv run uvicorn nexus.main:app --reload
uv run nexus-worker           # simulation, events and agents
uv run pytest                 # integration tests need TEST_DATABASE_URL
```
