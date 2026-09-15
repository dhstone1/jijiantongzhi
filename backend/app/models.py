"""系统自身的数据库模型。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class DataSource(Base):
    """公共数据库连接（只读）。"""

    __tablename__ = "data_source"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    db_type: Mapped[str] = mapped_column(String(16), default="postgresql")
    host: Mapped[str] = mapped_column(String(128), default="")
    port: Mapped[int] = mapped_column(Integer, default=5432)
    database: Mapped[str] = mapped_column(String(128), default="")
    username: Mapped[str] = mapped_column(String(128), default="")
    password_enc: Mapped[str] = mapped_column(Text, default="")
    file_path: Mapped[str] = mapped_column(String(512), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_msg: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Region(Base):
    """归属地字典：标准名 + 别名。"""

    __tablename__ = "region"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    standard_name: Mapped[str] = mapped_column(String(64), unique=True)
    short_name: Mapped[str] = mapped_column(String(64), default="")
    parent: Mapped[str] = mapped_column(String(64), default="")
    level: Mapped[str] = mapped_column(String(16), default="区县")
    aliases_json: Mapped[str] = mapped_column(Text, default="[]")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Staff(Base):
    """人员信息表：手机号识别身份，归属地决定数据可见范围。"""

    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    mobile: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    region_name: Mapped[str] = mapped_column(String(64), default="", index=True)
    role: Mapped[str] = mapped_column(String(16), default="user")
    position: Mapped[str] = mapped_column(String(64), default="")
    receive_alert: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class DingTalkBot(Base):
    """钉钉群机器人。"""

    __tablename__ = "dingtalk_bot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    # 这个群归哪个地市管。省级管理员能看全部，地市管理员只看本地的
    region_name: Mapped[str] = mapped_column(String(64), default="", index=True)
    webhook_enc: Mapped[str] = mapped_column(Text, default="")
    secret_enc: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_msg: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class PushRule(Base):
    """一条推送规则。"""

    __tablename__ = "push_rule"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    created_by: Mapped[str] = mapped_column(String(64), default="")
    region_name: Mapped[str] = mapped_column(String(64), default="", index=True)

    data_source_id: Mapped[int | None] = mapped_column(ForeignKey("data_source.id"), nullable=True)
    table_name: Mapped[str] = mapped_column(String(128), default="")
    query_json: Mapped[str] = mapped_column(Text, default="{}")
    region_field: Mapped[str] = mapped_column(String(128), default="")
    time_field: Mapped[str] = mapped_column(String(128), default="")

    template: Mapped[str] = mapped_column(Text, default="")
    msg_type: Mapped[str] = mapped_column(String(16), default="markdown")
    bot_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    at_json: Mapped[str] = mapped_column(Text, default="{}")
    # 是否把报表渲染成图片发送，以及图片标题、行数上限等
    image_json: Mapped[str] = mapped_column(Text, default="{}")
    # ActionCard 卡片设置：{title, btn_title, btn_url, btn_orientation}
    card_json: Mapped[str] = mapped_column(Text, default="{}")

    schedule_type: Mapped[str] = mapped_column(String(16), default="manual")
    schedule_json: Mapped[str] = mapped_column(Text, default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    sample_json: Mapped[str] = mapped_column(Text, default="{}")

    # 是否同时发送 Excel 数据文件
    send_excel: Mapped[bool] = mapped_column(Boolean, default=False)

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 上次"真正发送成功"的时间，用于触发冷却；跳过的执行不会覆盖它
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(16), default="")
    last_error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class SendLog(Base):
    """发送记录。"""

    __tablename__ = "send_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("push_rule.id"), nullable=True, index=True)
    rule_name: Mapped[str] = mapped_column(String(128), default="")
    bot_names: Mapped[str] = mapped_column(String(256), default="")
    trigger: Mapped[str] = mapped_column(String(16), default="auto")
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    message_text: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class AppSetting(Base):
    """系统级键值设置（图片服务地址、图片保留天数等）。"""

    __tablename__ = "app_setting"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class ResourcePermission(Base):
    """资源可见权限：记录数据源/钉钉群对哪些手机号可见。"""

    __tablename__ = "resource_permission"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resource_type: Mapped[str] = mapped_column(String(32), index=True)  # "datasource" 或 "dingtalk_bot"
    resource_id: Mapped[int] = mapped_column(Integer, index=True)
    mobile: Mapped[str] = mapped_column(String(20), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
