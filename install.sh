#!/bin/bash
# install.sh — Symlink wp-meta-skills into Claude and Codex skill dirs.
#
# Usage:
#   ./install.sh              # install (symlink) all skills
#   ./install.sh --remove     # remove all symlinks created by this script
#   ./install.sh --verify     # verify integrity without installing
#   ./install.sh --no-verify  # install without integrity checks
#   ./install.sh --force      # replace unrelated symlinks, never files/dirs
#
# Skills update automatically when you git pull. Re-run after adding new skills.

set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]}"
SCRIPT_LINK_HOPS=0
while [ -L "$SCRIPT_PATH" ]; do
  SCRIPT_LINK_HOPS=$((SCRIPT_LINK_HOPS + 1))
  if [ "$SCRIPT_LINK_HOPS" -gt 40 ]; then
    echo "Installer entrypoint exceeds 40 symlink hops" >&2
    exit 1
  fi
  SCRIPT_DIR="$(cd -P "$(dirname "$SCRIPT_PATH")" && pwd)"
  SCRIPT_TARGET="$(readlink "$SCRIPT_PATH")"
  if [[ "$SCRIPT_TARGET" = /* ]]; then
    SCRIPT_PATH="$SCRIPT_TARGET"
  else
    SCRIPT_PATH="$SCRIPT_DIR/$SCRIPT_TARGET"
  fi
done
REPO_DIR="$(cd -P "$(dirname "$SCRIPT_PATH")" && pwd)"
CLAUDE_SKILLS_DIR="$HOME/.claude/skills"
CODEX_SKILLS_DIR="$HOME/.codex/skills"
LEGACY_AGENTS_SKILLS_DIR="$HOME/.agents/skills"
CLAUDE_AGENTS_DIR="$HOME/.claude/agents"
SKILL_TARGET_DIRS=("$CLAUDE_SKILLS_DIR" "$CODEX_SKILLS_DIR" "$LEGACY_AGENTS_SKILLS_DIR")
INSTALL_LOG="$HOME/.claude/install.log"
MANIFEST="$REPO_DIR/MANIFEST.sha256"
VERIFY_ONLY=false
MODE="install"
SKIP_VERIFY=false
FORCE=false

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
  printf '%s action=%q name=%q commit=%q source=%q\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$action" "$name" "$commit" "$source" \
    >> "$INSTALL_LOG"
}

is_managed_link() {
  local link_path="$1"
  local raw_target
  local candidate
  local resolved_target
  local resolved_repo

  [ -L "$link_path" ] || return 1
  raw_target=$(readlink "$link_path") || return 1
  if [[ "$raw_target" = /* ]]; then
    candidate="$raw_target"
  else
    candidate="$(dirname "$link_path")/$raw_target"
  fi
  [ -e "$candidate" ] || return 1
  resolved_target=$(realpath "$candidate" 2>/dev/null) || return 1
  resolved_repo=$(realpath "$REPO_DIR" 2>/dev/null) || return 1

  [[ "$resolved_target" == "$resolved_repo" || "$resolved_target" == "$resolved_repo/"* ]]
}

is_repo_source() {
  local source="$1"
  local resolved_source
  local resolved_repo

  [ -e "$source" ] || return 1
  resolved_source=$(realpath "$source" 2>/dev/null) || return 1
  resolved_repo=$(realpath "$REPO_DIR" 2>/dev/null) || return 1
  [[ "$resolved_source" == "$resolved_repo/"* ]]
}

is_safe_entry_name() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]
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
      findings=$((findings + 1))
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
      failures=$((failures + 1))
      continue
    fi

    local actual_hash
    actual_hash=$(shasum -a 256 "$REPO_DIR/$file_path" | awk '{print $1}')

    if [ "$expected_hash" != "$actual_hash" ]; then
      echo "  MODIFIED: $file_path"
      echo "    Expected: $expected_hash"
      echo "    Actual:   $actual_hash"
      failures=$((failures + 1))
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
      local rel_path="${file#"$REPO_DIR"/}"
      shasum -a 256 "$file" | awk -v rp="$rel_path" '{print $1 "  " rp}'
    done >> "$MANIFEST"

  local count
  count=$(grep -c '^[a-f0-9]' "$MANIFEST" || echo 0)
  echo "  Generated checksums for $count files."
  echo "  Commit MANIFEST.sha256 to track integrity."
}

# ── Command-line mode ─────────────────────────────────────────────
while [ "$#" -gt 0 ]; do
  case "$1" in
    --remove|--verify|--generate-manifest)
      if [ "$MODE" != "install" ]; then
        echo "Only one operation may be selected" >&2
        exit 2
      fi
      MODE="${1#--}"
      ;;
    --no-verify)
      SKIP_VERIFY=true
      ;;
    --force)
      FORCE=true
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
  shift
done

if [ "$MODE" != "install" ] && [ "$FORCE" = true ]; then
  echo "--force is valid only for installation" >&2
  exit 2
fi
if [ "$MODE" != "install" ] && [ "$SKIP_VERIFY" = true ]; then
  echo "--no-verify is valid only for installation" >&2
  exit 2
fi

# ── Uninstall mode ────────────────────────────────────────────────
if [ "$MODE" = "remove" ]; then
  printf 'Removing symlinks managed by %q ...\n' "$REPO_DIR"
  removed=0

  for skills_dir in "${SKILL_TARGET_DIRS[@]}"; do
    [ -d "$skills_dir" ] || continue
    for link in "$skills_dir"/*; do
      [ -L "$link" ] || continue
      target="$(readlink "$link")"
      is_managed_link "$link" || continue
      rm "$link"
      printf '  removed skill: %q from %q\n' "$(basename "$link")" "$skills_dir"
      log_install "REMOVE" "$(basename "$link")" "$target"
      removed=$((removed + 1))
    done
  done

  for link in "$CLAUDE_AGENTS_DIR"/*.md; do
    [ -L "$link" ] && is_managed_link "$link" && {
      target="$(readlink "$link")"
      rm "$link"
      printf '  removed agent: %q\n' "$(basename "$link")"
      log_install "REMOVE" "$(basename "$link")" "$target"
      removed=$((removed + 1))
    }
  done

  echo "Done. Removed $removed symlinks."
  exit 0
fi

# ── Verify-only mode ─────────────────────────────────────────────
if [ "$MODE" = "verify" ]; then
  VERIFY_ONLY=true
  verify_manifest
  exit $?
fi

# ── Generate manifest mode ────────────────────────────────────────
if [ "$MODE" = "generate-manifest" ]; then
  generate_manifest
  exit 0
fi

# ── Install mode ──────────────────────────────────────────────────
if [ "$SKIP_VERIFY" = true ]; then
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

link_destination() {
  local source="$1"
  local destination="$2"
  local label="$3"
  local raw_target

  if ! is_repo_source "$source"; then
    printf '  BLOCK %s from unowned source %q\n' "$label" "$source"
    skipped=$((skipped + 1))
    return 1
  fi

  if [ -L "$destination" ]; then
    if is_managed_link "$destination"; then
      rm "$destination"
    elif [ "$FORCE" = true ]; then
      raw_target=$(readlink "$destination")
      printf '  FORCE replace: destination=%q prior-target=%q\n' \
        "$destination" "$raw_target"
      rm "$destination"
    else
      printf '  PRESERVE %s at %q (unowned symlink)\n' "$label" "$destination"
      skipped=$((skipped + 1))
      return 1
    fi
  elif [ -e "$destination" ]; then
    printf '  SKIP %s at %q (regular file or directory exists)\n' \
      "$label" "$destination"
    skipped=$((skipped + 1))
    return 1
  fi

  ln -s "$source" "$destination"
  return 0
}

link_one_skill() {
  local skill_path="$1"
  local name
  local skills_dir

  name="$(basename "$skill_path")"
  if ! is_safe_entry_name "$name"; then
    printf '  BLOCK unsafe skill name %q\n' "$name"
    skipped=$((skipped + 3))
    return
  fi

  for skills_dir in "${SKILL_TARGET_DIRS[@]}"; do
    link_destination "$skill_path" "$skills_dir/$name" "skill:$name" || continue

    log_install "INSTALL" "skill:$name" "$skill_path -> $skills_dir"
    installed=$((installed + 1))
  done
}

link_one_agent() {
  local agent_file="$1"
  local name

  name="$(basename "$agent_file")"
  if ! is_safe_entry_name "$name"; then
    printf '  BLOCK unsafe agent name %q\n' "$name"
    skipped=$((skipped + 1))
    return
  fi

  # Scan agent file for suspicious patterns.
  scan_agent_file "$agent_file"

  if ! link_destination \
    "$agent_file" "$CLAUDE_AGENTS_DIR/$name" "agent:$name"; then
    return
  fi

  log_install "INSTALL" "agent:$name" "$agent_file"
  installed=$((installed + 1))
}

install_repo_tree() {
  local root="$1"
  local skill_file
  local agent_file

  if [ -d "$root/.claude/skills" ]; then
    while IFS= read -r -d '' skill_file; do
      link_one_skill "$(dirname "$skill_file")"
    done < <(
      find "$root/.claude/skills" -mindepth 2 -maxdepth 2 \
        -name SKILL.md -type f -print0 | sort -z
    )
  fi

  if [ -d "$root/.claude/agents" ]; then
    while IFS= read -r -d '' agent_file; do
      link_one_agent "$agent_file"
    done < <(
      find "$root/.claude/agents" -mindepth 1 -maxdepth 1 \
        -name '*.md' -type f -print0 | sort -z
    )
  fi
}

printf 'Installing wp-meta-skills from %q\n' "$REPO_DIR"
printf '  Claude skills -> %q\n' "$CLAUDE_SKILLS_DIR"
printf '  Codex skills  -> %q\n' "$CODEX_SKILLS_DIR"
printf '  Legacy skills -> %q\n' "$LEGACY_AGENTS_SKILLS_DIR"
printf '  Claude agents -> %q\n' "$CLAUDE_AGENTS_DIR"
printf '  Log    -> %q\n' "$INSTALL_LOG"
echo ""

# Log install session start
log_install "SESSION_START" "install.sh" "$REPO_DIR"

install_repo_tree "$REPO_DIR"

# Log install session end
log_install "SESSION_END" "install.sh" "$REPO_DIR (installed=$installed, skipped=$skipped)"

echo ""
echo "Done. Installed $installed symlinks."
[ "$skipped" -gt 0 ] && echo "Skipped $skipped existing destinations."
echo ""
echo "Skills are now available in Claude Code and Codex skill directories."
echo "Run './install.sh --remove' to uninstall."
echo "Run './install.sh --verify' to check integrity."
echo ""
printf 'Install log: %q\n' "$INSTALL_LOG"
