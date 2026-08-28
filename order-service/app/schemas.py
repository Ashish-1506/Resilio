from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class OrderCreate(BaseModel):
    customer_name: str = Field(min_length=1, max_length=120)
    product: str = Field(min_length=1, max_length=200)
    quantity: int = Field(gt=0, le=10000)


class OrderResponse(OrderCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    created_at: datetime
