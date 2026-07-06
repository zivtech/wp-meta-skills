#!/bin/bash
# install.sh — Symlink all zivtech-meta-skills into Claude and Codex skill dirs.
#
# Usage:
#   ./install.sh              # install (symlink) all skills
#   ./install.sh --remove     # remove all symlinks created by this script
#   ./install.sh --verify     # verify integrity without installing
#   ./install.sh --no-verify  # install without integrity checks
#
# Skills update automatically when you git pull. Re-run after adding new skills.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
PARENT_DIR="$(dirname "$REPO_DIR")"
CLAUDE_SKILLS_DIR="$HOME/.claude/skills"
CODEX_SKILLS_DIR="$HOME/.codex/skills"
LEGACY_AGENTS_SKILLS_DIR="$HOME/.agents/skills"
CLAUDE_AGENTS_DIR="$HOME/.claude/agents"
SKILL_TARGET_DIRS=("$CLAUDE_SKILLS_DIR" "$CODEX_SKILLS_DIR" "$LEGACY_AGENTS_SKILLS_DIR")
INSTALL_LOG="$HOME/.claude/install.log"
MANIFEST="$REPO_DIR/MANIFEST.sha256"
VERIFY_ONLY=false

# ── Security: Expected git remotes for external repos ─────────────
# Returns the expected GitHub org/repo for a given repo name.
# Add new external repos here.
expected_remote_for() {
  case "$1" in
    drupal-meta-skills) echo "zivtech/drupal-meta-skills" ;;
    meta-router)       echo "zivtech/meta-router" ;;
    harsh-critic)      echo "zivtech/harsh-critic" ;;
    react-critic)      echo "zivtech/react-critic" ;;
    *)                 echo "" ;;
  esac
}

# ── Security: Suspicious patterns in agent prompts ────────────────
SUSPICIOUS_PATTERNS=(
  '\.ssh/'
  '\.aws/'
  'credentials\.json'
  'curl.*POST'
  'wget.*--post'
  'fetch\(.*https?://'
  'exfiltrat'
  'ignore previous'
  'ignore all previous'
  'disregard.*instructions'
  'cat /etc/passwd'
  'base64.*encode'
)

# ── Logging ───────────────────────────────────────────────────────
log_install() {
  if [ "$VERIFY_ONLY" = true ]; then
    return 0
  fi

  local action="$1"
  local name="$2"
  local source="$3"
  local commit="unknown"
  if [ -d "$source/.git" ] || [ -d "$(git -C "$source" rev-parse --git-dir 2>/dev/null)" ]; then
    commit=$(git -C "$source" rev-parse --short HEAD 2>/dev/null || echo "unknown")
  fi
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $action $name commit=$commit source=$source" >> "$INSTALL_LOG"
}

is_managed_target() {
  local target="$1"
  local roots=(
    "$REPO_DIR"
    "$PARENT_DIR/drupal-meta-skills"
    "$PARENT_DIR/meta-router"
    "$PARENT_DIR/harsh-critic"
    "$PARENT_DIR/react-critic"
  )

  for root in "${roots[@]}"; do
    [[ "$target" == "$root"* ]] && return 0
  done

  return 1
}

# ── Security: Verify git remote matches expected ──────────────────
verify_remote() {
  local repo_dir="$1"
  local repo_name="$2"
  local expected
  expected=$(expected_remote_for "$repo_name")

  if [ -z "$expected" ]; then
    return 0  # No expected remote registered — skip check
  fi

  if [ ! -d "$repo_dir/.git" ]; then
    echo "  WARNING: $repo_name is not a git repo — skipping (cannot verify origin)"
    return 1
  fi

  local actual_remote
  actual_remote=$(git -C "$repo_dir" remote get-url origin 2>/dev/null || echo "none")

  if [[ "$actual_remote" != *"$expected"* ]]; then
    echo "  SECURITY: $repo_name remote mismatch!"
    echo "    Expected: *$expected*"
    echo "    Actual:   $actual_remote"
    echo "    Skipping this repo. Use --no-verify to override."
    log_install "BLOCKED" "$repo_name" "$repo_dir (remote mismatch: $actual_remote)"
    return 1
  fi

  return 0
}

# ── Security: Scan agent files for suspicious patterns ────────────
scan_agent_file() {
  local file="$1"
  local findings=0

  for pattern in "${SUSPICIOUS_PATTERNS[@]}"; do
    if grep -qiE "$pattern" "$file" 2>/dev/null; then
      if [ "$findings" -eq 0 ]; then
        echo "  SECURITY WARNING in $(basename "$file"):"
      fi
      echo "    - matches pattern: $pattern"
      ((findings++))
    fi
  done

  if [ "$findings" -gt 0 ]; then
    log_install "SCAN_WARNING" "$(basename "$file")" "$file ($findings suspicious patterns)"
  fi

  return 0  # Warn but don't block
}

# ── Security: Verify manifest checksums ───────────────────────────
verify_manifest() {
  if [ ! -f "$MANIFEST" ]; then
    echo "  No MANIFEST.sha256 found — skipping integrity check"
    echo "  Run './install.sh --generate-manifest' to create one"
    return 0
  fi

  echo "Verifying file integrity against MANIFEST.sha256..."
  local failures=0

  while IFS= read -r line; do
    # Skip empty lines and comments
    [[ -z "$line" || "$line" == \#* ]] && continue

    local expected_hash file_path
    expected_hash=$(echo "$line" | awk '{print $1}')
    file_path=$(echo "$line" | awk '{print $2}')

    if [ ! -f "$REPO_DIR/$file_path" ]; then
      echo "  MISSING: $file_path"
      ((failures++))
      continue
    fi

    local actual_hash
    actual_hash=$(shasum -a 256 "$REPO_DIR/$file_path" | awk '{print $1}')

    if [ "$expected_hash" != "$actual_hash" ]; then
      echo "  MODIFIED: $file_path"
      echo "    Expected: $expected_hash"
      echo "    Actual:   $actual_hash"
      ((failures++))
    fi
  done < "$MANIFEST"

  if [ "$failures" -gt 0 ]; then
    echo ""
    echo "  INTEGRITY CHECK FAILED: $failures file(s) differ from manifest"
    echo "  This could indicate unauthorized modifications."
    echo "  If changes are intentional, run './install.sh --generate-manifest' to update."
    log_install "INTEGRITY_FAIL" "manifest" "$REPO_DIR ($failures failures)"
    return 1
  fi

  echo "  All files match manifest checksums."
  return 0
}

# ── Generate manifest ─────────────────────────────────────────────
generate_manifest() {
  echo "Generating MANIFEST.sha256..."
  {
    echo "# MANIFEST.sha256 — Integrity checksums for skill and agent files"
    echo "# Generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "# Commit: $(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
    echo "#"
    echo "# Verify with: shasum -a 256 -c MANIFEST.sha256"
    echo "# Or run: ./install.sh --verify"
    echo ""
  } > "$MANIFEST"

  # Hash all agent and skill files in the repo, excluding local worktrees.
  find "$REPO_DIR" \
    \( -path '*/.git' -o -path '*/.claude/worktrees' \) -prune -o \
    \( -path '*/.claude/agents/*.md' -o -path '*/.claude/skills/*/SKILL.md' \) \
    -type f -print | \
    sort | \
    while IFS= read -r file; do
      local rel_path="${file#$REPO_DIR/}"
      shasum -a 256 "$file" | awk -v rp="$rel_path" '{print $1 "  " rp}'
    done >> "$MANIFEST"

  local count
  count=$(grep -c '^[a-f0-9]' "$MANIFEST" || echo 0)
  echo "  Generated checksums for $count files."
  echo "  Commit MANIFEST.sha256 to track integrity."
}

# ── Uninstall mode ────────────────────────────────────────────────
if [[ "${1:-}" == "--remove" ]]; then
  echo "Removing symlinks managed by $REPO_DIR ..."
  removed=0

  for skills_dir in "${SKILL_TARGET_DIRS[@]}"; do
    [ -d "$skills_dir" ] || continue
    for link in "$skills_dir"/*; do
      [ -L "$link" ] || continue
      target="$(readlink "$link")"
      is_managed_target "$target" || continue
      rm "$link"
      echo "  removed skill: $(basename "$link") from $skills_dir"
      log_install "REMOVE" "$(basename "$link")" "$target"
      ((removed++))
    done
  done

  for link in "$CLAUDE_AGENTS_DIR"/*.md; do
    [ -L "$link" ] && is_managed_target "$(readlink "$link")" && {
      rm "$link"
      echo "  removed agent: $(basename "$link")"
      log_install "REMOVE" "$(basename "$link")" "$CLAUDE_AGENTS_DIR"
      ((removed++))
    }
  done

  echo "Done. Removed $removed symlinks."
  exit 0
fi

# ── Verify-only mode ─────────────────────────────────────────────
if [[ "${1:-}" == "--verify" ]]; then
  VERIFY_ONLY=true
  verify_manifest
  exit $?
fi

# ── Generate manifest mode ────────────────────────────────────────
if [[ "${1:-}" == "--generate-manifest" ]]; then
  generate_manifest
  exit 0
fi

# ── Install mode ──────────────────────────────────────────────────
SKIP_VERIFY=false
if [[ "${1:-}" == "--no-verify" ]]; then
  SKIP_VERIFY=true
  echo "WARNING: Skipping integrity verification (--no-verify)"
  echo ""
fi

mkdir -p "$CLAUDE_SKILLS_DIR" "$CODEX_SKILLS_DIR" "$LEGACY_AGENTS_SKILLS_DIR" "$CLAUDE_AGENTS_DIR"

# Run integrity check (unless --no-verify)
if [ "$SKIP_VERIFY" = false ] && [ -f "$MANIFEST" ]; then
  if ! verify_manifest; then
    echo ""
    echo "Install aborted due to integrity check failure."
    echo "Use --no-verify to override, or --generate-manifest to update checksums."
    exit 1
  fi
  echo ""
fi

installed=0
skipped=0
scan_warnings=0

link_one_skill() {
  local skill_path="$1"
  local name
  local skills_dir

  name="$(basename "$skill_path")"

  for skills_dir in "${SKILL_TARGET_DIRS[@]}"; do
    if [ -L "$skills_dir/$name" ]; then
      ln -sfn "$skill_path" "$skills_dir/$name"
    elif [ -d "$skills_dir/$name" ]; then
      echo "  SKIP skill $name in $skills_dir (non-symlink directory exists)"
      ((skipped++))
      continue
    else
      ln -sfn "$skill_path" "$skills_dir/$name"
    fi

    log_install "INSTALL" "skill:$name" "$skill_path -> $skills_dir"
    ((installed++))
  done
}

link_one_agent() {
  local agent_file="$1"
  local name

  name="$(basename "$agent_file")"

  # Scan agent file for suspicious patterns.
  scan_agent_file "$agent_file"

  if [ -L "$CLAUDE_AGENTS_DIR/$name" ]; then
    ln -sfn "$agent_file" "$CLAUDE_AGENTS_DIR/$name"
  elif [ -f "$CLAUDE_AGENTS_DIR/$name" ]; then
    echo "  SKIP agent $name (non-symlink file exists)"
    ((skipped++))
    return
  else
    ln -sfn "$agent_file" "$CLAUDE_AGENTS_DIR/$name"
  fi

  log_install "INSTALL" "agent:$name" "$agent_file"
  ((installed++))
}

install_repo_tree() {
  local root="$1"
  local skill_file
  local agent_file

  while IFS= read -r skill_file; do
    link_one_skill "$(dirname "$skill_file")"
  done < <(
    find "$root" \
      \( -path '*/.git' -o -path '*/.claude/worktrees' \) -prune -o \
      -path '*/.claude/skills/*/SKILL.md' -type f -print | sort
  )

  while IFS= read -r agent_file; do
    link_one_agent "$agent_file"
  done < <(
    find "$root" \
      \( -path '*/.git' -o -path '*/.claude/worktrees' \) -prune -o \
      -path '*/.claude/agents/*.md' -type f -print | sort
  )
}

install_named_entries() {
  local root="$1"
  shift
  local name
  local skill_path
  local agent_file

  for name in "$@"; do
    skill_path="$root/.claude/skills/$name"
    [ -f "$skill_path/SKILL.md" ] && link_one_skill "$skill_path"

    agent_file="$root/.claude/agents/$name.md"
    [ -f "$agent_file" ] && link_one_agent "$agent_file"
  done
}

echo "Installing zivtech-meta-skills from $REPO_DIR"
echo "  Claude skills -> $CLAUDE_SKILLS_DIR"
echo "  Codex skills  -> $CODEX_SKILLS_DIR"
echo "  Legacy skills -> $LEGACY_AGENTS_SKILLS_DIR"
echo "  Claude agents -> $CLAUDE_AGENTS_DIR"
echo "  Log    -> $INSTALL_LOG"
echo ""

# Log install session start
log_install "SESSION_START" "install.sh" "$REPO_DIR"

install_repo_tree "$REPO_DIR"

# External companion repos (sibling directories) — with remote verification
for ext_repo in drupal-meta-skills meta-router; do
  ext_path="$PARENT_DIR/$ext_repo"
  if [ -d "$ext_path/.claude" ]; then
    echo ""
    echo "Installing external repo: $ext_repo"

    # Verify git remote matches expected origin
    if [ "$SKIP_VERIFY" = false ]; then
      if ! verify_remote "$ext_path" "$ext_repo"; then
        echo "  Skipped $ext_repo (failed remote verification)"
        continue
      fi
    fi

    install_repo_tree "$ext_path"
  fi
done

# External critic repos contain some duplicate first-party skills; install only
# the canonical external commands that the registry routes to.
for ext_repo in harsh-critic react-critic; do
  ext_path="$PARENT_DIR/$ext_repo"
  if [ -d "$ext_path/.claude" ]; then
    echo ""
    echo "Installing external repo: $ext_repo"

    if [ "$SKIP_VERIFY" = false ]; then
      if ! verify_remote "$ext_path" "$ext_repo"; then
        echo "  Skipped $ext_repo (failed remote verification)"
        continue
      fi
    fi

    case "$ext_repo" in
      harsh-critic)
        install_named_entries "$ext_path" harsh-critic
        ;;
      react-critic)
        install_named_entries "$ext_path" react-critic next-critic react-native-critic js-critic-router
        ;;
    esac
  fi
done

# Log install session end
log_install "SESSION_END" "install.sh" "$REPO_DIR (installed=$installed, skipped=$skipped)"

echo ""
echo "Done. Installed $installed symlinks."
[ "$skipped" -gt 0 ] && echo "Skipped $skipped (non-symlink files/dirs already exist)."
echo ""
echo "Skills are now available in Claude Code and Codex skill directories."
echo "Run './install.sh --remove' to uninstall."
echo "Run './install.sh --verify' to check integrity."
echo ""
echo "Install log: $INSTALL_LOG"
