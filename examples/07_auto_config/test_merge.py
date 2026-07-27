import yaml

# Simulate the merge
global_config = {
    '__merge_probe__': {
        'kept': 'global-kept',
        'nested': {'a': 'global-a', 'b': 'global-b'},
        'list_value': ['global-list'],
        'empty_dict_value': {'old': 'must-be-replaced'},
        'null_value': {'old': 'must-be-replaced'}
    }
}

workflow_config = {
    '__merge_probe__': {
        'kept': 'workflow-kept',
        'nested': {'a': 'workflow-a', 'b': 'workflow-b'},
        'list_value': ['workflow-list'],
        'empty_dict_value': {'old': 'must-be-replaced'},
        'null_value': {'old': 'must-be-replaced'}
    }
}

def deep_merge(base, override):
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result

merged = deep_merge(global_config, workflow_config)
print('Merged result:')
print(yaml.dump(merged, default_flow_style=False))
print('Type of merged[\"__merge_probe__\"]:', type(merged['__merge_probe__']))
print('Merged[\"__merge_probe__\"]:', merged['__merge_probe__'])
