"""接口出入参模型。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    mobile: str = Field(..., min_length=4, max_length=20)


class DataSourceIn(BaseModel):
    name: str
    db_type: str = "postgresql"
    host: str = ""
    port: int = 5432
    database: str = ""
    username: str = ""
    password: str = ""
    file_path: str = ""
    is_active: bool = True
    is_public: bool = False


class ImportConfigIn(BaseModel):
    directory: str
    scan_time: str = "08:00"
    # 文件名格式模板：{前缀} 代表前缀，日期支持 {YYYYMMDD}/{YYYYMMDDHH}/{YYYYMMDDHHMM}/{YYYYMM}
    pattern: str = "{前缀}_{YYYYMMDD}.txt"
    # 导入成功后是否把原件改名为「已扫描_原文件名」
    rename: bool = True


class ImportRunIn(BaseModel):
    prefix: str | None = None
    force: bool = False


class RegionIn(BaseModel):
    standard_name: str
    short_name: str = ""
    parent: str = "邢台市"
    level: str = "区县"
    aliases: list[str] = Field(default_factory=list)
    sort_order: int = 0
    is_active: bool = True


class StaffIn(BaseModel):
    name: str
    mobile: str
    region_name: str = ""
    role: str = "user"
    position: str = ""
    receive_alert: bool = True


class BotIn(BaseModel):
    name: str
    # 这个群归哪个地市管；省级管理员留空表示全省共用
    region_name: str = ""
    webhook: str = ""
    secret: str = ""
    is_active: bool = True


class RuleIn(BaseModel):
    name: str
    region_name: str = ""
    data_source_id: int | None = None
    table_name: str = ""
    query: dict[str, Any] = Field(default_factory=dict)
    region_field: str = ""
    time_field: str = ""
    template: str = ""
    msg_type: str = "markdown"
    bot_ids: list[int] = Field(default_factory=list)
    at_config: dict[str, Any] = Field(default_factory=dict)
    # 图片推送：{enabled, title, subtitle, max_rows, with_text, footer}
    image: dict[str, Any] = Field(default_factory=dict)
    # ActionCard 卡片：{title, btn_title, btn_url, btn_orientation}
    card: dict[str, Any] = Field(default_factory=dict)
    schedule_type: str = "manual"
    schedule: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    sample: dict[str, Any] = Field(default_factory=dict)
    send_excel: bool = False


class PreviewIn(BaseModel):
    data_source_id: int
    query: dict[str, Any] = Field(default_factory=dict)
    region_field: str = ""
    region_name: str = ""
    template: str = ""
    # 纯文本消息不做 markdown 渲染，表格样式要跟着一起降级
    msg_type: str = "markdown"
    limit: int = 50
    image: dict[str, Any] = Field(default_factory=dict)
    send_excel: bool = False


class SettingsIn(BaseModel):
    public_base_url: str | None = None
    image_retention_days: int | None = None
    image_upload_mode: str | None = None
    beeimg_url: str | None = None
    beeimg_storage_id: str | None = None
    beeimg_token: str | None = None
    beeimg_expire_days: int | None = None
    beeimg_is_public: bool | None = None
    beeimg_remove_exif: bool | None = None


class PermissionGrantIn(BaseModel):
    resource_type: str
    resource_id: int
    mobiles: list[str] = Field(default_factory=list)
