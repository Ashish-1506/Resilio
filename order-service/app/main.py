from fastapi import Depends, FastAPI, status
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import Order
from .schemas import OrderCreate, OrderResponse

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Resilio Order Service", version="1.0.0")
FastAPIInstrumentor.instrument_app(app)


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "order-service"}


@app.get("/orders", response_model=list[OrderResponse])
def list_orders(db: Session = Depends(get_db)):
    return db.scalars(select(Order).order_by(Order.id)).all()


@app.post(
    "/orders",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_order(order: OrderCreate, db: Session = Depends(get_db)):
    new_order = Order(**order.model_dump())
    db.add(new_order)
    db.commit()
    db.refresh(new_order)
    return new_order
