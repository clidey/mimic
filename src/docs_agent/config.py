"""Configuration constants and session definitions."""

from __future__ import annotations

from docs_agent.models import SessionConfig

# ---------------------------------------------------------------------------
# Container names
# ---------------------------------------------------------------------------
DESKTOP_CONTAINER = "docsagent-desktop"
POSTGRES_CONTAINER = "docsagent-postgres"
WHODB_CONTAINER = "docsagent-whodb"
OLLAMA_CONTAINER = "docsagent-ollama"
NETWORK_NAME = "docsagent-net"

# ---------------------------------------------------------------------------
# Postgres
# ---------------------------------------------------------------------------
POSTGRES_USER = "whodb"
POSTGRES_PASSWORD = "whodb"
POSTGRES_DB = "whodb"
POSTGRES_PORT = 5432

# ---------------------------------------------------------------------------
# WhoDB
# ---------------------------------------------------------------------------
WHODB_PORT = 8080

# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------
DISPLAY_WIDTH = 1280
DISPLAY_HEIGHT = 800
DISPLAY = ":1"

# ---------------------------------------------------------------------------
# Claude API
# ---------------------------------------------------------------------------
CLAUDE_MODEL = "claude-sonnet-4-6"
CLAUDE_BETA = "computer-use-2025-11-24"
CLAUDE_MAX_TOKENS = 4096
MAX_AGENT_ITERATIONS = 40
WRAPUP_THRESHOLD = 30  # inject wrap-up nudge at this iteration

# ---------------------------------------------------------------------------
# Session definitions — map all 80 pages into logical groups
# ---------------------------------------------------------------------------
SESSIONS: list[SessionConfig] = [
    SessionConfig(
        name="Installation & First Run",
        page_slugs=[
            "installation",
            "first-login",
            "quick-start",
            "guides/complete-beginner",
        ],
    ),
    SessionConfig(
        name="Core Features",
        page_slugs=[
            "features/database-connectivity",
            "features/schema-explorer",
            "features/sidebar-navigation",
            "features/storage-units",
            "resources/keyboard-shortcuts",
            "resources/comparisons/overview",
            "resources/comparisons/vs-phpmyadmin",
            "resources/comparisons/vs-pgadmin",
        ],
    ),
    SessionConfig(
        name="Data Management",
        page_slugs=[
            "data/viewing-data",
            "data/adding-records",
            "data/editing-records",
            "data/deleting-records",
            "data/filtering-searching",
            "data/sorting-pagination",
            "use-cases/database-exploration",
            "use-cases/data-migration",
        ],
    ),
    SessionConfig(
        name="Query Interface",
        page_slugs=[
            "query/scratchpad-intro",
            "query/writing-queries",
            "query/query-results",
            "query/query-history",
            "query/multiple-cells",
        ],
    ),
    SessionConfig(
        name="Visualization",
        page_slugs=[
            "visualization/graph-view",
            "visualization/schema-topology",
            "visualization/relationships",
        ],
    ),
    SessionConfig(
        name="Advanced Features",
        page_slugs=[
            "advanced/mock-data",
            "advanced/export-options",
            "advanced/where-conditions",
            "advanced/batch-operations",
            "best-practices/collaboration",
        ],
    ),
    SessionConfig(
        name="AI Chat",
        page_slugs=[
            "ai/introduction",
            "ai/setup-providers",
            "ai/querying-data",
            "ai/modifying-data",
            "ai/conversation-features",
            "best-practices/ai-usage",
        ],
        needs_ollama=True,
    ),
    SessionConfig(
        name="Tutorials",
        page_slugs=[
            "guides/tutorials/first-database-connection",
            "guides/tutorials/data-exploration-workflow",
            "guides/tutorials/building-complex-queries",
            "guides/tutorials/data-export-analysis",
            "guides/tutorials/schema-visualization",
            "guides/tutorials/ai-first-query",
            "guides/roles/developers",
        ],
        needs_ollama=True,  # ai-first-query needs Ollama
    ),
    SessionConfig(
        name="Migration Guides",
        page_slugs=[
            "guides/migrating-from-phpmyadmin",
            "guides/migrating-from-pgadmin",
        ],
    ),
    SessionConfig(
        name="Integrations",
        page_slugs=[
            "resources/integrations/docker",
            "resources/integrations/ci-cd",
            "resources/integrations/monitoring",
            "resources/integrations/backup-tools",
            "resources/faq",
            "resources/troubleshooting",
        ],
    ),
    SessionConfig(
        name="Informational & Reference",
        page_slugs=[
            "introduction",
            "why-whodb",
            "guides/team-setup",
            "guides/roles/data-analysts",
            "guides/roles/database-administrators",
            "guides/roles/qa-testers",
            "use-cases/data-analysis",
            "use-cases/testing-development",
            "use-cases/debugging-production",
            "use-cases/ai-data-exploration",
            "best-practices/security",
            "best-practices/performance",
            "best-practices/data-management",
            "best-practices/query-optimization",
            "best-practices/postgresql",
            "best-practices/mysql",
            "best-practices/mongodb",
            "best-practices/access-control",
            "best-practices/documentation",
            "resources/common-errors",
            "resources/performance-tuning",
            "resources/comparisons/vs-dbeaver",
            "resources/comparisons/vs-tableplus",
            "resources/glossary",
            "resources/supported-databases",
            "resources/changelog",
        ],
        needs_whodb=False,
        needs_postgres=False,
        needs_desktop=False,
    ),
]


def find_session(name: str) -> SessionConfig | None:
    """Find a session by name (case-insensitive)."""
    lower = name.lower()
    for s in SESSIONS:
        if s.name.lower() == lower:
            return s
    return None
