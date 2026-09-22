"""数据文件导入接口：配置、扫描、导入、导入记录。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import FileImportLog
from ..schemas import ImportConfigIn, ImportRunIn
from ..services import file_import, scheduler

router = APIRouter()


@router.get("/imports/config")
def get_import_config(db: Session = Depends(get_db)) -> dict:
    return file_import.get_config(db)


@router.put("/imports/config")
def update_import_config(payload: ImportConfigIn, db: Session = Depends(get_db)) -> dict:
    try:
        file_import.save_config(
            db,
            payload.directory,
            payload.scan_time,
            pattern=payload.pattern,
            rename=payload.rename,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    scheduler.sync_import_job()
    return {"ok": True}


@router.post("/imports/scan")
def scan_imports(db: Session = Depends(get_db)) -> dict:
    cfg = file_import.get_config(db)
    try:
        types = file_import.scan_status(db, cfg["directory"], cfg["pattern"])
    except Exception as exc:  # noqa: BLE001 - 把真实错误回显给管理员
        raise HTTPException(status_code=400, detail=f"扫描失败：{exc}") from exc
    return {"directory": cfg["directory"], "types": types}


@router.post("/imports/import")
def run_imports(payload: ImportRunIn, db: Session = Depends(get_db)) -> dict:
    cfg = file_import.get_config(db)
    try:
        results = file_import.run_imports(
            db,
            cfg["directory"],
            pattern=cfg["pattern"],
            rename=cfg["rename"],
            prefix=payload.prefix,
            force=payload.force,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"导入失败：{exc}") from exc
    if payload.prefix and not results:
        raise HTTPException(status_code=404, detail=f"目录中未找到前缀「{payload.prefix}」的日期文件")
    return {"results": results}


@router.get("/imports/logs")
def list_import_logs(
    prefix: str = Query(""),
    limit: int = Query(100),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = db.query(FileImportLog)
    if prefix:
        query = query.filter(FileImportLog.prefix == prefix)
    logs = query.order_by(FileImportLog.id.desc()).limit(max(1, min(int(limit), 500))).all()
    return [
        {
            "id": item.id,
            "prefix": item.prefix,
            "file_name": item.file_name,
            "file_date": item.file_date,
            "status": item.status,
            "row_count": item.row_count,
            "duration_ms": item.duration_ms,
            "error": item.error,
            "created_at": item.created_at.strftime("%Y-%m-%d %H:%M:%S") if item.created_at else "",
        }
        for item in logs
    ]