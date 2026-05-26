from pydantic import BaseModel


class LinkSignerRequest(BaseModel):
    main_wallet_address: str
    linked_signer_private_key: str
