from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, synonym

class Base(DeclarativeBase):
    pass

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    max_user_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="student", server_default="student", nullable=False)
    balance_spasibki: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    xp: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    rank: Mapped[str] = mapped_column(String(32), default="Новичок", server_default="Новичок", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("role IN ('student', 'teacher', 'admin')", name="chk_users_role"),
        CheckConstraint("balance_spasibki >= 0", name="chk_users_balance_spasibki"),
        CheckConstraint("xp >= 0", name="chk_users_xp"),
    )

class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_chat_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    group_message_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    author_max_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open", nullable=False)
    resolved_answer_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("answers.id", ondelete="SET NULL", use_alter=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now(), nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('open', 'resolved', 'closed_by_teacher')", name="chk_questions_status"),
    )

    answers: Mapped[list["Answer"]] = relationship(
        back_populates="question",
        foreign_keys="Answer.question_id",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

class Answer(Base):
    __tablename__ = "answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(Integer, ForeignKey("questions.id", ondelete="CASCADE"), index=True, nullable=False)
    author_max_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    group_message_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    dm_approval_message_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'accepted', 'rejected', 'overridden')", name="chk_answers_status"),
    )

    question: Mapped["Question"] = relationship(
        back_populates="answers",
        foreign_keys=[question_id],
    )

class Reward(Base):
    __tablename__ = "rewards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_by_teacher_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    cost_spasibki: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)

    __table_args__ = (
        CheckConstraint("cost_spasibki > 0", name="chk_rewards_cost_spasibki"),
    )

    claims: Mapped[list["RewardClaim"]] = relationship(
        back_populates="reward",
    )

class RewardClaim(Base):
    __tablename__ = "reward_claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reward_id: Mapped[int] = mapped_column(Integer, ForeignKey("rewards.id", ondelete="RESTRICT"), index=True, nullable=False)
    student_max_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="requested", server_default="requested", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("status IN ('requested', 'approved', 'rejected')", name="chk_reward_claims_status"),
    )

    reward: Mapped["Reward"] = relationship(
        back_populates="claims",
    )

class Achievement(Base):
    __tablename__ = "achievements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name_ru: Mapped[str] = mapped_column(String(128), nullable=False)
    description_ru: Mapped[str] = mapped_column(Text, nullable=False)
    icon_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    user_achievements: Mapped[list["UserAchievement"]] = relationship(
        back_populates="achievement",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

class UserAchievement(Base):
    __tablename__ = "user_achievements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_max_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    achievement_id: Mapped[int] = mapped_column(Integer, ForeignKey("achievements.id", ondelete="CASCADE"), index=True, nullable=False)
    awarded_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_max_id", "achievement_id", name="uq_user_achievements_user_achievement"),
    )

    achievement: Mapped["Achievement"] = relationship(
        back_populates="user_achievements",
    )

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_max_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    target_user_max_id: Mapped[Optional[str]] = mapped_column(String(64), index=True, nullable=True)
    target_type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), server_default=func.now(), nullable=False)

    timestamp = synonym("created_at")

DEFAULT_ACHIEVEMENTS = [
    {
        "code": "first_step",
        "name_ru": "Первый шаг",
        "description_ru": "Первый принятый лучший ответ",
        "icon_url": "/static/icons/first_step.svg",
    },
    {
        "code": "fast_aid",
        "name_ru": "Скорая помощь",
        "description_ru": "Принятый ответ в течение 10 минут после публикации вопроса",
        "icon_url": "/static/icons/fast_aid.svg",
    },
    {
        "code": "rescuer",
        "name_ru": "Спасатель",
        "description_ru": "Принятый ответ на вопрос, остававшийся без ответа более 24 часов",
        "icon_url": "/static/icons/rescuer.svg",
    },
    {
        "code": "marathoner",
        "name_ru": "Марафонец",
        "description_ru": "5 лучших ответов за один день",
        "icon_url": "/static/icons/marathoner.svg",
    },
    {
        "code": "week_streak",
        "name_ru": "Неделя в строю",
        "description_ru": "Лучшие ответы 7 дней подряд",
        "icon_url": "/static/icons/week_streak.svg",
    },
    {
        "code": "mentor",
        "name_ru": "Наставник",
        "description_ru": "Оказана помощь 10 разным одноклассникам",
        "icon_url": "/static/icons/mentor.svg",
    },
    {
        "code": "subject_expert",
        "name_ru": "Знаток предмета",
        "description_ru": "10 принятых ответов по одному предмету",
        "icon_url": "/static/icons/subject_expert.svg",
    },
    {
        "code": "universal",
        "name_ru": "Универсал",
        "description_ru": "Принятые ответы по 5 разным предметам",
        "icon_url": "/static/icons/universal.svg",
    },
    {
        "code": "class_legend",
        "name_ru": "Легенда класса",
        "description_ru": "Суммарно 100 благодарностей",
        "icon_url": "/static/icons/class_legend.svg",
    },
    {
        "code": "brave_question",
        "name_ru": "Смелый вопрос",
        "description_ru": "Первый заданный вопрос в чате класса",
        "icon_url": "/static/icons/brave_question.svg",
    },
    {
        "code": "curious",
        "name_ru": "Любознательный",
        "description_ru": "10 заданных вопросов",
        "icon_url": "/static/icons/curious.svg",
    },
    {
        "code": "grateful",
        "name_ru": "Благодарный",
        "description_ru": "Автор отметил лучший ответ в 10 своих вопросах",
        "icon_url": "/static/icons/grateful.svg",
    },
    {
        "code": "week_leader",
        "name_ru": "Лидер недели",
        "description_ru": "1-е место в недельном рейтинге класса",
        "icon_url": "/static/icons/week_leader.svg",
    },
    {
        "code": "teacher_choice",
        "name_ru": "Выбор учителя",
        "description_ru": "Специальная награда, вручаемая педагогом вручную",
        "icon_url": "/static/icons/teacher_choice.svg",
    },
]
