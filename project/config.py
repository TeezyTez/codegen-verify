import os
import shutil
from pathlib import Path

"""
Pipeline 配置文件。

敏感信息不要写进代码里，运行前通过环境变量设置：
    export DEEPSEEK_API_KEY="..."
    export OPENAI_API_KEY="..."
"""

PROJECT_DIR = Path(__file__).resolve().parents[1]


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(PROJECT_DIR / ".env")

# ===== API Keys =====
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ===== 模型配置 =====
DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek").strip().lower()
SPEC_PROVIDER = os.getenv("SPEC_PROVIDER", DEFAULT_PROVIDER).strip().lower()
CODE_PROVIDER = os.getenv("CODE_PROVIDER", DEFAULT_PROVIDER).strip().lower()
REPAIR_PROVIDER = os.getenv("REPAIR_PROVIDER", CODE_PROVIDER).strip().lower()
REQUIREMENT_PROVIDER = os.getenv("REQUIREMENT_PROVIDER", SPEC_PROVIDER).strip().lower()
PLANNER_PROVIDER = os.getenv("PLANNER_PROVIDER", CODE_PROVIDER).strip().lower()
DIAGNOSIS_PROVIDER = os.getenv("DIAGNOSIS_PROVIDER", REPAIR_PROVIDER).strip().lower()
SPEC_MODEL = os.getenv(
    "SPEC_MODEL",
    "deepseek-v4-pro" if SPEC_PROVIDER == "deepseek" else "gpt-4.1-2025-04-14",
)
CODE_MODEL = os.getenv(
    "CODE_MODEL",
    "deepseek-v4-pro" if CODE_PROVIDER == "deepseek" else "gpt-4.1-2025-04-14",
)
REPAIR_MODEL = os.getenv("REPAIR_MODEL", CODE_MODEL)
REQUIREMENT_MODEL = os.getenv("REQUIREMENT_MODEL", SPEC_MODEL)
PLANNER_MODEL = os.getenv("PLANNER_MODEL", CODE_MODEL)
DIAGNOSIS_MODEL = os.getenv("DIAGNOSIS_MODEL", REPAIR_MODEL)
CRITIC_PROVIDER = os.getenv("CRITIC_PROVIDER", "deepseek").strip().lower()
CRITIC_MODEL = os.getenv(
    "CRITIC_MODEL",
    "deepseek-v4-pro" if CRITIC_PROVIDER == "deepseek" else "gpt-4.1-2025-04-14",
)
CRITIC_PROBE_PROVIDER = os.getenv("CRITIC_PROBE_PROVIDER", CRITIC_PROVIDER).strip().lower()
CRITIC_PROBE_MODEL = os.getenv("CRITIC_PROBE_MODEL", CRITIC_MODEL)

# ===== Agent 配置 =====
MAX_REPAIR_ROUNDS = int(os.getenv("MAX_REPAIR_ROUNDS", "3"))
MAX_SPEC_REVISIONS = int(os.getenv("MAX_SPEC_REVISIONS", "1"))
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))
LLM_RETRIES = int(os.getenv("LLM_RETRIES", "2"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "0"))
EVALUATION_MODE = os.getenv("EVALUATION_MODE", "strict").strip().lower()
MAX_SPEC_REPAIR_ROUNDS = int(os.getenv("MAX_SPEC_REPAIR_ROUNDS", "1"))
ENABLE_STRUCTURED_REQUIREMENTS = os.getenv("ENABLE_STRUCTURED_REQUIREMENTS", "1") != "0"
ENABLE_SPEC_PLANNING = os.getenv("ENABLE_SPEC_PLANNING", "1") != "0"
ENABLE_FAILURE_DIAGNOSIS = os.getenv("ENABLE_FAILURE_DIAGNOSIS", "1") != "0"
ENABLE_MUTATION_GUARD = os.getenv("ENABLE_MUTATION_GUARD", "1") != "0"
ENABLE_SPEC_CRITIC = os.getenv("ENABLE_SPEC_CRITIC", "1") != "0"
ALLOW_REFERENCE_IMPLEMENTATION = os.getenv("ALLOW_REFERENCE_IMPLEMENTATION", "0") != "0"
MAX_CRITIC_PARSE_RETRIES = int(os.getenv("MAX_CRITIC_PARSE_RETRIES", "1"))
CRITIC_REVIEW_PASSES = int(os.getenv("CRITIC_REVIEW_PASSES", "1"))
CRITIC_TEMPERATURE = float(os.getenv("CRITIC_TEMPERATURE", "0.0"))
CRITIC_MAX_TOKENS = int(os.getenv("CRITIC_MAX_TOKENS", "1800"))
CRITIC_PROBE_MAX_TOKENS = int(os.getenv("CRITIC_PROBE_MAX_TOKENS", "1200"))
MAX_CRITIC_PROBE_PARSE_RETRIES = int(os.getenv("MAX_CRITIC_PROBE_PARSE_RETRIES", "2"))
MIN_CRITIC_PROBES = int(os.getenv("MIN_CRITIC_PROBES", "3"))
MAX_CRITIC_PROBES = int(os.getenv("MAX_CRITIC_PROBES", "6"))
MAX_EXECUTED_CRITIC_PROBES = int(os.getenv("MAX_EXECUTED_CRITIC_PROBES", "12"))
CRITIC_REQUIRE_PRECONDITION_EVIDENCE = (
    os.getenv("CRITIC_REQUIRE_PRECONDITION_EVIDENCE", "1") != "0"
)
DAFNY_PATH = os.getenv("DAFNY_PATH") or shutil.which("dafny") or "dafny"
DAFNY_SOLVER_PATH = os.getenv("DAFNY_SOLVER_PATH", "")

# ===== 文件路径 =====
DATA_DIR = Path(os.getenv("DATA_DIR", PROJECT_DIR / "data"))
LOG_DIR = Path(os.getenv("LOG_DIR", PROJECT_DIR / "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
RUNS_DIR = Path(os.getenv("RUNS_DIR", LOG_DIR / "runs"))
