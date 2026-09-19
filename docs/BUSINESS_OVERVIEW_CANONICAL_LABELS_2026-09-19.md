# Current Canonical Account labels in Business Overview

At the user's request, Business Overview displays current Canonical Account names instead of names frozen in the mapping publication. Only labels are refreshed, after published rows have passed access filtering. Published account IDs, source codes, country assignments, Key Accounts and allocations remain unchanged. Accounts absent from the publication are not introduced. Missing canonical identities retain their published labels.

Customer filter groups use the current canonical label when all members resolve to the same name; heterogeneous groups retain their published group name. Identical labels do not merge identities. Revenue Explorer displays customer names without technical account-code suffixes. Bootstrap cache keys include labels so subsequent renames appear without waiting for cache expiry. Customer watchlist labels also follow authorized current names.

Local verification: 24 Business Command Center tests passed, including current labels, duplicate names, unpublished account exclusion, unchanged publication and unchanged Revenue. Live comparison checked 3,870 canonical account labels with identical per-account Revenue data and scope before and after the change. Django check, migration check and local health passed. No mapping was published and Production was not modified.
