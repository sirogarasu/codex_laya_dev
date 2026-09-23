"""Structural checks on caller-owned candidates; never grants execution permission."""


def check_preconditions(preconditions, choice):
    if not isinstance(preconditions, dict) or set(preconditions) != {'operation_count', 'candidates'}:
        return 'invalid_preconditions'
    count = preconditions['operation_count']
    if type(count) is not int or count < 0:
        return 'invalid_preconditions'
    if count != 1:
        return 'unresolved_operations'
    candidates = preconditions['candidates']
    if not isinstance(candidates, dict):
        return 'invalid_preconditions'
    if choice not in candidates:
        return 'candidate_missing'
    candidate = candidates[choice]
    if not isinstance(candidate, dict) or set(candidate) != {'required_arguments', 'arguments'}:
        return 'invalid_preconditions'
    required, arguments = candidate['required_arguments'], candidate['arguments']
    if (not isinstance(required, list) or not isinstance(arguments, dict)
            or any(not isinstance(key, str) or not key.strip() for key in required)
            or len(set(required)) != len(required)):
        return 'invalid_preconditions'
    for key in required:
        value = arguments.get(key)
        if value is None or (isinstance(value, str) and not value.strip()) or value == [] or value == {}:
            return 'argument_missing'
    return 'passed'
