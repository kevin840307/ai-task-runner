#!/usr/bin/env python3
"""Populate ans samples from the first complete sample.

This is fixture tooling for examples/07_auto_config only. It derives workflow,
target, and environment names from ans/<workflow>/<target>/<env> directories and
does not encode a fixed workflow or target list. Generated samples intentionally
vary resources, phases, and optional services so validators exercise generic
rendering instead of one copied shape.
"""
from __future__ import annotations

import argparse
import copy
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml


@dataclass(frozen=True)
class Sample:
    workflow: str
    target: str
    env: str
    root: Path

    @property
    def family(self) -> str:
        return self.target.split("-", 1)[0]

    @property
    def zone(self) -> str:
        return self.target.split("-", 1)[1] if "-" in self.target else self.target

    @property
    def workflow_suffix(self) -> str:
        return workflow_suffix(self.workflow)


def main() -> int:
    args = parse_args()
    root = Path(args.project_root).resolve()
    ans = root / "ans"
    source = first_complete_sample(ans)
    generated = 0

    for sample in ans_samples(ans):
        if sample.root == source.root:
            continue
        if has_files(sample.root) and not args.force:
            continue
        copy_tree(source, sample, args.force)
        generated += 1
        print(f"generated {relative(root, sample.root)}")

    print(f"generated samples: {generated}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite generated non-source ans samples",
    )
    return parser.parse_args()


def first_complete_sample(ans: Path) -> Sample:
    for sample in ans_samples(ans):
        if (sample.root / "values.yaml").is_file() and any(
            path.is_file() for path in (sample.root / "config").rglob("*")
        ):
            return sample
    raise SystemExit("no complete source sample found under ans")


def ans_samples(ans: Path) -> Iterable[Sample]:
    if not ans.is_dir():
        raise SystemExit(f"missing ans directory: {ans}")
    for env_root in sorted(path for path in ans.glob("*/*/*") if path.is_dir()):
        workflow, target, env = env_root.relative_to(ans).parts[:3]
        yield Sample(workflow, target, env, env_root)


def has_files(path: Path) -> bool:
    return any(child.is_file() for child in path.rglob("*"))


def copy_tree(source: Sample, target: Sample, force: bool) -> None:
    if force and target.root.exists():
        shutil.rmtree(target.root)
    for source_path in sorted(path for path in source.root.rglob("*") if path.is_file()):
        relative_path = source_path.relative_to(source.root)
        target_path = target.root / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        data = source_path.read_bytes()
        if is_text_file(source_path):
            text = data.decode("utf-8")
            target_path.write_text(transform_text(text, source, target), encoding="utf-8")
        else:
            target_path.write_bytes(data)
    customize_values(source, target)
    add_variant_output_files(source, target)


def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in {".yaml", ".yml", ".xml", ".txt", ".md", ""}


def transform_text(text: str, source: Sample, target: Sample) -> str:
    result = text
    replacements = [
        (source.workflow, target.workflow),
        (source.target, target.target),
        (source.env, target.env),
        (source.env.lower(), target.env.lower()),
        (source.family, target.family),
        (source.family.lower(), target.family.lower()),
        (source.zone, target.zone),
        (source.zone.lower(), target.zone.lower()),
    ]

    source_suffix = workflow_suffix(source.workflow)
    target_suffix = workflow_suffix(target.workflow)
    if source_suffix and target_suffix:
        replacements.extend(namespace_replacements(result, source_suffix, target_suffix))

    for old, new in replacements:
        if old and old != new:
            result = result.replace(old, new)
    return result


def customize_values(source: Sample, target: Sample) -> None:
    path = target.root / "values.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    seed = stable_seed(target)
    adjust_numbers(data, seed)
    if isinstance(data, dict):
        data["fab"] = target.family.lower()
        data["target"] = target.target
        data["environment"] = target.env.lower()
        app_deploy = data.get("app-deploy")
        if isinstance(app_deploy, dict):
            customize_app_deploy(app_deploy, source, target, seed)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def customize_app_deploy(
    app_deploy: dict,
    source: Sample,
    target: Sample,
    seed: int,
) -> None:
    phase_profiles = profiles_for(source, target)
    for app_name, app_config in list(app_deploy.items()):
        if not isinstance(app_config, dict):
            continue
        phase_keys = [
            key
            for key, value in app_config.items()
            if isinstance(value, dict) and all(isinstance(items, list) for items in value.values())
        ]
        for key in phase_keys:
            original = app_config.pop(key)
            app_config[target.family] = expand_profiles(original, phase_profiles, seed)
    if should_add_extra_service(source, target):
        app_deploy[extra_service_name(target)] = {
            "enabled": True,
            "resource": {
                "cpu": 2 + seed % 5,
                "gpu": seed % 3,
                "hpa": {"dataa": 10 + seed % 7, "datab": 20 + seed % 7},
            },
        }


def expand_profiles(source_profiles: dict, profile_names: list[str], seed: int) -> dict:
    result: dict = {}
    fallback = next(iter(source_profiles.values())) if source_profiles else []
    for index, profile in enumerate(profile_names, 1):
        values = copy.deepcopy(source_profiles.get(profile, fallback))
        adjust_numbers(values, seed + index)
        result[profile] = values
    return result


def profiles_for(source: Sample, target: Sample) -> list[str]:
    profiles = ["p1", "p2", "p3"]
    if target.zone != source.zone:
        profiles.append("p4")
    if target.family != source.family:
        profiles.append("p5")
    return profiles


def should_add_extra_service(source: Sample, target: Sample) -> bool:
    return target.workflow != source.workflow or target.family != source.family


def extra_service_name(target: Sample) -> str:
    return "service-" + slug(target.workflow_suffix) + "-" + slug(target.family.lower())


def add_variant_output_files(source: Sample, target: Sample) -> None:
    for profile in profiles_for(source, target):
        if profile in {"p1", "p2", "p3"}:
            continue
        for version_dir in profile_output_dirs(target.root / "config"):
            (version_dir / f"application-{profile}.yml").write_text(
                "",
                encoding="utf-8",
            )
    if should_add_extra_service(source, target):
        service_dir = target.root / "config" / extra_service_name(target)
        service_dir.mkdir(parents=True, exist_ok=True)
        (service_dir / "application.yml").write_text("", encoding="utf-8")


def adjust_numbers(value, seed: int) -> None:
    if isinstance(value, dict):
        for key, child in list(value.items()):
            if isinstance(child, int) and key != "id":
                value[key] = child + seed % 5
            else:
                adjust_numbers(child, seed)
    elif isinstance(value, list):
        for child in value:
            adjust_numbers(child, seed)


def stable_seed(sample: Sample) -> int:
    text = f"{sample.workflow}/{sample.target}/{sample.env}"
    return sum(ord(character) for character in text)


def workflow_suffix(workflow: str) -> str:
    match = re.search(r"([A-Za-z0-9]+)$", workflow)
    return match.group(1).lower() if match else ""


def profile_output_dirs(config_root: Path) -> list[Path]:
    if not config_root.is_dir():
        return []
    return sorted(
        path.parent
        for path in config_root.rglob("application-p1.yml")
        if path.is_file()
    )


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "x"


def namespace_replacements(text: str, source_suffix: str, target_suffix: str) -> list[tuple[str, str]]:
    values = yaml.safe_load(text) if text.strip() else None
    namespace = values.get("namespace") if isinstance(values, dict) else None
    if not isinstance(namespace, str) or not namespace.lower().endswith(source_suffix):
        return []
    return [(namespace, namespace[: -len(source_suffix)] + target_suffix)]


def relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
