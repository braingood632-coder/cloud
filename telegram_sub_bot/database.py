"""
database.py
-----------
طبقة قاعدة البيانات: تعريف جدول المشتركين، والدوال المساعدة للتعامل معه.
تستخدم SQLAlchemy (Async) مع SQLite افتراضياً. للانتقال إلى PostgreSQL
يكفي تغيير قيمة DATABASE_URL في ملف .env إلى مثل:
    postgresql+asyncpg://user:pass@host:5432/dbname
دون أي حاجة لتعديل هذا الملف.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import BigInteger, String, Integer, DateTime, Float, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from config import settings


class Base(DeclarativeBase):
    pass


class Subscriber(Base):
    """
    كل صف يمثّل محاولة اشتراك (فاتورة) واحدة. نبقي كل الفواتير (حتى الملغاة
    وغير المدفوعة) بدل حذفها، حتى تكون هناك سجلّية كاملة للمدفوعات.
    """

    __tablename__ = "subscribers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    invoice_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    plan_key: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    plan_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    amount: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # pending -> بانتظار الدفع | active -> مشترك نشط | expired -> انتهى | canceled -> ألغيت الفاتورة
    status: Mapped[str] = mapped_column(String(16), default="pending")
    start_date: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    end_date: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.utcnow)


engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def create_pending_invoice(
    telegram_user_id: int,
    invoice_id: str,
    plan_key: str,
    plan_name: str,
    amount: float,
) -> None:
    """يُستدعى فور إنشاء فاتورة ميسر، قبل أن يدفع المستخدم فعلياً."""
    async with async_session() as session:
        record = Subscriber(
            telegram_user_id=telegram_user_id,
            invoice_id=invoice_id,
            plan_key=plan_key,
            plan_name=plan_name,
            amount=amount,
            status="pending",
        )
        session.add(record)
        await session.commit()


async def activate_subscription_by_invoice(
    invoice_id: str,
    plan_days: int,
    phone_number: Optional[str] = None,
) -> Optional[Subscriber]:
    """
    تُستدعى من الـ Webhook بعد تأكيد نجاح الدفع من ميسر.
    تُرجع كائن المشترك بعد التفعيل، أو None إذا لم توجد فاتورة مطابقة
    (مثلاً إذا وصل Webhook مكرر أو لفاتورة غير معروفة لدينا).
    """
    async with async_session() as session:
        result = await session.execute(select(Subscriber).where(Subscriber.invoice_id == invoice_id))
        record = result.scalar_one_or_none()
        if record is None:
            return None

        now = dt.datetime.utcnow()
        record.status = "active"
        record.start_date = now
        record.end_date = now + dt.timedelta(days=plan_days)
        if phone_number:
            record.phone_number = phone_number

        await session.commit()
        await session.refresh(record)
        return record


async def is_user_active(telegram_user_id: int) -> bool:
    """
    يتحقق هل المستخدم مشترك ونشط الآن. يُستخدم في فلترة رسائل القروب.
    نأخذ آخر اشتراك نشط للمستخدم (وليس كل السجلات) لأن نفس المستخدم
    قد يكون اشترك أكثر من مرة عبر الزمن.
    """
    async with async_session() as session:
        result = await session.execute(
            select(Subscriber)
            .where(Subscriber.telegram_user_id == telegram_user_id, Subscriber.status == "active")
            .order_by(Subscriber.end_date.desc())
        )
        record = result.scalars().first()
        if record is None or record.end_date is None:
            return False
        return record.end_date >= dt.datetime.utcnow()


async def expire_outdated_subscriptions() -> list[int]:
    """
    مهمة دورية (Background Job): تبحث عن كل الاشتراكات النشطة التي
    انتهت مدتها وتغيّر حالتها إلى expired.
    ترجع قائمة بمعرفات المستخدمين الذين انتهى اشتراكهم للتو، حتى يمكن
    إخطارهم أو طردهم من القروب إن رغبت بذلك.
    """
    now = dt.datetime.utcnow()
    async with async_session() as session:
        result = await session.execute(
            select(Subscriber).where(Subscriber.status == "active", Subscriber.end_date < now)
        )
        expired_records = result.scalars().all()
        user_ids = [r.telegram_user_id for r in expired_records]

        if user_ids:
            await session.execute(
                update(Subscriber)
                .where(Subscriber.status == "active", Subscriber.end_date < now)
                .values(status="expired")
            )
            await session.commit()

        return user_ids


async def get_subscriber_by_invoice(invoice_id: str) -> Optional[Subscriber]:
    async with async_session() as session:
        result = await session.execute(select(Subscriber).where(Subscriber.invoice_id == invoice_id))
        return result.scalar_one_or_none()
