"""路径与运行限制放在这里，避免每个文件各写一份。"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

DATA_FILE = Path(__file__).resolve().parent / "data" / "hangzhou_demo.json"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_KEYS = {"LLM_API_KEY", "DEEPSEEK_API_KEY", "LLM_BASE_URL", "LLM_MODEL",
            "LLM_TIMEOUT_SECONDS", "LLM_MAX_TOKENS", "LLM_MAX_RETRIES",
            # 可选的向量化配置：不填就自动降级回词法检索（DeepSeek 没有 embedding 接口）。
            "EMBED_BASE_URL", "EMBED_API_KEY", "EMBED_MODEL", "EMBED_TIMEOUT_SECONDS"}


def read_env_file(path: Path) -> dict[str, str]:
    """读取简单 KEY=VALUE 文件，不执行 shell、不展开变量、不修改进程环境。"""
    if not path.exists():
        return {}
    values = {}
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or key not in ENV_KEYS:
            raise ValueError(f".env 第 {line_number} 行格式或配置名不正确，请对照 .env.example")
        if value[:1] in ("'", '"'):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f".env 第 {line_number} 行引号未闭合")
            value = value[1:-1]
        values[key] = value
    return values


@dataclass(frozen=True)
class ModelConfig:
    api_key: str = field(repr=False)
    base_url: str
    model: str
    timeout_seconds: int = 60
    max_tokens: int = 4096
    max_retries: int = 1

    def __post_init__(self):
        address = urlsplit(self.base_url)
        if (address.scheme != "https" or not address.hostname or address.username
                or address.password or address.query or address.fragment):
            raise ValueError("LLM_BASE_URL 必须是没有凭据、查询参数或片段的 HTTPS 基础地址")
        if address.path.rstrip("/").endswith("/chat/completions"):
            raise ValueError("LLM_BASE_URL 只填基础地址，不要附加 /chat/completions")
        if not self.model.strip() or any(c.isspace() for c in self.model):
            raise ValueError("LLM_MODEL 不能为空或包含空白；官方 Flash 使用 deepseek-flash")
        for name, value, low, high in (("LLM_TIMEOUT_SECONDS", self.timeout_seconds, 5, 300),
                                       ("LLM_MAX_TOKENS", self.max_tokens, 64, 16384),
                                       ("LLM_MAX_RETRIES", self.max_retries, 0, 2)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name} 必须是 {low}–{high} 的整数（本项目限制）")

    def public_info(self) -> dict:
        return {"base_url": self.base_url, "model": self.model,
                "key_configured": bool(self.api_key), "timeout_seconds": self.timeout_seconds,
                "max_tokens": self.max_tokens, "max_retries": self.max_retries,
                "thinking": "disabled" if urlsplit(self.base_url).hostname == "api.deepseek.com" else "provider_default"}

    @classmethod
    def from_env(cls, env_file: Path | None = None, environ: dict | None = None,
                 require_key: bool = True) -> "ModelConfig":
        file_values = read_env_file(env_file if env_file is not None else PROJECT_ROOT / ".env")
        environment = os.environ if environ is None else environ
        values = {**file_values, **{k: v for k, v in environment.items() if k in ENV_KEYS}}
        # 两种密钥变量名都支持；进程环境优先于文件，即使它使用另一种变量名。
        api_key = next((source[key].strip() for source in (environment, file_values)
                        for key in ("LLM_API_KEY", "DEEPSEEK_API_KEY") if key in source), "")
        if not api_key or api_key == "replace_with_your_key":
            api_key = ""
            if require_key:
                raise ValueError("尚未设置 LLM_API_KEY。请在项目根目录 .env 填写密钥，或设置环境变量。")
        def integer(key, default):
            try:
                return int(values.get(key, default))
            except (TypeError, ValueError):
                raise ValueError(f"{key} 必须是整数") from None
        return cls(
            api_key=api_key,
            base_url=values.get("LLM_BASE_URL", "https://api.deepseek.com").strip().rstrip("/"),
            model=values.get("LLM_MODEL", "deepseek-flash").strip(),
            timeout_seconds=integer("LLM_TIMEOUT_SECONDS", 60),
            max_tokens=integer("LLM_MAX_TOKENS", 4096),
            max_retries=integer("LLM_MAX_RETRIES", 1),
        )


@dataclass(frozen=True)
class EmbeddingConfig:
    """可选的向量化配置。

    与 ModelConfig 的关键差别：**缺失不算错误**。DeepSeek 没有 embedding 接口，
    因此没有这份配置是常态，调用方应当据此降级回词法检索，而不是报错。
    """

    api_key: str = field(repr=False)
    base_url: str
    model: str
    timeout_seconds: int = 60

    def __post_init__(self):
        address = urlsplit(self.base_url)
        if (address.scheme != "https" or not address.hostname or address.username
                or address.password or address.query or address.fragment):
            raise ValueError("EMBED_BASE_URL 必须是没有凭据、查询参数或片段的 HTTPS 基础地址")
        if not self.model.strip() or any(c.isspace() for c in self.model):
            raise ValueError("EMBED_MODEL 不能为空或包含空白")
        if type(self.timeout_seconds) is not int or not 5 <= self.timeout_seconds <= 300:
            raise ValueError("EMBED_TIMEOUT_SECONDS 必须是 5–300 的整数")

    def public_info(self) -> dict:
        return {"base_url": self.base_url, "model": self.model,
                "key_configured": bool(self.api_key)}

    @classmethod
    def from_env(cls, env_file: Path | None = None,
                 environ: dict | None = None) -> "EmbeddingConfig | None":
        """配置齐全时返回配置对象；任何一项缺失都返回 None（表示降级）。"""
        file_values = read_env_file(env_file if env_file is not None else PROJECT_ROOT / ".env")
        environment = os.environ if environ is None else environ
        values = {**file_values, **{k: v for k, v in environment.items() if k in ENV_KEYS}}
        api_key = values.get("EMBED_API_KEY", "").strip()
        base_url = values.get("EMBED_BASE_URL", "").strip().rstrip("/")
        model = values.get("EMBED_MODEL", "").strip()
        if not api_key or api_key == "replace_with_your_key" or not base_url or not model:
            return None
        try:
            timeout = int(values.get("EMBED_TIMEOUT_SECONDS", 60))
        except (TypeError, ValueError):
            raise ValueError("EMBED_TIMEOUT_SECONDS 必须是整数") from None
        return cls(api_key=api_key, base_url=base_url, model=model, timeout_seconds=timeout)
