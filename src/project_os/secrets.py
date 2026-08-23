import subprocess


def set_api_key(service: str, account: str, api_key: str) -> None:
    subprocess.run(
        [
            "security", "add-generic-password",
            "-U",  # update if it already exists
            "-s", service,
            "-a", account,
            "-w", api_key,
        ],
        check=True,
        capture_output=True,
    )


def get_api_key(service: str, account: str) -> str:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", account, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise LookupError(
            f"No Keychain entry found for service={service!r} account={account!r}"
        )
    return result.stdout.strip()
