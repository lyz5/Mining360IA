from django import template
from reports.access_control import user_module_access
from reports.platform_roles import can_manage_users

register = template.Library()
register.simple_tag(user_module_access, name="platform_module_access")
register.simple_tag(can_manage_users, name="users_management_access")
