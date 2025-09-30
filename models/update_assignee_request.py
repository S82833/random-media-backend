from pydantic import BaseModel
from typing import List

class UpdateAssigneeRequest(BaseModel):
    id: int
    assignee: str