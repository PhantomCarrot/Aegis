from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz() -> dict:
    """Liveness endpoint — deliberately without auth (used by monitoring/orchestration)."""
    return {"status": "ok"}
