from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models.ops import PanicPanelEvent
from app.panic import service

router = APIRouter(prefix="/panic", tags=["panic"])


class FlagChange(BaseModel):
    flag: str
    value: bool
    operator_intent: str


@router.get("")
def state(session: Session = Depends(get_session)) -> dict:
    return service.get_state(session).model_dump()


@router.post("/flag")
def set_flag(body: FlagChange, session: Session = Depends(get_session)) -> dict:
    return service.set_flag(session, body.flag, body.value, body.operator_intent).model_dump()


@router.post("/emergency-stop")
def emergency_stop(operator_intent: str = Body(embed=True),
                   session: Session = Depends(get_session)) -> dict:
    return service.emergency_stop(session, operator_intent).model_dump()


@router.post("/min-fit")
def min_fit(value: float | None = Body(embed=True),
            operator_intent: str = Body(embed=True),
            session: Session = Depends(get_session)) -> dict:
    return service.set_min_fit_override(session, value, operator_intent).model_dump()


@router.get("/events")
def events(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.exec(
        select(PanicPanelEvent).order_by(PanicPanelEvent.created_at.desc()).limit(100)
    )
    return [r.model_dump() for r in rows]
