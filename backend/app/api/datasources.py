"""数据源管理接口：配置连接、浏览表、浏览字段、预览数据。"""
from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import DataSource, ResourcePermission, Staff
from ..schemas import DataSourceIn
from ..security import decrypt, encrypt, mask
from ..services import metadata

router = APIRouter()


def _to_dict(item: DataSource) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "db_type": item.db_type,
        "host": item.host,
        "port": item.port,
        "database": item.database,
        "username": item.username,
        "password": mask(decrypt(item.password_enc)),
        "file_path": item.file_path,
        "is_active": item.is_active,
        "is_public": item.is_public,
        "last_test_at": item.last_test_at,
        "last_test_ok": item.last_test_ok,
        "last_test_msg": item.last_test_msg,
        "detail": f"{item.host}:{item.port}/{item.database}" if item.db_type == "postgresql" else item.file_path,
    }


def _get(db: Session, data_source_id: int) -> DataSource:
    item = db.get(DataSource, data_source_id)
    if item is None:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return item


@router.get("/datasources")
def list_datasources(mobile: str = Query(""), db: Session = Depends(get_db)):
    query = db.query(DataSource)
    if mobile:
        caller = db.query(Staff).filter(Staff.mobile == mobile).first()
        if caller is not None and caller.role != "admin":
            permitted_ids = [
                r.resource_id
                for r in db.query(ResourcePermission).filter(
                    ResourcePermission.resource_type == "datasource",
                    ResourcePermission.mobile == mobile,
                ).all()
            ]
            conditions = [DataSource.is_public.is_(True)]
            if permitted_ids:
                conditions.append(DataSource.id.in_(permitted_ids))
            query = query.filter(or_(*conditions))
    return [_to_dict(item) for item in query.order_by(DataSource.id).all()]


@router.post("/datasources")
def create_datasource(payload: DataSourceIn, db: Session = Depends(get_db)):
    if db.query(DataSource).filter(DataSource.name == payload.name).first():
        raise HTTPException(status_code=400, detail="该名称已存在")
    item = DataSource(
        name=payload.name,
        db_type=payload.db_type,
        host=payload.host,
        port=payload.port,
        database=payload.database,
        username=payload.username,
        password_enc=encrypt(payload.password),
        file_path=payload.file_path,
        is_active=payload.is_active,
        is_public=payload.is_public,
    )
    db.add(item)
    db.commit()
    return {"id": item.id}


@router.put("/datasources/{data_source_id}")
def update_datasource(data_source_id: int, payload: DataSourceIn, db: Session = Depends(get_db)):
    item = _get(db, data_source_id)
    item.name = payload.name
    item.db_type = payload.db_type
    item.host = payload.host
    item.port = payload.port
    item.database = payload.database
    item.username = payload.username
    item.file_path = payload.file_path
    item.is_active = payload.is_active
    item.is_public = payload.is_public
    if payload.password and "*" not in payload.password:
        item.password_enc = encrypt(payload.password)
    db.commit()
    metadata.drop_engine(item)
    return {"ok": True}


@router.delete("/datasources/{data_source_id}")
def delete_datasource(data_source_id: int, db: Session = Depends(get_db)):
    item = _get(db, data_source_id)
    metadata.drop_engine(item)
    db.delete(item)
    db.commit()
    return {"ok": True}


@router.post("/datasources/{data_source_id}/test")
def test_datasource(data_source_id: int, db: Session = Depends(get_db)):
    item = _get(db, data_source_id)
    ok, message = metadata.test_connection(item)
    item.last_test_at = datetime.now()
    item.last_test_ok = ok
    item.last_test_msg = message
    db.commit()
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message}


@router.get("/datasources/{data_source_id}/tables")
def list_tables(data_source_id: int, keyword: str = Query(""), db: Session = Depends(get_db)):
    item = _get(db, data_source_id)
    try:
        tables = metadata.list_tables(item)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"读取表清单失败：{exc}") from exc
    if keyword:
        lowered = keyword.lower()
        tables = [
            t for t in tables
            if lowered in t["name"].lower() or lowered in (t.get("comment") or "").lower()
        ]
    return tables


@router.get("/datasources/{data_source_id}/columns")
def list_columns(data_source_id: int, table: str = Query(...), db: Session = Depends(get_db)):
    item = _get(db, data_source_id)
    try:
        return metadata.list_columns(item, table)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"读取字段失败：{exc}") from exc


@router.get("/datasources/{data_source_id}/preview")
def preview_table(
    data_source_id: int,
    table: str = Query(...),
    limit: int = Query(20),
    db: Session = Depends(get_db),
):
    item = _get(db, data_source_id)
    try:
        return metadata.preview_table(item, table, limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"预览失败：{exc}") from exc


@router.post("/datasources/{data_source_id}/refresh")
def refresh_metadata(data_source_id: int, db: Session = Depends(get_db)):
    item = _get(db, data_source_id)
    try:
        snapshot = metadata.build_metadata_snapshot(item)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"刷新元数据失败：{exc}") from exc
    item.meta_json = json.dumps(snapshot, ensure_ascii=False)
    db.commit()
    return {"ok": True, "table_count": len(snapshot.get("tables", []))}


@router.get("/datasources/{data_source_id}/schema")
def get_schema(data_source_id: int, db: Session = Depends(get_db)):
    item = _get(db, data_source_id)
    snapshot = metadata.load_snapshot(item)
    if not snapshot.get("tables"):
        try:
            snapshot = metadata.build_metadata_snapshot(item)
            item.meta_json = json.dumps(snapshot, ensure_ascii=False)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"读取结构失败：{exc}") from exc
    return snapshot
