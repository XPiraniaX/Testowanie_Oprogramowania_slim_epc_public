import math

from pydantic import BaseModel, ConfigDict, Field, model_validator

class BearerConfig(BaseModel):
    bearer_id: int = Field(ge=1, le=9)
    protocol: str | None = Field(default=None, pattern="^(tcp|udp)$")
    target_bps: int | None = None  # bits per second
    active: bool = False


class ThroughputStats(BaseModel):
    bearer_id: int
    ue_id: int
    bytes_tx: int = 0  # uplink (MS->SS)
    bytes_rx: int = 0  # downlink (SS->MS)
    start_ts: float | None = None
    last_update_ts: float | None = None
    protocol: str | None = None
    target_bps: int | None = None


class UEState(BaseModel):
    ue_id: int = Field(ge=1, le=100)
    bearers: dict[int, BearerConfig] = {}
    stats: dict[int, ThroughputStats] = {}

    @model_validator(mode="before")
    def init_defaults(cls, values):
        if values.get("bearers") is None:
            values["bearers"] = {}
        if values.get("stats") is None:
            values["stats"] = {}
        return values


# POPRAWIONE
# Mimo że pydantic powinien konertować np string na int, dodano flagę strict
class AttachUERequest(BaseModel):
    model_config = ConfigDict(strict=True)

    ue_id: int = Field(ge=1, le=100)

# POPRAWIONE
# Mimo że pydantic powinien konertować np string na int, dodano flagę strict
class AddBearerRequest(BaseModel):
    model_config = ConfigDict(strict=True)

    bearer_id: int = Field(ge=1, le=9)

# POPRAWIONE
# Mbps, kbps, bps były zwykłymi float, bez dolnej granicy, wchodziły 0,
# ujemne, bardzo małe i potencjalnie NaN/inf.
# Popraiono validator
class StartTrafficRequest(BaseModel):
    protocol: str = Field(pattern="^(tcp|udp)$")
    Mbps: float | None = Field(default=None, gt=0)
    kbps: float | None = Field(default=None, gt=0)
    bps: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def exactly_one_throughput(self):
        provided = [v for v in [self.Mbps, self.kbps, self.bps] if v is not None]

        if len(provided) != 1:
            raise ValueError("Provide exactly one throughput value (Mbps, kbps, or bps)")

        if not math.isfinite(provided[0]):
            raise ValueError("Throughput value must be finite")

        if self.target_bps() <= 0:
            raise ValueError("Throughput value is too small after conversion to bps")

        return self

    def target_bps(self) -> int:
        if self.Mbps is not None:
            return int(self.Mbps * 1_000_000)
        if self.kbps is not None:
            return int(self.kbps * 1_000)
        return int(self.bps)


# Response Schemas
class StatusResponse(BaseModel):
    status: str


class AttachResponse(StatusResponse):
    ue_id: int


class DetachResponse(StatusResponse):
    ue_id: int


class BearerAddResponse(StatusResponse):
    ue_id: int
    bearer_id: int


class BearerDeleteResponse(StatusResponse):
    ue_id: int
    bearer_id: int


class TrafficStartResponse(StatusResponse):
    ue_id: int
    bearer_id: int
    target_bps: int


class TrafficStopResponse(StatusResponse):
    ue_id: int
    bearer_id: int


class TrafficStatsResponse(BaseModel):
    ue_id: int
    bearer_id: int
    protocol: str | None = None
    target_bps: int | None = None
    tx_bps: int
    rx_bps: int
    duration: float


class UEDisplayResponse(UEState):
    pass


class UEListResponse(BaseModel):
    ues: list[int]

# POPRAWIONE
# teraz zapisuje tx i rx a nie tylko tx
class AggregatedStatsResponse(BaseModel):
    scope: str  # 'all' or f'ue:{id}'
    ue_count: int
    bearer_count: int
    total_tx_bps: int
    total_rx_bps: int
    details: dict[str, dict[str, dict[str, int]]] | None = None
