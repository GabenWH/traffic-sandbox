"""Validated operational rules carried by the existing building templates."""
from copy import deepcopy
from math import isfinite

ROLES = {'home', 'workplace', 'farm', 'bakery', 'cafe', 'market', 'clinic', 'bus_stop'}


def validate_operation(value):
    if not isinstance(value, dict) or value.get('role') not in ROLES:
        raise ValueError('Building operation needs a known role')
    result = deepcopy(value)
    for key, default in (('quality', 50.0), ('rate', 0.0)):
        number = result.get(key, default)
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not isfinite(number) or number < 0:
            raise ValueError(f'Operation {key} must be finite and nonnegative')
        if key == 'quality' and number > 100:
            raise ValueError('Operation quality must be between 0 and 100')
        result[key] = float(number)
    for key in ('inputs', 'targets'):
        amounts = result.get(key, {})
        if not isinstance(amounts, dict):
            raise ValueError(f'Operation {key} must be resource amounts')
        for resource, amount in amounts.items():
            if (not isinstance(resource, str) or not resource or isinstance(amount, bool)
                    or not isinstance(amount, (int, float)) or not isfinite(amount) or amount <= 0):
                raise ValueError(f'Operation {key} needs positive finite resource amounts')
        result[key] = dict(amounts)
    output = result.get('output')
    if output is not None and (not isinstance(output, str) or not output):
        raise ValueError('Operation output must be a resource name')
    result['output'] = output
    return result


def operation_for(building):
    return building.operation or validate_operation({
        'role': 'home' if building.residents else 'workplace'})
