from pydantic import BaseModel


class LinkSignerUser(BaseModel):
    main_wallet_address: str
    linked_signer_private_key: str