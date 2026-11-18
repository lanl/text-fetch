# Contributing to text-fetch

For development setup, tests, code style, and the release process, see the
[developer guide](docs/DEVELOPER_GUIDE.md). Contributions are accepted under the
project's [MIT license](LICENSE).

## Credit

On the pull request that brings someone's first contribution, the contributor
or a maintainer adds them to [CONTRIBUTORS.md](CONTRIBUTORS.md). Use one line
per person, in family-name order, such as `- Ada Lovelace (@alovelace)`.
Use `- @alovelace` if only a handle is public or the contributor prefers it.
Use the name the contributor gives on their commits, profile, or pull request.
Contributors can request a correction, a handle-only entry, or removal on a
pull request or issue. Maintainers should honor that preference when reviewing
the check.

The advisory **contributors listed** check reads each PR's commit authors from
GitHub and looks for their handles in the list. For commits GitHub cannot link
to an account, it checks the recorded name against listed names and handles.
It skips bots. If someone is missing, add their entry on the same PR. If the
branch cannot be edited, a maintainer can add the entry immediately after merge.

With an authenticated GitHub CLI, run `python3 ci/contributors.py check --pr NUMBER`
for a PR (replace `NUMBER` with its number), or `python3 ci/contributors.py check --all`
to audit the default branch against your local copy of the list. GitHub's PR
endpoint returns up to 250 commits. Check additional commits and
`Co-authored-by` trailers manually when assigning credit.
