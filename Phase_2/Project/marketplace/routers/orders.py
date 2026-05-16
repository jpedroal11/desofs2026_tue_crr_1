from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from core.dependencies import get_db
from middleware.auth import get_current_user
from models.models import Order, OrderItem, Product, User
from schemas.schemas import OrderCreate, OrderUpdate, OrderResponse

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.get("/", response_model=List[OrderResponse])
def list_my_orders(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all orders for the current user."""
    return (
        db.query(Order)
        .filter(Order.buyer_id == current_user.id)
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific order. Only the buyer can view their order."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.buyer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to view this order")
    return order


@router.post("/", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    order_in: OrderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Place a new order. Validates stock and deducts inventory atomically."""
    if not order_in.items:
        raise HTTPException(status_code=400, detail="Order must have at least one item")

    order_items = []
    total = 0.0

    for item_in in order_in.items:
        product = db.query(Product).filter(
            Product.id == item_in.product_id,
            Product.is_active == True,
        ).first()

        if not product:
            raise HTTPException(
                status_code=404,
                detail=f"Product {item_in.product_id} not found or unavailable",
            )
        if product.stock < item_in.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock for '{product.name}' (available: {product.stock})",
            )

        product.stock -= item_in.quantity
        subtotal = product.price * item_in.quantity
        total += subtotal

        order_items.append(
            OrderItem(
                product_id=product.id,
                quantity=item_in.quantity,
                unit_price=product.price,
            )
        )

    order = Order(
        buyer_id=current_user.id,
        shipping_address=order_in.shipping_address,
        total_amount=round(total, 2),
        items=order_items,
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


@router.patch("/{order_id}", response_model=OrderResponse)
def update_order(
    order_id: int,
    order_in: OrderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an order's status or shipping address. Only the buyer can update."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.buyer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to update this order")

    for field, value in order_in.model_dump(exclude_unset=True).items():
        setattr(order, field, value)

    db.commit()
    db.refresh(order)
    return order


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancel a pending order and restore stock."""
    from models.models import OrderStatus

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.buyer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not allowed to cancel this order")
    if order.status not in (OrderStatus.pending, OrderStatus.confirmed):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel an order with status '{order.status}'",
        )

    # Restore stock
    for item in order.items:
        product = db.query(Product).filter(Product.id == item.product_id).first()
        if product:
            product.stock += item.quantity

    order.status = OrderStatus.cancelled
    db.commit()
