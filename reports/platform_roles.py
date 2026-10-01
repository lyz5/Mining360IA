"""Six assignable roles, with compatibility for existing access records.

The versioned role list lives alongside (not in place of) the existing scope.
Accounts without that list keep their pre-existing permissions until edited.
"""
ROLE_KEY = "platform_roles_v2"
ROLE_LABELS = {
    "excellence_center": ("Excellence Center", "Consult fleet performance within the authorized data scope."),
    "business_overview": ("Business Overview", "Consult governed business performance within the authorized data scope."),
    "reporting": ("Reporting", "Open authorized reports with existing Power BI security."),
    "resources": ("Ressources", "Browse and read the document library."),
    "admin": ("Admin", "Manage business users and their module access."),
    "super_admin": ("Super Admin", "Manage administrator roles, integrations and sensitive configuration."),
}
ADMIN_ROLES = {"admin", "super_admin"}
BUSINESS_ROLES = set(ROLE_LABELS) - ADMIN_ROLES


def explicit_roles(profile):
    scope = (profile.business_performance_scope or {}) if profile else {}
    if ROLE_KEY not in scope:
        return None
    raw = scope[ROLE_KEY]
    return {role for role in raw if isinstance(role, str) and role in ROLE_LABELS} if isinstance(raw, list) else set()


def profile_roles(profile):
    explicit = explicit_roles(profile)
    if explicit is not None:
        return [role for role in ROLE_LABELS if role in explicit]
    user = profile.django_user
    if profile.is_platform_admin or (user and (user.is_superuser or user.is_staff)):
        return ["super_admin"]
    roles = {"resources"}  # The legacy library was available to signed-in users.
    if profile.can_access_reporting:
        roles.update({"reporting", "excellence_center"})
    if user and user.has_perm("reports.view_business_review"):
        roles.add("business_overview")
    return [role for role in ROLE_LABELS if role in roles]


def active_profile(user):
    if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return None
    return getattr(user, "platformuser", None)


def is_super_admin(user):
    if not user or not getattr(user, "is_authenticated", False) or not getattr(user, "is_active", False):
        return False
    profile = active_profile(user)
    if profile and not profile.is_active:
        return False
    explicit = explicit_roles(profile)
    if explicit is not None:
        return "super_admin" in explicit
    return bool(user.is_superuser or user.is_staff or (profile and profile.is_platform_admin))


def has_business_role(user, role):
    if is_super_admin(user):
        return True
    profile = active_profile(user)
    return bool(profile and profile.is_active and role in profile_roles(profile))


def can_manage_users(user):
    return is_super_admin(user) or has_business_role(user, "admin")
