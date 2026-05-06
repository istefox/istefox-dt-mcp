# Publish-Registry Auto-Trigger via PAT — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Modify `.github/workflows/release.yml` so the tag push performed by the release workflow auto-triggers `publish-registry.yml`, eliminating the manual second-dispatch step from the release procedure.

**Architecture:** Replace the implicit `GITHUB_TOKEN` used by `actions/checkout@v4` with a fine-grained Personal Access Token stored as repo secret `RELEASE_PAT`. The `git push origin "$TAG"` step on line 132 inherits the PAT auth from checkout, so the resulting tag-push event is treated as a "user" event by GitHub Actions and does cross the workflow-chain firewall.

**Tech Stack:** GitHub Actions YAML, `gh` CLI for secret provisioning. No code changes outside the workflow file.

**Reference spec:** [`docs/superpowers/specs/2026-05-06-publish-registry-pat-design.md`](../specs/2026-05-06-publish-registry-pat-design.md)

**Pre-requisite (manual, performed by Stefano before merge):**

The fine-grained PAT must exist as repo secret `RELEASE_PAT`:

1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token.
2. Token name: `istefox-dt-mcp-release-pat`. Expiration: 90 days. Repository access: only `istefox/istefox-dt-mcp`. Permissions: `Contents: Read and write`. **No other permissions.**
3. From the repo working dir: `gh secret set RELEASE_PAT --body "<token>"`.
4. Verify: `gh secret list | grep RELEASE_PAT`.

If the PAT is not set when the next `release.yml` runs, the checkout step will fail loudly with an auth error and the release will not happen — no silent regression.

---

### Task 1: Branch + baseline

**Files:** No file changes — preparation only.

- [ ] **Step 1.1: Switch to a new feature branch off main**

```bash
git checkout main
git pull --ff-only
git checkout -b chore/release-yml-pat
```

- [ ] **Step 1.2: Confirm the current `release.yml` checkout step is unchanged from the spec's baseline**

```bash
sed -n '40,55p' .github/workflows/release.yml
```

Expected output includes:

```yaml
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # need full history for tagging
```

If the checkout step already has a `token:` parameter, stop — the spec assumes a clean baseline. Reconcile with whoever changed it before continuing.

---

### Task 2: Add `RELEASE_PAT` to the checkout step

**Files:**
- Modify: `.github/workflows/release.yml` (lines 41-43)

- [ ] **Step 2.1: Edit the checkout step**

Replace the block:

```yaml
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # need full history for tagging
```

With:

```yaml
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # need full history for tagging
          token: ${{ secrets.RELEASE_PAT }}  # PAT so tag push triggers publish-registry.yml
```

**No other changes.** The `git push origin "$TAG"` step at line 132 picks up the PAT automatically because `actions/checkout` configured the local git credential with whatever token was passed in.

- [ ] **Step 2.2: Verify the diff is exactly one line added**

```bash
git diff .github/workflows/release.yml
```

Expected: a single `+          token: ${{ secrets.RELEASE_PAT }}  # ...` line under the existing `with:` block. No other modifications.

- [ ] **Step 2.3: Validate the YAML is parseable**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/release.yml'))"
```

Expected: no output (success). If `yaml` is not available, fall back to:

```bash
gh workflow view release.yml --yaml | head -10
```

(This is a remote pull; do it only if local parse failed.)

- [ ] **Step 2.4: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "chore(ci): use RELEASE_PAT in release.yml so tag push triggers registry workflow"
```

---

### Task 3: Open the PR

**Files:** No file changes.

- [ ] **Step 3.1: Push the branch**

```bash
git push -u origin chore/release-yml-pat
```

- [ ] **Step 3.2: Open the PR with a body that documents the manual prerequisite**

```bash
gh pr create --title "chore(ci): release.yml uses RELEASE_PAT for auto-trigger of publish-registry" --body "$(cat <<'EOF'
## Summary
- Add `token: ${{ secrets.RELEASE_PAT }}` to the `actions/checkout` step in `release.yml` so the resulting tag push is treated as a user-authored event by GitHub Actions and crosses the workflow-chain firewall.
- This restores one-shot release UX: triggering `release.yml` will automatically chain into `publish-registry.yml`, removing the manual second-dispatch step.

## Pre-merge checklist
- [ ] Fine-grained PAT generated (90d, scope `Contents: write` on `istefox-dt-mcp`).
- [ ] Repo secret `RELEASE_PAT` set: `gh secret set RELEASE_PAT --body "<token>"` then `gh secret list | grep RELEASE_PAT`.

## Validation (post-merge)
- Next release (0.2.1 or 0.3.0) is the validation: dispatch `release.yml`, then within ~30s `publish-registry.yml` should appear on the Actions tab triggered by `push` event with the new tag ref. If not, open an issue and fall back to manual `gh workflow run publish-registry.yml -f tag=vX.Y.Z` (still works as fallback).

## Reference
- Design spec: `docs/superpowers/specs/2026-05-06-publish-registry-pat-design.md`
EOF
)"
```

- [ ] **Step 3.3: Verify the PR opened cleanly**

```bash
gh pr view --json number,title,state | jq
```

Expected: `state: "OPEN"`, title matches.

---

### Task 4: Post-merge — update memory + announce

**Files:**
- Modify: `~/.claude/projects/-Users-stefanoferri-Developer-Devonthink-MCP/memory/release_workflow.md`

This task runs **after the PR is merged** (manual squash-merge by Stefano). Purpose: keep the memory file in sync with reality so future sessions don't tell Stefano to manually dispatch publish-registry.

- [ ] **Step 4.1: Update the memory file**

Open `~/.claude/projects/-Users-stefanoferri-Developer-Devonthink-MCP/memory/release_workflow.md` and:

1. Rename section `## MCP Registry publish (manual trigger required)` → `## MCP Registry publish (auto-triggered, with manual fallback)`.

2. Replace the explanatory paragraph (lines about "GitHub Actions GITHUB_TOKEN limitation") with this updated text:

```markdown
`publish-registry.yml` declares `on: push: tags: ["v*"]`. Since the `release.yml` checkout step now uses `RELEASE_PAT` (fine-grained PAT, scope `Contents: write`, 90-day expiration), the tag push performed by `release.yml` auto-triggers `publish-registry.yml`. **No manual second-dispatch needed in normal operation.**

Manual dispatch is still available as fallback (PAT expired, registry-side failure, re-publish without new tag):

```bash
gh workflow run publish-registry.yml -f tag=vX.Y.Z
```
```

3. Add a new section before `## How to apply`:

```markdown
## PAT lifecycle

`RELEASE_PAT` is a fine-grained PAT scoped to this repo only, `Contents: write`, 90-day expiration. Renewal procedure:

1. ~80 days after issuance: generate a new fine-grained PAT with the same scope.
2. `gh secret set RELEASE_PAT --body "<new-token>"` to overwrite the existing secret.
3. Revoke the old PAT in GitHub → Settings → Developer settings.
4. Verify on the next release that the chain still works.

If the PAT lapses, `release.yml` will fail at the checkout step with an auth error. The release does not happen — no silent regression.
```

- [ ] **Step 4.2: Update step 4 of the existing "How to apply" list**

Find this block:

```markdown
4. **Trigger manuale** publish-registry: `gh workflow run publish-registry.yml -f tag=vX.Y.Z` (NON si auto-triggera, vedi sezione sopra)
```

Replace with:

```markdown
4. Verifica che `publish-registry.yml` sia partito automaticamente (dovrebbe comparire sulla tab Actions entro ~30s). Se non parte: fallback manuale `gh workflow run publish-registry.yml -f tag=vX.Y.Z`.
```

- [ ] **Step 4.3: Commit the memory update**

Memory files live outside the project repo — no git commit. The Write tool persists them directly. Verify the change loaded by `cat`-ing the file once.

```bash
head -10 ~/.claude/projects/-Users-stefanoferri-Developer-Devonthink-MCP/memory/release_workflow.md
```

Expected: frontmatter intact, `description:` line still present (does not need to be updated — describes the workflow, not the trigger mechanism).

---

## Self-Review

**Spec coverage check:**
- §4 (Approach: PAT, not GitHub App): covered by Task 2 + Task 3 (PR description). ✓
- §5.1 (release.yml change): Task 2. ✓
- §5.2 (Secret provisioning): Pre-requisite section + PR checklist. ✓
- §5.3 (Documentation updates): Task 4. ✓
- §6 (Failure modes): documented in PR description and Task 4 memory update. ✓
- §7 (Validation): Task 3 PR description includes post-merge validation steps. ✓

**Placeholder scan:** no TBD/TODO. All commands and YAML diffs are exact.

**Type/path consistency:** secret name `RELEASE_PAT` is used consistently in the YAML, PR body, memory file, and spec. ✓

No gaps. Plan is complete.
