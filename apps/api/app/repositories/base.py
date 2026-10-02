import uuid
from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

ModelT = TypeVar("ModelT")


class Repository[ModelT]:
    def __init__(self, model: type[ModelT]) -> None:
        self.model = model

    def list(self, db: Session, skip: int = 0, limit: int = 100) -> list[ModelT]:
        statement = select(self.model).offset(skip).limit(limit)
        return list(db.scalars(statement).all())

    def get(self, db: Session, item_id: uuid.UUID) -> ModelT | None:
        return db.get(self.model, item_id)

    def create(self, db: Session, data: dict) -> ModelT:
        item = self.model(**data)
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    def update(self, db: Session, item: ModelT, data: dict) -> ModelT:
        for key, value in data.items():
            setattr(item, key, value)
        db.add(item)
        db.commit()
        db.refresh(item)
        return item

    def delete(self, db: Session, item: ModelT) -> None:
        db.delete(item)
        db.commit()
