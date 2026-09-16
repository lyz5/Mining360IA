from django import template

from codex_admin.access import admin_access_allowed
from codex_chatbot.access import chatbot_access_allowed


register = template.Library()


@register.simple_tag
def codex_chatbot_visible(user):
    return chatbot_access_allowed(user)


@register.simple_tag
def codex_admin_visible(user):
    return admin_access_allowed(user)
