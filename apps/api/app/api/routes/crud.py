import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.base import CRUDService

MutationGuard = Callable[[str, Any | None, dict[str, Any] | None, Session], None]


def register_crud_routes(
    router: APIRouter,
    path: str,
    resource_name: str,
    service: CRUDService,
    create_schema: type[BaseModel],
    update_schema: type[BaseModel],
    read_schema: type[BaseModel],
    mutation_guard: MutationGuard | None = None,
) -> None:
    def not_found() -> HTTPException:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{resource_name} not found")

    def list_items(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)) -> list[Any]:
        return service.list(db, skip=skip, limit=limit)

    def create_item(payload: create_schema, db: Session = Depends(get_db)) -> Any:  # type: ignore[valid-type]
        data = payload.model_dump()
        if mutation_guard is not None:
            mutation_guard("create", None, data, db)
        return service.create(db, data)

    def get_item(item_id: uuid.UUID, db: Session = Depends(get_db)) -> Any:
        item = service.get(db, item_id)
        if item is None:
            raise not_found()
        return item

    def update_item(item_id: uuid.UUID, payload: update_schema, db: Session = Depends(get_db)) -> Any:  # type: ignore[valid-type]
        item = service.get(db, item_id)
        if item is None:
            raise not_found()
        data = payload.model_dump(exclude_unset=True)
        if mutation_guard is not None:
            mutation_guard("update", item, data, db)
        return service.update(db, item, data)

    def delete_item(item_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
        item = service.get(db, item_id)
        if item is None:
            raise not_found()
        if mutation_guard is not None:
            mutation_guard("delete", item, None, db)
        service.delete(db, item)

    router.add_api_route(path, list_items, methods=["GET"], response_model=list[read_schema])
    router.add_api_route(
        path, create_item, methods=["POST"], response_model=read_schema, status_code=status.HTTP_201_CREATED
    )
    router.add_api_route(f"{path}/{{item_id}}", get_item, methods=["GET"], response_model=read_schema)
    router.add_api_route(f"{path}/{{item_id}}", update_item, methods=["PATCH"], response_model=read_schema)
    router.add_api_route(f"{path}/{{item_id}}", delete_item, methods=["DELETE"], status_code=status.HTTP_204_NO_CONTENT)
