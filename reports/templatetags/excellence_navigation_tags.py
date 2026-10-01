from django import template
from reports.excellence_navigation import EXCELLENCE_ROADMAP

register = template.Library()


@register.inclusion_tag('reports/includes/excellence_roadmap.html')
def excellence_roadmap():
    return {'capabilities': EXCELLENCE_ROADMAP}
