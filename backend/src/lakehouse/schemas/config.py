from pydantic import BaseModel, Field


class ModelosConfig(BaseModel):
    llm: str = Field(...)
    embedding: str = Field(...)


class ConfigResponse(BaseModel):
    ambiente: str = Field(default="desconocido")
    docker: bool = Field(default=False)
    version: str = Field(...)
    modelos: ModelosConfig = Field(...)
