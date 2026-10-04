"""路径与运行限制放在这里，避免每个文件各写一份。"""

import os
from dataclasses import dataclass
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent / "data" / "hangzhou_demo.json"
PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ModelConfig:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: int = 45

    @classmethod
    def from_env(cls) -> "ModelConfig":
        api_key = os.getenv("LLM_API_KEY", "").strip()
        if not api_key or api_key == "replace_with_your_key":
            raise ValueError("尚未设置 LLM_API_KEY。先运行 --demo，或在终端配置模型密钥。")
        return cls(
            api_key=api_key,
            base_url=os.getenv("LLM_BASE_URL", "https://api.deepseek.com").rstrip("/"),
            model=os.getenv("LLM_MODEL", "deepseek-flash"),
        )
