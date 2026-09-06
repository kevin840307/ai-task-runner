from __future__ import annotations

from typing import Any, Dict, Mapping

INTEGRATION_MODES = {
    'REQUEST_RESPONSE', 'MESSAGE', 'TRANSACTION', 'DB_STATE', 'FILE',
    'WORKFLOW', 'DIRECT_CALL', 'UI', 'OTHER',
}
INTEGRATION_DIRECTIONS = {'INBOUND', 'OUTBOUND', 'BIDIRECTIONAL', 'INTERNAL'}

# Technology is intentionally open-ended. These aliases only canonicalize known names;
# unknown enterprise middleware remains valid as an uppercase technology identifier.
TECH_ALIASES = {
    'http': 'HTTP', 'https': 'HTTP', 'rest': 'HTTP',
    'grpc': 'GRPC', 'soap': 'SOAP',
    'kafka': 'KAFKA', 'nats': 'NATS', 'rabbitmq': 'RABBITMQ', 'rabbit': 'RABBITMQ',
    'jms': 'JMS', 'ibm_mq': 'IBM_MQ', 'ibmmq': 'IBM_MQ', 'mqseries': 'IBM_MQ',
    'ibm_txseries': 'IBM_TXSERIES', 'txseries': 'IBM_TXSERIES', 'cics': 'IBM_TXSERIES',
    'db': 'GENERIC_DB', 'database': 'GENERIC_DB', 'file': 'GENERIC_FILE',
}
LEGACY_PROTOCOL_TO_MODE = {
    'http': ('REQUEST_RESPONSE', 'HTTP'),
    'grpc': ('REQUEST_RESPONSE', 'GRPC'),
    'kafka': ('MESSAGE', 'KAFKA'),
    'nats': ('MESSAGE', 'NATS'),
    'rabbitmq': ('MESSAGE', 'RABBITMQ'),
    'jms': ('MESSAGE', 'JMS'),
    'ibm_mq': ('MESSAGE', 'IBM_MQ'),
    'ibm_txseries': ('TRANSACTION', 'IBM_TXSERIES'),
    'cics': ('TRANSACTION', 'IBM_TXSERIES'),
    'db': ('DB_STATE', 'GENERIC_DB'),
    'file': ('FILE', 'GENERIC_FILE'),
    'other': ('OTHER', 'OTHER'),
}
LEGACY_EDGE_TO_BOUNDARY = {
    'HTTP_MATCH': ('REQUEST_RESPONSE', 'HTTP'),
    'GRPC_MATCH': ('REQUEST_RESPONSE', 'GRPC'),
    'KAFKA_MATCH': ('MESSAGE', 'KAFKA'),
    'NATS_MATCH': ('MESSAGE', 'NATS'),
    'RABBITMQ_MATCH': ('MESSAGE', 'RABBITMQ'),
    'JMS_MATCH': ('MESSAGE', 'JMS'),
    'DB_STATE_MATCH': ('DB_STATE', 'GENERIC_DB'),
    'FILE_MATCH': ('FILE', 'GENERIC_FILE'),
    'WORKFLOW_EDGE': ('WORKFLOW', 'WORKFLOW'),
    'DIRECT_CALL': ('DIRECT_CALL', 'DIRECT_CALL'),
}


def canonical_technology(value: Any) -> str:
    raw = str(value or '').strip()
    if not raw:
        return ''
    key = raw.lower().replace('-', '_').replace(' ', '_')
    return TECH_ALIASES.get(key, raw.upper().replace('-', '_').replace(' ', '_'))


def canonical_direction(value: Any) -> str:
    raw = str(value or '').strip().lower()
    return {
        'in': 'INBOUND', 'inbound': 'INBOUND', 'consume': 'INBOUND', 'consumer': 'INBOUND',
        'out': 'OUTBOUND', 'outbound': 'OUTBOUND', 'publish': 'OUTBOUND', 'producer': 'OUTBOUND',
        'both': 'BIDIRECTIONAL', 'bidirectional': 'BIDIRECTIONAL',
        'internal': 'INTERNAL',
    }.get(raw, str(value or '').strip().upper())


def canonical_boundary(boundary: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the generic boundary shape, accepting V5 protocol-based input as compatibility.

    The function is intentionally non-destructive: unknown technologies are retained and do not
    require a core enum change.
    """
    b = dict(boundary)
    mode = str(b.get('mode') or '').strip().upper()
    tech = canonical_technology(b.get('technology'))
    if not mode and b.get('protocol') is not None:
        mode, default_tech = LEGACY_PROTOCOL_TO_MODE.get(str(b.get('protocol')).lower(), ('OTHER', canonical_technology(b.get('protocol')) or 'OTHER'))
        tech = tech or default_tech
    direction = canonical_direction(b.get('direction'))
    out = {
        'mode': mode,
        'technology': tech,
        'direction': direction,
        'operation': dict(b.get('operation') or {}),
        'address': dict(b.get('address') or {}),
        'semantics': dict(b.get('semantics') or {}),
    }
    # Legacy fields are mapped into generic address/operation when possible.
    target = b.get('target')
    if target and not out['address']:
        out['address'] = {'target': target}
    for field in ('transaction_id', 'region', 'program'):
        if b.get(field) is not None and field not in out['operation']:
            out['operation'][field] = b.get(field)
    if b.get('evidence_ref'):
        out['evidence_ref'] = b.get('evidence_ref')
    if b.get('evidence_refs'):
        out['evidence_refs'] = list(b.get('evidence_refs') or [])
    return out


def boundary_signature(boundary: Mapping[str, Any]) -> tuple[str, str]:
    b = canonical_boundary(boundary)
    return b['mode'], b['technology']


def edge_expected_boundary(edge: Mapping[str, Any]) -> tuple[str, str] | None:
    if edge.get('type') == 'INTEGRATION':
        channel = edge.get('channel') or edge.get('boundary') or {}
        b = canonical_boundary(channel)
        return (b['mode'], b['technology']) if b['mode'] and b['technology'] else None
    return LEGACY_EDGE_TO_BOUNDARY.get(str(edge.get('type') or ''))


def boundary_match_fields(mode: str, technology: str) -> tuple[str, ...]:
    """Fields that normally identify the same logical integration endpoint.

    These are not all mandatory. Flow Resolution may use evidence/runtime bridging when a field
    is unavailable, but when both sides provide a field, values must agree.
    """
    tech = canonical_technology(technology)
    if mode == 'REQUEST_RESPONSE' and tech == 'HTTP':
        return ('method', 'path')
    if mode == 'REQUEST_RESPONSE' and tech == 'GRPC':
        return ('service', 'method')
    if mode == 'MESSAGE' and tech == 'KAFKA':
        return ('topic',)
    if mode == 'MESSAGE' and tech == 'NATS':
        return ('subject',)
    if mode == 'MESSAGE' and tech in {'RABBITMQ', 'JMS', 'IBM_MQ'}:
        return ('queue', 'topic')
    if mode == 'TRANSACTION' and tech == 'IBM_TXSERIES':
        return ('transaction_id', 'region', 'program')
    if mode == 'DB_STATE':
        return ('table', 'field', 'value', 'business_key')
    if mode == 'FILE':
        return ('path', 'pattern')
    return ()
