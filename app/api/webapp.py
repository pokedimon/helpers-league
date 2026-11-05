from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import (
    Achievement,
    Answer,
    AuditLog,
    Question,
    Reward,
    RewardClaim,
    User,
    UserAchievement,
)
from app.database.session import get_db_session
from app.services.auth import get_current_user, require_teacher
from app.services.teacher_service import TeacherService

router = APIRouter(prefix="/webapp", tags=["webapp"])

class AchievementItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name_ru: str
    description_ru: str
    icon_url: Optional[str] = None
    unlocked: bool = False
    awarded_at: Optional[datetime] = None

class UserProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    max_user_id: str
    display_name: str
    role: str
    balance_spasibki: int
    xp: int
    rank: str
    level: int
    achievements: List[AchievementItem]

class LeaderboardEntry(BaseModel):
    rank_position: int
    max_user_id: str
    display_name: str
    rank: str
    xp: int
    balance_spasibki: int

class LeaderboardResponse(BaseModel):
    period: str
    items: List[LeaderboardEntry]

class RewardItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_by_teacher_id: str
    title: str
    description: str
    cost_spasibki: int
    is_active: bool

class ClaimRewardRequest(BaseModel):
    reward_id: int

class ClaimRewardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    reward_id: int
    student_max_id: str
    status: str
    created_at: datetime

class AdjustBalanceRequest(BaseModel):
    user_id: Optional[str] = None
    student_max_id: Optional[str] = None
    amount: Optional[int] = None
    delta_spasibki: Optional[int] = None
    delta_xp: Optional[int] = 0
    reason: str = "Teacher adjustment"

class OverrideAnswerRequest(BaseModel):
    answer_id: int
    status: str
    reason: str = "Teacher override"

class ReviewClaimRequest(BaseModel):
    claim_id: int
    action: Optional[str] = None
    decision: Optional[str] = None

class CreateRewardRequest(BaseModel):
    title: str
    description: str
    cost_spasibki: int

class TeacherOverviewResponse(BaseModel):
    pending_claims: List[Dict[str, Any]]
    active_questions: List[Dict[str, Any]]
    disputed_answers: List[Dict[str, Any]]
    total_students: int
    statistics: Dict[str, int]
    recent_audit_logs: List[Dict[str, Any]]

@router.get("/profile", response_model=UserProfileResponse)
async def get_profile(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    query = (
        select(Achievement, UserAchievement.awarded_at)
        .join(UserAchievement, Achievement.id == UserAchievement.achievement_id)
        .where(UserAchievement.user_max_id == current_user.max_user_id)
        .order_by(UserAchievement.awarded_at.desc())
    )
    res = await session.execute(query)
    achievements_data = [
        AchievementItem(
            id=ach.id,
            code=ach.code,
            name_ru=ach.name_ru,
            description_ru=ach.description_ru,
            icon_url=ach.icon_url,
            unlocked=True,
            awarded_at=awarded_at,
        )
        for ach, awarded_at in res.all()
    ]
    level = (current_user.xp // 100) + 1
    return UserProfileResponse(
        id=current_user.id,
        max_user_id=current_user.max_user_id,
        display_name=current_user.display_name,
        role=current_user.role,
        balance_spasibki=current_user.balance_spasibki,
        xp=current_user.xp,
        rank=current_user.rank,
        level=level,
        achievements=achievements_data,
    )

@router.get("/achievements", response_model=List[AchievementItem])
async def get_achievements(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    all_res = await session.execute(select(Achievement).order_by(Achievement.id.asc()))
    all_achievements = all_res.scalars().all()

    ua_res = await session.execute(
        select(UserAchievement).where(UserAchievement.user_max_id == current_user.max_user_id)
    )
    user_unlocked = {ua.achievement_id: ua.awarded_at for ua in ua_res.scalars().all()}

    return [
        AchievementItem(
            id=ach.id,
            code=ach.code,
            name_ru=ach.name_ru,
            description_ru=ach.description_ru,
            icon_url=ach.icon_url,
            unlocked=(ach.id in user_unlocked),
            awarded_at=user_unlocked.get(ach.id),
        )
        for ach in all_achievements
    ]

@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(
    period: str = Query("all_time"),
    limit: int = Query(50),
    offset: int = Query(0),
    session: AsyncSession = Depends(get_db_session),
):
    if period == "weekly":
        since_dt = datetime.now(timezone.utc) - timedelta(days=7)
        weekly_query = (
            select(
                User.max_user_id,
                User.display_name,
                User.rank,
                User.balance_spasibki,
                User.xp,
                (func.count(Answer.id) * 50).label("week_xp"),
            )
            .join(Answer, Answer.author_max_id == User.max_user_id)
            .where(User.role == "student", Answer.status == "accepted", Answer.created_at >= since_dt)
            .group_by(User.id)
            .order_by(func.count(Answer.id).desc(), User.xp.desc())
            .offset(offset)
            .limit(limit)
        )
        res = await session.execute(weekly_query)
        rows = res.all()
        if rows:
            items = [
                LeaderboardEntry(
                    rank_position=idx,
                    max_user_id=row[0],
                    display_name=row[1],
                    rank=row[2],
                    xp=row[4],
                    balance_spasibki=row[3],
                )
                for idx, row in enumerate(rows, offset + 1)
            ]
            return LeaderboardResponse(period=period, items=items)

    all_time_query = (
        select(User)
        .where(User.role == "student")
        .order_by(User.xp.desc(), User.balance_spasibki.desc(), User.id.asc())
        .offset(offset)
        .limit(limit)
    )
    res = await session.execute(all_time_query)
    students = res.scalars().all()
    items = [
        LeaderboardEntry(
            rank_position=idx,
            max_user_id=s.max_user_id,
            display_name=s.display_name,
            rank=s.rank,
            xp=s.xp,
            balance_spasibki=s.balance_spasibki,
        )
        for idx, s in enumerate(students, offset + 1)
    ]
    return LeaderboardResponse(period=period, items=items)

@router.get("/rewards", response_model=List[RewardItem])
async def get_rewards(
    session: AsyncSession = Depends(get_db_session),
):
    res = await session.execute(
        select(Reward).where(Reward.is_active == True).order_by(Reward.cost_spasibki.asc())
    )
    return res.scalars().all()

@router.post("/rewards/claim", response_model=ClaimRewardResponse)
async def claim_reward(
    body: ClaimRewardRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        claim = await TeacherService.claim_reward(
            session=session,
            student_max_id=current_user.max_user_id,
            reward_id=body.reward_id,
        )
        return claim
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

@router.get("/teacher/overview", response_model=TeacherOverviewResponse)
async def get_teacher_overview(
    current_teacher: User = Depends(require_teacher),
    session: AsyncSession = Depends(get_db_session),
):
    overview = await TeacherService.get_teacher_overview(
        session=session,
        teacher_max_id=current_teacher.max_user_id,
    )

    audit_res = await session.execute(
        select(AuditLog).order_by(AuditLog.created_at.desc()).limit(20)
    )
    recent_audits = [
        {
            "id": a.id,
            "actor_max_id": a.actor_max_id,
            "target_user_max_id": a.target_user_max_id,
            "target_type": a.target_type,
            "target_id": a.target_id,
            "action": a.action,
            "details": a.details,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in audit_res.scalars().all()
    ]

    total_q_res = await session.execute(select(func.count(Question.id)))
    total_q = total_q_res.scalar_one() or 0

    resolved_q_res = await session.execute(
        select(func.count(Question.id)).where(Question.status == "resolved")
    )
    resolved_q = resolved_q_res.scalar_one() or 0

    stats = {
        "total_questions": total_q,
        "resolved_questions": resolved_q,
        "open_questions": len(overview.get("active_questions", [])),
        "pending_claims": len(overview.get("pending_claims", [])),
        "total_students": overview.get("total_students", 0),
    }

    return TeacherOverviewResponse(
        pending_claims=overview.get("pending_claims", []),
        active_questions=overview.get("active_questions", []),
        disputed_answers=overview.get("disputed_answers", []),
        total_students=overview.get("total_students", 0),
        statistics=stats,
        recent_audit_logs=recent_audits,
    )

@router.post("/teacher/adjust-balance")
async def adjust_student_balance(
    body: AdjustBalanceRequest,
    current_teacher: User = Depends(require_teacher),
    session: AsyncSession = Depends(get_db_session),
):
    target_uid = body.user_id or body.student_max_id
    if not target_uid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing user_id")
    delta_spasibki = body.delta_spasibki if body.delta_spasibki is not None else (body.amount if body.amount is not None else 0)
    delta_xp = body.delta_xp if body.delta_xp is not None else 0
    try:
        user = await TeacherService.adjust_student_balance(
            session=session,
            teacher_max_id=current_teacher.max_user_id,
            student_max_id=target_uid,
            delta_spasibki=delta_spasibki,
            delta_xp=delta_xp,
            reason=body.reason,
        )
        return {
            "status": "ok",
            "user_id": user.max_user_id,
            "balance_spasibki": user.balance_spasibki,
            "xp": user.xp,
            "rank": user.rank,
        }
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

@router.post("/teacher/override-answer")
async def override_answer_status(
    body: OverrideAnswerRequest,
    current_teacher: User = Depends(require_teacher),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        ans = await TeacherService.override_answer_status(
            session=session,
            teacher_max_id=current_teacher.max_user_id,
            answer_id=body.answer_id,
            new_status=body.status,
            reason=body.reason,
        )
        return {
            "status": "ok",
            "answer_id": ans.id,
            "new_status": ans.status,
            "question_id": ans.question_id,
        }
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

@router.post("/teacher/review-claim")
async def review_reward_claim(
    body: ReviewClaimRequest,
    current_teacher: User = Depends(require_teacher),
    session: AsyncSession = Depends(get_db_session),
):
    decision_val = body.action or body.decision
    if not decision_val:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing action or decision")
    try:
        claim = await TeacherService.review_reward_claim(
            session=session,
            teacher_max_id=current_teacher.max_user_id,
            claim_id=body.claim_id,
            decision=decision_val,
        )
        return {
            "status": "ok",
            "claim_id": claim.id,
            "new_status": claim.status,
        }
    except ValueError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

@router.post("/teacher/rewards", response_model=RewardItem)
@router.post("/rewards", response_model=RewardItem)
async def create_reward(
    body: CreateRewardRequest,
    current_teacher: User = Depends(require_teacher),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        reward = await TeacherService.create_reward(
            session=session,
            teacher_max_id=current_teacher.max_user_id,
            title=body.title,
            description=body.description,
            cost_spasibki=body.cost_spasibki,
        )
        return reward
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
