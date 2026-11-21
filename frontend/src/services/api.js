const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api'

async function request(path, options = {}) {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const body = await response.json()
      detail = body.detail || body.message || detail
    } catch {}
    throw new Error(detail)
  }
  const body = await response.json()
  return body?.success === true && 'data' in body ? body.data : body
}

function normalizeEntity(entity) {
  const properties = entity.properties || entity
  return {
    ...entity,
    ...properties,
    id: entity.id || properties.id,
    name: entity.name || properties.name,
    type: entity.type || properties.type || entity.labels?.[0],
    properties,
  }
}

function normalizeRelationship(relationship) {
  const properties = relationship.properties || {}
  return {
    ...relationship,
    id: relationship.id || properties.relationship_id,
    source: relationship.source || relationship.source_id,
    target: relationship.target || relationship.target_id,
    type: relationship.type || properties.relationship_type,
  }
}

function normalizeIncident(incident) {
  return {
    ...incident,
    severity: incident.severity || incident.priority,
    associated_alerts: incident.associated_alerts || (incident.related_event_id ? [incident.related_event_id] : []),
  }
}

function normalizeInvestigation(investigation) {
  return {
    ...investigation,
    notes: (investigation.notes || []).map((entry) => ({
      ...entry,
      note: entry.note || entry.content,
    })),
  }
}

function normalizeThreat(threat) {
  const id = threat.id || threat.threat_id || threat.event_id
  return {
    ...threat,
    id,
    threat_id: id,
    category: threat.category || threat.event_type || threat.attack_category,
    entity_id: threat.entity_id || threat.source_entity_id,
    associated_entities: threat.associated_entities || (threat.entity_id ? [threat.entity_id] : []),
    detection_timestamp: threat.detection_timestamp || threat.event_time,
  }
}

function normalizeSubgraph(graph) {
  const nodes = (graph.nodes || []).map(normalizeEntity)
  const root = graph.root ? normalizeEntity(graph.root) : null
  if (root && !nodes.some((node) => String(node.id) === String(root.id))) nodes.unshift(root)
  return {
    ...graph,
    nodes,
    edges: (graph.edges || graph.relationships || []).map(normalizeRelationship),
  }
}

export const api = {
  dashboard: async () => {
    const data = await request('/dashboard/overview')
    return data.counts ? { ...data.counts } : data
  },
  threatDistribution: async () => {
    const data = await request('/dashboard/threat-distribution')
    if (data.by_severity) return data
    const by_severity = {}
    for (const item of data.distribution || []) {
      by_severity[item.severity] = (by_severity[item.severity] || 0) + item.count
    }
    return { by_severity }
  },
  recentActivity: async () => {
    const data = await request('/dashboard/recent-activity')
    if (data.items) return data
    return {
      items: (data.events || []).map((event) => ({
        ...event,
        id: event.id || event.event_id,
        description: event.description || event.event_type,
        timestamp: event.timestamp || event.event_time,
      })),
    }
  },
  graphEntities: async (params = {}) => {
    const query = new URLSearchParams(params).toString()
    const data = await request('/graph/entities' + (query ? '?' + query : ''))
    return { ...data, items: (data.items || data.entities || []).map(normalizeEntity) }
  },
  graphSubgraph: async (id, depth = 2) => {
    const data = await request('/graph/subgraph/' + encodeURIComponent(id) + '?depth=' + depth)
    return normalizeSubgraph(data)
  },
  graphEntity: async (id) => normalizeEntity(await request('/graph/entity/' + encodeURIComponent(id))),
  threats: async (params = {}) => {
    const query = new URLSearchParams({ limit: '20' }).toString()
    const data = await request('/threats' + (query ? '?' + query : ''))
    const items = (data.items || data.threats || []).map(normalizeThreat)
    return { ...data, items: params.severity ? items.filter((item) => item.severity?.toLowerCase() === params.severity.toLowerCase()) : items }
  },
  threat: async (id) => {
    const threat = normalizeThreat(await request('/threats/' + encodeURIComponent(id)))
    const evidence = await api.threatEvidence(id)
    return { ...threat, evidence: evidence.items[0] || null }
  },
  threatEvidence: async (id) => {
    const data = await request('/threats/evidence/' + encodeURIComponent(id))
    return { ...data, items: data.items || data.evidence || [] }
  },
  blastRadius: async (id, depth = 3) => {
    const data = await request('/blast-radius/' + encodeURIComponent(id) + '?depth=' + depth)
    const relationships = (data.relationships || []).map(normalizeRelationship)
    const entities = (data.entities || data.affected_entities || []).map(normalizeEntity)
    const source = data.source_entity ? normalizeEntity(data.source_entity) : null
    return {
      ...data,
      nodes: source ? [source, ...entities] : entities,
      edges: relationships,
      affected_entities: entities,
      reachable_entities_count: data.reachable_entities_count ?? data.reachable_entity_count,
      critical_assets_count: data.critical_assets_count ?? data.critical_infrastructure_exposure,
    }
  },
  incidents: async () => {
    const data = await request('/incidents')
    return { ...data, items: (data.items || data.incidents || []).map(normalizeIncident) }
  },
  incident: async (id) => normalizeIncident(await request('/incidents/' + encodeURIComponent(id))),
  containment: async (payload) => {
    const graph = await api.graphSubgraph(payload.entity_id, payload.depth)
    const actionTypes = {
      isolate_host: { action: 'isolate_entity', type: 'host', label: 'host' },
      disable_account: { action: 'disable_account', type: 'user', label: 'user account' },
      block_ip: { action: 'block_ip', type: 'ipaddress', label: 'IP address' },
      restrict_server: { action: 'restrict_server', type: 'server', label: 'server' },
    }
    const actions = payload.actions.map((id) => {
      const config = actionTypes[id]
      if (!config) throw new Error(`Unsupported containment action: ${id}`)
      const target = graph.nodes.find((node) => String(node.type || '').toLowerCase() === config.type)
      if (!target) throw new Error(`No related ${config.label} is available for this simulation.`)
      return { action: config.action, target_entity_id: target.id }
    })
    const data = await request('/containment/simulate', {
      method: 'POST',
      body: JSON.stringify({ source_entity_id: payload.entity_id, depth: payload.depth, actions }),
    })
    return {
      ...data,
      before: {
        reachable_entities_count: data.before.potentially_affected_entities,
        critical_assets_remaining: data.before.critical_assets_reachable,
        potentially_affected_users: data.before.users_potentially_affected,
        residual_risk: 'Baseline potential exposure',
      },
      after: {
        reachable_entities_count: data.after.remaining_exposed_entities,
        critical_assets_remaining: data.after.critical_assets_still_reachable,
        potentially_affected_users: data.after.users_still_potentially_affected,
        residual_risk: `${data.residual_exposure_percent}% of modeled exposure remains`,
      },
    }
  },
  investigations: async () => {
    const data = await request('/investigations')
    return { ...data, items: (data.items || data.investigations || []).map(normalizeInvestigation) }
  },
  createInvestigation: async (payload) => {
    const data = await request('/investigations', {
      method: 'POST',
      body: JSON.stringify({
        title: payload.title,
        alert_id: payload.alert_id || payload.event_id || null,
        entity_ids: payload.entity_ids || [],
      }),
    })
    return normalizeInvestigation(data)
  },
  investigation: async (id) => normalizeInvestigation(await request('/investigations/' + encodeURIComponent(id))),
  addNote: async (id, payload) => normalizeInvestigation(await request('/investigations/' + encodeURIComponent(id) + '/notes', {
    method: 'POST',
    body: JSON.stringify({ content: payload.content || payload.note }),
  })),
}
