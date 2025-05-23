from pydantic import BaseModel
from typing import List

class DeleteRequest(BaseModel):
    ids: List[int]