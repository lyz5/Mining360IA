"""Active Revenue queries with a SQL Server filtered-index predicate."""
from django.db import connections

from .models import RevenueSourceSnapshot


def active_revenue_snapshots():
    queryset = RevenueSourceSnapshot.objects.filter(active__in=[True])
    connection = connections[queryset.db]
    if connection.vendor == "microsoft":
        # A parameterized boolean predicate cannot guarantee selection of the
        # active-only filtered index in SQL Server. Repeat the same condition
        # literally while retaining the parameterized condition above.
        table = connection.ops.quote_name(RevenueSourceSnapshot._meta.db_table)
        queryset = queryset.extra(where=[f"{table}.[active] = 1"])
    return queryset
