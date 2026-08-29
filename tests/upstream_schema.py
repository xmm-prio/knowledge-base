"""The upstream's tool contract, transcribed from the installed binary.

Every argument name and enum below was read off `tools/list` of codebase-memory-mcp on the
deployment host. It is here because the fake channel used to accept anything: the gateway
spent a release sending `query` to a tool whose argument is `pattern`, and asking for a
project by its directory name when the upstream wanted the name it derived at index time.
Both were wrong in production and green in the suite, because the double agreed with
whatever it was told.

So the double is held to this instead. A call missing a required argument is refused exactly
as the binary refuses it, and a call naming an argument the tool does not have is recorded as
a violation and fails the test that made it -- the binary ignores those silently, which is
how an argument can be misspelled for a release without anyone noticing.

Refresh this by re-reading `tools/list` whenever the upstream is upgraded -- otherwise what is
pinned is the previous version's contract. See docs/adr/0008.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Contract:
    """What one upstream tool accepts."""

    required: frozenset[str] = frozenset()
    optional: frozenset[str] = frozenset()
    choices: dict[str, frozenset[str]] = field(default_factory=dict)

    @property
    def known(self) -> frozenset[str]:
        return self.required | self.optional


INDEX_MODES = frozenset({"full", "moderate", "fast", "cross-repo-intelligence"})
FORMATS = frozenset({"tree", "json"})
DIRECTIONS = frozenset({"inbound", "outbound", "both"})

CONTRACTS: dict[str, Contract] = {
    "index_repository": Contract(
        required=frozenset({"repo_path"}),
        optional=frozenset({"mode", "target_projects", "name", "persistence"}),
        choices={"mode": INDEX_MODES},
    ),
    "list_projects": Contract(
        optional=frozenset({"offset", "limit", "include_details", "metadata_only"}),
    ),
    "delete_project": Contract(required=frozenset({"project"})),
    "index_status": Contract(required=frozenset({"project"}), optional=frozenset({"verbose"})),
    "search_graph": Contract(
        required=frozenset({"project"}),
        optional=frozenset(
            {
                "query",
                "label",
                "name_pattern",
                "qn_pattern",
                "file_pattern",
                "relationship",
                "min_degree",
                "max_degree",
                "exclude_entry_points",
                "include_connected",
                "semantic_query",
                "limit",
                "offset",
                "format",
                "fields",
                "detail",
            }
        ),
        choices={"format": FORMATS, "detail": frozenset({"ids", "default"})},
    ),
    "search_code": Contract(
        required=frozenset({"pattern", "project"}),
        optional=frozenset(
            {"file_pattern", "path_filter", "mode", "context", "regex", "debug", "limit"}
        ),
        choices={"mode": frozenset({"compact", "full", "files"})},
    ),
    "query_graph": Contract(
        required=frozenset({"query", "project"}),
        optional=frozenset({"graph", "max_rows"}),
        choices={"graph": frozenset({"code", "missed"})},
    ),
    "trace_path": Contract(
        required=frozenset({"function_name", "project"}),
        optional=frozenset(
            {
                "direction",
                "depth",
                "limit",
                "cursor",
                "mode",
                "parameter_name",
                "edge_types",
                "risk_labels",
                "include_tests",
                "format",
                "include_evidence",
            }
        ),
        choices={
            "direction": DIRECTIONS,
            "mode": frozenset({"calls", "data_flow", "cross_service"}),
            "format": FORMATS,
        },
    ),
    "get_code_snippet": Contract(
        required=frozenset({"qualified_name", "project"}),
        optional=frozenset({"include_neighbors"}),
    ),
    "get_graph_schema": Contract(required=frozenset({"project"})),
    "get_architecture": Contract(
        required=frozenset({"project"}), optional=frozenset({"path", "aspects"})
    ),
    "check_index_coverage": Contract(
        required=frozenset({"project"}),
        optional=frozenset({"paths", "scopes", "scope_limit", "scope_offset"}),
    ),
    "detect_changes": Contract(
        required=frozenset({"project"}),
        optional=frozenset(
            {"scope", "direction", "depth", "limit", "base_branch", "since", "format"}
        ),
        choices={
            "scope": frozenset({"files", "impact"}),
            "direction": DIRECTIONS,
            "format": FORMATS,
        },
    ),
    "manage_adr": Contract(
        required=frozenset({"project"}),
        optional=frozenset({"mode", "content"}),
        choices={"mode": frozenset({"get", "update", "sections"})},
    ),
    "ingest_traces": Contract(required=frozenset({"traces", "project"})),
}


MISSING = "missing required argument: {name}"
"""How the binary words a required argument that was not sent. Quoted so a test asserting on
what a member sees is asserting on what they would really see."""


def refusal(tool: str, arguments: dict[str, object]) -> str | None:
    """What the upstream would refuse this call with, or None if it would run it."""
    contract = CONTRACTS.get(tool)
    if contract is None:
        return f"unknown tool: {tool}"
    for name in sorted(contract.required):
        if arguments.get(name) in (None, ""):
            return MISSING.format(name=name)
    for name, allowed in contract.choices.items():
        if (given := arguments.get(name)) is not None and str(given) not in allowed:
            return f"invalid {name}: {given}"
    return None


def unknown_arguments(tool: str, arguments: dict[str, object]) -> list[str]:
    """Arguments this tool does not declare. The binary ignores them; we do not."""
    contract = CONTRACTS.get(tool)
    return [] if contract is None else sorted(set(arguments) - contract.known)
