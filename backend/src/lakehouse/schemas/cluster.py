from pydantic import BaseModel, Field


class ClusterInfo(BaseModel):
    cluster_id: int
    label: str | None = None
    chunk_count: int = 0
    avg_membership: float = 0.0
    sample_chunk_keys: list[str] = Field(default_factory=list)


class ClusterPoint(BaseModel):
    chunk_key: str
    cluster_id: int
    pertenencia: float
    x: float
    y: float
    z: float


class ClusterDataResponse(BaseModel):
    run_id: str
    status: str
    cluster_count: int
    noise_count: int
    clusters: list[ClusterInfo] = Field(default_factory=list)
    points: list[ClusterPoint] = Field(default_factory=list)
