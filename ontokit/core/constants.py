"""OntoKit application-wide constants."""

# Committer identities used by OntoKit for automated commits.
# Any commit with one of these committer emails is considered OntoKit-authored
# and should be excluded from upstream sync processing to prevent feedback loops.
ONTOKIT_COMMITTER_NAME = "OntoKit"
ONTOKIT_COMMITTER_EMAIL = "noreply@ontokit.dev"

ONTOKIT_SYNC_COMMITTER_NAME = "OntoKit Sync"
ONTOKIT_SYNC_COMMITTER_EMAIL = "sync@ontokit.dev"

# Set of all emails used by OntoKit as committer identity.
# Used by the webhook handler to detect and skip self-authored commits.
ONTOKIT_COMMITTER_EMAILS: frozenset[str] = frozenset(
    {ONTOKIT_COMMITTER_EMAIL, ONTOKIT_SYNC_COMMITTER_EMAIL}
)
