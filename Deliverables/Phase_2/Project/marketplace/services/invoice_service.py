import os
import uuid
from datetime import datetime
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session

from models.models import Order


def _invoices_dir() -> str:
    base = os.path.join(os.path.dirname(__file__), "..", "uploads", "invoices")
    path = os.path.abspath(base)
    os.makedirs(path, exist_ok=True)
    return path


def invoice_path_for_order(order: Order) -> str:
    """Return the expected invoice path for an Order.

    If the order has an assigned `invoice_filename`, use it. Otherwise
    fall back to the legacy `invoice_<id>.pdf` name.
    """
    if getattr(order, "invoice_filename", None):
        return os.path.join(_invoices_dir(), order.invoice_filename)
    return os.path.join(_invoices_dir(), f"invoice_{order.id}.pdf")


def generate_invoice_pdf(order: Order, db: Session) -> str:
    """Generate a simple invoice PDF for the given order and return file path."""
    # Use a GUID filename to avoid predictable, easily-traceable filenames
    filename = f"{uuid.uuid4().hex}.pdf"
    path = os.path.join(_invoices_dir(), filename)

    c = canvas.Canvas(path, pagesize=A4)
    width, height = A4

    margin = 20 * mm
    y = height - margin

    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, y, f"Invoice #{order.id}")
    y -= 10 * mm

    c.setFont("Helvetica", 10)
    c.drawString(margin, y, f"Date: {datetime.utcnow().isoformat()} UTC")
    y -= 6 * mm
    buyer = getattr(order, "buyer", None)
    if buyer:
        c.drawString(margin, y, f"Billed to: {buyer.full_name or buyer.username} <{buyer.email}>")
        y -= 6 * mm

    y -= 4 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin, y, "Items")
    y -= 6 * mm

    c.setFont("Helvetica", 10)
    total = 0.0
    for item in order.items:
        product = getattr(item, "product", None)
        name = product.name if product is not None else f"Product {item.product_id}"
        qty = item.quantity
        unit = item.unit_price
        subtotal = qty * unit
        total += subtotal

        line = f"{name} — {qty} × {unit:.2f} = {subtotal:.2f}"
        c.drawString(margin, y, line)
        y -= 5 * mm
        if y < margin:
            c.showPage()
            y = height - margin

    y -= 4 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, f"Total: {order.total_amount:.2f}")

    c.showPage()
    c.save()
    # Persist filename on the order so future downloads can locate it
    try:
        order.invoice_filename = filename
        db.add(order)
        db.commit()
    except Exception:
        # Do not fail PDF generation if DB update fails; caller handles errors
        pass

    return path
