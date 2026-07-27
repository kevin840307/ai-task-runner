#!/usr/bin/env python3
import yaml
from pathlib import Path

# Load all config files
workflow_target_config = yaml.safe_load(Path('config/WORKFLOW-A/FAB29-FZ1/values.yaml').read_text())

# Check app-deploy structure
print('app-deploy type:', type(workflow_target_config.get('app-deploy')))
print('app-deploy keys:', list(workflow_target_config.get('app-deploy', {}).keys()) if isinstance(workflow_target_config.get('app-deploy'), dict) else 'not a dict')

# Check appB structure
appB = workflow_target_config.get('app-deploy', {}).get('appB')
print('appB:', appB)
print('appB type:', type(appB))
