from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, model_validator


class TimeFilterOut(BaseModel):
    requiere_filtro_tiempo: bool
    fecha_inicio: str | None = None
    fecha_fin: str | None = None
    texto_busqueda_semantica: str

    @model_validator(mode="after")
    def validar_coherencia(self) -> Self:
        if self.requiere_filtro_tiempo:
            if not self.fecha_inicio or not self.fecha_fin:
                raise ValueError(
                    "fecha_inicio y fecha_fin requeridos cuando requiere_filtro_tiempo=true"
                )
            for f in [self.fecha_inicio, self.fecha_fin]:
                datetime.strptime(f, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            if self.fecha_inicio > self.fecha_fin:
                raise ValueError("fecha_inicio debe ser menor o igual que fecha_fin")
        return self


class TimeParserResult(BaseModel):
    filter_out: TimeFilterOut
    fallback_ocurrido: bool
    raw_llm_response: str
