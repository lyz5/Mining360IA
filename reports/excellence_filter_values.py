"""Scalar-compatible multi-selection for Excellence Center dimensions."""
import re

MULTI_KEYS = {'minesite', 'model', 'prefix', 'equipment'}


def valid_prefix(value):
    return bool(re.fullmatch(r'[A-Z0-9]{3}', value))


def values(value):
    items = value if isinstance(value, (list, tuple)) else [value]
    return list(dict.fromkeys(str(item).strip() for item in items if item is not None and str(item).strip()))


def compact(items):
    items = values(items)
    return items if len(items) > 1 else items[0] if items else ''


def read_filters(params, keys):
    result = {}
    for key in keys:
        raw = params.getlist(key) if key in MULTI_KEYS and hasattr(params, 'getlist') else params.get(key)
        items = values(raw)
        if key == 'prefix':
            items = list(dict.fromkeys(item.upper() for item in items))
            if any(not valid_prefix(item) for item in items):
                from .homepage_availability_service import HomepageAvailabilityError
                raise HomepageAvailabilityError('Select a three-character serial number prefix.', code='invalid_prefix', status=400)
        if len(items) > 200 or any(len(item) > 250 for item in items):
            from .homepage_availability_service import HomepageAvailabilityError
            raise HomepageAvailabilityError('Too many or invalid filter selections.', code='invalid_filter', status=400)
        if items:
            result[key] = compact(items)
    return result


def merge_authorized_filters(scope, requested):
    from .homepage_availability_service import HomepageAvailabilityError
    merged = {key: values(value) for key, value in scope.items()}
    for key, value in requested.items():
        selected = values(value)
        if not selected:
            continue  # Clearing a selection never clears the authorization scope.
        if key in merged:
            allowed = {item.casefold(): item for item in merged[key]}
            if any(item.casefold() not in allowed for item in selected):
                raise HomepageAvailabilityError('You do not have access to the selected scope.', code='scope_forbidden', status=403)
            selected = list(dict.fromkeys(allowed[item.casefold()] for item in selected))
        merged[key] = selected
    return merged


def option_filters(merged, scope, dimension):
    """Drop only UI restrictions at/below this dropdown; retain authorization."""
    descendants = {'minesite': ('minesite', 'model', 'prefix', 'equipment', 'serial_number'),
                   'model': ('model', 'prefix', 'equipment', 'serial_number'),
                   'prefix': ('prefix', 'equipment', 'serial_number'),
                   'equipment': ('equipment', 'serial_number')}
    result = dict(merged)
    for key in descendants[dimension]:
        if key in scope:
            result[key] = values(scope[key])
        else:
            result.pop(key, None)
    return result


def prefix_clause(serial_column, selected):
    """Same serial-prefix definition across verified semantic models; keep RLS."""
    from .homepage_availability_service import _dax_string
    literals = ', '.join(_dax_string(value) for value in values(selected))
    return (f'FILTER(ALL({serial_column}), LEN(TRIM({serial_column})) >= 3 && '
            f'LEFT(UPPER(TRIM({serial_column})), 3) IN {{{literals}}})')
