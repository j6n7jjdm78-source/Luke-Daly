"""Run ON THE SERVER by you. Creates the burner keypair, prints ONLY the public address. Never run in chat/cloud."""
import json, os, sys

PATH = os.path.expanduser("~/.config/cliperz-wallet/burner.json")


def main():
    from solders.keypair import Keypair
    if os.path.exists(PATH):
        sys.exit(f"{PATH} already exists; refusing to overwrite. Back it up or delete it yourself if you really want a new wallet.")
    os.makedirs(os.path.dirname(PATH), mode=0o700, exist_ok=True)
    kp = Keypair()
    fd = os.open(PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(list(bytes(kp)), f)
    print("Burner wallet created. PUBLIC address (fund this from your own wallet):")
    print(kp.pubkey())
    print(f"Secret key stored at {PATH} (chmod 600). Never paste it anywhere.")


if __name__ == "__main__":
    main()
