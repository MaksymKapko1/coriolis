from pydantic import BaseModel


class LinkSignerRequest(BaseModel):
    linked_signer_private_key: str
