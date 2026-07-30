"""Application configuration using Pydantic BaseSettings."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Application ---
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    log_level: str = "info"

    # --- NVIDIA NIM ---
    nvidia_api_key: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_default_model: str = "qwen/qwen3.5-122b-a10b"   # Reliable on free tier
    nvidia_fast_model: str = "nvidia/nemotron-3-super-120b-a12b"  # Fast MoE
    nvidia_heavy_model: str = "qwen/qwen3.5-397b-a17b"     # Heavy (may timeout on free tier)
    nvidia_embed_model: str = "nvidia/llama-nemotron-embed-1b-v2"

    # --- Gemini (Fallback) ---
    gemini_api_key: str = ""
    gemini_default_model: str = "gemini-2.5-flash"
    gemini_pro_model: str = "gemini-2.5-pro"

    # --- GitHub ---
    github_token: str = ""
    github_webhook_secret: str = ""

    # --- Database ---
    database_url: str = "sqlite+aiosqlite:///./agentic_coder.db"

    # --- Docker Sandbox ---
    sandbox_image: str = "agentic-coder-sandbox:latest"
    sandbox_timeout: int = 300
    sandbox_memory_limit: str = "512m"
    sandbox_cpu_limit: float = 1.0
    # Allow network egress from inside the sandbox container. Default True
    # so cloned projects can run `pip install` / `npm install` and their
    # tests actually work. Flip to False for maximum isolation - but most
    # real repositories will regress because their deps can't be installed.
    sandbox_allow_network: bool = True

    # --- Workspace ---
    workspace_dir: str = "./workspaces"

    # --- Best-of-N (Coder inference-time compute) ---
    # K=1 disables Best-of-N (single LLM call, apply to main workspace).
    # K>=2 generates K candidate diffs in parallel at different temperatures,
    # applies each to a fresh git worktree, runs tests, and keeps the
    # candidate with the fewest NEW test failures. Grounded in the DeepSWE
    # / ACECoder line of work on execution-verified rewards.
    #
    # Cost scales linearly with K: default K=3 means 3x LLM calls + 3x test
    # runs per Coder step. On rate-limited free tiers you may want K=2 or
    # K=1 to avoid 429s.
    coder_bon_k: int = 3
    # Comma-separated temperatures. Padded with the last value if shorter
    # than K; truncated if longer.
    coder_bon_temperatures_csv: str = "0.1,0.5,0.9"
    coder_bon_max_parallel: int = 3
    coder_bon_timeout_seconds: int = 180

    @property
    def workspace_path(self) -> Path:
        path = Path(self.workspace_dir).resolve()  # Always absolute
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def has_nvidia(self) -> bool:
        return bool(self.nvidia_api_key)

    @property
    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def has_github(self) -> bool:
        return bool(self.github_token)


# Global singleton — import this everywhere
settings = Settings()
