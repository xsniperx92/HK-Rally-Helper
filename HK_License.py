import base64
import json
import os
import tkinter as tk

from datetime import datetime, timezone
from pathlib import Path
from tkinter import messagebox, ttk

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


APP_ID = "HK-RALLY-HELPER"

# IMPORTANT:
# Replace this placeholder with the public key printed by HK_Key_Setup.py.
# Never put your private signing key here.
PUBLIC_KEY_B64 = "9AyqdS2rXdkSGqh3gx6m+ymXqGwbWJsvAfGxiOOLSyE="

LICENSE_DIR = Path(os.environ.get("APPDATA", str(Path.home())))
LICENSE_DIR = LICENSE_DIR / "HKRallyHelper"
LICENSE_PATH = LICENSE_DIR / "license.key"


def decode_b64url(value):
    value += "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value.encode("ascii"))


def verify_license(token):
    """Return (valid, message) after checking the digital signature and expiry."""

    try:
        if not PUBLIC_KEY_B64 or PUBLIC_KEY_B64.startswith("REPLACE_"):
            return False, "Licensing has not been configured by the developer."

        public_key_bytes = base64.b64decode(PUBLIC_KEY_B64)
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)

        parts = token.strip().split(".")
        if len(parts) != 2:
            return False, "Invalid license format."

        payload_bytes = decode_b64url(parts[0])
        signature = decode_b64url(parts[1])

        # The signature is checked against the exact original payload bytes.
        public_key.verify(signature, payload_bytes)

        payload = json.loads(payload_bytes.decode("utf-8"))

        if payload.get("app") != APP_ID:
            return False, "This license is for a different application."

        license_type = payload.get("type")
        if license_type not in ("30-day", "90-day", "lifetime"):
            return False, "Unknown license type."

        expires_at = payload.get("expires_at")

        if license_type != "lifetime":
            if not expires_at:
                return False, "License expiration is missing."

            expiry = datetime.fromisoformat(expires_at)

            if expiry.tzinfo is None:
                return False, "Invalid license expiration."

            if datetime.now(timezone.utc) >= expiry.astimezone(timezone.utc):
                return False, "This license has expired."

        return True, f"License valid ({license_type})."

    except InvalidSignature:
        return False, "Invalid license signature."
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False, "The license file is invalid or corrupted."
    except Exception:
        return False, "Could not verify the license."


def get_saved_license():
    try:
        return LICENSE_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def save_license(token):
    LICENSE_DIR.mkdir(parents=True, exist_ok=True)

    # Write atomically to avoid leaving a partial license if interrupted.
    temp_path = LICENSE_PATH.with_suffix(".tmp")
    temp_path.write_text(token.strip(), encoding="utf-8")
    temp_path.replace(LICENSE_PATH)


def ensure_license():
    """Return True only when a valid license is available."""

    saved = get_saved_license()

    if saved:
        valid, _message = verify_license(saved)
        if valid:
            return True

    result = {"activated": False}

    window = tk.Tk()
    window.title("HK v1.2 - License Activation")
    window.geometry("470x250")
    window.resizable(False, False)

    window.protocol("WM_DELETE_WINDOW", window.destroy)

    frame = ttk.Frame(window, padding=18)
    frame.pack(fill="both", expand=True)

    ttk.Label(
        frame,
        text="HK Rally Helper v1.2",
        font=("Segoe UI", 16, "bold"),
    ).pack(pady=(0, 5))

    ttk.Label(
        frame,
        text="Enter your license key to activate the application.",
        wraplength=410,
    ).pack(pady=(0, 12))

    key_var = tk.StringVar()
    entry = ttk.Entry(frame, textvariable=key_var, width=57)
    entry.pack(fill="x", pady=5)
    entry.focus_set()

    status_var = tk.StringVar(value="30-day, 90-day, and lifetime licenses supported.")
    ttk.Label(
        frame,
        textvariable=status_var,
        wraplength=410,
    ).pack(pady=5)

    def activate():
        token = key_var.get().strip()

        if not token:
            status_var.set("Please enter your license key.")
            return

        valid, message = verify_license(token)

        if not valid:
            status_var.set(message)
            return

        try:
            save_license(token)
        except OSError as exc:
            messagebox.showerror(
                "HK v1.2",
                f"Could not save the license:\n{exc}",
                parent=window,
            )
            return

        result["activated"] = True
        window.destroy()

    buttons = ttk.Frame(frame)
    buttons.pack(pady=(8, 0))

    ttk.Button(
        buttons,
        text="Activate",
        command=activate,
    ).pack(side="left", padx=5)

    ttk.Button(
        buttons,
        text="Exit",
        command=window.destroy,
    ).pack(side="left", padx=5)

    window.bind("<Return>", lambda _event: activate())
    window.mainloop()

    return result["activated"]