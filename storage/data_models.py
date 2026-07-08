from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class MarketDataRecord(BaseModel):
    symbol: str
    name: str
    timestamp: datetime
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None
    amount: Optional[float] = None
    turnover_rate: Optional[float] = None
    volume_ratio: Optional[float] = None
    change_pct: Optional[float] = None
    inner_volume: Optional[float] = None
    outer_volume: Optional[float] = None
    data_type: str = "realtime"


class StockInfo(BaseModel):
    symbol: str
    name: str
    industry: Optional[str] = None
    market: str = "A股"
    list_date: Optional[str] = None


class VolumeAnalysisRecord(BaseModel):
    symbol: str
    date: str
    avg_volume_5d: Optional[float] = None
    avg_volume_10d: Optional[float] = None
    volume_breakout: Optional[bool] = None
    volume_ratio: Optional[float] = None
    turnover_rate: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.now)
