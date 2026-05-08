import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

if os.environ.get("LOGOS_DATA_ROOT", "").strip():
    DATA_ROOT = Path(os.environ["LOGOS_DATA_ROOT"]).expanduser().resolve()
else:
    DATA_ROOT = REPO_ROOT / "data"

# Working memory
WORKING_MEMORY_PATH = DATA_ROOT / "working" / "current.json"

# CLI: метаданные сессий (события диалога — в WM с полем cli_session_id)
CLI_SESSIONS_DIR = DATA_ROOT / "cli_sessions"
CLI_SESSION_LATEST_PATH = CLI_SESSIONS_DIR / "latest.json"

# Episodic memory
EPISODIC_DB_PATH = DATA_ROOT / "episodic" / "episodes.db"

# Semantic memory
SEMANTIC_DB_PATH = DATA_ROOT / "semantic" / "knowledge.db"

# Journal
JOURNAL_DIR = DATA_ROOT / "journal"
JOURNAL_VECTOR_INDEX_PATH = DATA_ROOT / "journal_vector_index.pkl"

# External memory
EXTERNAL_DB_PATH = DATA_ROOT / "external" / "documents.db"
EXTERNAL_VECTOR_INDEX_PATH = DATA_ROOT / "external" / "vector_index.pkl"

# Instrumental memory
INSTRUMENTAL_DB_PATH = DATA_ROOT / "instrumental" / "tools.db"

# Ethics / Moral
MORAL_DB_PATH = DATA_ROOT / "episodic" / "moral.db"

# Goals
GOALS_DB_PATH = DATA_ROOT / "goals" / "goals.db"
GOALS_CHECKPOINT_PATH = DATA_ROOT / "goals" / "checkpoint.json"

# Planner
PLANNER_DATA_DIR = DATA_ROOT / "planner"
PLANNER_OUTCOMES_PATH = PLANNER_DATA_DIR / "outcomes.json"

# Mission control
MISSION_STATE_PATH = DATA_ROOT / "mission" / "state.json"
MISSION_HYPOTHESES_PATH = DATA_ROOT / "mission" / "hypotheses.json"
MISSION_EXPERIMENTS_PATH = DATA_ROOT / "mission" / "experiments.json"
MISSION_PROTOCOL_PATH = DATA_ROOT / "mission" / "protocol.log"

# Sleep pipeline
SLEEP_LOCK_PATH = DATA_ROOT / "sleep" / ".sleep.lock"
SLEEP_CHECKPOINT_PATH = DATA_ROOT / "sleep" / "checkpoint.json"
SLEEP_LAST_WORDS_PATH = DATA_ROOT / "sleep" / "last_words.json"
EXPERIMENTS_ROOT = REPO_ROOT / "experiments"

# Embedding models
RUBERT_MODEL_PATH = REPO_ROOT / "rubert-tiny2"
ALL_MINILM_MODEL_PATH = REPO_ROOT / "all-MiniLM-L6-v2"

# experiments/* остаются в репозитории как исторические артефакты,
# но ядро kernel/* не должно зависеть от них через sys.path.
