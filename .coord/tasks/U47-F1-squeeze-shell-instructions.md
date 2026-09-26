===EDIT: v7_harness/olla.py===
<<<<<<< SEARCH
def cmd_squeeze(args: argparse.Namespace) -> int:
    script = Path(args.script)
    bash_path = os.environ.get("SHELL") or shutil.which("bash")
    if not bash_path and sys.platform == "win32":
=======
def cmd_squeeze(args: argparse.Namespace) -> int:
    script = Path(args.script)
    configured_shell = os.environ.get("SHELL")
    posix_shells = {"bash", "sh", "zsh", "dash", "ksh"}
    bash_path = (configured_shell if configured_shell and Path(configured_shell).stem.lower() in posix_shells
                 else shutil.which("bash"))
    if not bash_path and sys.platform == "win32":
>>>>>>> REPLACE
