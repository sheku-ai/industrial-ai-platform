import uuid
from typing import TypeVar

from sqlalchemy.orm import Session

from app.repositories.base import Repository

ModelT = TypeVar("ModelT")


class CRUDService[ModelT]:
    def __init__(self, repository: Repository[ModelT]) -> None:
        self.repository = repository

    def list(self, db: Session, skip: int = 0, limit: int = 100) -> list[ModelT]:
        return self.repository.list(db, skip=skip, limit=limit)

    def get(self, db: Session, item_id: uuid.UUID) -> ModelT | None:
        return self.repository.get(db, item_id)

    def create(self, db: Session, data: dict) -> ModelT:
        return self.repository.create(db, data)

    def update(self, db: Session, item: ModelT, data: dict) -> ModelT:
        clean_data = {key: value for key, value in data.items() if value is not None}
        return self.repository.update(db, item, clean_data)

    def delete(self, db: Session, item: ModelT) -> None:
        self.repository.delete(db, item)
