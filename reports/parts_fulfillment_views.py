from __future__ import annotations

import csv
from io import StringIO

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from .business_review_access_service import has_business_review_permission
from .business_review_views import _command_center_allowed
from .parts_fulfillment_service import PartsFulfillmentService, FulfillmentUnavailable, FIELDS


def allowed(user):
    return _command_center_allowed(user) and has_business_review_permission(user, 'view_business_review_financials')


def private(response):
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
@require_GET
def page(request):
    if not allowed(request.user):
        return HttpResponseForbidden('You do not have access to Business Overview financial data.')
    return private(render(request, 'reports/parts_fulfillment.html', {
        'active_section': 'business-review',
        'can_export': has_business_review_permission(request.user, 'export_business_command_center'),
    }))


def error_response(exc):
    if isinstance(exc, (ValueError, TypeError)):
        return private(JsonResponse({'ready': False, 'code': 'INVALID_CONTEXT', 'message': str(exc)}, status=400))
    if isinstance(exc, FulfillmentUnavailable):
        return private(JsonResponse({'ready': False, 'code': exc.code, 'message': str(exc)}, status=503))
    return private(JsonResponse({'ready': False, 'code': 'SOURCE_UNAVAILABLE',
                                 'message': 'The source is temporarily unavailable. Please retry.'}, status=503))


@login_required
@require_GET
def summary(request):
    if not allowed(request.user):
        return private(JsonResponse({'detail': 'Forbidden'}, status=403))
    try:
        return private(JsonResponse(PartsFulfillmentService(request.user).summary(request.GET.get('month'))))
    except Exception as exc:
        return error_response(exc)


@login_required
@require_GET
def details(request):
    if not allowed(request.user):
        return private(JsonResponse({'detail': 'Forbidden'}, status=403))
    try:
        return private(JsonResponse(PartsFulfillmentService(request.user).details(request.GET)))
    except Exception as exc:
        return error_response(exc)


def csv_text(value):
    text = str(value or '')
    return "'" + text if text.startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else text


@login_required
@require_GET
def export(request):
    if not allowed(request.user) or not has_business_review_permission(request.user, 'export_business_command_center'):
        return private(JsonResponse({'detail': 'Forbidden'}, status=403))
    try:
        result = PartsFulfillmentService(request.user).details(request.GET, export=True)
        output = StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['Accounting Date', 'Order Date', 'Order Key (complete)', 'Invoice Key (complete)', 'Cohort', 'Accounting Sales EUR'])
        for row in result['rows']:
            writer.writerow([csv_text(row.get(k)) if k != 'amount' else row[k] for k in FIELDS])
        response = HttpResponse('\ufeff' + output.getvalue(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="parts-sales-{result["month"]}.csv"'
        return private(response)
    except Exception as exc:
        return error_response(exc)
