from pydantic import BaseModel
from typing import List, Optional

class ApproveRequest(BaseModel):
    ids: List[int]
    ids_with_shade: List[int] = []
    user_email: Optional[str] = None
