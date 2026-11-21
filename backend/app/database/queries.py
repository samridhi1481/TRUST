DASHBOARD_OVERVIEW = """
OPTIONAL MATCH (entity:GraphNode:Entity)
RETURN
    count(entity) AS total_monitored_entities,
    count(CASE WHEN toLower(coalesce(entity.type, '')) IN $device_types
        THEN entity END) AS devices,
    count(CASE WHEN toLower(coalesce(entity.type, '')) = 'user'
        THEN entity END) AS users,
    count(CASE WHEN toLower(coalesce(entity.type, '')) = 'server'
        THEN entity END) AS servers,
    count(CASE WHEN toLower(coalesce(entity.type, '')) = 'incident'
          AND toUpper(coalesce(entity.status, '')) IN $active_incident_statuses
        THEN entity END) AS active_incidents
"""

DASHBOARD_RECENT_EVENTS = """
MATCH (event:GraphNode:SecurityEvent)
RETURN
    event.event_id AS event_id,
    event.event_type AS event_type,
    event.event_time AS event_time,
    event.severity AS severity,
    event.description AS description,
    event.is_synthetic AS is_synthetic
ORDER BY event.event_time IS NULL, event.event_time DESC, event.event_id
LIMIT $limit
"""

GRAPH_OVERVIEW = """
CALL {
    MATCH (node:GraphNode)
    RETURN count(node) AS total_nodes
}
CALL {
    MATCH (node:GraphNode:Entity)
    RETURN count(node) AS total_entities
}
CALL {
    MATCH (node:GraphNode:SecurityEvent)
    RETURN count(node) AS total_events
}
CALL {
    MATCH (node:GraphNode:Evidence)
    RETURN count(node) AS total_evidence
}
CALL {
    MATCH ()-[relationship]->()
    RETURN count(relationship) AS total_relationships
}
RETURN total_nodes, total_entities, total_events, total_evidence, total_relationships
"""

GRAPH_ENTITIES = """
MATCH (entity:GraphNode:Entity)
WHERE ($entity_type IS NULL
       OR toLower(coalesce(entity.type, '')) = toLower($entity_type))
  AND ($risk_level IS NULL
       OR toLower(coalesce(entity.risk_level, '')) = toLower($risk_level))
RETURN labels(entity) AS labels, properties(entity) AS properties
ORDER BY entity.id
SKIP $skip
LIMIT $limit
"""

GRAPH_ENTITY = """
MATCH (entity:GraphNode {id: $entity_id})
RETURN labels(entity) AS labels, properties(entity) AS properties
"""

GRAPH_NEIGHBORS = """
MATCH (entity:GraphNode {id: $entity_id})
OPTIONAL MATCH (entity)-[relationship]-(neighbor:GraphNode)
RETURN
    labels(entity) AS entity_labels,
    properties(entity) AS entity_properties,
    CASE WHEN neighbor IS NULL THEN null ELSE labels(neighbor) END AS neighbor_labels,
    properties(neighbor) AS neighbor_properties,
    CASE WHEN relationship IS NULL THEN null ELSE type(relationship) END
        AS relationship_type,
    CASE WHEN relationship IS NULL THEN null ELSE properties(relationship) END
        AS relationship_properties,
    CASE WHEN relationship IS NULL THEN null ELSE startNode(relationship).id END
        AS source_id,
    CASE WHEN relationship IS NULL THEN null ELSE endNode(relationship).id END
        AS target_id
ORDER BY neighbor_properties.id, relationship_properties.relationship_id
"""

GRAPH_RELATIONSHIPS = """
MATCH (entity:GraphNode {id: $entity_id})
OPTIONAL MATCH (entity)-[relationship]-(neighbor:GraphNode)
RETURN
    CASE WHEN relationship IS NULL THEN null
         ELSE properties(relationship) END AS properties,
    CASE WHEN relationship IS NULL THEN null ELSE type(relationship) END AS type,
    CASE WHEN relationship IS NULL THEN null ELSE startNode(relationship).id END
        AS source_id,
    CASE WHEN relationship IS NULL THEN null ELSE endNode(relationship).id END
        AS target_id,
    CASE WHEN relationship IS NULL THEN null ELSE labels(neighbor) END
        AS neighbor_labels,
    CASE WHEN relationship IS NULL THEN null ELSE properties(neighbor) END
        AS neighbor_properties
ORDER BY properties.relationship_id
"""

GRAPH_RISK_LEVEL_COVERAGE = """
MATCH (entity:GraphNode:Entity)
RETURN count(CASE WHEN entity.risk_level IS NOT NULL THEN entity END)
    AS labeled_entities
"""

THREAT_EVENTS = """
MATCH (event:GraphNode:SecurityEvent)
RETURN properties(event) AS event
ORDER BY event.event_time IS NULL, event.event_time DESC, event.event_id
SKIP $skip
LIMIT $limit
"""

THREAT_EVENT = """
MATCH (event:GraphNode:SecurityEvent {event_id: $threat_id})
RETURN properties(event) AS event
"""

THREAT_ASSOCIATED_ENTITIES = """
MATCH (event:GraphNode:SecurityEvent {event_id: $threat_id})
OPTIONAL MATCH (event)-[:OBSERVED_ON]->(entity:GraphNode:Entity)
RETURN entity.id AS entity_id, labels(entity) AS labels, properties(entity) AS properties
ORDER BY entity_id
"""

THREAT_EVIDENCE = """
MATCH (event:GraphNode:SecurityEvent {event_id: $threat_id})
OPTIONAL MATCH (event)-[:SUPPORTED_BY]->(evidence:GraphNode:Evidence)
RETURN evidence.evidence_id AS evidence_id, properties(evidence) AS evidence
ORDER BY evidence_id
"""

INCIDENT_LIST = """
MATCH (incident:GraphNode:Entity)
WHERE toLower(coalesce(incident.type, '')) = 'incident'
  AND ($status IS NULL OR toUpper(coalesce(incident.status, '')) = $status)
  AND ($priority IS NULL OR toLower(coalesce(incident.priority, '')) = $priority)
RETURN properties(incident) AS incident
ORDER BY incident.updated_at DESC, incident.id
SKIP $skip
LIMIT $limit
"""

INCIDENT_GET = """
MATCH (incident:GraphNode:Entity {id: $incident_id})
WHERE toLower(coalesce(incident.type, '')) = 'incident'
RETURN properties(incident) AS incident
"""

INCIDENT_STATUS = """
MATCH (incident:GraphNode:Entity {id: $incident_id})
WHERE toLower(coalesce(incident.type, '')) = 'incident'
RETURN incident.status AS status
"""

INCIDENT_CREATE = """
OPTIONAL MATCH (event:GraphNode:SecurityEvent {event_id: $event_id})
WITH event
WHERE $event_id IS NULL OR event IS NOT NULL
CREATE (incident:GraphNode:Entity)
SET incident += $properties
RETURN properties(incident) AS incident
"""

INCIDENT_UPDATE_STATUS = """
MATCH (incident:GraphNode:Entity {id: $incident_id})
WHERE toLower(coalesce(incident.type, '')) = 'incident'
  AND coalesce(incident.status, 'UNSET') = $expected_status
SET incident.status = $new_status,
    incident.updated_at = $updated_at,
    incident.status_history =
        coalesce(incident.status_history, []) + [$audit_entry]
RETURN properties(incident) AS incident
"""

INCIDENT_UPDATE_PRIORITY = """
MATCH (incident:GraphNode:Entity {id: $incident_id})
WHERE toLower(coalesce(incident.type, '')) = 'incident'
SET incident.priority = $priority,
    incident.updated_at = $updated_at,
    incident.status_history =
        coalesce(incident.status_history, []) + [$audit_entry]
RETURN properties(incident) AS incident
"""

ENTITY_TYPE_BY_ID = """
MATCH (entity:GraphNode:Entity {id: $entity_id})
RETURN entity.id AS id, entity.type AS type, properties(entity) AS properties
"""

ENTITY_TYPES_BY_IDS = """
MATCH (entity:GraphNode:Entity)
WHERE entity.id IN $entity_ids
RETURN entity.id AS id, entity.type AS type
"""

INCIDENT_SOURCE_EVENT = """
MATCH (incident:GraphNode:Entity {id: $incident_id})
WHERE toLower(coalesce(incident.type, '')) = 'incident'
OPTIONAL MATCH (event:GraphNode:SecurityEvent {event_id: incident.related_event_id})
RETURN properties(incident) AS incident, properties(event) AS event
"""

INVESTIGATION_LIST = """
MATCH (investigation:GraphNode:Entity)
WHERE toLower(coalesce(investigation.type, '')) = 'investigation'
  AND ($status IS NULL
       OR toUpper(coalesce(investigation.status, '')) = $status)
  AND ($alert_id IS NULL OR investigation.related_event_id = $alert_id)
RETURN properties(investigation) AS investigation
ORDER BY investigation.updated_at DESC, investigation.id
SKIP $skip
LIMIT $limit
"""

INVESTIGATION_GET = """
MATCH (investigation:GraphNode:Entity {id: $investigation_id})
WHERE toLower(coalesce(investigation.type, '')) = 'investigation'
RETURN properties(investigation) AS investigation
"""

INVESTIGATION_CREATE = """
OPTIONAL MATCH (event:GraphNode:SecurityEvent {event_id: $alert_id})
WITH event
WHERE $alert_id IS NULL OR event IS NOT NULL
OPTIONAL MATCH (entity:GraphNode:Entity)
WHERE entity.id IN $entity_ids
WITH event, collect(DISTINCT entity.id) AS matched_entity_ids
WHERE size(matched_entity_ids) = size($entity_ids)
CREATE (investigation:GraphNode:Entity)
SET investigation += $properties
RETURN properties(investigation) AS investigation
"""

INVESTIGATION_ADD_NOTE = """
MATCH (investigation:GraphNode:Entity {id: $investigation_id})
WHERE toLower(coalesce(investigation.type, '')) = 'investigation'
SET investigation.notes = coalesce(investigation.notes, []) + [$note_entry],
    investigation.audit_history =
        coalesce(investigation.audit_history, []) + [$audit_entry],
    investigation.updated_at = $updated_at
RETURN properties(investigation) AS investigation
"""

INVESTIGATION_ADD_EVIDENCE = """
MATCH (investigation:GraphNode:Entity {id: $investigation_id})
WHERE toLower(coalesce(investigation.type, '')) = 'investigation'
MATCH (evidence:GraphNode:Evidence {evidence_id: $evidence_id})
WITH investigation,
     $evidence_id IN coalesce(investigation.evidence_ids, []) AS already_attached
FOREACH (_ IN CASE WHEN already_attached THEN [] ELSE [1] END |
    SET investigation.evidence_ids =
            coalesce(investigation.evidence_ids, []) + [$evidence_id],
        investigation.audit_history =
            coalesce(investigation.audit_history, []) + [$audit_entry],
        investigation.updated_at = $updated_at
)
RETURN properties(investigation) AS investigation, already_attached
"""

INVESTIGATION_EVIDENCE = """
MATCH (investigation:GraphNode:Entity {id: $investigation_id})
WHERE toLower(coalesce(investigation.type, '')) = 'investigation'
UNWIND coalesce(investigation.evidence_ids, []) AS evidence_id
MATCH (evidence:GraphNode:Evidence {evidence_id: evidence_id})
RETURN properties(evidence) AS evidence
ORDER BY evidence.evidence_id
"""

INVESTIGATION_STATUS = """
MATCH (investigation:GraphNode:Entity {id: $investigation_id})
WHERE toLower(coalesce(investigation.type, '')) = 'investigation'
RETURN investigation.status AS status
"""

INVESTIGATION_UPDATE_STATUS = """
MATCH (investigation:GraphNode:Entity {id: $investigation_id})
WHERE toLower(coalesce(investigation.type, '')) = 'investigation'
  AND investigation.status = $expected_status
SET investigation.status = $new_status,
    investigation.audit_history =
        coalesce(investigation.audit_history, []) + [$audit_entry],
    investigation.updated_at = $updated_at
RETURN properties(investigation) AS investigation
"""

INVESTIGATION_RECENT_ACTIVITY = """
MATCH (investigation:GraphNode:Entity)
WHERE toLower(coalesce(investigation.type, '')) = 'investigation'
RETURN
    investigation.id AS investigation_id,
    investigation.title AS title,
    investigation.status AS status,
    investigation.updated_at AS updated_at
ORDER BY investigation.updated_at DESC, investigation.id
LIMIT $limit
"""


def blast_radius_paths_query(depth: int) -> str:
    if not 1 <= depth <= 6:
        raise ValueError("Blast-radius depth must be between 1 and 6.")
    return f"""
MATCH (source:GraphNode:Entity {{id: $entity_id}})
OPTIONAL MATCH path = (source)-[*1..{depth}]-(target:GraphNode:Entity)
WHERE path IS NULL OR (
    source.id NOT IN $excluded_entity_ids
    AND
    all(node IN nodes(path) WHERE 'Entity' IN labels(node))
    AND all(relationship IN relationships(path)
        WHERE coalesce(relationship.relationship_category, 'original_entity')
            = 'original_entity')
    AND all(node IN nodes(path)
        WHERE node = source OR node.id NOT IN $excluded_entity_ids)
)
RETURN
    labels(source) AS source_labels,
    properties(source) AS source_properties,
    coalesce(
        [node IN nodes(path) | {{
            id: node.id,
            labels: labels(node),
            properties: properties(node)
        }}],
        []
    ) AS nodes,
    coalesce(
        [relationship IN relationships(path) | {{
            id: relationship.relationship_id,
            type: type(relationship),
            source_id: startNode(relationship).id,
            target_id: endNode(relationship).id,
            properties: properties(relationship)
        }}],
        []
    ) AS relationships
LIMIT $limit
"""


def graph_subgraph_query(depth: int) -> str:
    if not 1 <= depth <= 6:
        raise ValueError("Graph traversal depth must be between 1 and 6.")
    return f"""
MATCH (source:GraphNode {{id: $entity_id}})
OPTIONAL MATCH path = (source)-[*1..{depth}]-(target:GraphNode)
WITH source, path
RETURN
    labels(source) AS source_labels,
    properties(source) AS source_properties,
    coalesce(
        [node IN nodes(path) | {{
            id: node.id,
            labels: labels(node),
            properties: properties(node)
        }}],
        []
    ) AS nodes,
    coalesce(
        [relationship IN relationships(path) | {{
            id: relationship.relationship_id,
            type: type(relationship),
            source_id: startNode(relationship).id,
            target_id: endNode(relationship).id,
            properties: properties(relationship)
        }}],
        []
    ) AS relationships
LIMIT $limit
"""
