from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from app.db.base import NAMING_CONVENTION


class IdentityBase(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
