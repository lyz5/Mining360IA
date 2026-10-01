"""UI-only capability metadata. No service imports, queries or future routes."""
EXCELLENCE_ROADMAP = (
    {'id': 'payload', 'title': 'Payload', 'description': 'Payload, overload & utilization insights',
     'icon': 'M5 8h14l2 12H3L5 8z M9 8V6a3 3 0 0 1 6 0v2'},
    {'id': 'wear', 'title': 'Wear Management', 'description': 'Component wear & remaining life',
     'icon': 'M5 4h14v16H5z M8 8h8 M8 12h5 M8 16h2'},
    {'id': 'sos', 'title': 'SOS Analysis', 'description': 'Oil condition & wear-metal analysis',
     'icon': 'M9 3h6 M10 3v6L5 18q-1 3 2 3h10q3 0 2-3l-5-9V3 M8 15h8'},
    {'id': 'service-letters', 'title': 'Service Letters', 'description': 'Technical service information & applicability',
     'icon': 'M14 3H5v18h14V8l-5-5v5h5 M8 12h8 M8 16h6'},
    {'id': 'events', 'title': 'Events', 'description': 'Equipment events & operational signals',
     'icon': 'M3 12h4l3-7 4 14 3-7h4'},
    {'id': 'pressure', 'title': 'Pressure', 'description': 'Pressure trends & abnormal conditions',
     'icon': 'M4 19a10 10 0 1 1 16 0H4z M12 15l4-6 M7 9l1 1 M12 5v2 M5 14h2'},
    {'id': 'temperature', 'title': 'Temperature', 'description': 'Temperature trends & abnormal conditions',
     'icon': 'M9 14V5a3 3 0 0 1 6 0v9a5 5 0 1 1-6 0z M12 8v10 M18 6h3 M18 10h2'},
    {'id': 'idle-percent', 'title': 'Idle %', 'description': 'Idle time insights',
     'icon': 'M9 5v14 M15 5v14'},
    {'id': 'utilization', 'title': 'Utilization', 'description': 'Equipment utilization insights',
     'icon': 'M4 20V10h4v10 M10 20V4h4v16 M16 20v-7h4v7'},
)
EXCELLENCE_ROADMAP = tuple({'status': 'comingSoon', 'route': None, **module} for module in EXCELLENCE_ROADMAP)
