from lakehouse.schemas.silver import DLQRejectRecord


class DLQ:
    def __init__(self) -> None:
        self._records: list[DLQRejectRecord] = []

    def add(self, source_record_id: str, rejection_reason: str, raw_data: str) -> None:
        record = DLQRejectRecord(
            source_record_id=source_record_id,
            rejection_reason=rejection_reason,
            raw_data=raw_data,
        )
        self._records.append(record)

    def count(self) -> int:
        return len(self._records)

    def get_records(self) -> list[DLQRejectRecord]:
        return list(self._records)
