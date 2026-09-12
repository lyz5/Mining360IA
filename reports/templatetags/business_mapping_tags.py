from django import template

from reports.business_mapping_access_service import has_mapping_permission
from reports.business_review_access_service import business_review_enabled


register = template.Library()


@register.simple_tag
def business_mapping_visible(user):
    return has_mapping_permission(user, "view_business_mapping")


@register.simple_tag
def business_review_visible(user):
    return business_review_enabled(user)
