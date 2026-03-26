"""
MCP server exposing New Relic microservice dependency tools.

Configure in Claude Code (~/.claude/settings.json):

    {
      "mcpServers": {
        "newrelic-dependencies": {
          "command": "python",
          "args": ["/path/to/scattered_world/mcp_server.py"],
          "env": { "NR_API_KEY": "YOUR_KEY_HERE" }
        }
      }
    }

Tools available to the AI agent:
  - search_services          : find entities by service name list
  - get_service_dependencies : build dependency graph for named services
  - get_service_map          : build dependency graph by tag
  - run_impact_analysis      : full pipeline — names → graph → impact report
"""

import os

from mcp.server.fastmcp import FastMCP

import newrelic_service_map as nrsm

mcp = FastMCP("newrelic-dependencies")


def _api_key() -> str:
    key = os.environ.get("NR_API_KEY", "")
    if not key:
        raise RuntimeError(
            "NR_API_KEY environment variable is not set. "
            "Add it to the MCP server env config."
        )
    return key


@mcp.tool()
def search_services(names: list[str]) -> list:
    """
    Find New Relic entities by exact service name.

    Args:
        names: List of service names to look up (e.g. ["payments-service", "orders-service"]).

    Returns:
        List of entity dicts, each with name, guid, entityType, and tags.
    """
    return nrsm.search_entities_by_name(names, _api_key())


@mcp.tool()
def get_service_dependencies(names: list[str]) -> dict:
    """
    Build a runtime dependency graph for the given service names.

    Fetches each service from New Relic and maps all CALLS relationships,
    including any services discovered transitively via those relationships.

    Args:
        names: List of service names to seed the graph.

    Returns:
        {
          "entities": { guid: { name, guid, entityType, tags } },
          "edges":    [ { source_guid, target_guid, type } ]
        }
    """
    return nrsm.get_dependencies_for_services(names, _api_key())


@mcp.tool()
def get_service_map(tag_key: str, tag_value: str) -> dict:
    """
    Build a runtime dependency graph for all services matching a tag.

    Useful for fetching all services in an environment (e.g. tag_key="environment",
    tag_value="production") and mapping their relationships.

    Args:
        tag_key:   The tag key to filter on (e.g. "environment", "team").
        tag_value: The tag value to match (e.g. "production", "payments").

    Returns:
        {
          "entities": { guid: { name, guid, entityType, tags } },
          "edges":    [ { source_guid, target_guid, type } ]
        }
    """
    return nrsm.extract_service_map(tag_key, tag_value, _api_key())


@mcp.tool()
def run_impact_analysis(names: list[str], target_name: str) -> dict:
    """
    Fetch the dependency graph for the given services and run impact analysis.

    Builds a dependency graph for `names`, then determines which services
    would be affected (directly or transitively) if `target_name` goes down.

    Args:
        names:       List of service names to include in the dependency graph.
                     Should contain target_name and the services you care about.
        target_name: Name of the service assumed to be failing.

    Returns:
        {
          "target":       { name, guid, entityType, tags },
          "direct":       [ entities that directly call target ],
          "transitive":   [ entities that indirectly call target ],
          "all_impacted": [ all affected entities, deduplicated ]
        }

    Raises:
        ValueError: if target_name is not found in the fetched graph.
    """
    graph = nrsm.get_dependencies_for_services(names, _api_key())

    # Resolve target_name to a GUID
    target_guid = None
    for guid, entity in graph["entities"].items():
        if entity.get("name") == target_name:
            target_guid = guid
            break

    if target_guid is None:
        raise ValueError(
            f"Service {target_name!r} not found in the dependency graph. "
            f"Available services: {[e['name'] for e in graph['entities'].values()]}"
        )

    return nrsm.analyze_impact(graph, target_guid)


if __name__ == "__main__":
    mcp.run()
