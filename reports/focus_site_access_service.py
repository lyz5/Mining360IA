"""Source-reviewed site access presets, separate from published Revenue mapping."""
from .models import SystemParameter

CATALOG_KEY = 'focus-sites-access-catalog'

def focus_site_catalog():
    item = SystemParameter.objects.filter(key=CATALOG_KEY, is_active=True).first()
    payload = item.value_json if item and isinstance(item.value_json, dict) else {}
    result = []
    seen = set()
    for row in payload.get('sites', []):
        if not isinstance(row, dict) or str(row.get('focus', '')).casefold() != 'yes':
            continue
        site = str(row.get('site') or '').strip()
        country = str(row.get('country') or '').strip()
        if not site or site.casefold() == 'global' or site.casefold() in seen:
            continue
        seen.add(site.casefold())
        result.append({'site':site, 'country':country, 'site_code':str(row.get('site_code') or '')})
    return sorted(result, key=lambda row:(row['country'].casefold(),row['site'].casefold()))

def focus_site_presets():
    return [{'id':row['site'], 'label':f"{row['country']} — {row['site']}",
             'country':row['country'], 'platform_roles':['excellence_center','reporting'],
             'business_performance_access':'MineSite', 'countries':[], 'customers':[],
             'minesites':[row['site']], 'powerbi_rls_role':row['site'],
             'rls_validation':'Dataset-specific role validation required'}
            for row in focus_site_catalog()]
