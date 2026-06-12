from uuid import UUID
import os
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session, selectinload
from typing import List

from core.dependencies import get_db
from middleware.auth import get_current_user
from models.models import Order, OrderItem, Product, User, ProductStatus, OrderStatus
from schemas.schemas import OrderCreate, OrderUpdate, OrderResponse

router = APIRouter(prefix="/orders", tags=["Orders"])

logger = logging.getLogger(__name__)

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
    order_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific order. Only the buyer can view their order."""
    order = (
        db.query(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.product))
        .filter(Order.id == order_id)
        .first()
    )
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
    """Place a new order. Validates stock and deducts inventory atomically.
    
    All items in the order must be from the same seller.
    """
    if not order_in.items:
        raise HTTPException(status_code=400, detail="Order must have at least one item")

    order_items = []
    total = 0.0
    seller_id = None

    for item_in in order_in.items:
        product = db.query(Product).filter(
            Product.id == item_in.product_id,
            Product.status == ProductStatus.active,
        ).first()

        if not product:
            raise HTTPException(
                status_code=404,
                detail=f"Product {item_in.product_id} not found or unavailable",
            )
        
        # Ensure all items are from the same seller
        if seller_id is None:
            seller_id = product.seller_id
        elif seller_id != product.seller_id:
            raise HTTPException(
                status_code=400,
                detail="All products in an order must be from the same seller",
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
        seller_id=seller_id,
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
    order_id: UUID,
    order_in: OrderUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an order's status or shipping address. Only the buyer can update."""
    order = (
        db.query(Order)
        .options(selectinload(Order.items).selectinload(OrderItem.product))
        .filter(Order.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    order_seller_ids = {
        item.product.seller_id for item in order.items if item.product is not None
    }
    buyer_can_update = order.buyer_id == current_user.id
    seller_can_update_status = current_user.is_admin or current_user.id in order_seller_ids

    for field, value in order_in.model_dump(exclude_unset=True).items():
        if field == "status":
            if not seller_can_update_status:
                raise HTTPException(status_code=403, detail="Not allowed to change order status")
            if not _is_valid_status_transition(order.status, value):
                raise HTTPException(status_code=400, detail="Invalid order status transition")
        elif field == "shipping_address":
            if not buyer_can_update or order.status != OrderStatus.pending:
                raise HTTPException(status_code=403, detail="Shipping address can only be updated while order is pending")
        else:
            raise HTTPException(status_code=400, detail=f"Cannot update field '{field}'")

    old_status = order.status

    for field, value in order_in.model_dump(exclude_unset=True).items():
        setattr(order, field, value)

    db.commit()
    db.refresh(order)

    # Generate invoice when order becomes confirmed
    try:
        from services.invoice_service import generate_invoice_pdf

        if old_status != OrderStatus.confirmed and order.status == OrderStatus.confirmed:
            generate_invoice_pdf(order, db)
    except Exception:
        pass

    return order



@router.get("/{order_id}/invoice")
def download_invoice(
    order_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Download invoice PDF for an order. Buyers can download their own invoices; admins can download any."""
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if not (current_user.is_admin or order.buyer_id == current_user.id):
        raise HTTPException(status_code=403, detail="Not allowed to download this invoice")

    from services.invoice_service import invoice_path_for_order, generate_invoice_pdf

    path = invoice_path_for_order(order)
    if not os.path.exists(path):
        try:
            generate_invoice_pdf(order, db)
            path = invoice_path_for_order(order)
        except Exception:
            raise HTTPException(status_code=500, detail="Failed to generate invoice")

    filename = os.path.basename(path)
    return FileResponse(path, media_type="application/pdf", filename=filename)


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel_order(
    order_id: UUID,
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


def _is_valid_status_transition(old_status: OrderStatus, new_status: OrderStatus) -> bool:
    if old_status == new_status:
        return True

    allowed_transitions = {
        OrderStatus.pending: {OrderStatus.confirmed, OrderStatus.shipped, OrderStatus.delivered, OrderStatus.cancelled},
        OrderStatus.confirmed: {OrderStatus.shipped, OrderStatus.delivered, OrderStatus.cancelled},
        OrderStatus.shipped: {OrderStatus.delivered},
        OrderStatus.delivered: set(),
        OrderStatus.cancelled: set(),
    }
    return new_status in allowed_transitions.get(old_status, set())
