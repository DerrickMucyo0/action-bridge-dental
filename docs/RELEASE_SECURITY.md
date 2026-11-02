# Publication security and rights gate

This is a local gate, not permission to publish source or host the application.
Keep the original contributors, notices and Git history. Never probe exposed
credentials, rewrite history or rotate credentials without the owner's approval.

Run the value-free audit before reviewing a release candidate:

```bash
python3 scripts/release_audit.py --history --archive /path/to/frontend.zip --output /private/tmp/actionbridge-release-audit.json
python3 -m unittest discover -s scripts/tests -p 'test_release_audit.py'
```

The scanner reads tracked and nonignored untracked current files, all locally reachable Git blobs and
commit messages, and the supplied static ZIP. It reports paths, line numbers,
blob IDs and affected commits, never matching values. It makes no network calls
and edits no Git state. Pattern matching does not prove that all secrets have
been found. Remote/unreachable history, ignored files, OCR and nested binary
contents remain outside its scope. Public account IDs, API URLs and Cognito
public-client IDs are configuration, not account credentials.

Historical shared-account credentials must be treated as exposed until the
administrator privately confirms rotation/revocation and session invalidation.
Record evidence status without recording the old or replacement password.
Removing a credential from the current file does not remove its historical copies.

The frontend includes the locally verified dependency/font licenses under
`web/public/licenses/` and `web/public/third-party-notices.txt`. Their source
versions and SHA-256 hashes are recorded in
[RELEASE_DEPENDENCY_NOTICES.json](RELEASE_DEPENDENCY_NOTICES.json). The artifact
gate requires those notices and verifies the exact license bytes. A dependency
change requires refreshing and reviewing that manifest; no automatic dependency
download or license substitution is performed. Build and package a new candidate
after adding notices; do not alter a previously reviewed ZIP in place.

These notices do not establish permission to redistribute the team's code,
brand mark, or historical assets. Before public hosting, the owner must confirm
that written approval covers this modified website, its name and mark. Before
source publication, additionally resolve retained historical photographs and
design archives. Keep existing photographer/font/icon credits, including credits
for assets no longer in the current application. Unresolved rights are not a
finding of infringement, and absence from the current bundle does not settle
historical redistribution rights.

The detailed historical findings and remaining human decisions remain in the
[release checklist](RELEASE_CHECKLIST.md). Functional, Cognito/JWT, API/CORS,
browser, privacy, dependency-vulnerability and deployment verification are
separate release gates; this audit cannot mark them complete.
