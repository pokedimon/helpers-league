from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.database.models import Answer, AuditLog, Question

SCHOOL_TIMEZONE = timezone(timedelta(hours=3))

class AntiCheatService:
    @staticmethod
    def validate_answer_eligibility(question_author_id: Any, helper_id: Any) -> bool:
        if question_author_id is None or helper_id is None:
            return False
        q_author = str(question_author_id).strip().lower()
        h_author = str(helper_id).strip().lower()
        if not q_author or not h_author:
            return False
        return q_author != h_author

    @staticmethod
    def is_curfew_active(
        dt: Optional[datetime] = None,
        start_hour: Optional[int] = None,
        end_hour: Optional[int] = None,
    ) -> bool:
        if dt is None:
            dt = datetime.now(SCHOOL_TIMEZONE)
        elif dt.tzinfo is None:
            dt = dt.replace(tzinfo=SCHOOL_TIMEZONE)
        else:
            dt = dt.astimezone(SCHOOL_TIMEZONE)

        current_time = dt.time()
        start_val = start_hour if start_hour is not None else settings.CURFEW_START_HOUR
        end_val = end_hour if end_hour is not None else settings.CURFEW_END_HOUR
        start = time(start_val, 0)
        end = time(end_val, 0)

        if start > end:
            return current_time >= start or current_time < end
        elif start < end:
            return start <= current_time < end
        return False

    @staticmethod
    async def check_daily_gratitude_limit(
        session: AsyncSession,
        author_id: Optional[str] = None,
        helper_id: Optional[str] = None,
        date: Optional[date] = None,
        *,
        author_max_id: Optional[str] = None,
        helper_max_id: Optional[str] = None,
        check_date: Optional[date] = None,
    ) -> bool:
        author = str(author_id or author_max_id or "").strip().lower()
        helper = str(helper_id or helper_max_id or "").strip().lower()
        target_date_val = date if date is not None else check_date
        if target_date_val is None:
            target_date_val = datetime.now(SCHOOL_TIMEZONE).date()
        elif isinstance(target_date_val, datetime):
            if target_date_val.tzinfo is None:
                target_date_val = target_date_val.replace(tzinfo=SCHOOL_TIMEZONE).date()
            else:
                target_date_val = target_date_val.astimezone(SCHOOL_TIMEZONE).date()

        start_school = datetime.combine(target_date_val, time.min).replace(tzinfo=SCHOOL_TIMEZONE)
        end_school = datetime.combine(target_date_val, time.max).replace(tzinfo=SCHOOL_TIMEZONE)
        start_dt = start_school.astimezone(timezone.utc).replace(tzinfo=None)
        end_dt = end_school.astimezone(timezone.utc).replace(tzinfo=None)

        q_answers = (
            select(func.count(Answer.id))
            .join(Question, Answer.question_id == Question.id)
            .where(
                func.lower(Question.author_max_id) == author,
                func.lower(Answer.author_max_id) == helper,
                Answer.status == "accepted",
                or_(
                    and_(Answer.created_at >= start_dt, Answer.created_at <= end_dt),
                    and_(
                        Question.closed_at.is_not(None),
                        Question.closed_at >= start_dt,
                        Question.closed_at <= end_dt,
                    ),
                ),
            )
        )
        res = await session.execute(q_answers)
        if res.scalar_one() >= 1:
            return True

        q_audit = (
            select(func.count(AuditLog.id))
            .where(
                func.lower(AuditLog.actor_max_id) == author,
                AuditLog.action == "award_gratitude",
                AuditLog.created_at >= start_dt,
                AuditLog.created_at <= end_dt,
                or_(
                    func.lower(AuditLog.target_user_max_id) == helper,
                    AuditLog.details.like(f"%helper={helper}%"),
                    AuditLog.details.like(f"%helper_id={helper}%"),
                ),
            )
        )
        res_audit = await session.execute(q_audit)
        return res_audit.scalar_one() >= 1

    @staticmethod
    async def log_audit_event(
        session: AsyncSession,
        actor_max_id: str,
        action: str,
        target_user_max_id: Optional[str] = None,
        details: Optional[str] = None,
        *,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        created_at: Optional[datetime] = None,
        timestamp: Optional[datetime] = None,
        commit: bool = False,
    ) -> AuditLog:
        audit = AuditLog(
            actor_max_id=str(actor_max_id),
            action=str(action),
            target_user_max_id=str(target_user_max_id) if target_user_max_id is not None else None,
            target_type=str(target_type) if target_type is not None else None,
            target_id=str(target_id) if target_id is not None else None,
            details=str(details) if details is not None else None,
        )
        if created_at is not None:
            audit.created_at = created_at
        elif timestamp is not None:
            audit.created_at = timestamp
        session.add(audit)
        if commit:
            await session.commit()
            await session.refresh(audit)
        else:
            await session.flush()
        return audit

validate_answer_eligibility = AntiCheatService.validate_answer_eligibility
is_curfew_active = AntiCheatService.is_curfew_active
check_daily_gratitude_limit = AntiCheatService.check_daily_gratitude_limit
log_audit_event = AntiCheatService.log_audit_event

__all__ = [
    "AntiCheatService",
    "SCHOOL_TIMEZONE",
    "validate_answer_eligibility",
    "is_curfew_active",
    "check_daily_gratitude_limit",
    "log_audit_event",
]
