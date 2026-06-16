import os
import uuid
import html
from datetime import datetime, timezone
from typing import Optional

from jinja2.sandbox import SandboxedEnvironment
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


def sanitize_template_input(text: str | None) -> str:
    """Sanitize input by stripping Jinja2 template metacharacters (`{`, `}`, `%`)."""
    if not text:
        return ""
    for char in ["{", "}", "%"]:
        text = text.replace(char, "")
    return text


def generate_invoice_pdf(order: Order, db: Session) -> str:
    """Generate a simple invoice PDF for the given order and return file path."""
    # Use a GUID filename to avoid predictable, easily-traceable filenames
    filename = f"{uuid.uuid4().hex}.pdf"
    path = os.path.join(_invoices_dir(), filename)

    c = canvas.Canvas(path, pagesize=A4, pageCompression=0)
    width, height = A4

    margin = 20 * mm
    y = height - margin

    # Initialize Jinja2 SandboxedEnvironment with autoescape enabled
    env = SandboxedEnvironment(autoescape=True)

    # Render Header using SandboxedEnvironment
    order_id_str = sanitize_template_input(str(order.id))
    header_tpl = env.from_string("Invoice #{{ order_id }}")
    header_text = html.unescape(header_tpl.render(order_id=order_id_str))

    c.setFont("Helvetica-Bold", 16)
    c.drawString(margin, y, header_text)
    y -= 10 * mm

    # Date
    date_str = datetime.now(timezone.utc).isoformat()
    date_tpl = env.from_string("Date: {{ date }} UTC")
    date_text = html.unescape(date_tpl.render(date=date_str))

    c.setFont("Helvetica", 10)
    c.drawString(margin, y, date_text)
    y -= 6 * mm

    # Buyer information
    buyer = getattr(order, "buyer", None)
    if buyer:
        buyer_name = sanitize_template_input(buyer.full_name or buyer.username)
        buyer_email = sanitize_template_input(buyer.email)
        buyer_tpl = env.from_string("Billed to: {{ name }} <{{ email }}>")
        buyer_text = html.unescape(buyer_tpl.render(name=buyer_name, email=buyer_email))

        c.drawString(margin, y, buyer_text)
        y -= 6 * mm

    # Shipping Address
    shipping_address = getattr(order, "shipping_address", None)
    if shipping_address:
        safe_address = sanitize_template_input(shipping_address)
        address_tpl = env.from_string("Shipping Address: {{ address }}")
        address_text = html.unescape(address_tpl.render(address=safe_address))

        c.drawString(margin, y, address_text)
        y -= 6 * mm

    y -= 4 * mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin, y, "Items")
    y -= 6 * mm

    c.setFont("Helvetica", 10)
    total = 0.0
    item_tpl = env.from_string("{{ name }} — {{ qty }} × {{ unit }} = {{ subtotal }}")

    for item in order.items:
        product = getattr(item, "product", None)
        raw_name = product.name if product is not None else f"Product {item.product_id}"
        name = sanitize_template_input(raw_name)
        qty = item.quantity
        unit = item.unit_price
        subtotal = qty * unit
        total += subtotal

        item_text = html.unescape(
            item_tpl.render(
                name=name,
                qty=str(qty),
                unit=f"{unit:.2f}",
                subtotal=f"{subtotal:.2f}"
            )
        )

        c.drawString(margin, y, item_text)
        y -= 5 * mm
        if y < margin:
            c.showPage()
            y = height - margin

    y -= 4 * mm
    c.setFont("Helvetica-Bold", 12)
    
    total_tpl = env.from_string("Total: {{ total }}")
    total_text = html.unescape(total_tpl.render(total=f"{order.total_amount:.2f}"))
    c.drawString(margin, y, total_text)

    c.showPage()
    c.save()
    try:
        os.chmod(path, 0o640)
    except Exception:
        pass

    # Persist filename on the order so future downloads can locate it
    try:
        order.invoice_filename = filename
        db.add(order)
        db.commit()
    except Exception:
        # Do not fail PDF generation if DB update fails; caller handles errors
        pass

    return path
