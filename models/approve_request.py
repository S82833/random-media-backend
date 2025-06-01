from pydantic import BaseModel
from typing import List

class ApproveRequest(BaseModel):
    ids: List[int]
