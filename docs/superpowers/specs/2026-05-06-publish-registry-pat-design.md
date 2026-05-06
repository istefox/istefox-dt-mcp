# Publish-Registry Auto-Trigger via PAT — Design Spec

- **Status**: proposed 2026-05-06
- **Target version**: 0.2.1 (or first release after merge)
- **Owner**: istefox
- **Scope**: `release.yml` workflow tagging step
- **Out of scope**: migration to release-please / GitHub App, `publish-registry.yml` internals

---

## 1. Context

Since 0.2.0 (released 2026-05-05), the canonical release procedure requires **two manual workflow dispatches**:

1. `release.yml` — bumps version, runs tests, builds `.mcpb`, creates the git tag `vX.Y.Z` and the GitHub Release.
2. `publish-registry.yml` — fetches the bundle, recomputes the sha256, patches `server.json`, publishes to the MCP Registry.

`publish-registry.yml` declares `on: push: tags: ["v*"]` plus `workflow_dispatch`. Intent: auto-publish when `release.yml` pushes a new tag.

**Observed behavior** (verified for v0.2.0): the tag push triggers nothing. Cause: GitHub Actions deliberately blocks workflow chaining when the originating event was authenticated with the implicit `GITHUB_TOKEN`. Quote from GitHub docs: *"events triggered by the GITHUB_TOKEN will not create a new workflow run"*. This is the defense against infinite workflow loops.

**Current workaround** (documented in memory `release_workflow.md`): manually dispatch `publish-registry.yml` after every release. Adds ~5 seconds and one extra cognitive step per release. Risk: forgetting to publish to the registry, leaving the latest version unreachable for users discovering the server through the registry.

## 2. Goals

- Restore one-shot release UX: trigger `release.yml`, registry publish happens automatically.
- Keep the manual dispatch path working as fallback (e.g., when re-publishing after a registry-side fix).
- Document PAT lifecycle so future-Stefano knows when/how to rotate.

## 3. Non-goals

- Migrating to a GitHub App (overkill for single-owner repo).
- Migrating to release-please / semantic-release (separate decision, larger scope).
- Changing `publish-registry.yml` itself — its trigger declaration is correct, only the upstream `git push` is broken.
- Removing the `workflow_dispatch` trigger from `publish-registry.yml` — needed for fallback and for re-publishing without a new tag.

## 4. Approach

Replace the implicit `GITHUB_TOKEN` used by `actions/checkout@v4` in `release.yml` with a fine-grained Personal Access Token (PAT) stored as repo secret `RELEASE_PAT`. The token's scope is restricted to `Contents: write` on the `istefox-dt-mcp` repository only. Tag pushes performed by `git push origin "$TAG"` will then carry PAT authentication, which **does** trigger downstream workflows.

### Why fine-grained PAT, not classic PAT

- Smallest scope possible (`Contents: write`, single repo) — matches our principle of least privilege from `CLAUDE.md` §2.4.
- Mandatory expiration (max 1 year). Forces rotation discipline.
- Visible in repo settings as a separate principal — auditable.

Classic PATs grant `repo` (read/write everything) and have optional expiration. Reject.

### Why not a GitHub App

Apps are the "right" answer for production-grade automation: no token expiration headaches, separate identity, granular permissions per installation. But for a single-owner personal repo the setup cost (App registration + private key handling + installation token exchange in workflow) is disproportionate. Park as future option if the repo becomes multi-maintainer.

## 5. Implementation

### 5.1 `.github/workflows/release.yml` change

The current first step:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0  # need full history for tagging
```

Becomes:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0
    token: ${{ secrets.RELEASE_PAT }}
```

Rationale: `actions/checkout` configures the local git remote with the provided token as credential. Subsequent `git push origin "$TAG"` (line 132) inherits the PAT auth automatically. **No changes elsewhere in the workflow.**

### 5.2 Secret provisioning (manual, one-time)

Stefano performs out-of-band:

1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token.
2. Token name: `istefox-dt-mcp-release-pat`. Expiration: 90 days. Repository access: only `istefox/istefox-dt-mcp`. Permissions: `Contents: Read and write`. **No other permissions.**
3. `gh secret set RELEASE_PAT --body "<token>"` from the repo working dir, or via web UI.

### 5.3 Documentation updates

- Update memory `release_workflow.md`:
  - Section "MCP Registry publish (manual trigger required)" → rename to "MCP Registry publish (auto-triggered, with manual fallback)".
  - Document PAT renewal cadence (90 days) and how to rotate.
  - Keep manual `gh workflow run publish-registry.yml -f tag=vX.Y.Z` as documented fallback for "PAT expired" / "manual re-publish".
- No `README.md` or `CHANGELOG.md` change — internal infra, not user-facing.

## 6. Failure modes & mitigations

| Failure | Behavior | Mitigation |
|---|---|---|
| `RELEASE_PAT` not set | `actions/checkout` fails with auth error at workflow start. Release does not happen. | Documented setup in `release_workflow.md`. Explicit error is loud and early. |
| `RELEASE_PAT` expired | Same: checkout step fails. | Calendar reminder at 80 days. Renewal procedure in memory. |
| PAT scope insufficient | `git push` of tag fails with 403. Release built but tag/Release not created. | Documented exact scope (`Contents: write`). Tested on first dispatch after rotation. |
| `publish-registry.yml` still doesn't auto-trigger after fix | Manual dispatch fallback unchanged from today. No regression. | Verified with first release after merge (0.2.1 or 0.3.0). |
| Two simultaneous releases (concurrency edge case) | `concurrency: group: release, cancel-in-progress: false` already in place. PAT change is orthogonal. | No additional change. |

## 7. Validation

No automated test possible — this is GitHub Actions infrastructure. Validation = first release after merge:

1. Bump to 0.2.1 (or 0.3.0) following standard procedure.
2. `gh workflow run release.yml -f version=0.2.1 -f prerelease=false`.
3. **Expected**: within ~30s of `release.yml` completing, `publish-registry.yml` shows up as a new run on the Actions tab triggered by `push` event with the tag ref.
4. Verify the registry entry is updated: `curl -s "https://registry.modelcontextprotocol.io/v0/servers?search=istefox" | jq '.servers[].server | {name, version}'`.

If step 3 fails: open issue, fall back to manual dispatch, do not block the release.

## 8. Open questions

None. The approach is mechanical, the failure modes are bounded, and the fallback path (manual dispatch) is preserved.

## 9. Effort

~30 min implementation + 5 min Stefano's PAT generation. One PR, one file changed (`.github/workflows/release.yml`), one memory update post-merge.
