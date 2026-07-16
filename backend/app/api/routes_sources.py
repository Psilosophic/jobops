from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.models.jobs import SearchRun
from app.models.sources import Source, SourceHealthEvent, SourcePolicy

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("")
def list_sources(session: Session = Depends(get_session)) -> list[dict]:
    out = []
    for src in session.exec(select(Source)):
        policy = session.exec(
            select(SourcePolicy).where(SourcePolicy.source_id == src.id)
        ).first()
        last_run = session.exec(
            select(SearchRun).where(SearchRun.source_id == src.id)
            .order_by(SearchRun.started_at.desc())
        ).first()
        out.append({
            "source": src.model_dump(),
            "policy": policy.model_dump() if policy else None,
            "last_run": last_run.model_dump() if last_run else None,
        })
    return out


@router.get("/{source_id}/health")
def source_health(source_id: int, session: Session = Depends(get_session)) -> list[dict]:
    events = session.exec(
        select(SourceHealthEvent).where(SourceHealthEvent.source_id == source_id)
        .order_by(SourceHealthEvent.created_at.desc()).limit(50)
    )
    return [e.model_dump() for e in events]


@router.patch("/{source_id}/config")
def update_config(source_id: int, config: dict,
                  session: Session = Depends(get_session)) -> dict:
    src = session.get(Source, source_id)
    if src is None:
        raise HTTPException(404)
    src.config = {**src.config, **config}
    session.add(src)
    session.commit()
    return src.model_dump()


@router.post("/{source_id}/run")
def trigger_run(source_id: int, session: Session = Depends(get_session)) -> dict:
    src = session.get(Source, source_id)
    if src is None:
        raise HTTPException(404)
    from app.tasks import discover_source
    discover_source.delay(source_id)
    return {"dispatched": src.slug}
