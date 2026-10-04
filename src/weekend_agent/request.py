"""表单提供的权威约束。模型不能通过修改工具参数放宽这些约束。"""

from dataclasses import asdict, dataclass, field
from datetime import date

from .tools import to_minutes, validate_arguments


@dataclass
class TripRequest:
    city: str = "杭州"
    travel_date: str = "2026-11-21"
    budget_per_person: float = 200
    group_size: int = 2
    tags: list[str] = field(default_factory=lambda: ["拍照", "美食"])
    indoor: bool | None = None
    rain: bool = False
    start_time: str = "10:00"
    end_time: str = "18:00"
    include_meal: bool = True

    @classmethod
    def from_dict(cls, values: dict) -> "TripRequest":
        properties = {
            "city": {"type": "string"}, "travel_date": {"type": "string"},
            "budget_per_person": {"type": "number", "minimum": 0, "maximum": 10000},
            "group_size": {"type": "integer", "minimum": 1, "maximum": 20},
            "tags": {"type": "array", "maxItems": 6, "items": {"type": "string"}},
            "indoor": {"type": ["boolean", "null"]}, "rain": {"type": "boolean"},
            "start_time": {"type": "string"}, "end_time": {"type": "string"},
            "include_meal": {"type": "boolean"},
        }
        validate_arguments(values, {"type": "object", "properties": properties,
                                   "additionalProperties": False})
        merged = asdict(cls())
        merged.update(values)
        request = cls(**merged)
        if request.city != "杭州":
            raise ValueError("当前教学地点库只支持杭州")
        date.fromisoformat(request.travel_date)
        if to_minutes(request.start_time) >= to_minutes(request.end_time):
            raise ValueError("开始时间必须早于结束时间，目前只支持同一天")
        if any(not tag.strip() or len(tag) > 30 for tag in request.tags):
            raise ValueError("兴趣标签必须是 1–30 个字符")
        if request.rain and request.indoor is False:
            raise ValueError("模拟雨天与仅户外要求冲突，请调整其中一个条件")
        return request

    def to_dict(self) -> dict:
        return asdict(self)

    def check_arguments(self, stops: list[dict]) -> dict:
        return {"stops": stops, "budget_per_person": self.budget_per_person,
                "group_size": self.group_size, "start_time": self.start_time,
                "end_time": self.end_time}
