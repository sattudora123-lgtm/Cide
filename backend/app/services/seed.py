"""Create the two complimentary accounts inside the encrypted vault.

The passwords below are used only to produce Argon2 hashes. The vault stores
the hashes, never the plaintext passwords, and the vault file is encrypted.
"""

from app.core.security import hash_password
from app.services.clock import utc_now
from app.services.ids import new_id
from app.storage.vault import EncryptedJsonStore

_ACCOUNTS = (
    {
        "username": "Senor",
        "email": "senor@users.cide.local",
        "display_name": "Senor",
        "password": "Senor123456987!",
    },
    {
        "username": "Aragon",
        "email": "aragon@users.cide.local",
        "display_name": "Aragon",
        "password": "Aragon31612101!",
    },
)


def seed_complimentary_users(store: EncryptedJsonStore) -> None:
    with store.transaction() as db:
        for account in _ACCOUNTS:
            if any((user.get("username") or "").lower() == account["username"].lower() for user in db["users"]):
                continue
            now = utc_now()
            db["users"].append(
                {
                    "id": new_id(),
                    "email": account["email"],
                    "username": account["username"],
                    "display_name": account["display_name"],
                    "password_hash": hash_password(account["password"]),
                    "is_active": True,
                    "complimentary": True,
                    "subscription_status": "complimentary",
                    "trial_ends_at": None,
                    "paypal_subscription_id": None,
                    "created_at": now,
                    "updated_at": now,
                }
            )
