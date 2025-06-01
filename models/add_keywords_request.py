from pydantic import BaseModel
from typing import List

class AddKeywordsRequest(BaseModel):
    ids: List[int]
    keywords: str