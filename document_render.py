"""
Render a shipment record as a PDF bill of lading.

A reviewer cannot judge a case from a risk score alone - they need the paperwork
the decision was based on. Cases that arrive as a document already have one.
Cases that arrive as a structured event (Pub/Sub, the bulk simulator) do not, and
until now those showed the reviewer nothing to read.

So the event record is rendered into the document it would have been in a real
freight desk. This is deliberately labelled `SYSTEM-GENERATED` on the page and
`generated: True` in the provenance: it is a faithful rendering of the event that
opened the case, not a scan of a shipper's original. Presenting a reconstruction
as an original would corrupt the audit trail this whole system exists to keep.

Degrades gracefully: if fpdf is unavailable the caller gets None and ingestion
continues exactly as before.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# Field order matters: a bill of lading reads parties, then route, then cargo.
_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Shipper",
        [
            ("shipper_company", "Company"),
            ("shipper_name", "Contact"),
            ("shipper_country", "Country"),
            ("shipper_tax_id", "Tax ID"),
        ],
    ),
    (
        "Consignee",
        [
            ("consignee_name", "Name"),
            ("consignee_company", "Company"),
            ("consignee_country", "Country"),
        ],
    ),
    (
        "Routing",
        [
            ("origin", "Port of loading"),
            ("destination", "Port of discharge"),
            ("route", "Service route"),
            ("carrier", "Carrier"),
            ("vessel", "Vessel / flight"),
        ],
    ),
    (
        "Cargo",
        [
            ("cargo_description", "Description of goods"),
            ("hs_code", "HS code"),
            ("weight_kg", "Gross weight (kg)"),
            ("quantity", "Pieces"),
            ("container_id", "Container"),
        ],
    ),
    (
        "Declared value",
        [
            ("declared_value", "Declared value (USD)"),
            ("currency", "Currency"),
            ("incoterms", "Incoterms"),
            ("payment_terms", "Payment terms"),
        ],
    ),
]


def _fmt(value: Any) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:,}"
    return str(value)


def _ascii(text: str) -> str:
    """
    fpdf's built-in fonts are latin-1 only. Shipper names in this corpus are
    Vietnamese, so transliterate rather than raise mid-ingest.
    """
    return text.encode("latin-1", "replace").decode("latin-1")


def render_bill_of_lading(
    shipment: dict[str, Any], case_id: str, source: str = "event"
) -> bytes | None:
    """
    Build a one-page bill of lading from a shipment record.

    Returns the PDF bytes, or None if the PDF library is not installed - the
    caller treats that as "no document" and carries on.
    """
    try:
        from fpdf import FPDF
    except Exception:  # noqa: BLE001
        return None

    try:
        pdf = FPDF(unit="mm", format="A4")
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        pdf.set_font("Helvetica", "B", 15)
        pdf.cell(0, 9, "BILL OF LADING", new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(120, 120, 120)
        pdf.multi_cell(
            0,
            4.5,
            _ascii(
                "SYSTEM-GENERATED from the shipment event that opened this case. "
                f"Source: {source}. This is a rendering of the received record, "
                "not a scan of an original document issued by the shipper."
            ),
            new_x="LMARGIN",
            new_y="NEXT",
        )
        pdf.ln(2)

        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 10)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        for label, value in (
            ("B/L number", shipment.get("shipment_id")),
            ("Case", case_id),
            ("Rendered at", stamp),
        ):
            pdf.cell(45, 6, _ascii(f"{label}:"))
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 6, _ascii(_fmt(value)), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 10)

        rendered_keys: set[str] = {"shipment_id"}

        for section, fields in _SECTIONS:
            present = [(k, lbl) for k, lbl in fields if shipment.get(k) not in (None, "")]
            if not present:
                continue
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 7, _ascii(section.upper()), new_x="LMARGIN", new_y="NEXT")
            pdf.set_draw_color(200, 200, 200)
            pdf.line(pdf.l_margin, pdf.get_y(), 210 - pdf.r_margin, pdf.get_y())
            pdf.ln(1.5)
            pdf.set_font("Helvetica", "", 10)
            for key, label in present:
                rendered_keys.add(key)
                pdf.cell(55, 6, _ascii(f"{label}:"))
                pdf.multi_cell(
                    0, 6, _ascii(_fmt(shipment.get(key))), new_x="LMARGIN", new_y="NEXT"
                )

        # Anything the template does not know about still has to be visible: a
        # reviewer must see the whole record, not the part this file anticipated.
        # Underscore-prefixed keys are excluded: the simulator tags records with
        # `_generated_profile`, and printing the expected answer on the document
        # a human is asked to judge independently would bias the review.
        extra = [
            (k, v)
            for k, v in sorted(shipment.items())
            if k not in rendered_keys
            and not k.startswith("_")
            and v not in (None, "")
            and not isinstance(v, (dict, list))
        ]
        if extra:
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 7, "OTHER FIELDS ON RECORD", new_x="LMARGIN", new_y="NEXT")
            pdf.set_draw_color(200, 200, 200)
            pdf.line(pdf.l_margin, pdf.get_y(), 210 - pdf.r_margin, pdf.get_y())
            pdf.ln(1.5)
            pdf.set_font("Helvetica", "", 10)
            for key, value in extra:
                pdf.cell(55, 6, _ascii(f"{key}:"))
                pdf.multi_cell(0, 6, _ascii(_fmt(value)), new_x="LMARGIN", new_y="NEXT")

        out = pdf.output()
        return bytes(out)
    except Exception:  # noqa: BLE001
        return None
