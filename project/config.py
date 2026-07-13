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
SPEC_MODEL = os.getenv("SPEC_MODEL", "deepseek-chat")       # Spec Agent
CODE_MODEL = os.getenv("CODE_MODEL", "deepseek-chat")       # Code Agent
REPAIR_MODEL = os.getenv("REPAIR_MODEL", "deepseek-chat")   # Repair Agent

# ===== Pipeline 配置 =====
MAX_REPAIR_ROUNDS = int(os.getenv("MAX_REPAIR_ROUNDS", "3"))
LLM_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "60"))
LLM_RETRIES = int(os.getenv("LLM_RETRIES", "2"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "0"))
USE_TEMPLATE_FALLBACK = os.getenv("USE_TEMPLATE_FALLBACK", "0") != "0"
EVALUATION_MODE = os.getenv("EVALUATION_MODE", "strict").strip().lower()
ENABLE_SPEC_REPAIR = os.getenv("ENABLE_SPEC_REPAIR", "1") != "0"
MAX_SPEC_REPAIR_RETRIES = int(os.getenv("MAX_SPEC_REPAIR_RETRIES", "1"))
ENABLE_PROOF_REPAIR = os.getenv("ENABLE_PROOF_REPAIR", "1") != "0"
ENABLE_BEHAVIOR_REPAIR_LOOP = os.getenv("ENABLE_BEHAVIOR_REPAIR_LOOP", "1") != "0"
ENABLE_INLOOP_MUTATION_ADEQUACY = os.getenv("ENABLE_INLOOP_MUTATION_ADEQUACY", "1") != "0"
ENABLE_MUTATION_SPEC_STRENGTHENING = os.getenv("ENABLE_MUTATION_SPEC_STRENGTHENING", "1") != "0"
DAFNY_PATH = os.getenv("DAFNY_PATH") or shutil.which("dafny") or "dafny"
DAFNY_SOLVER_PATH = os.getenv("DAFNY_SOLVER_PATH", "")

# ===== 文件路径 =====
DATA_DIR = Path(os.getenv("DATA_DIR", PROJECT_DIR / "data"))
LOG_DIR = Path(os.getenv("LOG_DIR", PROJECT_DIR / "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)
RUNS_DIR = Path(os.getenv("RUNS_DIR", LOG_DIR / "runs"))
