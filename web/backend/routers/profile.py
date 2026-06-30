"""
Профиль пользователя и история анализов.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Analysis, User

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("/")
async def get_profile(user_id: int = Query(...), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    analyses_result = await db.execute(
        select(Analysis).where(Analysis.user_id == user.id).order_by(Analysis.created_at.desc())
    )
    analyses = analyses_result.scalars().all()

    return {
        "user": {
            "id": user.id,
            "username": user.username,
            "name": user.name,
            "subscription": user.subscription,
            "paid_until": user.paid_until.isoformat() if user.paid_until else None,
        },
        "analyses": [
            {
                "id": a.id,
                "diagnosis": a.diagnosis,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in analyses
        ],
    }
