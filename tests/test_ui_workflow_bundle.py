import base64
import io
import json
import zipfile
from pathlib import Path

import pytest
import yaml

from ui.workflow_folder_package import classify_prompt_ref, export_folder_package, import_folder_package, inspect_folder_package
from ui.workflow_graph import build_workflow_graph


def _repo(tmp_path: Path) -> Path:
    (tmp_path / 'runner/workflow/custom/team-a').mkdir(parents=True)
    (tmp_path / 'runner/prompts/custom/team-a').mkdir(parents=True)
    (tmp_path / 'runner/prompts/custom/common').mkdir(parents=True)
    (tmp_path / 'runner/prompts/system').mkdir(parents=True)
    (tmp_path / 'runner/prompts/stages').mkdir(parents=True)
    return tmp_path


def _zip_entries(package: dict) -> dict[str, bytes]:
    raw = base64.b64decode(package['content'])
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        return {name: zf.read(name) for name in zf.namelist() if not name.endswith('/')}


def test_folder_export_contains_whole_workflow_and_owned_prompt_folders(tmp_path: Path):
    root = _repo(tmp_path)
    wf1 = root / 'runner/workflow/custom/team-a/regression.workflow.yaml'
    wf2 = root / 'runner/workflow/custom/team-a/extra.yaml'
    wf1.write_text('''stages:\n  run:\n    type: task\n    prompt: custom/team-a/run.md\n  review:\n    type: review\n    prompt: custom/common/review.md\n  final:\n    type: ai_validator\n    prompt: stages/ai_validator.md\nflow: [run, review, final]\n''')
    wf2.write_text('stages: {}\nflow: []\n')
    (root / 'runner/prompts/custom/team-a/run.md').write_text('own')
    (root / 'runner/prompts/custom/team-a/unused.md').write_text('owned but unreferenced')
    (root / 'runner/prompts/custom/common/review.md').write_text('common')
    (root / 'runner/prompts/stages/ai_validator.md').write_text('system')

    package = export_folder_package(wf1, root)
    entries = _zip_entries(package)
    manifest = json.loads(entries['manifest.json'])
    assert package['kind'] == 'workflow_folder'
    assert package['name'].endswith('.workflow-folder.zip')
    assert set(manifest['workflow_files']) == {'regression.workflow.yaml', 'extra.yaml'}
    assert set(manifest['prompt_files']) == {'run.md', 'unused.md'}
    assert 'workflow/regression.workflow.yaml' in entries
    assert 'workflow/extra.yaml' in entries
    assert entries['prompts/unused.md'] == b'owned but unreferenced'
    assert 'prompts/review.md' not in entries
    assert {d['scope'] for d in manifest['dependencies']} == {'common', 'system'}


def test_folder_export_rejects_root_custom_workflow(tmp_path: Path):
    root = _repo(tmp_path)
    wf = root / 'runner/workflow/custom/root.yaml'; wf.write_text('stages: {}\nflow: []\n')
    with pytest.raises(ValueError, match='Move this Workflow into a Custom folder'):
        export_folder_package(wf, root)


def test_folder_rejects_prompt_from_another_custom_folder():
    with pytest.raises(ValueError, match='outside the portable folder scope'):
        classify_prompt_ref('custom/team-b/secret.md', 'team-a')


def test_folder_import_replaces_whole_owned_folders_and_keeps_common_system(tmp_path: Path):
    root = _repo(tmp_path)
    source = _repo(tmp_path / 'source')
    wf = source / 'runner/workflow/custom/team-a/new.workflow.yaml'
    wf.write_text('stages:\n  x:\n    type: task\n    prompt: custom/team-a/x.md\nflow: [x]\n')
    (source / 'runner/prompts/custom/team-a/x.md').write_text('new prompt')
    (source / 'runner/prompts/custom/common/review.md').write_text('shared')
    (source / 'runner/prompts/stages/ai_validator.md').write_text('system')
    package = export_folder_package(wf, source)

    wf_folder = root / 'runner/workflow/custom/team-a'; prompt_folder = root / 'runner/prompts/custom/team-a'
    (wf_folder / 'old.workflow.yaml').write_text('old')
    (prompt_folder / 'stale.md').write_text('stale')
    common = root / 'runner/prompts/custom/common/review.md'; common.write_text('shared')
    system = root / 'runner/prompts/stages/ai_validator.md'; system.write_text('system')

    seen = []
    def validate_wf(path, text): seen.append(('workflow', path.name)); yaml.safe_load(text)
    def validate_prompt(path, text): seen.append(('prompt', path.name))
    folder, workflows = import_folder_package(package['content'], root, validate_wf, validate_prompt)
    assert folder == 'team-a'
    assert not (wf_folder / 'old.workflow.yaml').exists()
    assert not (prompt_folder / 'stale.md').exists()
    assert (prompt_folder / 'x.md').read_text() == 'new prompt'
    assert common.read_text() == 'shared'
    assert system.read_text() == 'system'
    assert workflows[0].name == 'new.workflow.yaml'
    assert ('workflow', 'new.workflow.yaml') in seen


def test_folder_import_rolls_back_both_owned_folders_on_validation_failure(tmp_path: Path):
    root = _repo(tmp_path)
    source = _repo(tmp_path / 'source')
    wf = source / 'runner/workflow/custom/team-a/new.workflow.yaml'; wf.write_text('stages: {}\nflow: []\n')
    (source / 'runner/prompts/custom/team-a/new.md').write_text('new')
    package = export_folder_package(wf, source)
    wf_folder = root / 'runner/workflow/custom/team-a'; prompt_folder = root / 'runner/prompts/custom/team-a'
    old_wf = wf_folder / 'old.workflow.yaml'; old_wf.write_text('old workflow')
    old_prompt = prompt_folder / 'old.md'; old_prompt.write_text('old prompt')
    with pytest.raises(ValueError, match='boom'):
        import_folder_package(package['content'], root, lambda *_: (_ for _ in ()).throw(ValueError('boom')), lambda *_: None)
    assert old_wf.read_text() == 'old workflow'
    assert old_prompt.read_text() == 'old prompt'
    assert not (wf_folder / 'new.workflow.yaml').exists()


def test_folder_inspect_reports_exact_destination_paths(tmp_path: Path):
    root = _repo(tmp_path)
    wf = root / 'runner/workflow/custom/team-a/a.yaml'; wf.write_text('stages: {}\nflow: []\n')
    package = export_folder_package(wf, root)
    info = inspect_folder_package(package['content'])
    assert info['workflow_path'] == 'runner/workflow/custom/team-a'
    assert info['prompt_path'] == 'runner/prompts/custom/team-a'
    assert info['workflow_count'] == 1


def test_flow_graph_includes_normal_recover_and_restart_edges():
    graph = build_workflow_graph({'stages': {'a': {'type':'task'}, 'b': {'type':'review','recover':['repair']}, 'repair': {'type':'task'}}, 'flow': ['a', {'stage':'b','restart_at':'a'}]})
    edges = {(e['from'],e['to'],e['kind']) for e in graph['edges']}
    assert ('a','b','normal') in edges
    assert ('b','repair','recover') in edges
    assert ('b','a','restart') in edges
