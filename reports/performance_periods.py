"""Validated date windows shared by governed performance queries."""
from datetime import date


def bounds(period):
    if period in {'ytd', 'last_12_months'}:
        return None
    try:
        prefix, first, last = period.split(':')
        start, end = date.fromisoformat(first), date.fromisoformat(last)
        if prefix != 'custom' or start > end or (end-start).days > 3660:
            raise ValueError()
        return start, end
    except (ValueError, TypeError):
        raise ValueError('Specify YTD, last 12 months, or a valid date range of at most ten years.') from None


def dax_window(period):
    window = bounds(period)
    if not window:
        return None
    start, end = window
    literal = lambda d: f'DATE({d.year}, {d.month}, {d.day})'
    # Custom periods compare to the same dates in the preceding year.
    return literal(start), literal(end), f'EDATE({literal(start)}, -12)', f'EDATE({literal(end)}, -12)'


def context(period, latest, default_start):
    window = bounds(period)
    if window:
        start, end = window
        return {'period_label': f'{start.isoformat()} to {end.isoformat()}',
                'start_date': start.isoformat(), 'end_date': end.isoformat()}
    return {'period_label': 'Year to Date' if period == 'ytd' else 'Last 12 Months',
            'start_date': default_start.isoformat() if default_start else None,
            'end_date': latest.isoformat() if latest else None}
