"""Backward-compatible imports for the renamed FlowEngine."""

from .flow_engine import FlowEngine, FlowNode, build_flow_engine

Pipeline = FlowEngine


def build_pipeline(context):
    return build_flow_engine(context)


__all__ = [
    "FlowEngine",
    "FlowNode",
    "Pipeline",
    "build_flow_engine",
    "build_pipeline",
]
