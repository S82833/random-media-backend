from pydantic import BaseModel
from typing import List

class UpdateDeliverablesRequest(BaseModel):
    id: int
    deliverables: int