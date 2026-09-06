from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Mapping, Sequence

from .coverage import stable_id
from .integration import canonical_technology

PROJECT_MARKERS = {
    '.sln', '.csproj', '.vbproj', '.fsproj',
    'pom.xml', 'build.gradle', 'build.gradle.kts',
    'settings.gradle', 'settings.gradle.kts',
    'pyproject.toml', 'package.json',
}
IGNORE_DIRS = {
    '.git', '.svn', '.hg', 'node_modules', '.venv', 'venv', 'bin', 'obj',
    'target', 'build', '.idea', '.vs', '__pycache__', '.gradle', 'dist',
    '.e2e-regression', '.e2e', 'result', '.ai-task-runner',
}
TEXT_EXTENSIONS = {
    '.java', '.kt', '.kts', '.vb', '.cs', '.fs', '.py', '.js', '.ts', '.tsx', '.jsx',
    '.xml', '.yaml', '.yml', '.json', '.properties', '.ini', '.cfg', '.conf', '.sql', '.gradle',
}
WORKFLOW_NAME_RE = re.compile(r'(workflow|work-flow|flow|pipeline|process|block|node|jobgraph)', re.I)
BACKGROUND_LOOP_RE = re.compile(r'\bwhile\s*\(?(true|running|isRunning|!stop|!stopped)\b', re.I)
BACKGROUND_ACTIVITY_RE = re.compile(r'\b(sleep|wait|poll|query|select|receive|consume|fetch|dequeue|read)\b', re.I)
WORKFLOW_CONTENT_RE = re.compile(r'(<\s*(workflow|pipeline|process|block|node|step|transition|edge)\b|\b(workflow|pipeline|process|blocks?|nodes?|steps?|transitions?|edges?|activities?)\s*[:=])', re.I)

# Stage-0 patterns are deliberately structural and coarse. They are discovery hints,
# not business facts. AI still decides decomposition; Python only creates an accounting baseline.
ENTRYPOINT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ('http', re.compile(r'@(Get|Post|Put|Delete|Patch|Request)Mapping\b|@Path\b|@(GET|POST|PUT|DELETE|PATCH)\b|\bWebMethod\b|\bOperationContract\b', re.I)),
    ('grpc', re.compile(r'@GrpcService\b|\bBindableService\b|\bextends\s+\w+ImplBase\b|\bServerServiceDefinition\b|\bBindServiceMethod\b', re.I)),
    ('scheduler', re.compile(r'@Scheduled\b|\bQuartz\b|\bIHostedService\b|\bBackgroundService\b|\bHandles\s+\w+\.Tick\b|\bTimer_Tick\b', re.I)),
    ('consumer', re.compile(r'@KafkaListener\b|@RabbitListener\b|@JmsListener\b|\bMessageListener\b', re.I)),
    ('worker', re.compile(r'\bimplements\s+Runnable\b|\bextends\s+Thread\b|\bBackgroundWorker\b|\bWorker(Service)?\b|\bServiceBase\b|\bOnStart\s*\(|\bFileSystemWatcher\b|\bWatchService\b', re.I)),
    ('ui', re.compile(r'\bHandles\s+\w+\.(Click|SelectedIndexChanged|Load)\b|\bActionListener\b|@FXML\b|\bonClick\s*=', re.I)),
)
BOUNDARY_PATTERNS: tuple[tuple[str, str, str, re.Pattern[str]], ...] = (
    ('http', 'REQUEST_RESPONSE', 'HTTP', re.compile(r'\b(RestTemplate|WebClient|HttpClient|HttpURLConnection|requests\.|httpx\.|axios\.|fetch\s*\()', re.I)),
    ('grpc', 'REQUEST_RESPONSE', 'GRPC', re.compile(r'\bgrpc\b|\bManagedChannel\b|\bStub\b', re.I)),
    ('soap', 'REQUEST_RESPONSE', 'SOAP', re.compile(r'\bSOAP\b|\bWebServiceTemplate\b|@WebServiceClient\b', re.I)),
    ('kafka', 'MESSAGE', 'KAFKA', re.compile(r'\bKafka(Template|Producer|Consumer|Listener)\b|@KafkaListener\b', re.I)),
    ('nats', 'MESSAGE', 'NATS', re.compile(r'\bNATS\b|\bnats\.', re.I)),
    ('rabbitmq', 'MESSAGE', 'RABBITMQ', re.compile(r'\bRabbit(MQ|Template|Listener)?\b|@RabbitListener\b', re.I)),
    ('jms', 'MESSAGE', 'JMS', re.compile(r'\bJms(Template|Listener)?\b|@JmsListener\b|\bJMS\b', re.I)),
    ('ibm_mq', 'MESSAGE', 'IBM_MQ', re.compile(r'\bcom\.ibm\.mq\b|\bMQQueue\b|\bMQQueueManager\b|\bMQEnvironment\b|\bWMQ_\w+\b|\bMQJMS\b', re.I)),
    ('ibm_txseries', 'TRANSACTION', 'IBM_TXSERIES', re.compile(r'\bTXSeries\b|\bCICS\b|\bECI(Request|Interaction)?\b|\bCics(Connection|Interaction)?\b|\bCOMMAREA\b', re.I)),
    ('db', 'DB_STATE', 'GENERIC_DB', re.compile(r'\b(JdbcTemplate|EntityManager|SqlConnection|OleDbConnection|DbConnection|Repository)\b|\b(SELECT|INSERT|UPDATE|DELETE)\b', re.I)),
    ('file', 'FILE', 'GENERIC_FILE', re.compile(r'\b(FileStream|StreamReader|StreamWriter|Files\.|Path\.|open\s*\()', re.I)),
)
CONCURRENCY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ('lock', re.compile(r'\bsynchronized\b|\bLock\b|\bSemaphore\b|\bMutex\b|\bMonitor\.|\bInterlocked\b|\bSyncLock\b', re.I)),
    ('parallel', re.compile(r'\bCompletableFuture\b|\bExecutorService\b|\bparallelStream\b|\bTask\.Run\b|\bParallel\.|\basyncio\.gather\b|\bmultiprocessing\b', re.I)),
    ('idempotency', re.compile(r'\bidempoten(t|cy)\b|\bdedup(licate|lication)?\b', re.I)),
    ('optimistic_version', re.compile(r'@Version\b|\boptimistic\s+lock', re.I)),
)

# Stage-1 anchors are richer than Stage-0 hints. They are still syntactic facts, not final semantics.
ANCHOR_PATTERNS: tuple[tuple[str, str, re.Pattern[str], bool], ...] = (
    ('entrypoint', 'http_endpoint', re.compile(r'@(Get|Post|Put|Delete|Patch|Request)Mapping\b|@Path\b|@(GET|POST|PUT|DELETE|PATCH)\b|\bWebMethod\b|\bOperationContract\b', re.I), True),
    ('entrypoint', 'grpc_endpoint', re.compile(r'@GrpcService\b|\bBindableService\b|\bextends\s+\w+ImplBase\b|\bServerServiceDefinition\b|\bBindServiceMethod\b', re.I), True),
    ('entrypoint', 'scheduler', re.compile(r'@Scheduled\b|\bIHostedService\b|\bBackgroundService\b|\bHandles\s+\w+\.Tick\b|\bTimer_Tick\b', re.I), True),
    ('entrypoint', 'consumer', re.compile(r'@KafkaListener\b|@RabbitListener\b|@JmsListener\b|\bMessageListener\b', re.I), True),
    ('entrypoint', 'worker', re.compile(r'\bimplements\s+Runnable\b|\bextends\s+Thread\b|\bBackgroundWorker\b|\bwhile\s*\(?(true|running|isRunning|!stop|!stopped)\b', re.I), True),
    ('entrypoint', 'ui_action', re.compile(r'\bHandles\s+\w+\.(Click|SelectedIndexChanged|Load)\b|\bActionListener\b|@FXML\b|\bonClick\s*=', re.I), True),
    ('condition', 'condition', re.compile(r'^\s*(if\b|else\s+if\b|elseif\b|switch\b|case\b|Select\s+Case\b)', re.I), True),
    ('state_write', 'state_write', re.compile(r'\b(status|state|stage|phase)\b\s*(?::=|=(?!=))|\bset(Status|State|Stage|Phase)\s*\(', re.I), True),
    ('db_read', 'db_read', re.compile(r'\bSELECT\b|\bfind(By|All|One)?\b|\bquery\s*\(', re.I), True),
    ('db_write', 'db_write', re.compile(r'\b(INSERT|UPDATE|DELETE)\b|\b(save|persist|merge|executeUpdate)\s*\(', re.I), True),
    ('external_call', 'external_call', re.compile(r'\b(RestTemplate|WebClient|HttpClient|ManagedChannel|grpc|requests\.|httpx\.|axios\.|KafkaTemplate|JmsTemplate|RabbitTemplate|NATS|MQQueue|MQQueueManager|TXSeries|CICS|ECIRequest|ECIInteraction|COMMAREA)\b', re.I), True),
    ('message_publish', 'message_publish', re.compile(r'\b(send|publish)\s*\(', re.I), False),
    ('message_consume', 'message_consume', re.compile(r'@KafkaListener\b|@RabbitListener\b|@JmsListener\b|\bsubscribe\s*\(', re.I), True),
    ('exception_handler', 'exception_handler', re.compile(r'\bcatch\s*\(|^\s*except\b|\bCatch\s+\w+', re.I), True),
    ('retry', 'retry_policy', re.compile(r'\bretry\b|\bbackoff\b|\bmaxAttempts\b|@Retryable\b', re.I), True),
    ('transaction_control', 'transaction_control', re.compile(r'\b(commit|rollback|syncpoint|TransactionScope|BEGIN\s+TRANSACTION|COMMIT\s+TRANSACTION|ROLLBACK\s+TRANSACTION)\b', re.I), True),
    ('loop', 'loop', re.compile(r'^\s*(while\b|for\b|foreach\b|For\s+Each\b|Do\s+While\b)', re.I), False),
    ('completion', 'completion_candidate', re.compile(r'\b(DONE|COMPLETED|SUCCESS|FINISHED|COMPLETE)\b', re.I), False),
    ('concurrency_actor', 'concurrency_actor', re.compile(r'\bCompletableFuture\b|\bExecutorService\b|\bThreadPool\b|\bparallelStream\b|\bTask\.Run\b|\bParallel\.|\basyncio\.gather\b|\bmultiprocessing\b', re.I), True),
    ('concurrency_control', 'concurrency_control', re.compile(r'\bsynchronized\b|\bLock\b|\bSemaphore\b|\bMutex\b|@Version\b|\bidempoten(t|cy)\b', re.I), True),
)


def _iter_files(root: Path) -> Iterator[Path]:
    if not root.exists():
        return
    if root.is_file():
        if not any(part in IGNORE_DIRS for part in root.parts):
            yield root
        return
    for p in root.rglob('*'):
        if any(part in IGNORE_DIRS for part in p.parts):
            continue
        if p.is_file():
            yield p


def _read_lines(path: Path) -> list[str]:
    if path.suffix.lower() not in TEXT_EXTENSIONS and path.name not in {'pom.xml', 'package.json'}:
        return []
    try:
        return path.read_text(encoding='utf-8', errors='ignore').splitlines()
    except OSError:
        return []


def _relative_key(path: Path, roots: Sequence[Path]) -> str:
    rp = path.resolve()
    for idx, root in enumerate(roots):
        rr = root.resolve()
        try:
            return f'r{idx}/{rp.relative_to(rr).as_posix()}'
        except ValueError:
            continue
    return rp.as_posix()


def _nearest_project_root(path: Path, project_roots: Sequence[Path]) -> Path | None:
    rp = path.resolve()
    matches = []
    for root in project_roots:
        rr = root.resolve()
        try:
            rp.relative_to(rr)
            matches.append(rr)
        except ValueError:
            pass
    return max(matches, key=lambda p: len(p.parts)) if matches else None


def _make_hint(*, kind: str, path: Path, line: int, line_text: str, roots: Sequence[Path], project_root: Path | None, required: bool, subtype: str | None = None, extra: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    rel = _relative_key(path, roots)
    normalized = ' '.join(line_text.strip().split())[:240]
    semantic_key = f'{kind}|{subtype or ""}|{rel}|{line}|{normalized}'
    source = {'file': str(path.resolve()), 'line': line, 'contains': line_text.strip()}
    out = {
        'id': stable_id('HINT', semantic_key),
        'semantic_key': semantic_key,
        'kind': kind,
        'subtype': subtype,
        'required': required,
        'project_root': str(project_root) if project_root else None,
        'source': source,
    }
    if extra:
        out.update(dict(extra))
    return out


def scan_workspace_inventory(roots: Sequence[Path], *, auxiliary_roots: Sequence[Path] = ()) -> Dict[str, Any]:
    """Build the deterministic Stage-0 input inventory.

    `roots` are SUT source roots and exclusively own the Project denominator.
    `auxiliary_roots` are read-only materials such as DDL/config/workflow docs. They may
    contribute discovery hints/evidence, but can never become SUT projects. This keeps a
    writable test workspace separate from the source/material universe.
    """
    source_roots = sorted({Path(r).resolve() for r in roots if Path(r).exists()}, key=lambda p: p.as_posix())
    aux_roots = sorted({Path(r).resolve() for r in auxiliary_roots if Path(r).exists() and Path(r).resolve() not in source_roots}, key=lambda p: p.as_posix())
    all_roots = [*source_roots, *aux_roots]
    files: list[str] = []
    markers: list[Dict[str, Any]] = []
    file_paths: list[Path] = []
    source_file_paths: list[Path] = []

    for root in all_roots:
        is_source_root = root in source_roots
        for p in _iter_files(root):
            rp=p.resolve()
            file_paths.append(rp); files.append(str(rp))
            if is_source_root:
                source_file_paths.append(rp)
                if p.name in PROJECT_MARKERS or p.suffix.lower() in {'.sln', '.csproj', '.vbproj', '.fsproj'}:
                    markers.append({'file': str(rp), 'name': p.name, 'project_root': str(p.parent.resolve())})

    # Solution files are workspace aggregators, not concrete projects when child projects exist.
    concrete_markers = [m for m in markers if not str(m.get('name', '')).lower().endswith('.sln')]
    root_markers = concrete_markers if concrete_markers else markers
    marker_roots = sorted({Path(m['project_root']).resolve() for m in root_markers}, key=lambda p: p.as_posix())
    project_roots = list(marker_roots)

    # Only actual source roots may form unmarked project candidates. Auxiliary DDL/docs/config
    # must never inflate the project denominator.
    source_files=[p for p in source_file_paths if p.suffix.lower() in TEXT_EXTENSIONS and p.suffix.lower() not in {'.json','.yaml','.yml','.xml','.properties','.ini','.cfg','.conf','.sql'}]
    for root in source_roots:
        if root.is_file():
            continue
        unclaimed=[]
        for fp in source_files:
            try: rel=fp.relative_to(root)
            except ValueError: continue
            if any(fp == mr or mr in fp.parents for mr in marker_roots):
                continue
            unclaimed.append((fp,rel))
        if not unclaimed:
            continue
        clusters=set()
        for fp,rel in unclaimed:
            if len(rel.parts)<=1:
                clusters.add(root)
            else:
                clusters.add((root/rel.parts[0]).resolve())
        project_roots.extend(clusters)

    if not project_roots:
        for root in source_roots:
            if root.is_file():
                if root in source_files: project_roots.append(root.parent.resolve())
            elif any(root == p.parent or root in p.parents for p in source_files):
                project_roots.append(root)
    project_roots = sorted(set(project_roots), key=lambda p: p.as_posix())

    projects = []
    for pr in project_roots:
        rel = _relative_key(pr, source_roots or all_roots)
        related = [m for m in markers if Path(m['project_root']).resolve() == pr]
        projects.append({
            'id': stable_id('PRJ', rel),
            'semantic_key': f'project|{rel}',
            'path': str(pr),
            'marker_refs': [m['file'] for m in sorted(related, key=lambda x: x['file'])],
            'required': True,
        })

    hints: list[Dict[str, Any]] = []
    seen_hint_keys: set[tuple[str, str, str]] = set()
    counts = {'workflow_definitions': 0, 'entrypoints': 0, 'boundaries': 0, 'concurrency': 0}

    for p in sorted(set(file_paths), key=lambda x: x.as_posix()):
        lines = _read_lines(p)
        if not lines:
            continue
        pr = _nearest_project_root(p, project_roots)

        if p.suffix.lower() in {'.xml', '.yaml', '.yml', '.json', '.cfg', '.conf', '.properties'} and (WORKFLOW_NAME_RE.search(p.stem) or any(WORKFLOW_CONTENT_RE.search(line) for line in lines[:400])):
            nonempty_line = next(((i, x) for i, x in enumerate(lines, 1) if x.strip()), (1, lines[0] if lines else p.name))
            hints.append(_make_hint(kind='workflow_definition', path=p, line=nonempty_line[0], line_text=nonempty_line[1], roots=all_roots, project_root=pr, required=True)); counts['workflow_definitions'] += 1

        for i, line in enumerate(lines, 1):
            for subtype, pattern in ENTRYPOINT_PATTERNS:
                if pattern.search(line):
                    key = ('entrypoint', subtype, str(p.resolve()) if subtype=='worker' else str(p.resolve()) + f':{i}')
                    if key not in seen_hint_keys:
                        hints.append(_make_hint(kind='entrypoint', subtype=subtype, path=p, line=i, line_text=line, roots=all_roots, project_root=pr, required=True))
                        seen_hint_keys.add(key); counts['entrypoints'] += 1

        loop_match = next(((i, line) for i, line in enumerate(lines, 1) if BACKGROUND_LOOP_RE.search(line)), None)
        if loop_match and any(BACKGROUND_ACTIVITY_RE.search(line) for line in lines[max(0,loop_match[0]-1):min(len(lines),loop_match[0]+12)]):
            key=('entrypoint','worker',str(p.resolve()))
            if key not in seen_hint_keys:
                hints.append(_make_hint(kind='entrypoint', subtype='worker', path=p, line=loop_match[0], line_text=loop_match[1], roots=all_roots, project_root=pr, required=True))
                seen_hint_keys.add(key); counts['entrypoints'] += 1

        for subtype, mode, technology, pattern in BOUNDARY_PATTERNS:
            match = next(((i, line) for i, line in enumerate(lines, 1) if pattern.search(line)), None)
            if match:
                key = ('boundary', subtype, str(p.resolve()))
                if key not in seen_hint_keys:
                    hints.append(_make_hint(kind='boundary', subtype=subtype, path=p, line=match[0], line_text=match[1], roots=all_roots, project_root=pr, required=False, extra={'integration': {'mode': mode, 'technology': canonical_technology(technology)}}))
                    seen_hint_keys.add(key); counts['boundaries'] += 1
        for subtype, pattern in CONCURRENCY_PATTERNS:
            match = next(((i, line) for i, line in enumerate(lines, 1) if pattern.search(line)), None)
            if match:
                key = ('concurrency', subtype, str(p.resolve()))
                if key not in seen_hint_keys:
                    hints.append(_make_hint(kind='concurrency', subtype=subtype, path=p, line=match[0], line_text=match[1], roots=all_roots, project_root=pr, required=False))
                    seen_hint_keys.add(key); counts['concurrency'] += 1

    manifest = {
        'filesystem': {'completed': True, 'count': len(set(files))},
        'project_markers': {'completed': True, 'count': len(markers)},
        'project_candidates': {'completed': True, 'count': len(projects)},
        'workflow_definitions': {'completed': True, 'count': counts['workflow_definitions']},
        'entrypoints': {'completed': True, 'count': counts['entrypoints']},
        'boundaries': {'completed': True, 'count': counts['boundaries']},
        'concurrency': {'completed': True, 'count': counts['concurrency']},
    }
    return {
        'roots': [str(r) for r in all_roots],
        'source_roots': [str(r) for r in source_roots],
        'auxiliary_roots': [str(r) for r in aux_roots],
        'files': sorted(set(files)),
        'project_markers': sorted(markers, key=lambda x: x['file']),
        'project_roots': [str(p) for p in project_roots],
        'projects': projects,
        'discovery_hints': sorted(hints, key=lambda x: x['id']),
        'scanner_manifest': manifest,
    }


def scan_analysis_unit_anchors(files: Sequence[Path], *, analysis_unit_id: str, project_id: str, roots: Sequence[Path] | None = None) -> Dict[str, Any]:
    """Create a deterministic Anchor Universe for one AI analysis unit.

    Anchors force accounting of source-level facts; they do not themselves establish
    business meaning or global E2E flow.
    """
    roots = [Path(r).resolve() for r in (roots or [])]
    file_paths = sorted({Path(p).resolve() for p in files if Path(p).exists() and Path(p).is_file()}, key=lambda p: p.as_posix())
    if not roots:
        roots = sorted({p.parent for p in file_paths}, key=lambda p: p.as_posix())
    anchors: list[Dict[str, Any]] = []
    evidence: list[Dict[str, Any]] = []

    for p in file_paths:
        lines = _read_lines(p)
        for i, line in enumerate(lines, 1):
            for kind, evidence_type, pattern, required in ANCHOR_PATTERNS:
                if not pattern.search(line):
                    continue
                rel = _relative_key(p, roots)
                normalized = ' '.join(line.strip().split())[:240]
                semantic_key = f'{analysis_unit_id}|{kind}|{rel}|{i}|{normalized}'
                aid = stable_id('AN', semantic_key)
                evid = stable_id('EV', semantic_key)
                anchors.append({
                    'id': aid,
                    'semantic_key': semantic_key,
                    'analysis_unit_ref': analysis_unit_id,
                    'project_ref': project_id,
                    'kind': kind,
                    'required': required,
                    'evidence_ref': evid,
                })
                evidence.append({
                    'id': evid,
                    'project': project_id,
                    'type': evidence_type,
                    'source': {'file': str(p), 'line': i, 'contains': line.strip()},
                })

    # Exact semantic duplicates can occur when multiple regexes hit the same line; ID makes them deterministic.
    anchors_by_id = {a['id']: a for a in anchors}
    evidence_by_id = {e['id']: e for e in evidence}
    return {
        'analysis_unit_ref': analysis_unit_id,
        'anchors': [anchors_by_id[k] for k in sorted(anchors_by_id)],
        'evidence': [evidence_by_id[k] for k in sorted(evidence_by_id)],
        'scanner_manifest': {
            'analysis_unit_anchors': {'completed': True, 'count': len(anchors_by_id)},
            'files_scanned': {'completed': True, 'count': len(file_paths)},
        },
    }
