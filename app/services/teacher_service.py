from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
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
from app.services.gamification import GamificationService

class TeacherService:
    @staticmethod
    async def _require_teacher(session: AsyncSession, teacher_max_id: str) -> User:
        user_res = await session.execute(
            select(User).where(User.max_user_id == teacher_max_id)
        )
        teacher = user_res.scalar_one_or_none()
        if teacher is None:
            raise PermissionError("Teacher user not found")
        if teacher.role not in ("teacher", "admin"):
            raise PermissionError("Only teachers or administrators can perform this action")
        return teacher

    @classmethod
    async def claim_reward(
        cls,
        session: AsyncSession,
        student_max_id: str,
        reward_id: int,
    ) -> RewardClaim:
        student_res = await session.execute(
            select(User).where(User.max_user_id == student_max_id)
        )
        student = student_res.scalar_one_or_none()
        if student is None:
            raise ValueError("Student not found")

        reward_res = await session.execute(
            select(Reward).where(Reward.id == reward_id)
        )
        reward = reward_res.scalar_one_or_none()
        if reward is None:
            raise ValueError("Reward not found")
        if not reward.is_active:
            raise ValueError("Reward is inactive")

        if student.balance_spasibki < reward.cost_spasibki:
            raise ValueError("Insufficient balance")

        student.balance_spasibki -= reward.cost_spasibki

        claim = RewardClaim(
            reward_id=reward.id,
            student_max_id=student_max_id,
            status="requested",
            created_at=datetime.now(timezone.utc),
        )
        session.add(claim)
        await session.flush()

        audit = AuditLog(
            actor_max_id=student_max_id,
            target_user_max_id=student_max_id,
            target_type="reward_claim",
            target_id=str(claim.id),
            action="claim_reward",
            details=f"reward_id={reward.id},cost={reward.cost_spasibki}",
            created_at=datetime.now(timezone.utc),
        )
        session.add(audit)
        await session.commit()
        return claim

    @classmethod
    async def review_reward_claim(
        cls,
        session: AsyncSession,
        teacher_max_id: str,
        claim_id: int,
        decision: str,
    ) -> RewardClaim:
        await cls._require_teacher(session, teacher_max_id)

        claim_res = await session.execute(
            select(RewardClaim).where(RewardClaim.id == claim_id)
        )
        claim = claim_res.scalar_one_or_none()
        if claim is None:
            raise ValueError("Reward claim not found")
        if claim.status != "requested":
            raise ValueError("Reward claim is already processed")

        if decision not in ("approved", "rejected", "approve", "reject"):
            raise ValueError("Invalid decision status")

        normalized_decision = "approved" if decision in ("approved", "approve") else "rejected"

        if normalized_decision == "rejected":
            reward_res = await session.execute(
                select(Reward).where(Reward.id == claim.reward_id)
            )
            reward = reward_res.scalar_one_or_none()

            student_res = await session.execute(
                select(User).where(User.max_user_id == claim.student_max_id)
            )
            student = student_res.scalar_one_or_none()

            if student is not None and reward is not None:
                student.balance_spasibki += reward.cost_spasibki

        claim.status = normalized_decision

        audit = AuditLog(
            actor_max_id=teacher_max_id,
            target_user_max_id=claim.student_max_id,
            target_type="reward_claim",
            target_id=str(claim.id),
            action=f"review_claim_{normalized_decision}",
            details=f"decision={normalized_decision}",
            created_at=datetime.now(timezone.utc),
        )
        session.add(audit)
        await session.commit()
        return claim

    @classmethod
    async def adjust_student_balance(
        cls,
        session: AsyncSession,
        teacher_max_id: str,
        student_max_id: str,
        delta_spasibki: int,
        delta_xp: int,
        reason: str,
    ) -> User:
        await cls._require_teacher(session, teacher_max_id)

        student_res = await session.execute(
            select(User).where(User.max_user_id == student_max_id)
        )
        student = student_res.scalar_one_or_none()
        if student is None:
            raise ValueError("Student not found")

        if student.balance_spasibki + delta_spasibki < 0:
            raise ValueError("Adjustment would result in negative balance")
        if student.xp + delta_xp < 0:
            raise ValueError("Adjustment would result in negative XP")

        student.balance_spasibki += delta_spasibki
        student.xp += delta_xp
        student.rank = GamificationService.calculate_rank(student.xp)

        audit = AuditLog(
            actor_max_id=teacher_max_id,
            target_user_max_id=student_max_id,
            target_type="user",
            target_id=student_max_id,
            action="adjust_balance",
            details=f"delta_spasibki={delta_spasibki},delta_xp={delta_xp},reason={reason}",
            created_at=datetime.now(timezone.utc),
        )
        session.add(audit)

        await GamificationService.evaluate_achievements(session, student_max_id)
        await session.commit()
        return student

    @classmethod
    async def override_answer_status(
        cls,
        session: AsyncSession,
        teacher_max_id: str,
        answer_id: int,
        new_status: str,
        reason: str,
    ) -> Answer:
        await cls._require_teacher(session, teacher_max_id)

        answer_res = await session.execute(
            select(Answer).where(Answer.id == answer_id)
        )
        answer = answer_res.scalar_one_or_none()
        if answer is None:
            raise ValueError("Answer not found")

        if new_status not in ("accepted", "rejected", "overridden"):
            raise ValueError("Invalid answer status")

        answer.status = new_status

        if new_status == "accepted":
            question_res = await session.execute(
                select(Question).where(Question.id == answer.question_id)
            )
            question = question_res.scalar_one_or_none()
            if question is not None and question.status == "open":
                question.status = "resolved"
                question.resolved_answer_id = answer.id
                question.closed_at = datetime.now(timezone.utc)

        audit = AuditLog(
            actor_max_id=teacher_max_id,
            target_user_max_id=answer.author_max_id,
            target_type="answer",
            target_id=str(answer.id),
            action="override_answer_status",
            details=f"new_status={new_status},reason={reason}",
            created_at=datetime.now(timezone.utc),
        )
        session.add(audit)
        await session.commit()
        return answer

    @classmethod
    async def create_reward(
        cls,
        session: AsyncSession,
        teacher_max_id: str,
        title: str,
        description: str,
        cost_spasibki: int,
    ) -> Reward:
        await cls._require_teacher(session, teacher_max_id)

        if cost_spasibki <= 0:
            raise ValueError("Cost in spasibki must be positive")

        reward = Reward(
            created_by_teacher_id=teacher_max_id,
            title=title,
            description=description,
            cost_spasibki=cost_spasibki,
            is_active=True,
        )
        session.add(reward)
        await session.flush()

        audit = AuditLog(
            actor_max_id=teacher_max_id,
            target_type="reward",
            target_id=str(reward.id),
            action="create_reward",
            details=f"title={title},cost={cost_spasibki}",
            created_at=datetime.now(timezone.utc),
        )
        session.add(audit)
        await session.commit()
        return reward

    @classmethod
    async def award_teacher_choice(
        cls,
        session: AsyncSession,
        teacher_max_id: str,
        student_max_id: str,
        reason: str = "",
    ) -> bool:
        await cls._require_teacher(session, teacher_max_id)

        student_res = await session.execute(
            select(User).where(User.max_user_id == student_max_id)
        )
        student = student_res.scalar_one_or_none()
        if student is None:
            raise ValueError("Student not found")

        ach_res = await session.execute(
            select(Achievement).where(Achievement.code == "teacher_choice")
        )
        ach = ach_res.scalar_one_or_none()
        if ach is None:
            raise ValueError("teacher_choice achievement not found")

        ua_res = await session.execute(
            select(UserAchievement).where(
                UserAchievement.user_max_id == student_max_id,
                UserAchievement.achievement_id == ach.id,
            )
        )
        if ua_res.scalar_one_or_none() is not None:
            return False

        now = datetime.now(timezone.utc)
        ua = UserAchievement(
            user_max_id=student_max_id,
            achievement_id=ach.id,
            awarded_at=now,
        )
        session.add(ua)

        audit = AuditLog(
            actor_max_id=teacher_max_id,
            target_user_max_id=student_max_id,
            target_type="achievement",
            target_id="teacher_choice",
            action="award_teacher_choice",
            details=reason,
            created_at=now,
        )
        session.add(audit)
        await session.commit()
        return True

    @classmethod
    async def get_teacher_overview(
        cls,
        session: AsyncSession,
        teacher_max_id: str,
    ) -> Dict[str, Any]:
        await cls._require_teacher(session, teacher_max_id)

        claims_query = (
            select(RewardClaim, Reward, User)
            .join(Reward, RewardClaim.reward_id == Reward.id)
            .join(User, RewardClaim.student_max_id == User.max_user_id)
            .where(RewardClaim.status == "requested")
            .order_by(RewardClaim.created_at.desc())
        )
        claims_res = await session.execute(claims_query)
        pending_claims = [
            {
                "claim_id": claim.id,
                "student_max_id": claim.student_max_id,
                "student_name": user.display_name,
                "reward_id": reward.id,
                "reward_title": reward.title,
                "cost_spasibki": reward.cost_spasibki,
                "created_at": claim.created_at.isoformat() if claim.created_at else None,
            }
            for claim, reward, user in claims_res.all()
        ]

        questions_query = (
            select(Question)
            .where(Question.status == "open")
            .order_by(Question.created_at.desc())
        )
        questions_res = await session.execute(questions_query)
        active_questions = [
            {
                "question_id": q.id,
                "group_chat_id": q.group_chat_id,
                "author_max_id": q.author_max_id,
                "text": q.text,
                "subject": q.subject,
                "created_at": q.created_at.isoformat() if q.created_at else None,
            }
            for q in questions_res.scalars().all()
        ]

        answers_query = (
            select(Answer)
            .where(Answer.status.in_(("pending", "overridden")))
            .order_by(Answer.created_at.desc())
        )
        answers_res = await session.execute(answers_query)
        disputed_answers = [
            {
                "answer_id": a.id,
                "question_id": a.question_id,
                "author_max_id": a.author_max_id,
                "text": a.text,
                "status": a.status,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in answers_res.scalars().all()
        ]

        total_students_res = await session.execute(
            select(func.count(User.id)).where(User.role == "student")
        )
        total_students = total_students_res.scalar_one() or 0

        return {
            "pending_claims": pending_claims,
            "active_questions": active_questions,
            "disputed_answers": disputed_answers,
            "total_students": total_students,
        }

claim_reward = TeacherService.claim_reward
review_reward_claim = TeacherService.review_reward_claim
adjust_student_balance = TeacherService.adjust_student_balance
override_answer_status = TeacherService.override_answer_status
create_reward = TeacherService.create_reward
award_teacher_choice = TeacherService.award_teacher_choice
get_teacher_overview = TeacherService.get_teacher_overview

__all__ = [
    "TeacherService",
    "claim_reward",
    "review_reward_claim",
    "adjust_student_balance",
    "override_answer_status",
    "create_reward",
    "award_teacher_choice",
    "get_teacher_overview",
]
