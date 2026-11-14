"""Presentation switches only. No database, permissions or business queries."""
from django import template
from django.conf import settings

register = template.Library()


@register.simple_tag
def presentation_flags():
    return {
        'responsive': settings.MINING360_RESPONSIVE_UI_ENABLED,
        'business_theme': settings.MINING360_BUSINESS_THEME_ENABLED,
    }
