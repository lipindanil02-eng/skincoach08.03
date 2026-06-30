"""
28-дневная программа.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import ProgramProgress, User

router = APIRouter(prefix="/api/program", tags=["program"])


@router.get("/")
async def get_program(user_id: int = Query(...), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    progress_result = await db.execute(
        select(ProgramProgress).where(ProgramProgress.user_id == user.id)
    )
    progress = progress_result.scalar_one_or_none()
    if not progress:
        progress = ProgramProgress(user_id=user.id, day=1, week=1)
        db.add(progress)
        await db.commit()
        await db.refresh(progress)

    return {
        "day": progress.day,
        "week": progress.week,
        "last_plan": progress.last_plan,
    }


@router.post("/next")
async def next_day(user_id: int = Query(...), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    progress_result = await db.execute(
        select(ProgramProgress).where(ProgramProgress.user_id == user.id)
    )
    progress = progress_result.scalar_one_or_none()
    if not progress:
        progress = ProgramProgress(user_id=user.id, day=1, week=1)
        db.add(progress)

    progress.day += 1
    if progress.day > 7 and progress.day % 7 == 1:
        progress.week += 1
    if progress.week > 4:
        progress.week = 4

    progress.last_plan = f"План на день {progress.day}, неделя {progress.week}. Скоро здесь будет персональная программа."

    await db.commit()
    await db.refresh(progress)

    return {
        "day": progress.day,
        "week": progress.week,
        "plan": progress.last_plan,
    }
