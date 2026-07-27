import sys
sys.path.insert(0, '.')
from rander import convert_hyphenated_keys_to_underscore, deep_merge

# Simulate the merge
global_config = {
    '__merge_probe__': {
        'kept': 'global-kept',
        'nested': {'a': 'global-a', 'b': 'global-b'},
        'list_value': ['global-list'],
        'empty_dict_value': {'old': 'must-be-replaced'},
        'null_value': {'old': 'must-be-replaced'}
    },
    'app-deploy': {
        'appA': {'web': 'fab14-prod.com.tw/name-a'}
    },
    'flow-deploy': {
        'appAA': {'config-v604': 'abc'}
    }
}

workflow_config = {
    '__merge_probe__': {
        'kept': 'workflow-kept',
        'nested': {'a': 'workflow-a', 'b': 'workflow-b'},
        'list_value': ['workflow-list'],
        'empty_dict_value': {'old': 'must-be-replaced'},
        'null_value': {'old': 'must-be-replaced'}
    },
    'app-deploy': {
        'appB': {'test': 'abc'}
    },
    'flow-deploy': {
        'appBB': {'list': ['v412', 'v407']}
    }
}

merged = deep_merge(global_config, workflow_config)
print('Merged config keys:', list(merged.keys()))
print('app-deploy key exists:', 'app-deploy' in merged)
print('flow-deploy key exists:', 'flow-deploy' in merged)

converted = convert_hyphenated_keys_to_underscore(merged)
print('Converted keys:', list(converted.keys()))
print('app_deploy key exists:', 'app_deploy' in converted)
print('flow_deploy key exists:', 'flow_deploy' in converted)
