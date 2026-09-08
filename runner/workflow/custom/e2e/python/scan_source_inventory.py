#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml

SKIP_DIRS = {'.git', '.svn', '.hg', '.idea', '.vs', 'bin', 'obj', 'target', 'build', 'dist', 'node_modules', '.venv', 'venv', '__pycache__', '.ai-task-runner', 'result'}
SOURCE_EXTS = {'.java': 'java', '.vb': 'vbnet', '.py': 'python'}
CONFIG_EXTS = {'.properties', '.ini', '.cfg', '.yaml', '.yml', '.json', '.xml', '.config'}
MAX_FILE_BYTES = 4 * 1024 * 1024
TAIL_FILE_BYTES = 512 * 1024

ENTRY_PATTERNS: dict[str, list[tuple[str, re.Pattern[str]]]] = {
    'java': [
        ('http', re.compile(r'@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)\b')),
        ('scheduler', re.compile(r'@Scheduled\b')),
        ('kafka_consumer', re.compile(r'@KafkaListener\b')),
        ('mq_consumer', re.compile(r'@(RabbitListener|JmsListener)\b')),
        ('application', re.compile(r'public\s+static\s+void\s+main\s*\(')),
    ],
    'vbnet': [
        ('application', re.compile(r'\bSub\s+Main\s*\(', re.I)),
        ('service_start', re.compile(r'\bOverrides\s+Sub\s+OnStart\s*\(', re.I)),
        ('timer', re.compile(r'\bHandles\s+\w+\.(Tick|Elapsed)\b', re.I)),
        ('http', re.compile(r'<(WebMethod|HttpGet|HttpPost|Route)\b', re.I)),
        ('message_consumer', re.compile(r'\b(Subscribe|Receive|Consume)\s*\(', re.I)),
    ],
    'python': [
        ('application', re.compile(r'if\s+__name__\s*==\s*[\'\"]__main__[\'\"]\s*:')),
        ('http', re.compile(r'@\w+\.(get|post|put|delete|patch|route)\s*\(', re.I)),
        ('scheduler', re.compile(r'@(scheduled|scheduler|repeat_every|cron)\b', re.I)),
        ('worker', re.compile(r'@(app\.)?task\s*\(', re.I)),
        ('message_consumer', re.compile(r'\b(subscribe|consume|receive)\s*\(', re.I)),
    ],
}

INTEGRATION_PATTERNS = [
    ('kafka', re.compile(r'\b(kafka|topic|KafkaTemplate|KafkaListener)\b', re.I)),
    ('nats', re.compile(r'\b(nats|subject|publish\s*\(|subscribe\s*\()\b', re.I)),
    ('mq', re.compile(r'\b(rabbitmq|rabbit|jms|queue|messagequeue|send\s*\(|receive\s*\()\b', re.I)),
    ('http', re.compile(r'\b(http://|https://|HttpClient|RestTemplate|WebClient|requests\.|httpx\.|urllib)\b', re.I)),
    ('scheduler', re.compile(r'\b(cron|scheduled|scheduler|timer|elapsed|tick)\b', re.I)),
]

SYSTEM_PARAM_PATTERNS = [
    re.compile(r'ConfigurationManager\.AppSettings(?:\s*\[|\s*\()\s*[\'\"]([^\'\"]+)', re.I),
    re.compile(r'GetEnvironmentVariable\s*\(\s*[\'\"]([^\'\"]+)', re.I),
    re.compile(r'System\.getenv\s*\(\s*[\'\"]([^\'\"]+)', re.I),
    re.compile(r'@Value\s*\(\s*[\'\"]\$\{([^}:]+)', re.I),
    re.compile(r'os\.getenv\s*\(\s*[\'\"]([^\'\"]+)', re.I),
    re.compile(r'os\.environ(?:\.get)?\s*\(??\s*[\'\"]([^\'\"]+)', re.I),
]
USER_PARAM_PATTERNS = [
    re.compile(r'@(RequestParam|PathVariable)\s*(?:\([^)]*\))?\s+[\w<>?,. ]+\s+(\w+)', re.I),
    re.compile(r'Request\.(?:QueryString|Form)\s*\(\s*[\'\"]([^\'\"]+)', re.I),
    re.compile(r'Console\.ReadLine\s*\(', re.I),
    re.compile(r'input\s*\(', re.I),
    re.compile(r'sys\.argv\b', re.I),
]

SQL_PATTERNS = [
    ('select', re.compile(r'\bSELECT\b[\s\S]{0,1200}?\bFROM\s+([\[\]`"\w.$#]+)', re.I)),
    ('insert', re.compile(r'\bINSERT\s+INTO\s+([\[\]`"\w.$#]+)', re.I)),
    ('update', re.compile(r'\bUPDATE\s+([\[\]`"\w.$#]+)\s+SET\b', re.I)),
    ('delete', re.compile(r'\bDELETE\s+FROM\s+([\[\]`"\w.$#]+)', re.I)),
    ('merge', re.compile(r'\bMERGE\s+(?:INTO\s+)?([\[\]`"\w.$#]+)', re.I)),
    ('stored_procedure', re.compile(r'\b(?:EXEC(?:UTE)?|CALL)\s+([\[\]`"\w.$#]+)', re.I)),
]


DYNAMIC_RISK_PATTERNS = [
    ('reflection', re.compile(r'\b(?:Class\.forName|Method\.invoke|Assembly\.Load|Assembly\.LoadFrom|Activator\.CreateInstance|getattr\s*\(|importlib\.|__import__\s*\()', re.I)),
    ('dynamic_sql', re.compile(r'\b(?:SELECT|INSERT|UPDATE|DELETE|MERGE)\b[^\n]{0,240}(?:\+|StringBuilder|format\s*\(|f[\'"]|\$\")', re.I)),
    ('dynamic_topic_or_queue', re.compile(r'\b(?:topic|queue|subject|destination)\b[^\n]{0,160}(?:\+|format\s*\(|StringBuilder|\$\")', re.I)),
    ('factory_or_di', re.compile(r'\b(?:Factory|ServiceProvider|GetService|GetInstance|Resolve|dependency[_ ]?inject|ApplicationContext|getBean)\b', re.I)),
]


def stable_id(prefix: str, *parts: object) -> str:
    raw = '|'.join(str(p) for p in parts).encode('utf-8', errors='ignore')
    return f"{prefix}_{hashlib.sha1(raw).hexdigest()[:10].upper()}"


def rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def iter_files(root: Path):
    for path in root.rglob('*'):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def read_text(path: Path) -> tuple[str, dict[str, Any]]:
    """Best-effort legacy-safe reader.

    Important: a partial/failed decode is reported as a scanner limitation; callers must
    not interpret a miss from such a file as proof that the construct does not exist.
    """
    meta: dict[str, Any] = {'path': str(path), 'status': 'ok', 'encoding': None, 'truncated': False}
    try:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            with path.open('rb') as fh:
                head = fh.read(MAX_FILE_BYTES - TAIL_FILE_BYTES)
                fh.seek(max(0, size - TAIL_FILE_BYTES))
                tail = fh.read(TAIL_FILE_BYTES)
            data = head + b'\n...<scanner-bounded>...\n' + tail
            meta['status'] = 'bounded'
            meta['truncated'] = True
            meta['bytes_total'] = size
            meta['bytes_scanned'] = len(head) + len(tail)
        else:
            data = path.read_bytes()
            meta['bytes_total'] = size
            meta['bytes_scanned'] = size
        # Common encodings in modern and legacy Java/VB.NET/Python repositories.
        encodings=['utf-8-sig']
        if data.startswith((b'\xff\xfe', b'\xfe\xff')) or (data and data.count(b'\x00')/len(data) > 0.15):
            encodings.append('utf-16')
        encodings += ['cp950', 'big5', 'cp1252', 'latin1']
        for enc in encodings:
            try:
                text_value = data.decode(enc)
                meta['encoding'] = enc
                if enc not in {'utf-8-sig'} and meta['status'] == 'ok':
                    meta['status'] = 'decoded_non_utf8'
                return text_value, meta
            except UnicodeDecodeError:
                continue
        meta['status'] = 'decode_failed'
        return data.decode('utf-8', errors='ignore'), meta
    except OSError as exc:
        meta['status'] = 'read_failed'
        meta['error'] = str(exc)
        return '', meta


def line_no(text: str, pos: int) -> int:
    return text.count('\n', 0, pos) + 1


def clean_sql_name(name: str) -> str:
    return name.strip().strip('[]`"').rstrip(';,')


def detect_projects(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    markers = {'*.vbproj': 'vbnet', 'pom.xml': 'java', 'build.gradle': 'java', 'build.gradle.kts': 'java', 'pyproject.toml': 'python', 'setup.py': 'python'}
    seen_dirs: set[tuple[str, str]] = set()
    for pattern, language in markers.items():
        matches = root.rglob(pattern) if '*' in pattern else root.rglob(pattern)
        for p in matches:
            if not p.is_file() or any(part in SKIP_DIRS for part in p.parts):
                continue
            key = (str(p.parent.resolve()), language)
            if key in seen_dirs:
                continue
            seen_dirs.add(key)
            name = p.stem if p.suffix in {'.vbproj', '.csproj'} else p.parent.name
            rows.append({'id': stable_id('PRJ', rel(root, p.parent), language), 'name': name, 'language': language, 'path': rel(root, p.parent), 'marker': rel(root, p)})
    if not rows:
        langs = sorted({SOURCE_EXTS[p.suffix.lower()] for p in iter_files(root) if p.suffix.lower() in SOURCE_EXTS})
        for lang in langs:
            rows.append({'id': stable_id('PRJ', '.', lang), 'name': root.name, 'language': lang, 'path': '.', 'marker': None})
    return sorted(rows, key=lambda x: (x['language'], x['path']))


def scan(root: Path) -> dict[str, Any]:
    projects = detect_projects(root)
    source_files: list[dict[str, Any]] = []
    entrypoints: list[dict[str, Any]] = []
    integrations: list[dict[str, Any]] = []
    sql_ops: list[dict[str, Any]] = []
    system_params: list[dict[str, Any]] = []
    user_params: list[dict[str, Any]] = []
    config_keys: list[dict[str, Any]] = []
    log_candidates: list[dict[str, Any]] = []
    scanner_limitations: list[dict[str, Any]] = []
    dynamic_candidates: list[dict[str, Any]] = []

    for path in iter_files(root):
        suffix = path.suffix.lower()
        language = SOURCE_EXTS.get(suffix)
        is_config = suffix in CONFIG_EXTS
        if not language and not is_config:
            continue
        rpath = rel(root, path)
        content, read_meta = read_text(path)
        if read_meta.get('status') != 'ok':
            scanner_limitations.append({
                'id': stable_id('LIM', rpath, read_meta.get('status')),
                'type': 'source_read', 'path': rpath,
                'status': read_meta.get('status'), 'encoding': read_meta.get('encoding'),
                'truncated': bool(read_meta.get('truncated')),
                'details': {k:v for k,v in read_meta.items() if k not in {'path','status','encoding','truncated'}},
                'impact': 'candidate discovery may be incomplete; do not treat scanner miss as proof of absence',
            })
        if language:
            source_files.append({'path': rpath, 'language': language, 'bytes': path.stat().st_size, 'scan_status': read_meta.get('status'), 'encoding': read_meta.get('encoding'), 'truncated': bool(read_meta.get('truncated'))})
            for kind, pattern in ENTRY_PATTERNS.get(language, []):
                for m in pattern.finditer(content):
                    ln = line_no(content, m.start())
                    entrypoints.append({'id': stable_id('EP', rpath, ln, kind), 'type': kind, 'path': rpath, 'line': ln, 'match': m.group(0)[:180]})
            for kind, pattern in INTEGRATION_PATTERNS:
                for m in pattern.finditer(content):
                    ln = line_no(content, m.start())
                    integrations.append({'id': stable_id('INT', rpath, ln, kind, m.group(0)[:80]), 'type': kind, 'path': rpath, 'line': ln, 'match': m.group(0)[:180]})
            for op, pattern in SQL_PATTERNS:
                for m in pattern.finditer(content):
                    name = clean_sql_name(m.group(1))
                    ln = line_no(content, m.start())
                    sql_ops.append({'id': stable_id('SQL', rpath, ln, op, name), 'operation': op, 'object': name, 'path': rpath, 'line': ln})
            for pattern in SYSTEM_PARAM_PATTERNS:
                for m in pattern.finditer(content):
                    key = m.group(1) if m.lastindex else m.group(0)
                    ln = line_no(content, m.start())
                    system_params.append({'id': stable_id('SYS', rpath, ln, key), 'name': key, 'path': rpath, 'line': ln, 'source': 'code'})
            for pattern in USER_PARAM_PATTERNS:
                for m in pattern.finditer(content):
                    if m.lastindex:
                        key = m.group(m.lastindex)
                    else:
                        key = m.group(0).strip()
                    ln = line_no(content, m.start())
                    user_params.append({'id': stable_id('USR', rpath, ln, key), 'name': key, 'path': rpath, 'line': ln, 'source': 'code'})
            # Candidate logging statements for outcome observability. This is intentionally
            # deterministic discovery only; AI decides whether a log is business-relevant.
            log_patterns = [
                ('java_logger', re.compile(r'\b(?:log|logger)\.(?:trace|debug|info|warn|error)\s*\(', re.I)),
                ('vbnet_logger', re.compile(r'\b(?:Trace|Debug|Logger|Log)\.(?:WriteLine|Write|Info|Warn|Error|Debug)\s*\(', re.I)),
                ('python_logger', re.compile(r'\b(?:logging|logger)\.(?:debug|info|warning|warn|error|exception|critical)\s*\(', re.I)),
                ('console', re.compile(r'\b(?:Console\.WriteLine|print)\s*\(', re.I)),
            ]
            for kind, pattern in log_patterns:
                for m in pattern.finditer(content):
                    ln=line_no(content,m.start())
                    line=content.splitlines()[ln-1].strip() if ln-1 < len(content.splitlines()) else m.group(0)
                    log_candidates.append({'id': stable_id('LOG', rpath, ln, kind), 'type': kind, 'path': rpath, 'line': ln, 'match': line[:240]})
            for kind, pattern in DYNAMIC_RISK_PATTERNS:
                for m in pattern.finditer(content):
                    ln=line_no(content,m.start())
                    dynamic_candidates.append({'id': stable_id('DYN', rpath, ln, kind), 'type': kind, 'path': rpath, 'line': ln, 'match': m.group(0)[:240], 'impact': 'static scanner may not resolve the runtime target; require direct evidence / Grill review'})
        if is_config:
            for ln, line in enumerate(content.splitlines(), 1):
                s = line.strip()
                if not s or s.startswith(('#', ';', '//')):
                    continue
                m = re.match(r'[\'\"]?([A-Za-z_][\w.:-]{1,120})[\'\"]?\s*[:=]', s)
                if m:
                    key = m.group(1)
                    config_keys.append({'id': stable_id('CFG', rpath, ln, key), 'name': key, 'path': rpath, 'line': ln})

    def dedupe(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
        seen = set(); out=[]
        for row in rows:
            key = tuple(row.get(k) for k in keys)
            if key in seen: continue
            seen.add(key); out.append(row)
        return out

    entrypoints = dedupe(entrypoints, ('id',))
    integrations = dedupe(integrations, ('id',))
    sql_ops = dedupe(sql_ops, ('operation','object','path','line'))
    system_params = dedupe(system_params, ('name','path','line'))
    user_params = dedupe(user_params, ('name','path','line'))
    config_keys = dedupe(config_keys, ('name','path','line'))
    log_candidates = dedupe(log_candidates, ('path','line','type'))
    scanner_limitations = dedupe(scanner_limitations, ('path','status','type'))
    dynamic_candidates = dedupe(dynamic_candidates, ('path','line','type'))
    languages = sorted({x['language'] for x in source_files})
    return {
        'version': 2,
        'root': str(root),
        'languages': languages,
        'projects': projects,
        'source_files': source_files,
        'entrypoint_candidates': entrypoints,
        'integration_candidates': integrations,
        'sql_operations': sql_ops,
        'system_parameters': system_params,
        'user_input_parameters': user_params,
        'config_keys': config_keys,
        'log_candidates': log_candidates,
        'dynamic_candidates': dynamic_candidates,
        'scanner_limitations': scanner_limitations,
        'stats': {
            'projects': len(projects), 'source_files': len(source_files), 'entrypoints': len(entrypoints),
            'integrations': len(integrations), 'sql_operations': len(sql_ops), 'system_parameters': len(system_params),
            'user_input_parameters': len(user_params), 'config_keys': len(config_keys), 'log_candidates': len(log_candidates),
            'dynamic_candidates': len(dynamic_candidates), 'scanner_limitations': len(scanner_limitations),
        },
        'notes': [
            'Inventory is deterministic candidate discovery, not a business-flow graph and not proof of completeness.',
            'A scanner miss must never be treated as proof that a construct does not exist.',
            'Explicit AI evidence (path/symbol/keywords) is still a hard contract: if declared and not found, validation fails.',
            'SQL/parameter/log candidates are facts for traceability; they must not automatically become E2E cases.',
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--project-root', required=True)
    args = ap.parse_args()
    root = Path(args.project_root).resolve()
    out = root / 'result' / 'e2e_spec'
    out.mkdir(parents=True, exist_ok=True)
    doc = scan(root)
    (out / 'source_inventory.yaml').write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding='utf-8')
    print('E2E_SOURCE_INVENTORY_PASS')
    print(json.dumps(doc['stats'], ensure_ascii=False))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
