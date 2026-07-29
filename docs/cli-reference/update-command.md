# Update Command

Upgrade SuperQode itself to the latest released version.

---

## update

Update SuperQode to the latest release on PyPI.

```bash
superqode update
```

The correct upgrade command depends on how SuperQode was installed, so
`superqode update` detects the environment first and runs the matching command:

| Installed as | Command it runs |
|--------------|-----------------|
| `uv tool install` | `uv tool upgrade superqode` |
| virtual environment or project | `uv pip install --python <interpreter> --upgrade superqode` |
| system Python | `uv pip install --upgrade superqode`, or pip when uv is absent |
| SuperQode git checkout | Nothing. It reports the checkout path and tells you to `git pull` |

`uv tool upgrade` is used rather than a reinstall because it keeps the optional
extras the tool was installed with. Upgrading a `superqode[copilot-sdk]`
installation therefore keeps the Copilot SDK.

The command prints the installed and latest versions, shows the exact command
it is about to run, and asks for confirmation before changing anything.

### Options

| Option | Description |
|--------|-------------|
| `--check` | Report the latest version and exit without installing anything |
| `--version TEXT` | Install an exact version instead of the newest release |
| `-y`, `--yes` | Skip the confirmation prompt |

### Examples

```bash
# See whether an update is available, changing nothing
superqode update --check

# Update to the latest release
superqode update

# Pin or roll back to an exact version
superqode update --version 0.2.62

# Non-interactive, for scripts
superqode update --yes
```

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | Updated, or already up to date |
| `1` | Running from a git checkout, no supported upgrade path, or the upgrade failed |

If PyPI cannot be reached, the latest version is reported as unavailable and
the update is still attempted, so an offline mirror or private index continues
to work.
