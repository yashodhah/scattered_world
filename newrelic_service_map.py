"""
New Relic Service Map Extraction via NerdGraph GraphQL API.

Usage:
    from newrelic_service_map import extract_service_map

    result = extract_service_map(
        tag_key="environment",
        tag_value="production",
        api_key="YOUR_NR_USER_API_KEY"
    )
"""

import requests

NERDGRAPH_URL = "https://api.newrelic.com/graphql"


def _run_query(query: str, api_key: str) -> dict:
    """Execute a NerdGraph GraphQL query and return the parsed JSON response."""
    headers = {
        "Content-Type": "application/json",
        "Api-Key": api_key,
    }
    response = requests.post(NERDGRAPH_URL, json={"query": query}, headers=headers)
    response.raise_for_status()
    data = response.json()
    if "errors" in data:
        raise RuntimeError(f"NerdGraph errors: {data['errors']}")
    return data


def get_entity_relationships(guid: str, api_key: str) -> dict:
    """
    Fetch an entity and its related entities (CALLS relationships) by GUID.

    Returns a dict with:
        - name: entity name
        - guid: entity GUID
        - entityType: entity type string
        - relationships: list of dicts with source/target entity info and type
    """
    query = """
    {
      actor {
        entity(guid: "%s") {
          name
          guid
          entityType
          tags { key values }
          relatedEntities(filter: { relationshipTypes: { include: CALLS } }) {
            results {
              source { entity { name guid entityType } }
              target { entity { name guid entityType } }
              type
            }
          }
        }
      }
    }
    """ % guid

    data = _run_query(query, api_key)
    entity = data["data"]["actor"]["entity"]
    if entity is None:
        return {}

    return {
        "name": entity["name"],
        "guid": entity["guid"],
        "entityType": entity["entityType"],
        "tags": {t["key"]: t["values"] for t in (entity.get("tags") or [])},
        "relationships": entity.get("relatedEntities", {}).get("results", []),
    }


def search_entities_by_tag(tag_key: str, tag_value: str, api_key: str) -> list:
    """
    Search for all entities matching a tag key/value pair.

    Returns a list of dicts, each with:
        - name, guid, entityType, tags
    """
    query = """
    {
      actor {
        entitySearch(query: "tags.%s = '%s'") {
          results {
            entities {
              name
              guid
              entityType
              tags { key values }
            }
          }
        }
      }
    }
    """ % (tag_key, tag_value)

    data = _run_query(query, api_key)
    entities = (
        data["data"]["actor"]["entitySearch"]["results"].get("entities") or []
    )
    return [
        {
            "name": e["name"],
            "guid": e["guid"],
            "entityType": e["entityType"],
            "tags": {t["key"]: t["values"] for t in (e.get("tags") or [])},
        }
        for e in entities
    ]


def extract_service_map(tag_key: str, tag_value: str, api_key: str) -> dict:
    """
    Build a service map for all entities matching the given tag.

    Steps:
      1. Find all entities with the tag via entitySearch.
      2. For each entity, fetch its CALLS relationships.
      3. Return a unified graph structure.

    Returns:
        {
            "entities": { guid: { name, guid, entityType, tags } },
            "edges": [ { source_guid, target_guid, type } ]
        }
    """
    entities = search_entities_by_tag(tag_key, tag_value, api_key)

    graph: dict = {"entities": {}, "edges": []}

    for entity in entities:
        graph["entities"][entity["guid"]] = entity

    for entity in entities:
        detail = get_entity_relationships(entity["guid"], api_key)
        for rel in detail.get("relationships", []):
            src = rel.get("source", {}).get("entity") or {}
            tgt = rel.get("target", {}).get("entity") or {}
            if src.get("guid") and tgt.get("guid"):
                graph["edges"].append(
                    {
                        "source_guid": src["guid"],
                        "target_guid": tgt["guid"],
                        "type": rel.get("type"),
                    }
                )
                # Add related entities to the entity map if not already present
                for ent in (src, tgt):
                    if ent["guid"] not in graph["entities"]:
                        graph["entities"][ent["guid"]] = {
                            "name": ent.get("name"),
                            "guid": ent["guid"],
                            "entityType": ent.get("entityType"),
                            "tags": {},
                        }

    return graph
