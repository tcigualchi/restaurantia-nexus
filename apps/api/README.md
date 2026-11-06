# RestaurantIA Nexus — API

FastAPI modular monolith: REST API, SSE stream, deterministic simulator, event worker,
agents (LangGraph) and approval workflow. See the repository root `README.md` for the
full quickstart and `docs/` for architecture and ADRs.

```bash
uv sync                      # install
uv run alembic upgrade head  # migrate
uv run nexus-seed            # seed synthetic templates
uv run uvicorn nexus.main:app --reload
uv run nexus-worker          # simulation + event + agent worker
uv run pytest                # tests (integration tests need TEST_DATABASE_URL)
```
