# Repository maintenance

Shared dead-code checks for affromero projects. Knip checks JavaScript and
TypeScript reachability, Vulture checks tracked Python files at 80% confidence,
and cargo-machete checks Rust dependency declarations. Existing project CI
continues to compile and test native code.

Each caller checks out its repository, then invokes this composite action at
an immutable release SHA. Use Node 22, a committed npm lockfile with an exact
Knip dev dependency, and a tracked `knip.json` describing runtime entry points.
The optional `prepare` input generates imports such as Prisma clients. The
optional `rust-paths` input lists crate directories separated by spaces.

Run callers on every pull request, pushes to main, a weekly schedule, and manual
dispatch. Give the workflow read-only repository permissions. Enable the stable
dead-code job as a required check alongside existing project tests.

The source scanner compares exact finding identities against
`.maintenance-exceptions.json`. Each exception requires a reason:

```json
{
  "version": 1,
  "findings": [
    {
      "tool": "knip",
      "mode": "all",
      "file": "package.json",
      "kind": "dependencies",
      "name": "native-binding",
      "reason": "Loaded by the native build configuration."
    }
  ]
}
```

New findings and stale exceptions fail the check. Scanner crashes, malformed
reports, and inconsistent exit statuses also fail. Python identities include
the enclosing class or function, so identical unused argument names in separate
functions remain separate findings. Line movement does not invalidate exceptions.

Knip runs all checks across source and tests, then a production files check to
expose modules used only by tests. Review those modules against supported
behavior before retiring their tests. Public library entry points and dynamic
runtime registrations belong in project configuration. Keep exceptions exact
and explain why the code remains live or which unresolved contract requires it.

Reports are uploaded from `.maintenance-reports/`, including scanner stderr.
To inspect locally, run `python3 /path/to/repo-maintenance/scripts/audit.py`
from the project after installing dependencies and generating imports.
`--report-only` collects findings without changing exceptions. Never use it as
the CI gate. The action never deletes project code or approves new exceptions.

Dependabot updates the shared action dependencies and the pinned Vulture
requirement weekly after a seven-day cooldown. A scheduled workflow proposes
cargo-machete updates with a tracking issue and PR after the same cooldown;
it validates installation and runner tests before publishing the PR. Repository
settings must allow GitHub Actions to create pull requests. These token-created
PRs do not trigger other workflows automatically, so the updater runs its
validation directly. Review and merge updates through the normal PR workflow.

Successful main-branch CI publishes an immutable `v1.0.<run-number>` release.
Project Dependabot configurations update the pinned action SHA and their local
Knip package. This distributes scanner fixes without copying the runner into
each project. Keep action version comments next to caller SHAs for Dependabot.
