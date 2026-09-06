from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

class GateStatus(str, Enum):
    PASS='PASS'
    FAIL='FAIL'
    REVIEW_REQUIRED='REVIEW_REQUIRED'

class ArtifactStatus(str, Enum):
    VALID='VALID'
    STALE='STALE'
    INVALID='INVALID'
    REVIEW_REQUIRED='REVIEW_REQUIRED'
    DEPRECATED='DEPRECATED'

@dataclass(frozen=True)
class GateViolation:
    code: str
    message: str
    artifact_id: Optional[str]=None
    repair_from: Optional[str]=None
    severity: str='MAJOR'
    details: Dict[str, Any]=field(default_factory=dict)

@dataclass
class GateResult:
    gate: str
    status: GateStatus
    violations: List[GateViolation]=field(default_factory=list)
    metrics: Dict[str, Any]=field(default_factory=dict)

    @property
    def ok(self)->bool:
        return self.status==GateStatus.PASS

    def to_dict(self)->Dict[str,Any]:
        return {
            'gate': self.gate,
            'status': self.status.value,
            'violations': [
                {
                    'code':v.code,'message':v.message,'artifact_id':v.artifact_id,
                    'repair_from':v.repair_from,'severity':v.severity,'details':v.details,
                } for v in self.violations
            ],
            'metrics': self.metrics,
        }
